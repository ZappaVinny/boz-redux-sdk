"""Your own model on a weapon: an asset (bozkit.assets, kind weapon) in place of a stock gun's
model, riding the stock gun's skeleton, animations and state machines.

A weapon's ``model`` (bozkit.weapons.WeaponDef) says::

    {"asset": "idgun",
     "fit": {"location": [x, y, z], "rotation": [w, x, y, z], "scale": s},
     "bones": {"tag_clip": "J_Clip", "tag_flash": "TAG_FLASH", ...}}

The fit places the asset (its stored units, game axes) in the stock gun's model space:
``model = location + rotation * (scale * asset)``. Each asset bone follows a stock bone (by name,
or "#<index>" for a bone without a known name); a part on an unmapped bone follows the root.

``build`` makes the weapon's resources: the view model and its skin (vertices seen from the stock
bones in their bind pose, so the stock animations move the parts), the model shown while aiming
down the sights, three distance models (LODs), their materials and textures. The weapon's spec
then points renderableAsset, renderableAssetADS and LODS at them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import anim, native
from .hashing import iw_hash

SKINNED_FLAGS = 0x30000      # every shipped skinned model (rigid ones: 0x20000)
LEVELS = ('ads', 'lod0', 'lod1', 'lod2')
# Stock gun bone names (the skeletons keep only hashes; found by hashing the names).
BONE_NAMES = ('J_Gun', 'J_BOLT', 'J_Charging_Handle', 'J_Clip', 'J_GRIP', 'J_SHELL_BOTTOM',
              'J_STOCK', 'J_Shell_Top', 'J_Sight_Front', 'J_TRIGGER', 'TAG_BRASS', 'TAG_DRUM',
              'TAG_KNOB', 'Tag_Dial', 'Tag_Flash2', 'Tag_Light', 'Tag_Pump2', 'j_clip_release',
              'j_pump', 'j_slide', 'tag_ammo2', 'tag_brass2', 'tag_clip', 'tag_clip2', 'tag_flash',
              'tag_grip', 'tag_pump', 'tag_rear_sight', 'tag_stock')
_BONE_LABELS = {iw_hash(name): name for name in BONE_NAMES}
# Asset bone -> stock bones it follows by default (first found).
DEFAULT_BONES = {
    'tag_weapon': ('#0',),
    'tag_clip': ('J_Clip', 'tag_clip', '@reload'),
    'tag_flash': ('tag_flash',),
    'tag_brass': ('TAG_BRASS', 'tag_brass2'),
}


class WeaponModelError(ValueError):
    pass


def bone_label(bones: list[anim.Bone], index: int) -> str:
    return _BONE_LABELS.get(bones[index].name, f'bone {index}')


def bone_key(bones: list[anim.Bone], index: int) -> str:
    """How a weapon file names a stock bone: its name when known, else '#<index>'."""
    return _BONE_LABELS.get(bones[index].name, f'#{index}')


def bone_index(bones: list[anim.Bone], key: str) -> int | None:
    if key.startswith('#'):
        try:
            index = int(key[1:])
        except ValueError:
            return None
        return index if 0 <= index < len(bones) else None
    wanted = iw_hash(key)
    return next((i for i, b in enumerate(bones) if b.name == wanted), None)


def reload_mover(bones: list[anim.Bone], reload_anim: anim.Anim | None) -> int | None:
    """The bone the reload moves furthest from where it starts (a magazine, a canister): the part
    a magazine should follow on a gun without a J_Clip."""
    if reload_anim is None or not reload_anim.keyframes:
        return None
    start = anim.pose(bones, reload_anim.keyframes[0])
    best, distance = None, 0.0
    for keyframe in reload_anim.keyframes[1:]:
        for index, (position, _rotation) in enumerate(anim.pose(bones, keyframe)):
            moved = math.dist(position, start[index][0])
            if index and moved > distance:
                best, distance = index, moved
    return best


def default_bones(asset_bones: list[str], bones: list[anim.Bone], mover: int | None) -> dict:
    """Each asset bone's stock bone: the usual pairs (tag_clip -> J_Clip, or the bone the reload
    moves most), the same name, else the root."""
    out = {}
    for name in asset_bones:
        choices = DEFAULT_BONES.get(name.lower(), ()) + (name,)
        index = None
        for choice in choices:
            if choice == '@reload':
                index = mover
            else:
                index = bone_index(bones, choice)
                if index is None and not choice.startswith('#'):
                    index = next((i for i, b in enumerate(bones)
                                  if _BONE_LABELS.get(b.name, '').lower() == choice.lower()), None)
            if index is not None:
                break
        out[name] = bone_key(bones, index if index is not None else 0)
    return out


# --- Fitting --------------------------------------------------------------------------------

def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _norm(v):
    length = math.sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v) if length > 1e-9 else (0.0, 0.0, 0.0)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _quat_between(a, b):
    """The shortest rotation (w, x, y, z) turning direction *a* into *b*."""
    a, b = _norm(a), _norm(b)
    d = _dot(a, b)
    if d < -0.999999:
        axis = _cross((1.0, 0.0, 0.0), a)
        if math.sqrt(_dot(axis, axis)) < 1e-6:
            axis = _cross((0.0, 1.0, 0.0), a)
        axis = _norm(axis)
        return (0.0, *axis)
    axis = _cross(a, b)
    q = (1.0 + d, *axis)
    length = math.sqrt(_dot(q, q))
    return tuple(c / length for c in q)


def _quat_axis(axis, angle):
    axis = _norm(axis)
    s = math.sin(angle / 2)
    return (math.cos(angle / 2), axis[0] * s, axis[1] * s, axis[2] * s)


def bind_point(bones: list[anim.Bone], index: int):
    """A stock bone's bind position in model units."""
    return tuple(c / anim.SKEL_SCALE for c in anim.pose(bones)[index][0])


