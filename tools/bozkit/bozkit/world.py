"""A map project's world source and the compiler that turns it into the game's groups.

The source lives in the project's ``source/`` folder, as files the editor writes and people can
read::

    source/world.json          what the world is made of (below)
    source/meshes/<n>.json     a level mesh: vertices (centimetres, Y up, world space), UVs,
                               triangles, and per triangle the texture it uses
    source/props/<n>.json      a prop's mesh, in its own space (placed by instances)
    source/textures/<n>.png    textures (power-of-two sides, 4 to 1024); <n>_<i>.png for the
                               second and later textures of a mesh

``world.json`` (format 2; format 1 files still load)::

    {"format": 2,
     "base": "kino",          shipped level giving rounds, zombie types, sounds, cameras, weapons
     "meshes": [{"name": "floor", "file": "meshes/floor.json", "textures": ["textures/floor.png"],
                 "collision": "floor", "double_sided": true}],
     "props": [{"name": "crate", "file": "props/crate.json", "textures": ["textures/crate.png"],
                "collision": "solid", "shape": "box"}],
     "instances": [{"prop": "crate", "position": [0, 0, 300], "yaw": 45},
                   {"model": "ingame/ingame.group.bin#0x1234abcd", "position": [...], "yaw": 0,
                    "collision": "solid", "shape": "box"}],
     "entities": [{"source": "spawn_player_1", "position": [0, 5, 0], "yaw": 0},
                  {"source": "0x9f1e2d3c", "group": "ingame/ingame.group.bin", "position": [...]}]}

- Triangles are in the game's winding; ``double_sided`` also draws their backs.
- ``collision`` is ``floor`` (walked on), ``solid`` (blocks) or ``none``. Floor and solid
  geometry goes into the level's collision and the navmesh is built on top of it. A prop or
  model's ``shape`` is ``box`` (its bounds) or ``mesh`` (its triangles).
- An instance places a project prop, or a model from the game (``<group path>#0x<hash>``),
  which is copied into the level with its materials and textures.
- Entities are copies of the game's entities (perks, spawns, the power switch, ...), by name or
  ``0x`` hash, from the base level's statics or from ``group``. Zombie spawn points among them
  become the starting area's spawns; entities with a model get a solid box in the collision.
"""
from __future__ import annotations

import copy
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import group, levels, png
from .hashing import iw_hash

FORMAT = 2
COLLISION_KINDS = ('floor', 'solid', 'none')
SHAPES = ('box', 'mesh')
NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
SCRIPT_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,47}$')
# An object scripts can change ("script": {...}): its name in the game (CIsNamed, what
# boz.objects finds), and how it starts. Scripted meshes and props get a collision entity of their
# own (<name>_collision) and, when they block, a tagged walkable area instead of a hole, so
# boz.objects can switch both; boz.world applies the start state when the level starts.
SCRIPT_DEFAULTS = {'name': '', 'visible': True, 'collision': True, 'blocks': False}
MAX_TEXTURE = 1024
INGAME = 'ingame/ingame.group.bin'


class WorldError(ValueError):
    pass


@dataclass
class Texture:
    width: int
    height: int
    bgra: bytes

    def check(self, label: str) -> None:
        for side in (self.width, self.height):
            if side < 4 or side > MAX_TEXTURE or side & (side - 1):
                raise WorldError(f'{label}: texture sides must be powers of two from 4 to '
                                 f'{MAX_TEXTURE} (it is {self.width} x {self.height})')
        if len(self.bgra) != self.width * self.height * 4:
            raise WorldError(f'{label}: texture data does not match its size')


@dataclass
class Mesh:
    """Level geometry (world space) or a prop (its own space)."""
    name: str
    vertices: list[tuple[int, int, int]]
    uvs: list[tuple[float, float]]
    triangles: list[tuple[int, int, int]]
    textures: list[Texture]
    collision: str = 'floor'
    double_sided: bool = False
    face_textures: list[int] = field(default_factory=list)  # per triangle; empty: all 0
    shape: str = 'mesh'
    script: dict = field(default_factory=dict)   # level meshes only (SCRIPT_DEFAULTS)

    def faces(self) -> list[int]:
        return self.face_textures or [0] * len(self.triangles)

    def model_triangles(self) -> tuple[list[tuple[int, int, int]], list[int]]:
        """Triangles and their texture slots as drawn (backs added when double-sided)."""
        triangles, faces = list(self.triangles), self.faces()
        if self.double_sided:
            return triangles + [(a, c, b) for a, b, c in triangles], faces + faces
        return triangles, list(faces)


UNIT = (1.0, 1.0, 1.0)


def _yaw_quaternion(degrees: float) -> tuple[float, float, float, float]:
    import math
    half = math.radians(degrees) / 2
    return (0.0, math.sin(half), 0.0, math.cos(half))


@dataclass
class Instance:
    """A placed prop (``prop``) or game model (``model``: '<group path>#0x<hash>')."""
    position: tuple[float, float, float]
    yaw: float = 0.0
    prop: str = ''
    model: str = ''
    collision: str = 'solid'   # for game models; props have their own
    shape: str = 'box'
    rotation: tuple[float, float, float, float] | None = None   # x, y, z, w; None: from yaw
    scale: tuple[float, float, float] = UNIT
    script: dict = field(default_factory=dict)   # SCRIPT_DEFAULTS

    def model_ref(self) -> tuple[str, int]:
        path, _, value = self.model.partition('#')
        return path, int(value, 16)

    def quaternion(self) -> tuple[float, float, float, float]:
        return tuple(self.rotation) if self.rotation else _yaw_quaternion(self.yaw)


@dataclass
class Placement:
    source: str                              # entity name, or 0x hash
    position: tuple[float, float, float]
    yaw: float = 0.0
    group: str = ''                          # pack path of its group; empty: the base statics
    rotation: tuple[float, float, float, float] | None = None   # x, y, z, w; None: from yaw
    scale: tuple[float, float, float] = UNIT
    prop: str = ''                           # a project prop drawn instead of its own model
    model: str = ''                          # or a game model ('<group path>#0x<hash>')
    fields: dict = field(default_factory=dict)   # "Component.field": value overrides
    piece: str = ''                          # the toolkit piece it was placed as (bozkit.toolkit)
    settings: dict = field(default_factory=dict)  # the piece's settings as the editor shows them
    chalk_texture: Texture | None = field(default=None, compare=False, repr=False)  # boz.chalk image
    script: dict = field(default_factory=dict)   # SCRIPT_DEFAULTS; a copy's name is script name

    @property
    def hash(self) -> int:
        return int(self.source, 16) if self.source.startswith('0x') else iw_hash(self.source)

    def quaternion(self) -> tuple[float, float, float, float]:
        return tuple(self.rotation) if self.rotation else _yaw_quaternion(self.yaw)


@dataclass
class World:
    base: str = 'kino'
    meshes: list[Mesh] = field(default_factory=list)
    entities: list[Placement] = field(default_factory=list)
    props: list[Mesh] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    inherit: bool = False    # start from the whole base level (its rooms, entities, navmesh)
    removed: list[str] = field(default_factory=list)   # base level entities taken out (0x hashes)


# Files


def _bgra_to_rgba(bgra: bytes) -> bytes:
    out = bytearray(bgra)
    out[0::4], out[2::4] = bgra[2::4], bgra[0::4]
    return bytes(out)


def read_texture(path: Path) -> Texture:
    """A PNG as a texture (Pillow when available, else bozkit.png)."""
    try:
        from PIL import Image
    except ImportError:
        width, height, rgba = png.read_rgba(path.read_bytes())
        return Texture(width, height, _bgra_to_rgba(rgba))  # the same swap both ways
    image = Image.open(path).convert('RGBA')
    return Texture(image.width, image.height, image.tobytes('raw', 'BGRA'))


def write_texture(texture: Texture, path: Path) -> None:
    path.write_bytes(png.write_rgba(texture.width, texture.height, _bgra_to_rgba(texture.bgra)))


def _texture_files(name: str, count: int) -> list[str]:
    return [f'textures/{name}.png' if i == 0 else f'textures/{name}_{i}.png' for i in range(count)]


def _write_mesh(source: Path, folder: str, mesh: Mesh) -> dict:
    data = {'vertices': [list(v) for v in mesh.vertices],
            'uvs': [[round(u, 6), round(v, 6)] for u, v in mesh.uvs],
            'triangles': [list(t) for t in mesh.triangles]}
    if any(mesh.face_textures):
        data['materials'] = list(mesh.face_textures)
    (source / folder / f'{mesh.name}.json').write_text(json.dumps(data, separators=(',', ':'))
                                                       + '\n', encoding='utf-8')
    files = _texture_files(mesh.name, len(mesh.textures))
    for texture, relative in zip(mesh.textures, files):
        write_texture(texture, source / relative)
    item = {'name': mesh.name, 'file': f'{folder}/{mesh.name}.json', 'textures': files,
            'collision': mesh.collision}
    if folder == 'props':
        item['shape'] = mesh.shape
    item['double_sided'] = mesh.double_sided
    if mesh.script:
        item['script'] = _script_json(mesh.script)
    return item


def script_of(item) -> dict:
    """The script settings of a mesh, instance or entity with the defaults filled in ({} when
    scripts do not change it)."""
    if not item.script:
        return {}
    return {**SCRIPT_DEFAULTS, **item.script}


def _script_json(script: dict) -> dict:
    return {key: value for key, value in script.items()
            if key == 'name' or SCRIPT_DEFAULTS.get(key) != value}


