"""Chalk outlines for wall buys.

In the shipped maps a wall buy's chalk drawing is not part of the wall buy: it is a decal, a
two-triangle quad with its own 128 x 64 texture (white chalk on black), placed in a room group
next to the wall buy. ``find_decals`` finds each weapon's decal and where it sits relative to its
wall buy; ``draw`` makes a chalk texture for any weapon from its model's side silhouette.
"""
from __future__ import annotations

import json
import math
import random
import struct
from dataclasses import dataclass

from . import blender_scene as scene
from . import group, levels, native, resources
from . import maps
from .hashing import iw_hash

SIZE = (128, 64)
CACHE_VERSION = 1
MAX_DISTANCE = 150.0   # centimetres between a wall buy and its decal


@dataclass
class Decal:
    group: str                                   # pack path of the decal's group
    model: int                                   # the decal quad's model
    position: tuple[float, float, float]         # relative to the wall buy's position and rotation
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]

    def as_json(self) -> dict:
        return {'group': self.group, 'model': self.model, 'position': self.position,
                'rotation': self.rotation, 'scale': self.scale}


def _conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])


def compose(position, rotation, scale, decal: Decal):
    """World (position, rotation, scale) of *decal* for a wall buy at *position*, *rotation*,
    with the placement's relative *scale*."""
    offset = tuple(decal.position[i] * scale[i] for i in range(3))
    turned = scene._rotate(rotation, offset)
    return (tuple(position[i] + turned[i] for i in range(3)),
            scene._quat_mul(rotation, decal.rotation),
            tuple(decal.scale[i] * scale[i] for i in range(3)))


def _weapon_of(spec) -> int | None:
    for _cls, _reserved, child in spec.children:
        renderable = levels._component(child, 'CIsRenderableModel')
        if renderable is None or renderable.blob is None:
            continue
        for element in levels._blob_prop(renderable.blob, 'assets').elements or ():
            for prop in element.properties:
                if prop.name_hash in (iw_hash('name'), iw_hash('Name')):
                    from . import reflect
                    value = reflect.typed_value(prop)
                    return value if isinstance(value, int) else None
    return None


def find_decals(pack, cache_path=None) -> dict[int, Decal]:
    """Each weapon's chalk decal in the game's levels: weapon name hash -> Decal."""
    if cache_path is not None:
        try:
            data = json.loads(cache_path.read_text())
            if data.get('version') == CACHE_VERSION:
                return {int(k): Decal(v['group'], v['model'], tuple(v['position']),
                                      tuple(v['rotation']), tuple(v['scale']))
                        for k, v in data['decals'].items()}
        except (OSError, ValueError, KeyError):
            pass
    names = pack.names() if hasattr(pack, 'names') else []
    found: dict[int, Decal] = {}
    for level in maps.SHIPPED:
        statics = f'levels/{level}/{level}_statics.group.bin'
        if statics not in names:
            continue
        wall_buys = []
        for item, spec in _specs(group.parse(pack.read(statics))):
            if levels._component(spec, 'CWeaponChalkOutline') is None:
                continue
            weapon = _weapon_of(spec)
            if weapon:
                position, rotation, _scale = scene._local_transform(spec)
                wall_buys.append((weapon, position, rotation))
        if not wall_buys:
            continue
        quads = []   # (group, model, position, rotation, scale)
        for path in names:
            if not (path.startswith(f'levels/{level}/') and path.endswith('.group.bin')):
                continue
            parsed = group.parse(pack.read(path))
            two_triangles = set()
            for resource_type in parsed.types():
                if resource_type.class_hash != levels.MODEL:
                    continue
                for resource in resource_type.resources:
                    if len(resource.body) > 4096:
                        continue
                    try:
                        if len(native.decode_model(resource.body).triangles) == 2:
                            two_triangles.add(resource.in_group_hash)
                    except (ValueError, struct.error, IndexError):
                        pass
            for item, spec in _specs(parsed):
                model = scene._model_reference(spec)
                if model is not None:
                    quads.append((path, model, *scene._local_transform(spec), model in two_triangles))
        for weapon, position, rotation in wall_buys:
            best = None
            for path, model, q_position, q_rotation, q_scale, is_quad in quads:
                if not is_quad:
                    continue
                distance = math.dist(position, q_position)
                if distance <= MAX_DISTANCE and (best is None or distance < best[0]):
                    best = (distance, path, model, q_position, q_rotation, q_scale)
            if best is None or weapon in found:
                continue
            _distance, path, model, q_position, q_rotation, q_scale = best
            inverse = _conjugate(rotation)
            offset = scene._rotate(inverse, tuple(q_position[i] - position[i] for i in range(3)))
            found[weapon] = Decal(path, model, tuple(offset), scene._quat_mul(inverse, q_rotation),
                                  tuple(q_scale))
    if cache_path is not None:
        try:
            cache_path.write_text(json.dumps({'version': CACHE_VERSION, 'decals': {
                str(k): v.as_json() for k, v in found.items()}}))
        except OSError:
            pass
    return found


