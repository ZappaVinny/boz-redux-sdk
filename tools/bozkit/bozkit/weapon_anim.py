"""A weapon's own animations: clips made in the editor's Animation tab, the gun's own skeleton
(your asset's bones), and the stock animations moved onto it.

The game keeps keyframes with their times (4096 = 1 second, on a 30 frames a second grid); the
editor works in frames at FPS. A clip, stored in a project as
``source/weapons/anims/<weapon>/<state hash>.json``, is::

    {"state": "reloading", "arms": {"frames": [{"frame": 0, "bones": {"<bone>": [px, py, pz,
     qw, qx, qy, qz]}}, ...]}, "gun": {...}}

Positions are skeleton units (the model's x 4) and, like the rotations, relative to the bone's
parent. Arm bones are named by number ("3"), gun bones by name. A part without a clip plays the
stock animation (moved onto the gun's own skeleton when it has one).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import anim
from .hashing import iw_hash

FPS = 30
TICKS = 4096        # keyframe time units per second


class WeaponAnimError(ValueError):
    pass


def frame_of(time: int) -> int:
    return int(round(time * FPS / TICKS))


def time_of(frame: int) -> int:
    return int(round(frame * TICKS / FPS))


@dataclass
class Clip:
    """One part's animation for one state: per frame, bone -> (position, rotation) local."""
    frames: list = field(default_factory=list)   # [(frame, {bone key: ((x, y, z), (w, x, y, z))})]

    def length(self) -> int:
        return self.frames[-1][0] if self.frames else 0


# --- Project files --------------------------------------------------------------------------

def clips_dir(source: Path, weapon: str) -> Path:
    return Path(source) / 'weapons' / 'anims' / weapon


def _clip_json(clip: Clip) -> dict:
    return {'frames': [{'frame': frame, 'bones': {
        str(bone): [round(c, 2) for c in position] + [round(c, 5) for c in rotation]
        for bone, (position, rotation) in bones.items()}} for frame, bones in clip.frames]}


def _clip_from(data: dict) -> Clip:
    frames = []
    for entry in data.get('frames', []):
        bones = {}
        for bone, values in entry.get('bones', {}).items():
            if len(values) != 7:
                raise WeaponAnimError(f'bone {bone}: a key is 3 position and 4 rotation values')
            bones[bone] = (tuple(float(v) for v in values[:3]), tuple(float(v) for v in values[3:]))
        frames.append((int(entry['frame']), bones))
    frames.sort(key=lambda f: f[0])
    return Clip(frames)


def load_clips(source: Path, weapon: str) -> dict:
    """{state hash: {"arms": Clip, "gun": Clip, "state": label}} of a weapon."""
    out = {}
    folder = clips_dir(source, weapon)
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            state = int(path.stem, 16)
        except (OSError, ValueError) as exc:
            raise WeaponAnimError(f'{path}: {exc}') from None
        entry = {'state': str(data.get('state', '')), 'edits': dict(data.get('edits', {})),
                 'length': int(data.get('length', 0)),
                 'legacy': 'edits' not in data}       # made by an older editor: its clips are the edit
        for part in ('arms', 'gun'):
            if part in data:
                entry[part] = _clip_from(data[part])
            if f'{part}_layer' in data:
                entry[f'{part}_layer'] = data[f'{part}_layer']   # the editor's keys on the stock motion
        out[state] = entry
    return out


def save_clip(source: Path, weapon: str, state: int, label: str, part: str, clip: Clip | None,
              layer: dict | None = None) -> None:
    """Store (or with None, remove) one part's clip of one state. *layer*: the editor's keys made on
    top of the stock motion (kept to edit them again; the build uses the clip)."""
    folder = clips_dir(source, weapon)
    path = folder / f'{state:08x}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    data['state'] = label
    if clip is None:
        data.pop(part, None)
        data.pop(f'{part}_layer', None)
    else:
        data[part] = _clip_json(clip)
        if layer is not None:
            data[f'{part}_layer'] = layer
        else:
            data.pop(f'{part}_layer', None)
    if 'arms' not in data and 'gun' not in data:
        if path.is_file():
            path.unlink()
        return
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(',', ':')) + '\n', encoding='utf-8')


def save_state(source: Path, weapon: str, state: int, label: str, clips: dict, edits: dict,
               length: int) -> None:
    """Store one animation of a weapon as the editor made it: *edits* ({part: changes}, see
    Timelines) to edit it again, and the *clips* ({part: Clip} at every frame) the build uses.
    No changes: the file goes and the stock animation plays."""
    folder = clips_dir(source, weapon)
    path = folder / f'{state:08x}.json'
    if not any(edits.values()):
        if path.is_file():
            path.unlink()
        return
    data = {'state': label, 'length': int(length), 'edits': edits}
    for part, clip in clips.items():
        if clip is not None:
            data[part] = _clip_json(clip)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(',', ':')) + '\n', encoding='utf-8')