def _transform_json(item) -> dict:
    out = {'position': [round(c, 3) for c in item.position]}
    if item.rotation:
        out['rotation'] = [round(c, 6) for c in item.rotation]
    else:
        out['yaw'] = item.yaw
    if tuple(item.scale) != UNIT:
        out['scale'] = [round(c, 5) for c in item.scale]
    return out


def _transform_args(item: dict) -> dict:
    rotation = item.get('rotation')
    return {'position': tuple(float(c) for c in item['position']),
            'yaw': float(item.get('yaw', 0.0)),
            'rotation': tuple(float(c) for c in rotation) if rotation else None,
            'scale': tuple(float(c) for c in item.get('scale', UNIT))}


def _lines(key: str, items: list[dict], last: bool = False) -> list[str]:
    lines = [f'  "{key}": [']
    lines += [f'    {json.dumps(item)}' + (',' if i < len(items) - 1 else '')
              for i, item in enumerate(items)]
    return lines + ['  ]' + ('' if last else ',')]


def save(world: World, source: str | Path) -> None:
    """Write *world* into a project's source folder, removing files it no longer uses."""
    source = Path(source)
    wanted = set()
    for folder in ('meshes', 'props', 'textures'):
        (source / folder).mkdir(parents=True, exist_ok=True)
    meshes = [_write_mesh(source, 'meshes', mesh) for mesh in world.meshes]
    props = [_write_mesh(source, 'props', prop) for prop in world.props]
    for item in meshes + props:
        wanted.add(item['file'])
        wanted.update(item['textures'])
    for folder in ('meshes', 'props', 'textures'):
        for old in (source / folder).iterdir():
            if old.suffix in ('.json', '.png') and f'{folder}/{old.name}' not in wanted:
                old.unlink()
    instances = []
    for item in world.instances:
        entry = {'prop': item.prop} if item.prop else {
            'model': item.model, 'collision': item.collision, 'shape': item.shape}
        entry.update(_transform_json(item))
        if item.script:
            entry['script'] = _script_json(item.script)
        instances.append(entry)
    entities = []
    for entity in world.entities:
        entry = {'source': entity.source}
        if entity.group:
            entry['group'] = entity.group
        if entity.piece:
            entry['piece'] = entity.piece
        if entity.prop:
            entry['prop'] = entity.prop
        if entity.model:
            entry['model'] = entity.model
        if entity.settings:
            entry['settings'] = entity.settings
        if entity.fields:
            entry['fields'] = entity.fields
        if entity.script:
            entry['script'] = _script_json(entity.script)
        entry.update(_transform_json(entity))
        entities.append(entry)
    # One line per item, so the file stays readable and diffs stay small.
    lines = ['{', f'  "format": {FORMAT},', f'  "base": {json.dumps(world.base)},']
    if world.inherit:
        lines.append('  "inherit": true,')
    if world.removed:
        lines.append(f'  "removed": {json.dumps(sorted(world.removed))},')
    lines += _lines('meshes', meshes) + _lines('props', props) + _lines('instances', instances)
    lines += _lines('entities', entities, last=True) + ['}']
    (source / 'world.json').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _inside(source: Path, relative: str) -> Path:
    path = (source / relative).resolve()
    if source.resolve() not in path.parents:
        raise WorldError(f'{relative} is outside the source folder')
    return path


def _read_mesh(source: Path, item: dict, default_collision: str) -> Mesh:
    name = str(item.get('name', ''))
    try:
        geometry = json.loads(_inside(source, item['file']).read_text(encoding='utf-8'))
        files = item.get('textures') or [item['texture']]
        textures = [read_texture(_inside(source, relative)) for relative in files]
    except (KeyError, OSError, ValueError) as exc:
        raise WorldError(f'{name!r}: {exc}') from exc
    return Mesh(name, [tuple(int(round(c)) for c in v) for v in geometry['vertices']],
                [tuple(map(float, uv)) for uv in geometry['uvs']],
                [tuple(map(int, t)) for t in geometry['triangles']], textures,
                str(item.get('collision', default_collision)), bool(item.get('double_sided', False)),
                [int(i) for i in geometry.get('materials', [])], str(item.get('shape', 'mesh')),
                dict(item.get('script', {})))


