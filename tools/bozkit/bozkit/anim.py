"""Skeletal animation data: skeletons, skins, animations and the game's animation state machines,
and posing a skinned model (Marmalade IwAnim formats as BOZ ships them; Ghidra names in the game
definition: CIwAnimSkel/CIwAnimBone/CIwAnimSkin/CIwAnimSkinSet/CIwAnim/CIsAnimState Serialise).

CIwAnimSkel: u32 bone count, then per bone (CIwAnimBone::Serialise): u32 class hash
(CIwAnimBone), u32 name hash, u32 parent name hash (0: root), u32 rotation (compressed
quaternion, see below), s16 x3 position (relative to the parent), s16 bone number, s16 (3), s32
(1024); then the skeleton's own s32 (0x4000). Written by encode_skel; every shipped skeleton,
skin and animation round-trips byte for byte through the decoders and encoders here.

CIwAnimSkin: u32 flags, u32 model hash, u32 skeleton hash, u32 set count, then per set: u32 class
hash (CIwAnimSkinSet), u32 0, u32 vertex count, u32 data size, data: up to 4 bone ids (0xff ends
the list; 2 bytes for one bone, else 4), then per vertex: u16 vertex index (low 14 bits), s16 x3
position in each bone's space (in bind pose: bone world position + this = the model's vertex x 4),
then one weight byte per bone (128 = 1.0; they add up to 128) padded to 2 bytes (1-2 bones) or
4 (3-4 bones).

CIwAnim: u32 skeleton hash, u32 bone count, u32 bone mask words, u32 keyframe count, u32 data size,
data: the keyframes as the game keeps them in memory, one after the other (4-byte aligned, the
padding left as it was in memory): a 0x90-byte header (+0 u32 time, 4096 = 1 second, on a 30 a
second grid and not evenly spaced; +4 u16 bone count; +6 flags: bit 0 rotation only, bit 2 bones
in order; the rest mostly 0xff and leftover memory, copied from a stock keyframe), then
per bone s16 x3 position and s16 x4 quaternion (w, x, y, z; 4096 = 1.0) (8 bytes, rotation only,
with flag bit 0), then the bone indices (one byte each) unless flag bit 2. Then s32 duration
(the last keyframe's time), s32 (16384), u32 (a resource reference, 0).

CIsAnimStateMachine: u32 state count, then per state: u32 name hash ("idle", "shooting", ...),
u32 animation hash, u32 second animation hash, s32 speed (4096 = 1.0), s32 length in
milliseconds (its animation's; 0 for idle and states without one; reaching it fires the
state's end event, e.g. back to idle when a reload is done), s16 index, u32, u8 (looping), u8, three transition lists (u32 count + count x (s16, s32, u8, s32)), and an event list
(u32 count + count x (s16, s16, s16, s32, u8, u8)); then the triggers, and the default state
(s16) at the end. patch_asm copies one with other animations in its states.

Compressed quaternions (32 bits): the top 2 bits say which component was largest and dropped
(0 x, 1 y, 2 z, 3 w); three 10-bit fields v give the others as (v * 0x16a2 >> 10) - 0xb51 (4096 =
1.0); the dropped one is sqrt(1 - the others squared).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from .hashing import iw_hash

SKEL_SCALE = 4   # skeleton, skin and animation positions are the model's units x 4


class AnimError(ValueError):
    pass


def decompress_quat(packed: int) -> tuple[float, float, float, float]:
    """(w, x, y, z) of a 32-bit compressed quaternion."""
    def unpack(bits: int) -> float:
        return (((bits * 0x16a2) >> 10) - 0xb51) / 4096.0

    a = unpack(packed & 0x3ff)
    b = unpack((packed >> 10) & 0x3ff)
    c = unpack((packed >> 20) & 0x3ff)
    largest = math.sqrt(max(0.0, 1.0 - a * a - b * b - c * c))
    which = packed >> 30
    if which == 0:
        return c, largest, a, b
    if which == 1:
        return c, a, largest, b
    if which == 2:
        return c, a, b, largest
    return largest, a, b, c


def compress_quat(w: float, x: float, y: float, z: float) -> int:
    """The inverse of decompress_quat (for tests and writers)."""
    values = (x, y, z, w)
    which = max(range(4), key=lambda i: abs(values[i]))
    if values[which] < 0:
        w, x, y, z = -w, -x, -y, -z
    a, b, c = {0: (y, z, w), 1: (x, z, w), 2: (x, y, w), 3: (x, y, z)}[which]

    def pack(v: float) -> int:
        return max(0, min(0x3ff, round((v * 4096 + 0xb51) * 1024 / 0x16a2)))

    return (which << 30) | (pack(c) << 20) | (pack(b) << 10) | pack(a)


@dataclass
class Bone:
    name: int
    parent: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]   # w, x, y, z
    packed: int | None = None     # the stored compressed rotation (kept so files round-trip)
    index: int = 0                # s16: the bone's number
    flags: int = 3                # s16, 3 in every shipped bone
    value: int = 1024             # s32, 1024 in every shipped bone


def decode_skel(body: bytes) -> list[Bone]:
    count = struct.unpack_from('<I', body)[0]
    marker = iw_hash('CIwAnimBone')
    bones, p = [], 4
    while len(bones) < count:
        if struct.unpack_from('<I', body, p)[0] != marker:
            raise AnimError(f'skeleton: no bone record at {p}')
        _cls, name, parent, packed = struct.unpack_from('<IIII', body, p)
        position = struct.unpack_from('<3h', body, p + 16)
        index, flags, value = struct.unpack_from('<hhi', body, p + 22)
        bones.append(Bone(name, parent, tuple(float(v) for v in position), decompress_quat(packed),
                          packed, index, flags, value))
        nxt = body.find(struct.pack('<I', marker), p + 30)
        p = nxt if nxt >= 0 else len(body)
    return bones


@dataclass
class SkinSet:
    bones: list[int]
    vertices: list[tuple[int, list[tuple[int, int, int]], list[float]]]  # index, locals, weights


@dataclass
class Skin:
    model: int
    skeleton: int
    sets: list[SkinSet] = field(default_factory=list)


def decode_skin(body: bytes) -> Skin:
    _flags, model, skeleton, count = struct.unpack_from('<IIII', body)
    skin, p = Skin(model, skeleton), 16
    for _ in range(count):
        _cls, _name, vertex_count, size = struct.unpack_from('<IIII', body, p)
        p += 16
        data = body[p:p + size]
        p += size
        ids = list(data[:4])
        used = 1 if ids[1] == 0xff else 2 if ids[2] == 0xff else 3 if ids[3] == 0xff else 4
        q = 2 if used == 1 else 4
        stride = 2 + 6 * used + (2 if used < 3 else 4)
        vertices = []
        for v in range(vertex_count):
            at = q + v * stride
            index = struct.unpack_from('<H', data, at)[0] & 0x3fff
            locals_ = [struct.unpack_from('<3h', data, at + 2 + 6 * b) for b in range(used)]
            weights = [data[at + 2 + 6 * used + b] / 128.0 for b in range(used)]
            vertices.append((index, locals_, weights))
        skin.sets.append(SkinSet(ids[:used], vertices))
    if p != len(body):
        raise AnimError(f'skin: {len(body) - p} bytes left over')
    return skin


BONE_CLASS = iw_hash('CIwAnimBone')
SKEL_VALUE = 0x4000     # the s32 after a skeleton's last bone (every shipped skeleton)


def encode_skel(bones: list[Bone], value: int = SKEL_VALUE) -> bytes:
    """A CIwAnimSkel body: u32 count, then per bone (CIwAnimBone::Serialise) class hash, name,
    parent name (0: root), compressed rotation, s16 x3 position (relative to the parent), s16
    number, s16 flags, s32; then the skeleton's own s32. Parents come before their children."""
    out = bytearray(struct.pack('<I', len(bones)))
    for number, bone in enumerate(bones):
        packed = bone.packed if bone.packed is not None else compress_quat(*bone.rotation)
        position = tuple(max(-32768, min(32767, int(round(c)))) for c in bone.position)
        out += struct.pack('<IIII3hhhi', BONE_CLASS, bone.name, bone.parent, packed, *position,
                           bone.index if bone.packed is not None else number, bone.flags, bone.value)
    out += struct.pack('<i', value)
    return bytes(out)