# --- Timelines --------------------------------------------------------------------------------
# Each part (arms, gun) of an animation has its own list of changes, sorted by frame:
#   {"frame": f, "pose": {bone: [px, py, pz, qw, qx, qy, qz]}}   your pose, held from f on
#   {"frame": f, "original": s}                                   the original again from f, playing
#                                                                 its frame s at f (s = f: as it was)
#   {"frame": 0, "legacy": true}                                  a clip made by an older editor
# Before a part's first change it plays the original; a change lasts until the next one, and never
# touches the frames before it.

def change_at(changes: list, frame: int):
    """The change in force at *frame* (None: the original)."""
    found = None
    for change in changes:
        if change['frame'] <= frame:
            found = change
        else:
            break
    return found


def source_of(changes: list, frame: int):
    """What a part plays at *frame*: ("original", frame of the original), ("pose", bones) or
    ("legacy", frame)."""
    change = change_at(changes, frame)
    if change is None:
        return 'original', frame
    if 'pose' in change:
        return 'pose', change['pose']
    if change.get('legacy'):
        return 'legacy', frame
    return 'original', int(change['original']) + frame - change['frame']


def is_yours(changes: list, frame: int) -> bool:
    return source_of(changes, frame)[0] != 'original'


def _put(changes: list, change: dict) -> list:
    out = [c for c in changes if c['frame'] != change['frame']]
    out.append(change)
    return sorted(out, key=lambda c: c['frame'])


def add_pose(changes: list, frame: int, bones: dict) -> list:
    return _put(changes, {'frame': int(frame), 'pose': {
        str(k): [round(c, 5) for c in v[0]] + [round(c, 7) for c in v[1]] for k, v in bones.items()}})


def add_original(changes: list, frame: int, source: int | None = None) -> list:
    """The original again from *frame* (its frame *source* first, else as it was)."""
    change = {'frame': int(frame), 'original': int(frame if source is None else source)}
    out = _put(changes, change)
    # Nothing to undo before it: drop a back-to-original that only restores the original.
    if out and out[0] is change and change['original'] == change['frame']:
        out = out[1:]
    return out


def copy_frames(changes: list, at: int, start: int, end: int, last_pose: dict) -> list:
    """The original's frames *start*..*end* played from *at*, then its last pose held."""
    out = _put(changes, {'frame': int(at), 'original': int(start)})
    return add_pose(out, at + (end - start) + 1, last_pose)


def change_frames(changes: list) -> list:
    return [c['frame'] for c in changes]


def pose_values(pose: dict) -> dict:
    return {k: (tuple(v[:3]), tuple(v[3:])) for k, v in pose.items()}


def _slerp(a, b, t: float):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-c for c in b), -dot
    if dot > 0.9995:
        return _normalise(tuple(x + (y - x) * t for x, y in zip(a, b)))
    theta = math.acos(min(1.0, dot))
    sa, sb = math.sin((1 - t) * theta) / math.sin(theta), math.sin(t * theta) / math.sin(theta)
    return tuple(x * sa + y * sb for x, y in zip(a, b))


def sample(clip: Clip | None, frame: float, defaults: dict) -> dict:
    """{key: (position, rotation)} of *clip* at *frame* (blended between its frames, held after
    its last one); keys it lacks take *defaults*."""
    out = dict(defaults)
    if clip is None or not clip.frames:
        return out
    frames = clip.frames
    before = frames[0]
    after = frames[-1]
    for entry in frames:
        if entry[0] <= frame:
            before = entry
        if entry[0] >= frame:
            after = entry
            break
    span = after[0] - before[0]
    t = (frame - before[0]) / span if span > 0 else 0.0
    for key in set(before[1]) | set(after[1]):
        a = before[1].get(key, after[1].get(key))
        b = after[1].get(key, a)
        out[key] = (tuple(x + (y - x) * t for x, y in zip(a[0], b[0])), _slerp(a[1], b[1], t))
    return out


# --- Maths ----------------------------------------------------------------------------------

def _compose(a, b):
    """World (position, rotation) of transform *b* under *a*."""
    position, rotation = a
    offset = anim.quat_rotate(rotation, b[0])
    return (tuple(p + o for p, o in zip(position, offset)), anim.quat_mul(rotation, b[1]))


def _inverse(t):
    position, rotation = t
    inverse = anim.quat_conj(rotation)
    return (tuple(-c for c in anim.quat_rotate(inverse, position)), inverse)


def _normalise(q):
    length = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / length for c in q)


# --- Where the arms sit ---------------------------------------------------------------------