def _specs(parsed):
    for resource_type in parsed.types():
        if resource_type.class_hash != levels.ENTITY_SPEC:
            continue
        for item in resource_type.resources:
            try:
                yield item, resources.decode_entity_spec(item.body)
            except (ValueError, struct.error):
                continue


def draw(vertices, triangles, seed: int = 0) -> bytes:
    """A 128 x 64 chalk outline (B, G, R, A rows, top first) of a model seen from its side: the
    longest axis across, the next longest up."""
    width, height = SIZE
    extents = [max(v[i] for v in vertices) - min(v[i] for v in vertices) for i in range(3)]
    across = max(range(3), key=lambda i: extents[i])
    up = max((i for i in range(3) if i != across), key=lambda i: extents[i])
    low = [min(v[i] for v in vertices) for i in range(3)]
    margin = 6
    scale = min((width - 2 * margin) / (extents[across] or 1), (height - 2 * margin) / (extents[up] or 1))
    left = (width - extents[across] * scale) / 2
    top = (height - extents[up] * scale) / 2

    def project(v):
        return (left + (v[across] - low[across]) * scale,
                height - (top + (v[up] - low[up]) * scale))

    points = [project(v) for v in vertices]
    mask = bytearray(width * height)
    for a, b, c in triangles:
        (ax, ay), (bx, by), (cx, cy) = points[a], points[b], points[c]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(area) < 1e-9:
            continue
        x0, x1 = max(0, int(min(ax, bx, cx))), min(width - 1, int(max(ax, bx, cx)) + 1)
        y0, y1 = max(0, int(min(ay, by, cy))), min(height - 1, int(max(ay, by, cy)) + 1)
        for y in range(y0, y1 + 1):
            py = y + 0.5
            for x in range(x0, x1 + 1):
                px = x + 0.5
                w0 = (bx - px) * (cy - py) - (by - py) * (cx - px)
                w1 = (cx - px) * (ay - py) - (cy - py) * (ax - px)
                w2 = (ax - px) * (by - py) - (ay - py) * (bx - px)
                if (w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0):
                    mask[y * width + x] = 1
    # The shipped drawings point the barrel left: the barrel is the thinner end.
    columns = [sum(mask[y * width + x] for y in range(height)) for x in range(width)]
    filled = [x for x in range(width) if columns[x]]
    if filled:
        span = max(1, (filled[-1] - filled[0]) // 6)
        start = sum(columns[filled[0]:filled[0] + span])
        end = sum(columns[filled[-1] - span + 1:filled[-1] + 1])
        if end < start:
            mask = bytearray(b''.join(bytes(mask[y * width:(y + 1) * width][::-1])
                                      for y in range(height)))
    edge = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            if not mask[y * width + x]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height) or not mask[ny * width + nx]:
                    edge[y * width + x] = 1
                    break
    # Chalk: a line about two pixels wide, broken here and there, a little uneven.
    rng = random.Random(seed)
    out = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            near = edge[y * width + x] or (x + 1 < width and edge[y * width + x + 1]) or \
                (y + 1 < height and edge[(y + 1) * width + x])
            if near and rng.random() > 0.12:
                value = rng.randint(190, 255)
                out[(y * width + x) * 4:(y * width + x) * 4 + 4] = bytes((value, value, value, 255))
            else:
                out[(y * width + x) * 4 + 3] = 255
    return bytes(out)