def skel_value(body: bytes) -> int:
    return struct.unpack_from('<i', body, len(body) - 4)[0]


SKIN_SET = iw_hash('CIwAnimSkinSet')


def encode_skin(skin: Skin, flags: int = 1) -> bytes:
    """A CIwAnimSkin body (the layout decode_skin reads; every shipped skin round-trips): sets of
    up to 4 bones, each vertex's position in each bone's space (skeleton units) and one weight
    byte per bone (128 = 1.0; they add up to 128), padded with 0xff."""
    out = bytearray(struct.pack('<IIII', flags, skin.model, skin.skeleton, len(skin.sets)))
    for skin_set in skin.sets:
        used = len(skin_set.bones)
        if not 1 <= used <= 4 or any(not 0 <= b < 255 for b in skin_set.bones):
            raise AnimError('a skin set has 1 to 4 bones, numbered below 255')
        q = 2 if used == 1 else 4
        data = bytearray(bytes(skin_set.bones) + b'\xff' * (q - used))
        for index, locals_, weights in skin_set.vertices:
            if not 0 <= index <= 0x3fff:
                raise AnimError('a skinned model has at most 16384 positions')
            data += struct.pack('<H', index)
            for local in locals_:
                data += struct.pack('<3h', *(max(-32768, min(32767, int(round(c)))) for c in local))
            total = sum(weights) or 1.0
            raw = [int(round(w / total * 128)) for w in weights]
            raw[raw.index(max(raw))] += 128 - sum(raw)      # the bytes always add up to 128
            data += bytes(max(0, min(255, w)) for w in raw)
            data += b'\xff' * ((2 if used < 3 else 4) - used)
        out += struct.pack('<IIII', SKIN_SET, 0, len(skin_set.vertices), len(data)) + data
    return bytes(out)