def arms_offset(arms: dict):
    """(position in skeleton units, rotation) of a weapon's arms entry, or None when they sit
    where the game puts them."""
    if not arms:
        return None
    location = tuple(float(c) * anim.SKEL_SCALE for c in arms.get('location', (0.0, 0.0, 0.0)))
    rotation = _normalise(tuple(arms.get('rotation', (1.0, 0.0, 0.0, 0.0))))
    if max(abs(c) for c in location) < 1e-6 and abs(abs(rotation[0]) - 1.0) < 1e-9:
        return None
    return location, rotation


def offset_arms(clip: Clip, bones, offset) -> Clip:
    """An arms clip moved by *offset* (in front of the camera): the bones under the root take it
    (the root stays at the origin, where the game keeps it in every animation)."""
    root = next((i for i, b in enumerate(bones) if not b.parent), 0)
    children = [str(i) for i, b in enumerate(bones) if b.parent == bones[root].name]
    frames = []
    for frame, keys in clip.frames:
        out = dict(keys)
        root_key = keys.get(str(root), (tuple(bones[root].position), tuple(bones[root].rotation)))
        for key in children:
            local = keys.get(key, (tuple(bones[int(key)].position), tuple(bones[int(key)].rotation)))
            world = _compose(offset, _compose(root_key, local))
            moved = _compose(_inverse(root_key), world)
            out[key] = (moved[0], _normalise(moved[1]))
        frames.append((frame, out))
    return Clip(frames)


# --- The gun's own skeleton -----------------------------------------------------------------

ROOT = 'tag_origin'   # bone 0 of a gun's own skeleton: at the origin, unturned, like every stock gun's


def own_skeleton(model, fit: dict) -> list[anim.Bone]:
    """The gun's skeleton for the game: bone 0 a root at the origin (as every stock gun has),
    then the asset's bones (parents first) placed by the fit in skeleton units, every one turned
    like the fitted asset so animation rotations are the asset's."""
    from . import weapon_model
    names = bone_names(model)
    by_name = {b.name: b for b in model.bones}
    rotation = _normalise(tuple(fit.get('rotation', (1.0, 0.0, 0.0, 0.0))))
    heads = {name: tuple(c * anim.SKEL_SCALE for c in weapon_model.apply_fit(fit, [by_name[name].head])[0])
             for name in names}
    bones = [anim.Bone(iw_hash(ROOT), 0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), None, 0)]
    for number, name in enumerate(names, start=1):
        parent = by_name[name].parent if by_name[name].parent in heads else ''
        if parent:
            offset = tuple(h - p for h, p in zip(heads[name], heads[parent]))
            local = (anim.quat_rotate(anim.quat_conj(rotation), offset), (1.0, 0.0, 0.0, 0.0))
        else:
            local = (heads[name], rotation)
        bones.append(anim.Bone(iw_hash(name), iw_hash(parent or ROOT), local[0], local[1], None,
                               number))
    return bones


def follow_list(model, stock_bones, bone_map: dict) -> list[int]:
    """For each bone of own_skeleton, the stock bone whose motion it takes (the root: the stock
    root)."""
    from . import weapon_model
    return [0] + [weapon_model.bone_index(stock_bones, bone_map.get(name, '#0')) or 0
                  for name in bone_names(model)]


def bone_names(model) -> list[str]:
    """The asset's bone names in own_skeleton's order."""
    by_name = {b.name: b for b in model.bones}
    order, seen = [], set()

    def add(bone):
        if bone.name in seen:
            return
        if bone.parent and bone.parent in by_name:
            add(by_name[bone.parent])
        seen.add(bone.name)
        order.append(bone.name)

    for bone in model.bones:
        add(bone)
    return order


def retarget(stock_bones, stock_anim: anim.Anim, own_bones, own_follow: list[int]) -> Clip:
    """The stock animation moved onto the gun's own skeleton: each own bone moves the way the
    stock bone it follows (*own_follow*, by own bone) moves away from its bind pose, so the result
    is what the stock skeleton does to your model."""
    stock_bind = anim.pose(stock_bones)
    own_bind = anim.pose(own_bones)
    index_of = {b.name: i for i, b in enumerate(own_bones)}
    frames = []
    for keyframe in stock_anim.keyframes:
        stock_now = anim.pose(stock_bones, keyframe)
        worlds = []
        for i, bone in enumerate(own_bones):
            s = own_follow[i] if i < len(own_follow) and 0 <= own_follow[i] < len(stock_bones) else 0
            delta = _compose(stock_now[s], _inverse(stock_bind[s]))
            worlds.append(_compose(delta, own_bind[i]))
        keys = {}
        for i, bone in enumerate(own_bones):
            parent = index_of.get(bone.parent)
            local = _compose(_inverse(worlds[parent]), worlds[i]) if parent is not None else worlds[i]
            keys[i] = (local[0], _normalise(local[1]))
        frames.append((frame_of(keyframe.time), keys))
    return Clip(_dedupe(frames))