def load(source: str | Path) -> World:
    source = Path(source)
    try:
        data = json.loads((source / 'world.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise WorldError(f'{source / "world.json"} not found: this map has no world yet') from None
    except (OSError, ValueError) as exc:
        raise WorldError(f'cannot read world.json: {exc}') from exc
    if data.get('format') not in (1, FORMAT):
        raise WorldError(f'world.json format {data.get("format")!r} is not supported')
    world = World(str(data.get('base', 'kino')), inherit=bool(data.get('inherit', False)),
                  removed=[str(item) for item in data.get('removed', [])])
    world.meshes = [_read_mesh(source, item, 'floor') for item in data.get('meshes', [])]
    world.props = [_read_mesh(source, item, 'solid') for item in data.get('props', [])]
    try:
        for item in data.get('instances', []):
            world.instances.append(Instance(
                prop=str(item.get('prop', '')), model=str(item.get('model', '')),
                collision=str(item.get('collision', 'solid')), shape=str(item.get('shape', 'box')),
                script=dict(item.get('script', {})), **_transform_args(item)))
        for item in data.get('entities', []):
            world.entities.append(Placement(str(item['source']), group=str(item.get('group', '')),
                                            prop=str(item.get('prop', '')),
                                            model=str(item.get('model', '')),
                                            piece=str(item.get('piece', '')),
                                            settings=dict(item.get('settings', {})),
                                            fields=dict(item.get('fields', {})),
                                            script=dict(item.get('script', {})),
                                            **_transform_args(item)))
    except (KeyError, TypeError, ValueError) as exc:
        raise WorldError(f'world.json: {exc}') from exc
    for entity in world.entities:
        image = entity.settings.get(CHALK_FIELD, '')
        if isinstance(image, str) and image not in ('', 'none'):
            try:
                entity.chalk_texture = read_texture(_inside(source, image))
            except (OSError, ValueError) as exc:
                raise WorldError(f'{entity.source}: chalk image {image}: {exc}') from exc
    return world


def _check_mesh(mesh: Mesh, label: str, problems: list[str]) -> None:
    if not NAME_RE.fullmatch(mesh.name):
        problems.append(f'{label}: names use a-z, 0-9 and _ (at most 32, starting with a letter)')
    if mesh.collision not in COLLISION_KINDS:
        problems.append(f'{label}: collision must be floor, solid or none')
    if mesh.shape not in SHAPES:
        problems.append(f'{label}: shape must be box or mesh')
    if len(mesh.uvs) != len(mesh.vertices):
        problems.append(f'{label}: needs one UV per vertex')
    if len(mesh.vertices) > 0xFFFF:
        problems.append(f'{label}: more than 65535 vertices; split it')
    if any(not -32768 <= c <= 32767 for v in mesh.vertices for c in v):
        problems.append(f'{label}: vertices must stay within ±327 m of its origin')
    if any(not -8.0 <= c < 8.0 for uv in mesh.uvs for c in uv):
        problems.append(f'{label}: texture coordinates must stay between -8 and 8 (the texture '
                        'repeats at most 8 times across it); scale its UVs down')
    if any(i >= len(mesh.vertices) or i < 0 for t in mesh.triangles for i in t):
        problems.append(f'{label}: a triangle uses a vertex that does not exist')
    if not mesh.textures:
        problems.append(f'{label}: needs a texture')
    if mesh.face_textures and (len(mesh.face_textures) != len(mesh.triangles)
                               or max(mesh.face_textures) >= len(mesh.textures)):
        problems.append(f'{label}: a triangle uses a texture that does not exist')
    for texture in mesh.textures:
        try:
            texture.check(label)
        except WorldError as exc:
            problems.append(str(exc))


def validate(world: World) -> list[str]:
    """Problems that would stop the world from compiling."""
    problems = []
    if world.base not in levels.SHIPPED_LEVELS:
        problems.append(f'base level {world.base!r} is not one of the game\'s levels')
    names = [mesh.name for mesh in world.meshes + world.props]
    for mesh in world.meshes:
        _check_mesh(mesh, f'mesh {mesh.name!r}', problems)
    for prop in world.props:
        _check_mesh(prop, f'prop {prop.name!r}', problems)
    for name in set(names):
        if names.count(name) > 1:
            problems.append(f'{name!r}: two meshes or props have this name')
    props = {prop.name for prop in world.props}
    for instance in world.instances:
        if instance.prop and instance.prop not in props:
            problems.append(f'an instance places prop {instance.prop!r}, which does not exist')
        elif not instance.prop:
            try:
                instance.model_ref()
            except ValueError:
                problems.append(f'instance model {instance.model!r} is not <group path>#0x<hash>')
            if instance.collision not in COLLISION_KINDS or instance.shape not in SHAPES:
                problems.append(f'instance of {instance.model!r}: bad collision or shape')
    for entity in world.entities:
        if entity.model:
            try:
                Instance((0.0, 0.0, 0.0), model=entity.model).model_ref()
            except ValueError:
                problems.append(f'entity {entity.source!r}: model {entity.model!r} is not '
                                '<group path>#0x<hash>')
        if entity.prop and entity.prop not in props:
            problems.append(f'entity {entity.source!r} draws prop {entity.prop!r}, which does not exist')
    script_names = []
    for item in world.meshes + world.instances + world.entities:
        name = script_of(item).get('name', '')
        if item.script and not SCRIPT_NAME_RE.fullmatch(name):
            problems.append(f'script name {name!r}: use letters, digits and _ (at most 48, '
                            'starting with a letter)')
        if name:
            script_names.append(name.lower())
    for name in set(script_names):
        if script_names.count(name) > 1:
            problems.append(f'{name!r}: two objects have this script name')
    if world.inherit:   # the base level brings its floors and spawns
        return sorted(set(problems), key=problems.index)
    if not any(entity.source.startswith('spawn_player_') for entity in world.entities):
        problems.append('the world needs a player spawn (spawn_player_1)')
    if not any(mesh.collision == 'floor' for mesh in world.meshes + world.props):
        problems.append('the world needs a floor mesh to walk on')
    return sorted(set(problems), key=problems.index)


# Templates


def _quads(quads):
    """(vertices, uvs, triangles) for quads given as (four corners, v offset): each quad is
    textured once, using the half of the texture from v offset."""
    vertices, uvs, triangles = [], [], []
    for corners, v0 in quads:
        base = len(vertices)
        vertices.extend(corners)
        uvs.extend([(0.0, v0), (1.0, v0), (1.0, v0 + 0.5), (0.0, v0 + 0.5)])
        triangles.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    return vertices, uvs, triangles


def _floor_quads(half: int, cell: int):
    steps = range(-half, half, cell)
    return [(((x, 0, z), (x + cell, 0, z), (x + cell, 0, z + cell), (x, 0, z + cell)), 0.0)
            for x in steps for z in steps]


def _wall_quads(half: int, cell: int, top: int):
    quads = []
    for s in range(-half, half, cell):
        for y in range(0, top, cell):
            y2 = min(y + cell, top)
            quads += [(((s, y, -half), (s + cell, y, -half), (s + cell, y2, -half), (s, y2, -half)), 0.5),
                      (((s, y, half), (s + cell, y, half), (s + cell, y2, half), (s, y2, half)), 0.5),
                      (((-half, y, s), (-half, y, s + cell), (-half, y2, s + cell), (-half, y2, s)), 0.5),
                      (((half, y, s), (half, y, s + cell), (half, y2, s + cell), (half, y2, s)), 0.5)]
    return quads


def _arena_texture() -> Texture:
    return Texture(128, 128, levels.arena_texture(128))


def _player_spawns(spread: int = 100) -> list[Placement]:
    return [Placement(f'spawn_player_{number}', (float(x), 5.0, float(z)))
            for number, (x, z) in enumerate(((-spread, -spread), (spread, -spread),
                                             (-spread, spread), (spread, spread)), 1)]


def empty_world(base: str = 'kino') -> World:
    """A 6 m floor tile and the four player spawns: nothing else to start from."""
    vertices, uvs, triangles = _quads(_floor_quads(300, 200))
    floor = Mesh('floor', vertices, uvs, triangles, [_arena_texture()], 'floor', True)
    return World(base, [floor], _player_spawns())


def start_area_spawns(pack, base: str = 'kino') -> list[tuple[int, int]]:
    """(entity hash, spawn type hash) of the base level's starting-area zombie spawn points."""
    from . import resources

    statics = levels._read(pack, f'levels/{base}/{base}_statics')
    by_class = {t.class_hash: t for t in statics.types()}
    blob = resources.decode_reflected(by_class[levels.LEVEL].resources[0].body)
    (area_hash,) = struct.unpack_from('<I', levels._blob_prop(blob, 'm_StartingArea').raw)
    area = next((r for r in by_class[levels.AREA].resources if r.in_group_hash == area_hash), None)
    if area is None:
        raise WorldError(f'{base} has no starting area')
    raw = levels._blob_prop(resources.decode_reflected(area.body), 'm_SpawnPoints').raw
    hashes = struct.unpack_from(f'<{struct.unpack_from("<I", raw)[0]}I', raw, 4)
    specs = {r.in_group_hash: r for r in by_class[levels.ENTITY_SPEC].resources}
    out = []
    for value in hashes:
        spec = resources.decode_entity_spec(specs[value].body)
        point = levels._component(spec, 'CSpawnPoint').blob
        out.append((value, struct.unpack_from('<I', levels._blob_prop(point, 'spawnType').raw)[0]))
    return out


def arena_world(pack, arena: levels.Arena | None = None, base: str = 'kino') -> World:
    """The debug arena: a walled square with the base level's starting-area zombie spawns around
    the walls (crawlers on top), Juggernog and the power switch."""
    arena = arena or levels.Arena()
    h, inset = arena.half_size, 120
    vertices, uvs, triangles = _quads(_floor_quads(h, arena.cell)
                                      + _wall_quads(h, arena.cell, arena.wall_height))
    mesh = Mesh('arena', vertices, uvs, triangles, [_arena_texture()], 'floor', True)
    ring = [(0, h - inset), (0, -h + inset), (h - inset, 0), (-h + inset, 0),
            (h - inset, h - inset), (-h + inset, h - inset), (h - inset, -h + inset),
            (-h + inset, -h + inset), (h // 2, h - inset), (-h // 2, -h + inset),
            (h - inset, h // 2), (-h + inset, -h // 2)]
    entities = _player_spawns()
    for index, (value, spawn_type) in enumerate(start_area_spawns(pack, base)):
        x, z = ring[index % len(ring)]
        y = arena.wall_height if spawn_type == iw_hash('hole') else 0
        entities.append(Placement(f'0x{value:08x}', (float(x), float(y), float(z))))
    entities.append(Placement('Juggernog', (float(-h + 200), 0.0, -400.0), 90.0))
    entities.append(Placement('powerSwitch', (float(h - 60), 0.0, 0.0), -90.0))
    return World(base, [mesh], entities)


def template_world(template: str, pack=None) -> World:
    """The starting world of a map template: 'empty', 'debug' (needs the game's data) or one
    of the game's levels, inherited whole (a fresh copy every time)."""
    if template == 'empty':
        return empty_world()
    if template == 'debug':
        if pack is None:
            raise WorldError('the debug arena needs the game data (build the asset library)')
        return arena_world(pack)
    if template in levels.SHIPPED_LEVELS:
        if pack is None:
            raise WorldError(f'the {template} template needs the game data (build the asset library)')
        return World(template, inherit=True)
    raise WorldError(f'unknown map template {template!r}')


# Compiling


class _GameModels:
    """Game models with their materials and textures, read from the game's groups, for copying
    into a level and for collision bounds."""

    def __init__(self, pack) -> None:
        self.pack = pack
        self.groups: dict[str, group.Group] = {}

    def group(self, path: str) -> group.Group:
        if path not in self.groups:
            try:
                self.groups[path] = group.parse(self.pack.read(path))
            except KeyError:
                raise WorldError(f'{path} is not in the game data') from None
        return self.groups[path]

    def _find(self, cls: int, value: int, paths) -> bytes | None:
        for path in paths:
            for resource_type in self.group(path).types():
                if resource_type.class_hash == cls:
                    for resource in resource_type.resources:
                        if resource.in_group_hash == value:
                            return resource.body
        return None

    def model(self, path: str, value: int) -> bytes:
        body = self._find(levels.MODEL, value, [path])
        if body is None:
            raise WorldError(f'{path} has no model 0x{value:08x}')
        return body

    def map_paths(self, path: str) -> list[str]:
        """*path*, the other groups of its map (rooms share materials and textures), ingame."""
        names = self.pack.names() if hasattr(self.pack, 'names') else []
        level = library_map(path)
        same = [p for p in names if p.endswith('.group.bin') and p != path
                and p.startswith(f'levels/{level}/')] if level != 'shared' else []
        return [path] + sorted(same) + ([INGAME] if path != INGAME else [])

    def find_model(self, value: int, prefer: list[str]) -> str | None:
        """The group holding a model, looking in *prefer* first, then in every level group."""
        names = self.pack.names() if hasattr(self.pack, 'names') else []
        rest = [p for p in names if p.endswith('.group.bin') and p not in prefer and (
            p.startswith('levels/') or p.startswith('ingame/'))]
        for path in list(prefer) + rest:
            try:
                if self._find(levels.MODEL, value, [path]) is not None:
                    return path
            except WorldError:
                continue
        return None

    def resources(self, path: str, value: int) -> dict[int, list[tuple[int, bytes]]]:
        """{class hash: [(name hash, body)]} of a model and the materials and textures it uses,
        looked up in its own group first, then its map's other groups, then ingame."""
        from . import blender_scene, native

        paths = self.map_paths(path)
        body = self.model(path, value)
        materials_known = {r.in_group_hash for p in paths for t in self.group(p).types()
                           if t.class_hash == levels.MATERIAL for r in t.resources}
        out = {levels.MODEL: [(value, body)], levels.MATERIAL: [], levels.TEXTURE: []}
        for material_hash in blender_scene._model_materials(body, materials_known):
            material_body = self._find(levels.MATERIAL, material_hash, paths)
            if material_body is None:
                continue
            out[levels.MATERIAL].append((material_hash, material_body))
            try:
                textures = native.decode_material(material_body).textures
            except ValueError:
                textures = []
            for texture_hash in textures:
                texture_body = self._find(levels.TEXTURE, texture_hash, paths) if texture_hash else None
                if texture_body is not None:
                    out[levels.TEXTURE].append((texture_hash, texture_body))
        return out


TRIGGER_SOURCE = 'boz:trigger_volume'   # bozkit.toolkit's trigger volume piece
TRIGGER_TEMPLATE = 'levels/callofthedead/callofthedead_statics.group.bin'
TRIGGER_SIZE = 100.0   # centimetres: the editor's trigger cube at scale 1
WEAPON_FIELD = 'boz.weapon'   # a wall buy's weapon (Placement.fields)
CHALK_FIELD = 'boz.chalk'     # a wall buy's chalk (Placement.settings): '' auto, 'none', an image


def library_map(path: str) -> str:
    parts = path.split('/')
    return parts[1] if parts[0] == 'levels' and len(parts) > 2 else 'shared'


def _blob_hashes(blob) -> list[int]:
    from . import reflect

    out = []
    for prop in blob.properties:
        value = reflect.typed_value(prop)
        if isinstance(value, int) and not isinstance(value, bool):
            out.append(value)
        elif isinstance(value, list):
            out += [v for v in value if isinstance(v, int) and not isinstance(v, bool)]
        elif value is None and len(prop.raw) >= 4 and prop.nested is None and not prop.elements:
            count = struct.unpack_from('<I', prop.raw)[0]   # counted u32 lists
            if 4 + 4 * count == len(prop.raw):
                out += list(struct.unpack_from(f'<{count}I', prop.raw, 4))
        if prop.nested is not None:
            out += _blob_hashes(prop.nested)
        for element in prop.elements or ():
            out += _blob_hashes(element)
    return out


def _spec_hashes(spec) -> list[int]:
    out = []
    for component in spec.components:
        if component.blob is not None:
            out += _blob_hashes(component.blob)
    for _cls, _reserved, child in spec.children:
        out += _spec_hashes(child)
    return out


def _assets(blob) -> list[tuple[int, tuple[int, int]]]:
    """(name, (model, skin)) of the CIsRenderableAsset-like entries under a blob."""
    from . import reflect

    out = []
    values = {prop.name_hash: reflect.typed_value(prop) for prop in blob.properties}
    model, skin = values.get(iw_hash('model')), values.get(iw_hash('skin'))
    if isinstance(model, int) and model:
        name = values.get(iw_hash('name')) or values.get(iw_hash('Name')) or 0
        out.append((name if isinstance(name, int) else 0, (model, skin or model)))
    for prop in blob.properties:
        if prop.nested is not None:
            out += _assets(prop.nested)
        for element in prop.elements or ():
            out += _assets(element)
    return out


def _hull(points):
    """Convex hull of XZ points (monotone chain)."""
    points = sorted(set(points))
    if len(points) <= 2:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _box_corners(vertices):
    low = [min(v[i] for v in vertices) for i in range(3)]
    high = [max(v[i] for v in vertices) for i in range(3)]
    return [tuple(high[i] if corner >> i & 1 else low[i] for i in range(3)) for corner in range(8)]


class _Level:
    """A level's statics group being filled with a world's meshes, props, models and entities."""

    def __init__(self, pack, name: str, base: str, statics: group.Group) -> None:
        from . import native, resources

        self.pack, self.name, self.base, self.statics = pack, name, base, statics
        self.base_statics = f'levels/{base}/{base}_statics.group.bin'
        self.by_class = {t.class_hash: t for t in statics.types()}
        self.specs = {}
        for resource in self.by_class[levels.ENTITY_SPEC].resources:
            self.specs.setdefault(resource.in_group_hash, resource)
        self.game = _GameModels(pack)
        if levels.MODEL not in self.by_class:
            # Shipped groups list materials before the models that use them.
            model_type = self.by_class[levels.MODEL] = group.ResourceType(levels.MODEL, 1, 1)
            types = statics.sections[[x.hash for x in statics.sections].index(group.RESOURCES)].types
            types.insert(types.index(self.by_class[levels.MATERIAL]) + 1, model_type)
        self.present = {cls: {r.in_group_hash for r in self.by_class[cls].resources}
                        for cls in (levels.MODEL, levels.MATERIAL, levels.TEXTURE)}
        self.models = levels._model_index(pack, [f'levels/{base}/{base}_dynamics', 'ingame/ingame'])
        for resource in self.by_class[levels.MODEL].resources:
            self.models.setdefault(resource.in_group_hash, resource.body)
        self.loaded = {INGAME, f'levels/{base}/{base}_dynamics.group.bin', self.base_statics}
        placed = next(r.body for t in levels._read(pack, levels.PLACED_TEMPLATE).types()
                      if t.class_hash == levels.ENTITY_SPEC for r in t.resources)
        self.placed_template = placed
        self.transform_template = levels._component(resources.decode_entity_spec(placed),
                                                    'CIsTransform')
        self.texture_template = next(r.body for t in levels._read(pack, levels.TEXTURE_TEMPLATE).types()
                                     if t.class_hash == levels.TEXTURE for r in t.resources
                                     if levels._raw_texture(r.body))
        self.material_template = native.decode_material(
            self.by_class[levels.MATERIAL].resources[0].body)
        self.kept: list[group.Resource] = []
        self.own: set[int] = set()       # resources whose collision comes from collide()
        self.added: list[group.Resource] = []
        self.solid: list[tuple[float, float, float]] = []
        self.single: list[tuple[int, int, int]] = []
        self.blocking: list[int] = []     # per collision triangle: 1 = blocks, never floor
        self.zombie_spawns: list[int] = []
        self.used: set[int] = set()       # entity names already placed
        self.copies = 0
        self._by_hash = None
        self._loaded = None
        self._material_ids = None
        self.inherited = False
        self.moved: list[group.Resource] = []   # an inherited level's own entities, moved
        self.wall_buys: list = []                  # (placement, spec) of placed wall buys
        self.dirty: list[tuple[float, float, float, float]] = []   # XZ metres, for the navmesh
        # Objects scripts change: their own collision, tagged walkable areas, start state.
        self.script_collision: dict[str, tuple[list, list]] = {}
        self.blockers: list = []                   # door_footprints entries tagged by script name
        self.runtime = {'hidden': [], 'no_collision': [], 'blocked': []}
        self.scripted: set[int] = set()            # id() of scripted entity resources

    def add(self, cls: int, key: int, body: bytes) -> None:
        if key in self.present[cls]:
            return
        resource_type = self.by_class[cls]
        resource_type.resources.append(group.Resource(
            None if resource_type.names_omitted else key, key, body))
        self.present[cls].add(key)
        if cls == levels.MODEL:
            self.models[key] = body

    def copy_model(self, path: str, value: int) -> None:
        self.repack([value], path)

    # Repacking: whatever a placed entity or model uses comes with it from its own map.

    NOT_COPIED = {levels.ENTITY_SPEC, levels.LEVEL, levels.AREA, levels.NAVMESH,
                  iw_hash('CIsPortal'), iw_hash('CIsOccluder'), iw_hash('CWave'),
                  iw_hash('CZombieConfiguration')}

    def _index(self) -> dict[int, list[tuple[int, str, group.Resource, group.ResourceType]]]:
        """Every resource of the game's Zombies level groups and the ingame groups (pickups,
        props, ...), by name hash. Weapon groups are left out: their models share names such as
        Base and LOD1. Levels and ingame itself come first, so their resources win a clash."""
        if self._by_hash is None:
            self._by_hash = {}
            names = self.pack.names() if hasattr(self.pack, 'names') else []
            groups = [path for path in names if path.endswith('.group.bin')]
            paths = [path for path in groups if path.startswith('levels/') or path == INGAME]
            paths += sorted(path for path in groups if path.startswith('ingame/')
                            and path != INGAME and not path.startswith('ingame/weapons/'))
            for path in paths:
                for resource_type in self.game.group(path).types():
                    for resource in resource_type.resources:
                        self._by_hash.setdefault(resource.in_group_hash, []).append(
                            (resource_type.class_hash, path, resource, resource_type))
        return self._by_hash

    def _own_groups(self, source: str, index) -> dict:
        """Resources of a source group the index leaves out (weapon groups), with the weapon
        group's textures and materials (weapon_projectiles_<level>): what a dropped weapon or
        projectile model uses comes from its own groups."""
        if not source or not source.startswith('ingame/weapons/'):
            return {}
        paths = [source]
        folder, _, file_name = source.rpartition('/')
        for prefix, other in (('weapons_', 'weapon_projectiles_'), ('weapon_projectiles_', 'weapons_')):
            if file_name.startswith(prefix):
                paths.append(f'{folder}/{other}{file_name[len(prefix):]}')
        own: dict = {}
        for path in paths:
            try:
                parsed = self.game.group(path)
            except (WorldError, KeyError):
                continue
            for resource_type in parsed.types():
                for resource in resource_type.resources:
                    own.setdefault(resource.in_group_hash, []).append(
                        (resource_type.class_hash, path, resource, resource_type))
        return own

    def _present(self, cls: int, value: int) -> bool:
        if self._loaded is None:
            self._loaded = set()
            for path in self.loaded - {self.base_statics}:
                try:
                    for resource_type in self.game.group(path).types():
                        self._loaded.update((resource_type.class_hash, r.in_group_hash)
                                            for r in resource_type.resources)
                except WorldError:
                    pass
        if (cls, value) in self._loaded:
            return True
        resource_type = self.by_class.get(cls)
        return resource_type is not None and any(r.in_group_hash == value
                                                 for r in resource_type.resources)

    # Resources load in group order and some resolve others by name while loading (a skin its
    # skeleton and model), so types keep the shipped order.
    LOAD_ORDER = [levels.TEXTURE, levels.MATERIAL, levels.MODEL, iw_hash('CIwAnimSkel'),
                  iw_hash('CIwAnimSkin'), iw_hash('CIwAnim'), iw_hash('CIsAnimStateMachine')]

    def _type(self, cls: int, like: group.ResourceType) -> group.ResourceType:
        resource_type = self.by_class.get(cls)
        if resource_type is None:
            resource_type = self.by_class[cls] = group.ResourceType(cls, like.names_omitted,
                                                                    like.has_size)
            types = self.statics.sections[[x.hash for x in self.statics.sections]
                                          .index(group.RESOURCES)].types
            if cls in self.LOAD_ORDER:
                rank = self.LOAD_ORDER.index(cls)
                earlier = [i for i, t in enumerate(types) if t.class_hash in self.LOAD_ORDER
                           and self.LOAD_ORDER.index(t.class_hash) < rank]
                later = [i for i, t in enumerate(types) if t.class_hash in self.LOAD_ORDER
                         and self.LOAD_ORDER.index(t.class_hash) > rank]
                index = earlier[-1] + 1 if earlier else (later[0] if later else len(types))
                types.insert(index, resource_type)
            else:
                types.insert(types.index(self.by_class[levels.ENTITY_SPEC]), resource_type)
        return resource_type

    def repack(self, hashes, source: str) -> int:
        """Copy the resources *hashes* name (and what they use, transitively) from the game's
        groups into the level, unless the level already has them. Returns how many."""
        from . import blender_scene as scene
        from . import native, reflect as reflection, resources

        index = self._index()
        own = self._own_groups(source, index)
        queue, seen, copied = list(hashes), set(), 0
        while queue:
            value = queue.pop()
            if value in seen or not value:
                continue
            seen.add(value)
            candidates = [c for c in own.get(value, []) + index.get(value, [])
                          if c[0] not in self.NOT_COPIED]
            if not candidates:
                continue
            same_map = library_map(source)
            candidates.sort(key=lambda c: (c[1] != source, library_map(c[1]) != same_map,
                                           c[1] != INGAME))
            # One name can hold several resources of different classes (a door's texture,
            # model, skeleton, skin and state machine): each class comes along.
            chosen = {}
            for candidate in candidates:
                chosen.setdefault(candidate[0], candidate)
            for cls, _path, resource, like in chosen.values():
                if self._present(cls, value):
                    continue
                copied += self._copy_one(cls, value, resource, like, queue, index)
        return copied

    def _copy_one(self, cls, value, resource, like, queue, index) -> int:
        """Copy one resource into the level and queue the names it uses."""
        from . import blender_scene as scene
        from . import native, reflect as reflection, resources

        if True:
            body = resource.body
            resource_type = self._type(cls, like)
            resource_type.resources.append(group.Resource(
                None if resource_type.names_omitted else value, value, body))
            if cls == levels.MODEL:
                self.models[value] = body
                if self._material_ids is None:
                    self._material_ids = {h for h, items in index.items()
                                          if any(c[0] == levels.MATERIAL for c in items)}
                queue.extend(scene._model_materials(body, self._material_ids))
            elif cls == levels.MATERIAL:
                try:
                    queue.extend(native.decode_material(body).textures)
                except ValueError:
                    pass
            elif cls == levels.TEXTURE:
                return 1
            elif reflection.is_blob(body):
                blob = resources.decode_reflected(body)
                queue.extend(_blob_hashes(blob) if blob else [])
            else:
                # Binary resources (state machines, skins, skeletons, animations, sounds): any word
                # that names a game resource. Small ones (state machines) store names unaligned.
                if len(body) <= 0x10000:
                    queue.extend(word for word in (struct.unpack_from('<I', body, offset)[0]
                                                   for offset in range(len(body) - 3))
                                 if word in index)
                else:
                    queue.extend(word for (word,) in
                                 struct.iter_unpack('<I', body[:len(body) // 4 * 4]) if word in index)
            return 1

    def _mark(self, points) -> None:
        if points:
            xs = [p[0] / 100 for p in points]
            zs = [p[2] / 100 for p in points]
            self.dirty.append((min(xs) - 1, min(zs) - 1, max(xs) + 1, max(zs) + 1))

    def entity(self, entity: Placement, move_existing: bool) -> None:
        from . import blender_scene as scene
        from . import reflect, resources

        if entity.source == TRIGGER_SOURCE:
            self._trigger_volume(entity)
            return
        in_base = not entity.group or entity.group == self.base_statics
        existing = self.specs.get(entity.hash) if in_base else None
        rotation, scale = entity.quaternion(), tuple(entity.scale)
        if existing is not None and move_existing and not entity.piece and entity.hash not in self.used:
            # An inherited level's own entity: move it where the world puts it.
            self.used.add(entity.hash)
            spec = resources.decode_entity_spec(existing.body)
            old = scene._local_transform(spec)[0]
            self._configure(spec, entity, rotation, scale)
            existing.body = resources.encode_entity_spec(spec)
            self._mark([old, entity.position])
            self.moved.append(existing)
            if entity.script:
                self._script_entity(entity, existing, spec)
            return
        if existing is not None:
            body = existing.body
        else:
            if in_base:
                raise WorldError(f'{self.base} has no entity {entity.source!r}')
            body = self.game._find(levels.ENTITY_SPEC, entity.hash, [entity.group])
            if body is None:
                raise WorldError(f'{entity.group} has no entity {entity.source!r}')
        key = entity.hash
        copy_name = None
        script = script_of(entity).get('name', '')
        if script and script.lower() != entity.source.lower():
            # Placed with a script name: the copy is called that (scripts find it by it).
            copy_name = script
            key = iw_hash(script)
        elif key in self.used or (move_existing and in_base and key in self.specs):
            # A second copy of the same entity gets a name of its own (its entity name and
            # CIsNamed name: doors are told apart by it, in the navmesh too).
            self.copies += 1
            copy_name = f'{self.name}_copy_{self.copies}'
            key = iw_hash(copy_name)
        self.used.add(key)
        spec = resources.decode_entity_spec(body)
        if copy_name is not None:
            named = levels._component(spec, 'CIsNamed')
            prop = levels._blob_prop(named.blob, 'name') if named and named.blob else None
            if prop is not None:
                reflect.set_typed_value(prop, copy_name)
        door = levels._component(spec, 'CDoor')
        if door is not None and door.blob is not None and not (self.inherited and in_base):
            # A door unlocks areas of its own map: generated maps have one area, and another
            # map's areas are not in this one, so it unlocks none.
            areas = levels._blob_prop(door.blob, 'm_AreasUnlock')
            if areas is not None:
                areas.raw = struct.pack('<I', 0)
        if levels._component(spec, 'CIsTransform') is None:
            # Templates (in ingame) have no transform of their own; placed copies need one.
            spec.components.insert(0, copy.deepcopy(self.transform_template))
        self._configure(spec, entity, rotation, scale)
        resource = group.Resource(None, key, resources.encode_entity_spec(spec))
        if entity.group and entity.group not in self.loaded:
            # Everything it uses comes with it from its own map (models, textures, animations,
            # state machines, sounds), unless the level already has them.
            self.repack(_spec_hashes(spec), entity.group)
        if levels._component(spec, 'CSpawnPoint'):
            self.zombie_spawns.append(key)
        if levels._component(spec, 'CWeaponChalkOutline') is not None:
            self.wall_buys.append((entity, spec))
            poi = levels._component(spec, 'CPOI')
            if poi is not None and poi.blob is not None:
                # Usable from either side, as doors are: a wall buy placed facing the wall
                # would otherwise have no prompt.
                prop = levels._blob_prop(poi.blob, 'm_BiDirection')
                if prop is None:
                    prop = reflect.Property(iw_hash('CPOI'), iw_hash('bool'),
                                            iw_hash('m_BiDirection'), b'')
                    poi.blob.properties.append(prop)
                reflect.set_typed_value(prop, True)
                resource.body = resources.encode_entity_spec(spec)
        self.kept.append(resource)
        self.added.append(resource)
        self._mark([entity.position])
        if entity.script:
            self._script_entity(entity, resource, spec)

    def _trigger_volume(self, entity: Placement) -> None:
        """A trigger volume: an invisible ghost box (from Call of the Dead's snow triggers) that
        reports who enters and leaves it (boz.objects "enter"/"exit"), sized by its scale."""
        from . import reflect, resources

        template = None
        parsed = group.parse(self.pack.read(TRIGGER_TEMPLATE))
        for resource_type in parsed.types():
            if resource_type.class_hash != levels.ENTITY_SPEC:
                continue
            for item in resource_type.resources:
                spec = resources.decode_entity_spec(item.body)
                if levels._component(spec, 'CSnowTrigger') is not None and spec.children:
                    template = spec.children[0][2]
                    break
            if template is not None:
                break
        if template is None:
            raise WorldError('the game has no trigger box to copy (Call of the Dead\'s snow triggers)')
        spec = copy.deepcopy(template)
        spec.components = [c for c in spec.components if c.type_hash != iw_hash('CIsHierarchy')]
        spec.children = []
        self.copies += 1
        name = script_of(entity).get('name') or f'{self.name}_trigger_{self.copies}'
        self._name(spec, name)
        levels._set_transform(spec, entity.position, entity.quaternion())
        box = levels._component(spec, 'CIsCollisionBox')
        half = [TRIGGER_SIZE / 2 * abs(c) for c in entity.scale]
        reflect.set_typed_value(levels._blob_prop(box.blob, 'm_halfAxis'), half)
        for prop in box.blob.properties:
            # m_Offset and an unnamed offset (0x3f9a899b, non-zero in the snow boxes): centred.
            if prop.name_hash in (iw_hash('m_Offset'), 0x3f9a899b):
                reflect.set_typed_value(prop, [0.0, 0.0, 0.0])
        ghost = levels._blob_prop(box.blob, 'm_Ghost')
        if ghost is None:
            ghost = reflect.Property(iw_hash('CIsCollisionObject'), iw_hash('bool'),
                                     iw_hash('m_Ghost'), b'')
            box.blob.properties.append(ghost)
        reflect.set_typed_value(ghost, True)
        resource = group.Resource(None, iw_hash(name), resources.encode_entity_spec(spec))
        self.kept.append(resource)
        self.own.add(id(resource))    # no box of its own in the collision or the navmesh
        self._mark([entity.position])
        self.script(entity)

    def _script_entity(self, entity: Placement, resource, spec) -> None:
        """A scripted entity: no baked box (its own collision is switched instead); a blocking
        one tags the walkable area under it with its name."""
        from . import blender_scene as scene
        from . import native

        self.scripted.add(id(resource))
        corners = []
        for box in levels.prop_boxes(spec, self.models):
            corners += box
        model = scene._model_reference(spec)
        if not corners and model in self.models:
            chain = [scene._local_transform(spec)]
            corners = [scene._native_apply(chain, c)
                       for c in _box_corners(native.decode_model(self.models[model]).vertices)]
        if not corners:
            corners = [tuple(entity.position)]
        self.script(entity, corners)

    def _configure(self, spec, entity: Placement, rotation, scale) -> None:
        """Transform, custom model and field overrides of a placed entity."""
        from . import reflect

        levels._set_transform(spec, entity.position, rotation)
        levels._scale_by(spec, scale)   # relative: weapons and wall buys have their own scale
        if entity.prop:
            self._draw_model(spec, iw_hash(f'{self.name}_prop_{entity.prop}'))
        elif entity.model:
            path, model_hash = Instance((0.0, 0.0, 0.0), model=entity.model).model_ref()
            self.copy_model(path, model_hash)
            self._draw_model(spec, model_hash)
        for key, value in entity.fields.items():
            if key == WEAPON_FIELD:
                self._set_weapon(spec, entity, str(value))
                continue
            component_name, _, field_name = key.partition('.')
            component = levels._component(spec, component_name)
            prop = levels._blob_prop(component.blob, field_name) if component and component.blob \
                else None
            if prop is None and component is not None and component.blob is not None \
                    and isinstance(value, (bool, int, float)):
                # Fields the shipped data leaves at their default (Pack-a-Punch m_HasPower,
                # ammo costs, ...): added with the field's type.
                type_name = 'bool' if isinstance(value, bool) else \
                    'float' if isinstance(value, float) else 'unsigned int'
                prop = reflect.Property(iw_hash(component_name), iw_hash(type_name),
                                        iw_hash(field_name), b'')
                component.blob.properties.append(prop)
            if prop is None:
                raise WorldError(f'entity {entity.source!r} has no field {key}')
            if isinstance(value, str) and not isinstance(reflect.typed_value(prop), str):
                # Name fields hold hashes: "0x..." is one already, anything else is a name.
                value = int(value, 16) if value.startswith('0x') else iw_hash(value)
            reflect.set_typed_value(prop, value)

    def _draw_model(self, spec, model_hash: int) -> None:
        """Make an entity draw *model_hash*; one that draws nothing (a shootable target, a
        trigger) gets a renderable of its own (the placed models' one)."""
        from . import reflect, resources

        renderable = levels._component(spec, 'CIsRenderableModel')
        if renderable is None:
            template = levels._component(resources.decode_entity_spec(self.placed_template),
                                         'CIsRenderableModel')
            renderable = copy.deepcopy(template)
            at = next((i + 1 for i, c in enumerate(spec.components)
                       if c.type_hash == iw_hash('CIsTransform')), 0)
            spec.components.insert(at, renderable)
        for element in levels._blob_prop(renderable.blob, 'assets').elements:
            for prop in element.properties:
                if prop.name_hash in (iw_hash('Name'), iw_hash('model')):
                    reflect.set_typed_value(prop, model_hash)

    def _set_weapon(self, spec, entity: Placement, weapon: str) -> None:
        """Make a wall buy sell *weapon*: its "model" child shows the weapon (asset name =
        weapon name, the weapon's skeleton, its low-detail model and skin)."""
        from . import reflect

        name_hash = int(weapon, 16) if weapon.startswith('0x') else iw_hash(weapon)
        display = self._weapon_display(name_hash)
        if display is None:
            raise WorldError(f'wall buy {entity.source!r}: the level has no weapon {weapon!r}')
        skel, model, skin = display
        child = next((c for _cls, _reserved, c in spec.children
                      if levels._component(c, 'CIsRenderableModel') is not None), None)
        if child is None:
            raise WorldError(f'entity {entity.source!r} has no weapon display to change')
        renderable = levels._component(child, 'CIsRenderableModel').blob
        skel_prop = levels._blob_prop(renderable, 'skel')
        if skel_prop is not None and skel:
            reflect.set_typed_value(skel_prop, skel)
        for element in levels._blob_prop(renderable, 'assets').elements:
            for prop in element.properties:
                if prop.name_hash in (iw_hash('name'), iw_hash('Name')):
                    reflect.set_typed_value(prop, name_hash)
                elif prop.name_hash == iw_hash('model'):
                    reflect.set_typed_value(prop, model)
                elif prop.name_hash == iw_hash('skin'):
                    reflect.set_typed_value(prop, skin)

    def _weapon_display(self, name_hash: int):
        """(skeleton, model, skin) a wall buy shows for a weapon of the level's weapons group."""
        from . import reflect, resources

        # A shipped wall buy of the same weapon shows exactly what the game expects.
        for resource in self.by_class[levels.ENTITY_SPEC].resources + [
                r for t in self.game.group(self.base_statics).types()
                if t.class_hash == levels.ENTITY_SPEC for r in t.resources]:
            try:
                spec = resources.decode_entity_spec(resource.body)
            except (ValueError, struct.error):
                continue
            if levels._component(spec, 'CWeaponChalkOutline') is None:
                continue
            for _cls, _reserved, child in spec.children:
                renderable = levels._component(child, 'CIsRenderableModel')
                if renderable is None or renderable.blob is None:
                    continue
                for name, (model, skin) in _assets(renderable.blob):
                    if name == name_hash:
                        skel = levels._blob_prop(renderable.blob, 'skel')
                        return (reflect.typed_value(skel) if skel is not None else 0), model, skin
        gear = levels.GEAR.get(self.base, self.base)
        try:
            weapons = self.game.group(f'ingame/weapons/weapons_{gear}.group.bin')
        except WorldError:
            return None
        for resource_type in weapons.types():
            if resource_type.class_hash != levels.ENTITY_SPEC:
                continue
            for resource in resource_type.resources:
                if resource.in_group_hash != name_hash:
                    continue
                blob = resources.decode_entity_spec(resource.body).components[0].blob
                skel = levels._blob_prop(blob, 'skel')
                skel = reflect.typed_value(skel) if skel is not None else 0
                found = []
                for prop in blob.properties:
                    for nested in ([prop.nested] if prop.nested else []):
                        found += _assets(nested)
                low = next((pair for name, pair in found if name == iw_hash('LOD1')), None)
                pair = low or (found[-1][1] if found else None)
                if pair is None:
                    return None
                return skel, pair[0], pair[1]
        return None

    def build(self, mesh: Mesh, model_name: str) -> None:
        from . import native

        materials = []
        for index, texture in enumerate(mesh.textures):
            suffix = '' if index == 0 else str(index)
            texture_name, material_name = f'{model_name}_tex{suffix}', f'{model_name}_mat{suffix}'
            self.add(levels.TEXTURE, iw_hash(texture_name), native.build_texture(
                texture.width, texture.height, texture.bgra, self.texture_template))
            template = self.material_template
            material = native.Material(False, 0, template.unknown,
                                       [(255, 255, 255, 255)] * 3 + [(0, 0, 0, 10)],
                                       [iw_hash(texture_name), 0, 0, 0], template.trailer)
            self.add(levels.MATERIAL, iw_hash(material_name), native.encode_material(material))
            materials.append(iw_hash(material_name))
        triangles, faces = mesh.model_triangles()
        self.add(levels.MODEL, iw_hash(model_name),
                 native.build_model(mesh.vertices, mesh.uvs, triangles, materials, faces))

    def place(self, entity_name: str, model_hash: int, position, rotation=(0.0, 0.0, 0.0, 1.0),
              scale=UNIT, named: bool = False) -> None:
        from . import reflect, resources

        spec = resources.decode_entity_spec(self.placed_template)
        levels._set_transform(spec, position, rotation)
        levels._set_scale(spec, scale)
        if named:
            self._name(spec, entity_name)
        renderable = levels._component(spec, 'CIsRenderableModel').blob
        for element in levels._blob_prop(renderable, 'assets').elements:
            for prop in element.properties:
                if prop.name_hash in (iw_hash('Name'), iw_hash('model')):
                    reflect.set_typed_value(prop, model_hash)
        resource = group.Resource(None, iw_hash(entity_name), resources.encode_entity_spec(spec))
        self.kept.append(resource)
        self.own.add(id(resource))

    def _name(self, spec, name: str) -> None:
        """Give an entity spec the CIsNamed name boz.objects finds it by."""
        from . import reflect, resources

        named = levels._component(spec, 'CIsNamed')
        if named is None:
            template = next(c for r in self.by_class[levels.ENTITY_SPEC].resources
                            for c in resources.decode_entity_spec(r.body).components
                            if c.type_hash == iw_hash('CIsNamed') and c.blob is not None)
            named = copy.deepcopy(template)
            spec.components.insert(1, named)
        reflect.set_typed_value(levels._blob_prop(named.blob, 'name'), name)

    def script(self, item, footprint_points=None) -> str:
        """Record a scripted object's start state; returns its script name ('' for none)."""
        script = script_of(item)
        name = script.get('name', '')
        if not name:
            return ''
        if not script['visible']:
            self.runtime['hidden'].append(name)
        if not script['collision']:
            self.runtime['no_collision'].append(name)
        if script['blocks']:
            self.runtime['blocked'].append(name)
            if footprint_points:
                # A little below it: the floor it stands on is what gets tagged.
                self.blockers.append(_tag_area(iw_hash(name), footprint_points, below=0.3))
        return name

    def collide(self, vertices, triangles, kind: str, shape: str, position=None,
                rotation=(0.0, 0.0, 0.0, 1.0), scale=UNIT, script: str = '') -> list:
        """Add collision; a scripted object's goes into its own collision entity. Returns the
        world-space points used."""
        from . import blender_scene as scene

        if kind == 'none':
            return []
        chain = [(tuple(position), tuple(rotation), tuple(scale))] if position else []
        if script:
            solid, single = self.script_collision.setdefault(script, ([], []))
            if shape == 'box':
                points = [scene._native_apply(chain, c) for c in _box_corners(vertices)]
                single.extend(levels.box_triangles(len(solid)))
            else:
                points = [scene._native_apply(chain, tuple(map(float, v))) if chain
                          else tuple(map(float, v)) for v in vertices]
                single.extend((a + len(solid), b + len(solid), c + len(solid))
                              for a, b, c in triangles)
            solid.extend(points)
            self._mark(points)
            return points
        before = len(self.single)
        if shape == 'box':
            points = [scene._native_apply(chain, c) for c in _box_corners(vertices)]
            self.single.extend(levels.box_triangles(len(self.solid)))
            self.solid.extend(points)
        else:
            offset = len(self.solid)
            points = [scene._native_apply(chain, tuple(map(float, v))) if chain
                      else tuple(map(float, v)) for v in vertices]
            self.solid.extend(points)
            self.single.extend((a + offset, b + offset, c + offset) for a, b, c in triangles)
        self.blocking.extend([1 if kind == 'solid' else 0] * (len(self.single) - before))
        self._mark(points)
        return points

    def add_chalks(self) -> None:
        """A chalk decal for each placed wall buy, where the shipped maps put theirs: the
        weapon's own chalk when the game has one, else the placement's image, else an outline
        drawn from the weapon's model (bozkit.chalk)."""
        from . import chalk

        if not self.wall_buys:
            return
        folder = getattr(self.pack, 'folder', None)
        decals = chalk.find_decals(self.pack, folder.parent / 'chalks.json' if folder else None)
        if not decals:
            return
        template = decals.get(iw_hash('KQX')) or next(iter(decals.values()))
        for number, (entity, spec) in enumerate(self.wall_buys):
            mode = entity.settings.get(CHALK_FIELD, '')
            if mode == 'none':
                continue
            weapon = chalk._weapon_of(spec)
            decal = decals.get(weapon) if not entity.chalk_texture else None
            position, rotation, scale = chalk.compose(entity.position, entity.quaternion(),
                                                      tuple(entity.scale), decal or template)
            name = f'{self.name}_chalk_{number}'
            texture = entity.chalk_texture or (self._shipped_chalk(decal) if decal else None) \
                or self._drawn_chalk(weapon)
            if texture is not None and self._decal_model(decal or template, texture, name):
                self.place(name, iw_hash(name), position, rotation, scale)

    def _shipped_chalk(self, decal) -> Texture | None:
        """The texture of a weapon's shipped chalk decal (B, G, R, A)."""
        from . import native

        try:
            found = self.game.resources(self.game.find_model(
                decal.model, self.game.map_paths(decal.group)) or decal.group, decal.model)
            body = found[levels.TEXTURE][0][1]
            decoded = native.decode_texture_rgba(body)
        except (WorldError, IndexError, ValueError):
            return None
        rgba = decoded.rgba
        bgra = bytearray(rgba)
        bgra[0::4], bgra[2::4] = rgba[2::4], rgba[0::4]
        return Texture(decoded.width, decoded.height, bytes(bgra))

    def _drawn_chalk(self, weapon: int | None) -> Texture | None:
        from . import chalk, native

        display = self._weapon_display(weapon) if weapon else None
        if display is None:
            return None
        gear = levels.GEAR.get(self.base, self.base)
        body = self.game._find(levels.MODEL, display[1], [f'ingame/weapons/weapons_{gear}.group.bin'])
        if body is None:
            return None
        model = native.decode_model(body)
        width, height = chalk.SIZE
        return Texture(width, height, chalk.draw(model.vertices, model.triangles, weapon))

    def _decal_model(self, template, texture: Texture, model_name: str) -> bool:
        """A decal quad like *template*'s (its geometry and material settings) drawing
        *texture*."""
        from . import blender_scene as scene
        from . import native

        paths = self.game.map_paths(template.group)
        body = self.game._find(levels.MODEL, template.model, paths)
        if body is None:
            return False
        quad = native.decode_model(body)
        known = {r.in_group_hash for p in paths for t in self.game.group(p).types()
                 if t.class_hash == levels.MATERIAL for r in t.resources}
        refs = scene._model_materials(body, known)
        material_body = self.game._find(levels.MATERIAL, refs[0], paths) if refs else None
        material = native.decode_material(material_body) if material_body else native.Material(
            False, 0, self.material_template.unknown, [(255, 255, 255, 255)] * 4, [0, 0, 0, 0],
            self.material_template.trailer)
        texture_name, material_name = f'{model_name}_tex', f'{model_name}_mat'
        self.add(levels.TEXTURE, iw_hash(texture_name), native.build_texture(
            texture.width, texture.height, texture.bgra, self.texture_template))
        material.textures = [iw_hash(texture_name)] + list(material.textures[1:])
        self.add(levels.MATERIAL, iw_hash(material_name), native.encode_material(material))
        # Double-sided: the chalk shows whichever way the wall buy was turned.
        triangles = list(quad.triangles) + [(a, c, b) for a, b, c in quad.triangles]
        self.add(levels.MODEL, iw_hash(model_name), native.build_model(
            quad.vertices, quad.uvs, triangles, [iw_hash(material_name)]))
        return True

    def build_props(self, world: World) -> None:
        for prop in world.props:
            self.build(prop, f'{self.name}_prop_{prop.name}')

    def contents(self, world: World) -> None:
        """The world's own meshes and instances (props are built first: build_props)."""
        from . import native

        name = self.name
        for mesh in world.meshes:
            model_name = f'{name}_{mesh.name}'
            script = script_of(mesh).get('name', '')
            self.build(mesh, model_name)
            self.place(script or model_name, iw_hash(model_name), (0, 0, 0), named=bool(script))
            points = self.collide(mesh.vertices, mesh.triangles, mesh.collision, 'mesh',
                                  script=script)
            self.script(mesh, points or [tuple(map(float, v)) for v in mesh.vertices])
        props = {prop.name: prop for prop in world.props}
        for number, instance in enumerate(world.instances):
            rotation, scale = instance.quaternion(), tuple(instance.scale)
            script = script_of(instance).get('name', '')
            if instance.prop:
                prop = props[instance.prop]
                self.place(script or f'{name}_prop_{prop.name}_{number}',
                           iw_hash(f'{name}_prop_{prop.name}'), instance.position, rotation, scale,
                           named=bool(script))
                points = self.collide(prop.vertices, prop.triangles, prop.collision, prop.shape,
                                      instance.position, rotation, scale, script=script)
            else:
                path, model_hash = instance.model_ref()
                self.copy_model(path, model_hash)
                self.place(script or f'{name}_model_{number}', model_hash, instance.position,
                           rotation, scale, named=bool(script))
                decoded = native.decode_model(self.models[model_hash])
                points = self.collide(decoded.vertices, decoded.triangles, instance.collision,
                                      instance.shape, instance.position, rotation, scale,
                                      script=script)
            self.script(instance, points)

    def script_collisions(self) -> None:
        """A collision entity (<name>_collision, a copy of the level's) for each scripted object
        with collision, so boz.objects can switch it."""
        from . import collision, resources

        if not self.script_collision:
            return
        source = next((r for r in self.kept if any(
            c.class_hash == resources.COLLISION_MESH_SPEC
            for c in resources.decode_entity_spec(r.body).components)), None)
        if source is None:
            raise WorldError(f'{self.base} has no collision entity to copy')
        for name, (solid, single) in sorted(self.script_collision.items()):
            spec = resources.decode_entity_spec(source.body)
            levels._set_transform(spec, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
            self._name(spec, f'{name}_collision')
            component = next(c for c in spec.components
                             if c.class_hash == resources.COLLISION_MESH_SPEC)
            mesh_data = collision.decode(component.extra)
            mesh_data.vertices = list(solid)
            mesh_data.indices = [i for t in single for i in t]
            mesh_data.materials = bytes(len(single))
            component.extra = collision.encode(mesh_data)
            self.kept.append(group.Resource(None, iw_hash(f'{name}_collision'),
                                            resources.encode_entity_spec(spec)))

    def entity_boxes(self, resources_list) -> None:
        """Shipped levels bake props into their collision and navmesh; added entities get a box."""
        from . import resources

        for resource in resources_list:
            if id(resource) in self.own or id(resource) in self.scripted:
                continue
            spec = resources.decode_entity_spec(resource.body)
            if levels._component(spec, 'CDoor') is not None:
                continue   # doors gate the navmesh (door_footprints), they do not cut it
            for box in levels.prop_boxes(spec, self.models):
                self.single += levels.box_triangles(len(self.solid))
                self.blocking += [1] * 12
                self.solid += box
                self._mark(box)

    def door_footprints(self, resources_list) -> list:
        """(name hash, XZ footprint in metres, min y, max y) of each door (its collision boxes
        and its model), for navbuild."""
        from . import blender_scene as scene
        from . import native, resources

        doors = []
        for resource in resources_list:
            spec = resources.decode_entity_spec(resource.body)
            if levels._component(spec, 'CDoor') is None:
                continue
            own = scene._blob_value(scene._component(spec, 'CIsNamed'), 'name', None)
            name_hash = iw_hash(own) if isinstance(own, str) else resource.in_group_hash
            corners = [c for box in levels.prop_boxes(spec, self.models) for c in box]
            # Debris and boats are bigger than their collision slab: the whole model is shut.
            model = scene._model_reference(spec)
            if model in self.models:
                vertices = native.decode_model(self.models[model]).vertices
                chain = [scene._local_transform(spec)]
                corners += [scene._native_apply(chain, c) for c in _box_corners(vertices)]
            if not corners:
                continue
            doors.append(_tag_area(name_hash, corners))
        return doors + self.blockers

    def set_collision(self, resource: group.Resource) -> None:
        from . import collision, resources

        spec = resources.decode_entity_spec(resource.body)
        component = next(c for c in spec.components
                         if c.class_hash == resources.COLLISION_MESH_SPEC)
        mesh_data = collision.decode(component.extra)
        mesh_data.vertices = list(self.solid)
        mesh_data.indices = [i for t in self.single for i in t]
        mesh_data.materials = bytes(len(self.single))
        component.extra = collision.encode(mesh_data)
        resource.body = resources.encode_entity_spec(spec)

    def finish_entities(self) -> None:
        self.by_class[levels.ENTITY_SPEC].resources = self.kept


def _tag_area(name_hash: int, corners, below: float = 0.0) -> tuple:
    """(name hash, XZ hull in metres, min y, max y) of points in centimetres, grown a little: a
    navmesh area tagged with the name (doors, and objects scripts open and close)."""
    points = [(x / 100, z / 100) for x, _y, z in corners]
    centre = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    # Reach a little past it: the area must catch whole polygons.
    grown = []
    for x, z in _hull(points) if len(points) >= 3 else [(centre[0] - 0.5, centre[1] - 0.5),
                                                        (centre[0] + 0.5, centre[1] - 0.5),
                                                        (centre[0] + 0.5, centre[1] + 0.5),
                                                        (centre[0] - 0.5, centre[1] + 0.5)]:
        dx, dz = x - centre[0], z - centre[1]
        length = (dx * dx + dz * dz) ** 0.5 or 1.0
        grown.append((x + dx / length * 0.4, z + dz / length * 0.4))
    ys = [y / 100 for _x, y, _z in corners]
    return (name_hash, grown, min(ys) - below, max(ys))


def compile_world(pack, name: str, world: World,
                  fixed: group.Group | None = None) -> levels.LevelFiles:
    """The game's groups for *world* under the level name *name*.

    A generated world gets the base level's weapons, arms, rounds, zombie types, sounds and
    cameras, the world's own models, props and entities, and a collision mesh and navmesh built
    from them (no rooms). An inherited world (``inherit``) is the whole base level, rooms and
    all, with the world's additions and moved entities; only the navmesh tiles near changes are
    rebuilt.
    """
    problems = validate(world)
    if problems:
        raise WorldError('; '.join(problems))
    if world.inherit:
        return _compile_inherited(pack, name, world, fixed)
    from . import navbuild, resources

    base = world.base
    files = levels.common_files(pack, name, base, fixed)
    statics = levels._read(pack, f'levels/{base}/{base}_statics')
    levels.rename_level_resource(statics, base, name)
    level = _Level(pack, name, base, statics)
    by_class = level.by_class
    for resource in by_class[levels.ENTITY_SPEC].resources:  # cameras: intro and main
        if levels._component(resources.decode_entity_spec(resource.body), 'CIsCamera'):
            level.kept.append(resource)
    level.build_props(world)
    for entity in world.entities:
        level.entity(entity, move_existing=False)

    # The starting area lists the zombie spawns that are in the world.
    level_blob = resources.decode_reflected(by_class[levels.LEVEL].resources[0].body)
    (start_area,) = struct.unpack_from('<I', levels._blob_prop(level_blob, 'm_StartingArea').raw)
    areas = [r for r in by_class[levels.AREA].resources if r.in_group_hash == start_area]
    if not areas:
        raise WorldError(f'{base} has no starting area')
    area_blob = resources.decode_reflected(areas[0].body)
    spawns = level.zombie_spawns
    levels._blob_prop(area_blob, 'm_SpawnPoints').raw = struct.pack(
        f'<I{len(spawns)}I', len(spawns), *spawns)
    areas[0].body = resources.encode_reflected(area_blob)
    by_class[levels.AREA].resources = areas

    level.contents(world)
    level.add_chalks()
    level.entity_boxes(list(level.kept))
    level.script_collisions()
    collision_key = iw_hash('COLLISION')
    if collision_key not in level.specs:
        raise WorldError(f'{base} has no COLLISION entity')
    level.set_collision(level.specs[collision_key])
    level.kept.append(level.specs[collision_key])
    level.finish_entities()
    navmesh = by_class[levels.NAVMESH].resources[0]
    navmesh.body = navbuild.build(navmesh.body,
                                  [(x / 100, y / 100, z / 100) for x, y, z in level.solid],
                                  level.single, blocking=level.blocking,
                                  doors=level.door_footprints(level.kept))

    files.groups[f'{name}.group.bin'] = levels.renamed(
        levels._read(pack, f'levels/{base}/{base}'), name,
        [levels.Child(f'levels/{base}//{base}_dynamics.group', f'{base}_dynamics'),
         levels.Child(f'levels/{name}//{name}_statics.group', f'{name}_statics')])
    without_children = levels.renamed(statics, f'{name}_statics')
    without_children.sections = [x for x in without_children.sections if x.hash != levels.CHILDREN]
    files.groups[f'{name}_statics.group.bin'] = without_children
    files.runtime = level.runtime
    return files


def _compile_inherited(pack, name: str, world: World, fixed) -> levels.LevelFiles:
    from . import blender_scene as scene
    from . import blender_scene, navbuild, resources

    base = world.base
    files = levels.clone_level(pack, name, base, fixed)
    statics = files.groups[f'{name}_statics.group.bin']
    level = _Level(pack, name, base, statics)
    level.inherited = True
    removed = {int(value, 16) if value.startswith('0x') else iw_hash(value) for value in world.removed}
    level.kept = []
    for resource in level.by_class[levels.ENTITY_SPEC].resources:
        if resource.in_group_hash in removed:
            # Taken out in the editor: its navmesh tiles are rebuilt without it.
            level._mark([blender_scene._local_transform(resources.decode_entity_spec(resource.body))[0]])
            continue
        level.kept.append(resource)
    level.build_props(world)
    for entity in world.entities:
        level.entity(entity, move_existing=True)
    level.contents(world)
    level.add_chalks()
    level.entity_boxes(level.added)
    level.script_collisions()
    level.finish_entities()
    navmesh_input = None
    if level.dirty:
        # The level's own navmesh input, before the world's collision entity is added.
        parsed = {f'levels/{name}/{name}_statics.group.bin': statics}
        sectors = files.groups.get(f'{name}_sectors.group.bin')
        for path, _hash, _flags in levels.children(sectors) if sectors else []:
            relative = path.replace('//', '/') + '.bin'
            try:
                parsed[relative] = group.parse(pack.read(relative))
            except KeyError:
                pass
        navmesh_input = scene.navmesh_input(parsed)
    if level.solid:
        # The world's own collision: a copy of the level's collision entity, at the origin.
        source = next((r for r in level.kept if any(
            c.class_hash == resources.COLLISION_MESH_SPEC
            for c in resources.decode_entity_spec(r.body).components)), None)
        if source is None:
            raise WorldError(f'{base} has no collision entity to copy')
        spec = resources.decode_entity_spec(source.body)
        levels._set_transform(spec, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        added = group.Resource(None, iw_hash(f'{name}_world_collision'),
                               resources.encode_entity_spec(spec))
        level.set_collision(added)
        level.kept.append(added)
        level.finish_entities()
    if navmesh_input is not None:
        vertices, triangles = navmesh_input
        offset = len(vertices)
        vertices = list(vertices) + [(x / 100, y / 100, z / 100) for x, y, z in level.solid]
        triangles = list(triangles) + [(a + offset, b + offset, c + offset)
                                       for a, b, c in level.single]
        blocking = [0] * len(navmesh_input[1]) + level.blocking
        navmesh = level.by_class[levels.NAVMESH].resources[0]
        navmesh.body, _report = navbuild.rebuild(navmesh.body, vertices, triangles,
                                                 dirty=level.dirty, blocking=blocking,
                                                 doors=level.door_footprints(level.added + level.moved))
    files.runtime = level.runtime
    return files