def quat_conj(q):
    w, x, y, z = q
    return (w, -x, -y, -z)


def build_skin(model: int, skeleton: int, bones: list[Bone], positions, weights) -> Skin:
    """A skin that puts *positions* (model units, the skeleton's bind pose) on *bones*:
    *weights* gives each position's [(bone index, weight)] (up to 4). Each bone's local position
    is the vertex seen from that bone, so the bind pose reproduces the model exactly."""
    worlds = pose(bones)
    sets: dict[tuple, list] = {}
    for index, (position, vertex_weights) in enumerate(zip(positions, weights)):
        merged: dict[int, float] = {}
        for bone, weight in vertex_weights:
            if 0 <= bone < len(bones) and weight > 0:
                merged[bone] = merged.get(bone, 0.0) + weight
        chosen = sorted(merged.items(), key=lambda bw: -bw[1])[:4] or [(0, 1.0)]
        chosen.sort()
        target = tuple(c * SKEL_SCALE for c in position)
        locals_ = []
        for bone, _w in chosen:
            bone_position, rotation = worlds[bone]
            offset = tuple(t - b for t, b in zip(target, bone_position))
            locals_.append(quat_rotate(quat_conj(rotation), offset))
        key = tuple(b for b, _w in chosen)
        sets.setdefault(key, []).append((index, locals_, [w for _b, w in chosen]))
    skin = Skin(model, skeleton)
    for key in sorted(sets, key=lambda k: (len(k), k)):
        skin.sets.append(SkinSet(list(key), sets[key]))
    return skin


@dataclass
class Keyframe:
    keys: dict[int, tuple[tuple[float, float, float] | None, tuple[float, float, float, float]]]
    time: int = 0                 # 4096 = 1 second
    header: bytes = b''           # the stored 0x90-byte header (kept so files round-trip)
    order: list = field(default_factory=list)   # bones in stored order
    pad: bytes = b''              # the stored padding to 4 bytes (leftover memory, kept)


@dataclass
class Anim:
    skeleton: int
    bone_count: int
    keyframes: list[Keyframe]
    mask: list = field(default_factory=list)    # u32 words: which bones it animates
    duration: int = 0             # 4096 = 1 second: the last keyframe's time
    value: int = 16384            # s32 after the duration (16384 in every shipped animation)
    link: int = 0                 # u32 resource reference after it (0 in every shipped one)