def auto_fit(asset_heads: dict, asset_vertices, bones: list[anim.Bone], stock_vertices) -> dict:
    """A fit that lines the asset up with the stock gun: its barrel (tag_weapon -> tag_flash)
    along the stock gun's forward axis (the model axis its muzzle bone lies furthest along),
    upright, as long as the stock gun along that axis and centred on it. Without those tags, the
    two models' longest bounding-box axes line up instead."""
    lower = {k.lower(): v for k, v in asset_heads.items()}
    flash = bone_index(bones, 'tag_flash')     # bone names hash without case
    if 'tag_flash' in lower and flash is not None:
        a0 = lower.get('tag_weapon', (0.0, 0.0, 0.0))
        a1 = lower['tag_flash']
        s0, s1 = bind_point(bones, 0), bind_point(bones, flash)
    else:
        a0, a1 = _long_axis(asset_vertices)
        s0, s1 = _long_axis(stock_vertices)
    stock_dir = _sub(s1, s0)
    axis = max(range(3), key=lambda i: abs(stock_dir[i]))
    forward = tuple((1.0 if stock_dir[axis] > 0 else -1.0) if i == axis else 0.0 for i in range(3))
    asset_dir = _sub(a1, a0)
    length = math.sqrt(_dot(asset_dir, asset_dir))
    scale = abs(stock_dir[axis]) / length if length > 1e-9 else 1.0
    rotation = _quat_between(asset_dir, forward)
    # Roll around the barrel so the asset's up (game +Y) is as close to up as it can be.
    up = anim.quat_rotate(rotation, (0.0, 1.0, 0.0))
    up = _norm(_sub(up, tuple(forward[i] * _dot(up, forward) for i in range(3))))
    want = _norm(_sub((0.0, 1.0, 0.0), tuple(forward[i] * forward[1] for i in range(3))))
    if up != (0.0, 0.0, 0.0) and want != (0.0, 0.0, 0.0):
        angle = math.atan2(_dot(_cross(up, want), forward), _dot(up, want))
        rotation = anim.quat_mul(_quat_axis(forward, angle), rotation)
    # Size and place it by the bounds: as long as the stock gun along the barrel, centred on it,
    # where the player sees the stock gun (the tags of ripped models rarely sit where a stock
    # gun's bones do).
    turned = [anim.quat_rotate(rotation, v) for v in asset_vertices] if asset_vertices else []
    if turned and stock_vertices:
        asset_low = [min(v[i] for v in turned) for i in range(3)]
        asset_high = [max(v[i] for v in turned) for i in range(3)]
        stock_low = [min(v[i] for v in stock_vertices) for i in range(3)]
        stock_high = [max(v[i] for v in stock_vertices) for i in range(3)]
        span = asset_high[axis] - asset_low[axis]
        if span > 1e-9:
            scale = (stock_high[axis] - stock_low[axis]) / span
        location = tuple((stock_low[i] + stock_high[i]) / 2 - (asset_low[i] + asset_high[i]) / 2 * scale
                         for i in range(3))
    else:
        location = _sub(s0, anim.quat_rotate(rotation, tuple(c * scale for c in a0)))
    return {'location': [round(c, 3) for c in location],
            'rotation': [round(c, 6) for c in rotation], 'scale': round(scale, 6)}