def _dedupe(frames):
    out = {}
    for frame, keys in frames:
        out[frame] = keys
    return sorted(out.items())


def stock_clip(stock_anim: anim.Anim, bones) -> Clip:
    """A stock animation as a clip (every bone, bind values where it has no key)."""
    frames = []
    for keyframe in stock_anim.keyframes:
        keys = {}
        for i, bone in enumerate(bones):
            position, rotation = bone.position, bone.rotation
            if i in keyframe.keys:
                key_position, rotation = keyframe.keys[i]
                if key_position is not None:
                    position = key_position
            keys[i] = (tuple(position), _normalise(tuple(rotation)))
        frames.append((frame_of(keyframe.time), keys))
    return Clip(_dedupe(frames))


def encode_clip(clip: Clip, skeleton: int, bones, keys_of, template: bytes | None) -> bytes:
    """A CIwAnim for *clip* on *bones* (skeleton hash *skeleton*): every bone keyed at every
    frame, in bone order. *keys_of(frame bones)* turns the clip's keys into {bone index: key}."""
    keyframes = []
    for frame, keys in clip.frames:
        by_index = keys_of(keys)
        full = {}
        for i, bone in enumerate(bones):
            full[i] = by_index.get(i, (tuple(bone.position), tuple(bone.rotation)))
        keyframes.append(anim.Keyframe(full, time_of(frame), template or b'', list(range(len(bones)))))
    if not keyframes:
        raise WeaponAnimError('a clip needs at least one keyframe')
    animation = anim.Anim(skeleton, len(bones), keyframes)
    return anim.encode_anim(animation, template)


def asset_skeleton(model) -> list[anim.Bone]:
    """The asset's bones in its own space (the editor's gun armature, before the fit): positions
    in the asset's units relative to the parent, no turn."""
    by_name = {b.name: b for b in model.bones}
    bones = []
    for number, name in enumerate(bone_names(model)):
        bone = by_name[name]
        parent = bone.parent if bone.parent in by_name else ''
        head = tuple(bone.head)
        offset = tuple(h - p for h, p in zip(head, by_name[parent].head)) if parent else head
        bones.append(anim.Bone(iw_hash(name), iw_hash(parent) if parent else 0, offset,
                               (1.0, 0.0, 0.0, 0.0), None, number))
    return bones


def _fit_parts(fit: dict):
    scale = float(fit.get('scale', 1.0))
    rotation = _normalise(tuple(fit.get('rotation', (1.0, 0.0, 0.0, 0.0))))
    location = tuple(c * anim.SKEL_SCALE for c in fit.get('location', (0.0, 0.0, 0.0)))
    return scale * anim.SKEL_SCALE, rotation, location


def _tops(model) -> set:
    names = set(bone_names(model))
    return {b.name for b in model.bones if not b.parent or b.parent not in names}


def gun_clip_to_game(clip: Clip, model, fit: dict) -> Clip:
    """A gun clip made in the editor (bones by name, the asset's space and units) on the game's
    own skeleton (bones by number, skeleton units, the fit baked in: the bones under the root
    take it, every position its scale; the root stays at the origin)."""
    scale, rotation, location = _fit_parts(fit)
    names = bone_names(model)
    index = {name: i + 1 for i, name in enumerate(names)}
    tops = _tops(model)
    frames = []
    for frame, keys in clip.frames:
        out = {0: ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))}
        for name, (position, q) in keys.items():
            if name not in index:
                continue
            scaled = tuple(c * scale for c in position)
            if name in tops:
                out[index[name]] = (tuple(l + c for l, c in zip(location, anim.quat_rotate(rotation, scaled))),
                                    _normalise(anim.quat_mul(rotation, q)))
            else:
                out[index[name]] = (scaled, _normalise(tuple(q)))
        frames.append((frame, out))
    return Clip(frames)


def game_clip_to_asset(clip: Clip, model, fit: dict) -> Clip:
    """The inverse of gun_clip_to_game (to show a stock animation on the editor's gun). The
    root's motion (a stock root that moves) goes into the bones under it."""
    scale, rotation, location = _fit_parts(fit)
    inverse = anim.quat_conj(rotation)
    names = bone_names(model)
    tops = _tops(model)
    frames = []
    for frame, keys in clip.frames:
        root = keys.get(0, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)))
        out = {}
        for i, (position, q) in keys.items():
            if not 1 <= i <= len(names):
                continue
            name = names[i - 1]
            if name in tops:
                position, q = _compose(root, (position, q))
                local = anim.quat_rotate(inverse, tuple(p - l for p, l in zip(position, location)))
                out[name] = (tuple(c / scale for c in local), _normalise(anim.quat_mul(inverse, q)))
            else:
                out[name] = (tuple(c / scale for c in position), _normalise(tuple(q)))
        frames.append((frame, out))
    return Clip(frames)