def decode_anim(body: bytes) -> Anim:
    skeleton, bone_count = struct.unpack_from('<II', body)
    words = (bone_count + 31) >> 5
    mask = list(struct.unpack_from(f'<{words}I', body, 8))
    p = 8 + 4 * words
    frames, size = struct.unpack_from('<II', body, p)
    data = body[p + 8:p + 8 + size]
    keyframes, at = [], 0
    for _ in range(frames):
        count = struct.unpack_from('<H', data, at + 4)[0]
        flags = data[at + 6]
        rotation_only = bool(flags & 1)
        stride = 8 if rotation_only else 14
        keys_at = at + 0x90
        index_at = keys_at + count * stride
        keys, order = {}, []
        for i in range(count):
            bone = i if flags & 4 else data[index_at + i]
            order.append(bone)
            rec = keys_at + i * stride
            if rotation_only:
                position = None
                w, x, y, z = struct.unpack_from('<4h', data, rec)
            else:
                position = tuple(float(v) for v in struct.unpack_from('<3h', data, rec))
                w, x, y, z = struct.unpack_from('<4h', data, rec + 6)
            keys[bone] = (position, (w / 4096.0, x / 4096.0, y / 4096.0, z / 4096.0))
        length = 0x90 + count * stride + (0 if flags & 4 else count)
        keyframes.append(Keyframe(keys, struct.unpack_from('<I', data, at)[0],
                                  bytes(data[at:at + 0x90]), order,
                                  bytes(data[at + length:at + ((length + 3) & ~3)])))
        at += (length + 3) & ~3
    duration, value, link = struct.unpack_from('<iiI', body, p + 8 + size) \
        if len(body) >= p + 8 + size + 12 else (0, 16384, 0)
    return Anim(skeleton, bone_count, keyframes, mask, duration, value, link)


def encode_anim(animation: Anim, template: bytes | None = None) -> bytes:
    """A CIwAnim body (the layout decode_anim reads). Each keyframe keeps its stored header, or
    takes *template* (a stock keyframe header) with its time, bone count and flags written in.
    A keyframe with a position for every key is written in full (14 bytes a bone), else rotation
    only (8 bytes); keys in bone order skip the index list."""
    words = (animation.bone_count + 31) >> 5
    mask = list(animation.mask) or [0] * words
    if not animation.mask:
        for frame in animation.keyframes:
            for bone in frame.keys:
                mask[bone >> 5] |= 1 << (bone & 31)
    data = bytearray()
    for frame in animation.keyframes:
        order = list(frame.order) or sorted(frame.keys)
        rotation_only = all(frame.keys[b][0] is None for b in order)
        in_order = order == list(range(len(order)))
        header = bytearray(frame.header or template or b'\xff' * 0x90)
        if len(header) != 0x90:
            raise AnimError('a keyframe header is 0x90 bytes')
        struct.pack_into('<IH', header, 0, frame.time, len(order))
        header[6] = (header[6] & ~5) | (1 if rotation_only else 0) | (4 if in_order else 0)
        block = bytearray(header)
        for bone in order:
            position, rotation = frame.keys[bone]
            if not rotation_only:
                block += struct.pack('<3h', *(max(-32768, min(32767, int(round(c))))
                                              for c in (position or (0.0, 0.0, 0.0))))
            block += struct.pack('<4h', *(max(-32768, min(32767, int(round(c * 4096))))
                                          for c in rotation))
        if not in_order:
            block += bytes(order)
        padding = -len(block) % 4
        block += frame.pad if len(frame.pad) == padding else b'\0' * padding
        data += block
    duration = animation.duration or (animation.keyframes[-1].time if animation.keyframes else 0)
    return (struct.pack('<II', animation.skeleton, animation.bone_count)
            + struct.pack(f'<{words}I', *mask)
            + struct.pack('<II', len(animation.keyframes), len(data)) + bytes(data)
            + struct.pack('<iiI', duration, animation.value, animation.link))


@dataclass
class State:
    name: int
    anim: int
    anim2: int
    looping: bool


def decode_asm(body: bytes) -> tuple[list[State], int]:
    """(states, default state index) of an animation state machine."""
    p = 0

    def take(fmt):
        nonlocal p
        values = struct.unpack_from(fmt, body, p)
        p += struct.calcsize(fmt)
        return values

    (count,) = take('<I')
    states = []
    for _ in range(count):
        name, anim, anim2, _speed, _b, _index, _d, looping, _e = take('<IIIiihIBB')
        for _ in range(3):
            (n,) = take('<I')
            p += n * 11
        (events,) = take('<I')
        p += events * 12
        states.append(State(name, anim, anim2, bool(looping)))
    default = struct.unpack_from('<h', body, len(body) - 2)[0]
    return states, default


def asm_anim_offsets(body: bytes) -> list[tuple[int, int, int]]:
    """(state name, offset of its animation reference, offset of its second one) per state."""
    p, out = 0, []
    (count,) = struct.unpack_from('<I', body, p)
    p += 4
    for _ in range(count):
        name = struct.unpack_from('<I', body, p)[0]
        out.append((name, p + 4, p + 8))
        p += struct.calcsize('<IIIiihIBB')
        for _ in range(3):
            (n,) = struct.unpack_from('<I', body, p)
            p += 4 + n * 11
        (events,) = struct.unpack_from('<I', body, p)
        p += 4 + events * 12
    return out