def _long_axis(vertices):
    """The two ends of a model's longest bounding-box axis (through the box's centre)."""
    lows = [min(v[i] for v in vertices) for i in range(3)]
    highs = [max(v[i] for v in vertices) for i in range(3)]
    axis = max(range(3), key=lambda i: highs[i] - lows[i])
    centre = [(lo + hi) / 2 for lo, hi in zip(lows, highs)]
    a, b = list(centre), list(centre)
    a[axis], b[axis] = lows[axis], highs[axis]
    return tuple(a), tuple(b)


def apply_fit(fit: dict, points):
    location = tuple(fit.get('location', (0.0, 0.0, 0.0)))
    rotation = tuple(fit.get('rotation', (1.0, 0.0, 0.0, 0.0)))
    scale = float(fit.get('scale', 1.0))
    return [tuple(l + c for l, c in zip(location, anim.quat_rotate(rotation, tuple(p * scale for p in point))))
            for point in points]


# --- Building ---------------------------------------------------------------------------------

@dataclass
class Built:
    resources: list = field(default_factory=list)   # (class name, hash, body)
    view: int = 0
    ads: int = 0
    lods: list = field(default_factory=list)


def skinned(model, fit: dict, bone_map: dict, bones: list[anim.Bone]):
    """(model-unit vertices, per-vertex [(stock bone, weight)]) of a GameModel-like *model*
    (vertices, weights, bones) on the stock skeleton."""
    vertices = apply_fit(fit, model.vertices)
    stock = []
    for asset_bone in model.bones:
        index = bone_index(bones, bone_map.get(asset_bone.name, '#0'))
        stock.append(index if index is not None else 0)
    weights = []
    for vertex in range(len(model.vertices)):
        own = model.weights[vertex] if vertex < len(model.weights) else []
        weights.append([(stock[b] if b < len(stock) else 0, w) for b, w in own] or [(0, 1.0)])
    return vertices, weights


def build(weapon: str, model, textures, fit: dict, bone_map: dict, bones: list[anim.Bone],
          skeleton: int, material_template: native.Material, texture_template: bytes) -> Built:
    """The resources for *weapon*'s own model (bozkit.assets.GameModel with its levels)."""
    built = Built()
    materials = []
    for index, texture in enumerate(textures):
        texture_hash = iw_hash(f'{weapon}_tex{index}')
        material_hash = iw_hash(f'{weapon}_mat{index}')
        built.resources.append(('CIwTexture', texture_hash, native.build_texture(
            texture.width, texture.height, texture.bgra, texture_template)))
        if material_template.same_as_default:
            material = native.Material(True, material_template.flags, textures=[texture_hash],
                                       trailer=material_template.trailer)
        else:
            material = native.Material(False, material_template.flags, material_template.unknown,
                                       list(material_template.colours),
                                       [texture_hash] + [0] * (max(1, len(material_template.textures)) - 1),
                                       material_template.trailer)
        built.resources.append(('CIwMaterial', material_hash, native.encode_material(material)))
        materials.append(material_hash)

    def one(name: str, level) -> int:
        vertices, weights = skinned(level, fit, bone_map, bones)
        rounded = [tuple(int(round(c)) for c in v) for v in vertices]
        if any(not -32768 <= c <= 32767 for v in rounded for c in v):
            raise WeaponModelError(f'{weapon}: the fitted model is too big for the game '
                                   '(lower its scale)')
        if len(rounded) > 0x4000:
            raise WeaponModelError(f'{weapon}: {len(rounded)} vertices; a skinned model takes '
                                   'at most 16384 (lower the asset\'s budget)')
        model_hash = iw_hash(name)
        body = bytearray(native.build_model(rounded, level.uvs, level.triangles, materials,
                                            level.materials or None))
        body[0:4] = SKINNED_FLAGS.to_bytes(4, 'little')
        built.resources.append(('CIwModel', model_hash, bytes(body)))
        skin = anim.build_skin(model_hash, skeleton, bones, vertices, weights)
        built.resources.append(('CIwAnimSkin', model_hash, anim.encode_skin(skin)))
        return model_hash

    built.view = one(f'{weapon}_model', model)
    levels = getattr(model, 'levels', {}) or {}
    built.ads = one(f'{weapon}_model_ads', levels['ads']) if 'ads' in levels else built.view
    built.lods = [one(f'{weapon}_model_{key}', levels[key]) if key in levels else built.view
                  for key in ('lod0', 'lod1', 'lod2')]
    return built


def use_on_rig(rig, model, fit: dict, bone_map: dict) -> None:
    """Put *model* (an asset's GameModel) on a viewmodel.Rig in place of the stock gun, skinned
    to its skeleton the way the build does, so the preview plays the stock animations with it."""
    vertices, weights = skinned(model, fit, bone_map, rig.gun_bones)
    skin = anim.build_skin(0, 0, rig.gun_bones, vertices, weights)
    rig.use_model(vertices, skin)
