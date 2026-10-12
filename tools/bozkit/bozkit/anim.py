"""Skeletal animation data: skeletons, skins, animations and the game's animation state machines,
and posing a skinned model (Marmalade IwAnim formats as BOZ ships them; Ghidra names in the game
definition: CIwAnimSkel/CIwAnimBone/CIwAnimSkin/CIwAnimSkinSet/CIwAnim/CIsAnimState Serialise).

CIwAnimSkel: u32 bone count, then per bone: u32 class hash (CIwAnimBone), u32 name hash, u32
parent name hash (0: root), u32 rotation (compressed quaternion, see below), s16 x3 position
(relative to the parent), s16 bone id, s16, s32 (scale, 0x400) [+ 4 bytes on some bones].

CIwAnimSkin: u32 flags, u32 model hash, u32 skeleton hash, u32 set count, then per set: u32 class
hash (CIwAnimSkinSet), u32 0, u32 vertex count, u32 data size, data: up to 4 bone ids (0xff ends
the list; 2 bytes for one bone, else 4), then per vertex: u16 vertex index (low 14 bits), s16 x3
position in each bone's space (in bind pose: bone world position + this = the model's vertex x 4),
then one weight byte per bone (x2 = 0..255) padded to 2 bytes (1-2 bones) or 4 (3-4 bones).

CIwAnim: u32 skeleton hash, u32 bone count, u32 bone mask words, u32 keyframe count, u32 data size,
data: the keyframes as the game keeps them in memory, one after the other (4-byte aligned): a
0x90-byte header (+4 u16 bone count, +6 flags: bit 0 rotation only, bit 2 bones in order), then
per bone s16 x3 position and s16 x4 quaternion (w, x, y, z; 4096 = 1.0) (8 bytes, rotation only,
with flag bit 0), then the bone indices (one byte each) unless flag bit 2. Then s32 duration
(4096 = 1 second; keyframes are 1/24 s apart), s32, u32 (unknown).

CIsAnimStateMachine: u32 state count, then per state: u32 name hash ("idle", "shooting", ...),
u32 animation hash, u32 second animation hash, s32 speed (4096 = 1.0), s32, s16 index, u32, u8
(looping), u8, three transition lists (u32 count + count x (s16, s32, u8, s32)), and an event list
(u32 count + count x (s16, s16, s16, s32, u8, u8)); then the triggers, and the default state
(s16) at the end.

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


def decode_skel(body: bytes) -> list[Bone]:
    count = struct.unpack_from('<I', body)[0]
    marker = iw_hash('CIwAnimBone')
    bones, p = [], 4
    while len(bones) < count:
        if struct.unpack_from('<I', body, p)[0] != marker:
            raise AnimError(f'skeleton: no bone record at {p}')
        _cls, name, parent, packed = struct.unpack_from('<IIII', body, p)
        position = struct.unpack_from('<3h', body, p + 16)
        bones.append(Bone(name, parent, tuple(float(v) for v in position), decompress_quat(packed)))
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
            weights = [min(255, data[at + 2 + 6 * used + b] * 2) / 255.0 for b in range(used)]
            vertices.append((index, locals_, weights))
        skin.sets.append(SkinSet(ids[:used], vertices))
    if p != len(body):
        raise AnimError(f'skin: {len(body) - p} bytes left over')
    return skin


@dataclass
class Keyframe:
    keys: dict[int, tuple[tuple[float, float, float] | None, tuple[float, float, float, float]]]


@dataclass
class Anim:
    skeleton: int
    bone_count: int
    keyframes: list[Keyframe]


def decode_anim(body: bytes) -> Anim:
    skeleton, bone_count = struct.unpack_from('<II', body)
    words = (bone_count + 31) >> 5
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
        keys = {}
        for i in range(count):
            bone = i if flags & 4 else data[index_at + i]
            rec = keys_at + i * stride
            if rotation_only:
                position = None
                w, x, y, z = struct.unpack_from('<4h', data, rec)
            else:
                position = tuple(float(v) for v in struct.unpack_from('<3h', data, rec))
                w, x, y, z = struct.unpack_from('<4h', data, rec + 6)
            keys[bone] = (position, (w / 4096.0, x / 4096.0, y / 4096.0, z / 4096.0))
        keyframes.append(Keyframe(keys))
        length = 0x90 + count * stride + (0 if flags & 4 else count)
        at += (length + 3) & ~3
    return Anim(skeleton, bone_count, keyframes)


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


def state_anim(states: list[State], name: str) -> int | None:
    """The animation of the state called *name* ("idle"), or None."""
    wanted = iw_hash(name)
    for state in states:
        if state.name == wanted and state.anim:
            return state.anim
    return None


# --- Posing ---------------------------------------------------------------------------------

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