LENGTH_AFTER_ANIM = 12      # a state's length (ms) from its animation reference (asm_anim_offsets)


# The aiming transitions: aiming enters them and moves on when they end, so they need a length
# even where the weapon's own state machine has none (a weapon that could not aim, as the
# Thundergun, would otherwise snap in and out of the sights).
ENDS_WITH_CLIP = {iw_hash('Aim_up'), iw_hash('aim_down')}


def asm_lengths(body: bytes, lengths: dict) -> dict:
    """{offset: milliseconds} to give the states in *lengths* ({state name hash: ms}) their new
    lengths; states with no length (0: idle and the like) keep none, except ENDS_WITH_CLIP."""
    out = {}
    for name, at, _second in asm_anim_offsets(body):
        offset = at + LENGTH_AFTER_ANIM
        if name in lengths and (struct.unpack_from('<i', body, offset)[0] > 0 or name in ENDS_WITH_CLIP):
            out[offset] = max(1, int(lengths[name]))
    return out


def patch_asm(body: bytes, animations: dict) -> bytes:
    """A copy of a state machine with *animations* ({state name hash: animation hash}) in place
    of its states' animations; timing, looping, transitions and events stay as they are."""
    out = bytearray(body)
    for name, at, _second in asm_anim_offsets(body):
        if name in animations:
            struct.pack_into('<I', out, at, animations[name])
    return bytes(out)


def state_anim(states: list[State], name: str) -> int | None:
    """The animation of the state called *name* ("idle"), or None."""
    wanted = iw_hash(name)
    for state in states:
        if state.name == wanted and state.anim:
            return state.anim
    return None


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw)


def quat_rotate(q, v):
    w, x, y, z = q
    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    vx, vy, vz = v
    # v' = q v q*
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz,
            vz + w * tz + x * ty - y * tx)


def pose(bones: list[Bone], keyframe: Keyframe | None = None, root=None):
    """World (position, rotation) of each bone: the keyframe's local transforms where it has
    them, else the bind pose. *root*: a (position, rotation) the whole skeleton is put under."""
    worlds = []
    index_of = {bone.name: i for i, bone in enumerate(bones)}
    for i, bone in enumerate(bones):
        position, rotation = bone.position, bone.rotation
        if keyframe is not None and i in keyframe.keys:
            key_position, key_rotation = keyframe.keys[i]
            rotation = key_rotation
            if key_position is not None:
                position = key_position
        parent = index_of.get(bone.parent)
        if parent is None:
            base = root or ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
        else:
            base = worlds[parent]
        base_position, base_rotation = base
        offset = quat_rotate(base_rotation, position)
        worlds.append((tuple(b + o for b, o in zip(base_position, offset)),
                       quat_mul(base_rotation, rotation)))
    return worlds


def bone_world(bones: list[Bone], worlds, name: str):
    wanted = iw_hash(name)
    for bone, world in zip(bones, worlds):
        if bone.name == wanted:
            return world
    return None


def skin_positions(skin: Skin, worlds, vertex_count: int, fallback=None, remap=None) -> list:
    """Posed vertex positions in the model's units (skeleton units / SKEL_SCALE), by vertex index.
    The skin indexes the model's unique positions; *remap* (native.Model.position_remap: vertex
    -> unique position) expands them to every vertex. Positions the skin leaves out take
    *fallback* (the model's own) where given."""
    if remap:
        unique_count = max(remap) + 1
        base = [None] * unique_count
        for vertex, unique in enumerate(remap):
            if fallback is not None and base[unique] is None:
                base[unique] = fallback[vertex]
        posed = skin_positions(skin, worlds, unique_count,
                               [b or (0.0, 0.0, 0.0) for b in base])
        return [posed[unique] for unique in remap]
    out = list(fallback) if fallback is not None else [(0.0, 0.0, 0.0)] * vertex_count
    for skin_set in skin.sets:
        for index, locals_, weights in skin_set.vertices:
            total = sum(weights) or 1.0
            px = py = pz = 0.0
            for bone, local, weight in zip(skin_set.bones, locals_, weights):
                if bone >= len(worlds):
                    continue
                position, rotation = worlds[bone]
                rx, ry, rz = quat_rotate(rotation, local)
                share = weight / total
                px += (position[0] + rx) * share
                py += (position[1] + ry) * share
                pz += (position[2] + rz) * share
            if index < len(out):
                out[index] = (px / SKEL_SCALE, py / SKEL_SCALE, pz / SKEL_SCALE)
    return out
