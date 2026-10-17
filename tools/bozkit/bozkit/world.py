"""A map project's world source and the compiler that turns it into the game's groups.

The source lives in the project's ``source/`` folder, as files the editor writes and people can
read::

    source/world.json          what the world is made of (format 3, below)
    source/meshes/<n>.json     a mesh of the world's own: vertices (centimetres, Y up, the
                               model's own space), UVs, triangles, per triangle its texture
    source/textures/<n>.png    textures (power-of-two sides, 4 to 1024); <n>_<i>.png for the
                               second and later textures of a mesh
    source/prefabs/<n>.json    the prefab library (save_prefab / load_prefab)

``world.json`` lists **models** (a mesh you see and bump into), **volumes** (invisible boxes that
send script events) and **prefabs** (named groups of parts with a script, or the game's own
entities); see the Format 3 section. Compiling lowers a world into a Layout (level meshes,
props, instances, entities), which _compile_layout turns into the game's groups.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import re
import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import group, levels, png
from . import spec_fields
from . import maps
from .hashing import iw_hash

COLLISION_KINDS = ('floor', 'solid', 'none')
SHAPES = ('box', 'mesh')
NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
SCRIPT_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_.]{0,95}$')   # '.' joins prefab parts
# An object scripts can change ("script": {...}): its name in the game (CIsNamed, what
# boz.objects finds), and how it starts. Scripted meshes and props get a collision entity of their
# own (<name>_collision) and, when they block, a tagged walkable area instead of a hole, so
# boz.objects can switch both; boz.world applies the start state when the level starts.
SCRIPT_DEFAULTS = {'name': '', 'visible': True, 'collision': True, 'blocks': False,
                   'dynamic': True}   # dynamic: scripts may switch it (own collision, tagged area)
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
BLOCK_MARGIN = 10.0   # centimetres between a blocking object and the player's body, by default
PLAYER_RADIUS = 0.4   # metres: the navmesh's agent radius in every shipped level (the walkable area
                      # is where the player's centre may go, so it always stops this far from walls)


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
    padding: float = 0.0      # centimetres a box collision reaches past the model's bounds
    block_margin: float = BLOCK_MARGIN   # centimetres between that and the player's body

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
class Layout:
    """The compiler's input: level meshes, props and their instances, and game entities. Worlds
    lower into it (lower()); the templates are built as one (from_layout)."""
    base: str = 'kino'
    meshes: list[Mesh] = field(default_factory=list)
    entities: list[Placement] = field(default_factory=list)
    props: list[Mesh] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    inherit: bool = False    # start from the whole base level (its rooms, entities, navmesh)
    removed: list[str] = field(default_factory=list)   # base level entities taken out (0x hashes)
    weapons: list = field(default_factory=list)   # bozkit.weapons.WeaponDef: the project's weapons


# Files


def bgra_to_rgba(bgra: bytes) -> bytes:
    out = bytearray(bgra)
    out[0::4], out[2::4] = bgra[2::4], bgra[0::4]
    return bytes(out)


def read_texture(path: Path) -> Texture:
    """A PNG as a texture (Pillow when available, else bozkit.png)."""
    try:
        from PIL import Image
    except ImportError:
        width, height, rgba = png.read_rgba(path.read_bytes())
        return Texture(width, height, bgra_to_rgba(rgba))  # the same swap both ways
    image = Image.open(path).convert('RGBA')
    return Texture(image.width, image.height, image.tobytes('raw', 'BGRA'))


def write_texture(texture: Texture, path: Path) -> None:
    path.write_bytes(png.write_rgba(texture.width, texture.height, bgra_to_rgba(texture.bgra)))


def texture_files(name: str, count: int) -> list[str]:
    return [f'textures/{name}.png' if i == 0 else f'textures/{name}_{i}.png' for i in range(count)]


def _write_mesh(source: Path, folder: str, mesh: Mesh) -> dict:
    data = {'vertices': [list(v) for v in mesh.vertices],
            'uvs': [[round(u, 6), round(v, 6)] for u, v in mesh.uvs],
            'triangles': [list(t) for t in mesh.triangles]}
    if any(mesh.face_textures):
        data['materials'] = list(mesh.face_textures)
    (source / folder / f'{mesh.name}.json').write_text(json.dumps(data, separators=(',', ':'))
                                                       + '\n', encoding='utf-8')
    files = texture_files(mesh.name, len(mesh.textures))
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


def _lines(key: str, items: list[dict], last: bool = False) -> list[str]:
    lines = [f'  "{key}": [']
    lines += [f'    {json.dumps(item)}' + (',' if i < len(items) - 1 else '')
              for i, item in enumerate(items)]
    return lines + ['  ]' + ('' if last else ',')]


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


def _validate_layout(world: Layout) -> list[str]:
    """Problems that would stop a layout from compiling."""
    problems = []
    if world.base not in maps.SHIPPED:
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


def _empty_layout(base: str = 'kino') -> Layout:
    """A 6 m floor tile and the four player spawns: nothing else to start from."""
    vertices, uvs, triangles = _quads(_floor_quads(300, 200))
    floor = Mesh('floor', vertices, uvs, triangles, [_arena_texture()], 'floor', True)
    return Layout(base, [floor], _player_spawns())


def start_area_spawns(pack, base: str = 'kino') -> list[tuple[int, int]]:
    """(entity hash, spawn type hash) of the base level's starting-area zombie spawn points."""
    from . import resources

    statics = levels.read_group_at(pack, f'levels/{base}/{base}_statics')
    by_class = {t.class_hash: t for t in statics.types()}
    blob = resources.decode_reflected(by_class[levels.LEVEL].resources[0].body)
    (area_hash,) = struct.unpack_from('<I', spec_fields.prop(blob, 'm_StartingArea').raw)
    area = next((r for r in by_class[levels.AREA].resources if r.in_group_hash == area_hash), None)
    if area is None:
        raise WorldError(f'{base} has no starting area')
    raw = spec_fields.prop(resources.decode_reflected(area.body), 'm_SpawnPoints').raw
    hashes = struct.unpack_from(f'<{struct.unpack_from("<I", raw)[0]}I', raw, 4)
    specs = {r.in_group_hash: r for r in by_class[levels.ENTITY_SPEC].resources}
    out = []
    for value in hashes:
        spec = resources.decode_entity_spec(specs[value].body)
        point = spec_fields.component(spec, 'CSpawnPoint').blob
        out.append((value, struct.unpack_from('<I', spec_fields.prop(point, 'spawnType').raw)[0]))
    return out


def _arena_layout(pack, arena: levels.Arena | None = None, base: str = 'kino') -> Layout:
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
    return Layout(base, [mesh], entities)


def template_world(template: str, pack=None) -> 'World':
    """The starting world of a map template: 'empty', 'debug' (needs the game's data) or one
    of the game's levels, inherited whole (a fresh copy every time)."""
    if template == 'empty':
        return from_layout(_empty_layout())
    if template == 'debug':
        if pack is None:
            raise WorldError('the debug arena needs the game data (build the asset library)')
        return from_layout(_arena_layout(pack))
    if template in maps.SHIPPED:
        if pack is None:
            raise WorldError(f'the {template} template needs the game data (build the asset library)')
        return World(template, inherit=True)
    raise WorldError(f'unknown map template {template!r}')


def empty_world(base: str = 'kino') -> 'World':
    """A 6 m floor tile and the four player spawns: nothing else to start from."""
    return from_layout(_empty_layout(base))


# Format 3: models, volumes and prefabs
#
# Everything placed in a map is one of three kinds, each with a name scripts find it by:
#
# - Model: one mesh you see and bump into, either a game model ('<group path>#0x<hash>') or one
#   of the world's own meshes (source/meshes, in the model's own space). Collision floor /
#   solid / none, shape box / mesh, and a start state (visible, collision, blocks the walkable
#   area).
# - Volume: an invisible box that sends events to scripts: trigger (enter / exit), hit (shot),
#   use (the player presses use).
# - Prefab: one object made of parts (models, volumes, prefabs), with an optional script and
#   its property values; or a game prefab: one of the game's entities (a perk machine, wall buy,
#   door, spawn, ...) with its settings, by toolkit piece, entity name or 0x hash. In an
#   inherited map, the base level's own entities are game prefabs with ``base`` set.
#
# Prefab parts are flattened when compiled: a part is an entity named '<Prefab>.<Part>'.

FORMAT = 3
OBJECT_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,47}$')
VOLUME_KINDS = ('trigger', 'hit', 'use')
VOLUME_WHO = ('players', 'zombies', 'anyone')
START_DEFAULTS = {'visible': True, 'collision': True, 'blocks': False}


@dataclass
class Model:
    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = UNIT
    mesh: str = ''            # one of World.meshes (your own geometry)
    game: str = ''            # or a game model: '<group path>#0x<hash>'
    asset: str = ''           # or a project asset (bozkit.assets; attach() sets mesh and scale)
    collision: str = 'solid'
    shape: str = 'mesh'
    padding: float = 0.0      # centimetres a box collision reaches past the model on every side
    block_margin: float = BLOCK_MARGIN   # centimetres between its collision and the player's body
    start: dict = field(default_factory=dict)      # START_DEFAULTS keys that differ
    script: str = ''          # scripts/<path>.lua, e.g. 'prefabs/Wall.lua'
    properties: dict = field(default_factory=dict)

    kind = 'model'

    def quaternion(self) -> tuple[float, float, float, float]:
        return tuple(self.rotation)


@dataclass
class Volume:
    name: str
    kind_of: str = 'trigger'  # VOLUME_KINDS
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    size: tuple[float, float, float] = (100.0, 100.0, 100.0)   # centimetres
    who: str = 'players'      # VOLUME_WHO
    once: bool = False
    prompt: str = ''          # use volumes: the text players see
    cost: int = 0             # use volumes: points it takes
    script: str = ''
    properties: dict = field(default_factory=dict)

    kind = 'volume'

    def quaternion(self) -> tuple[float, float, float, float]:
        return tuple(self.rotation)


@dataclass
class Prefab:
    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = UNIT
    parts: list = field(default_factory=list)      # Model / Volume / Prefab, in the prefab's space
    script: str = ''
    properties: dict = field(default_factory=dict)
    start: dict = field(default_factory=dict)
    library: str = ''         # the library prefab it was placed from (information only)
    # A game prefab: one of the game's entities.
    source: str = ''          # entity name or 0x hash
    group: str = ''           # its group; empty: the base level
    piece: str = ''           # bozkit.toolkit piece
    settings: dict = field(default_factory=dict)   # the piece's settings as the editor shows them
    fields: dict = field(default_factory=dict)     # "Component.field" overrides
    mesh: str = ''            # draws one of the world's meshes instead of its own model
    game: str = ''            # or a game model
    base: bool = False        # the inherited base level's own entity (moved / edited)
    chalk_texture: Texture | None = field(default=None, compare=False, repr=False)

    kind = 'prefab'

    @property
    def is_game(self) -> bool:
        return bool(self.source)

    @property
    def hash(self) -> int:
        return int(self.source, 16) if self.source.startswith('0x') else iw_hash(self.source)

    def quaternion(self) -> tuple[float, float, float, float]:
        return tuple(self.rotation)


@dataclass
class World:
    base: str = 'kino'
    inherit: bool = False     # start from the whole base level (its rooms, entities, navmesh)
    removed: list[str] = field(default_factory=list)   # base level entities taken out (0x hashes)
    meshes: list[Mesh] = field(default_factory=list)   # geometry the models and prefabs use
    models: list[Model] = field(default_factory=list)
    volumes: list[Volume] = field(default_factory=list)
    prefabs: list[Prefab] = field(default_factory=list)

    def objects(self):
        return [*self.models, *self.volumes, *self.prefabs]


def walk(items, prefix: str = ''):
    """(full name, object) of every object and prefab part, depth first ('<Prefab>.<Part>')."""
    for item in items:
        full = f'{prefix}{item.name}'
        yield full, item
        if isinstance(item, Prefab):
            yield from walk(item.parts, full + '.')


# Format 3 files

def _vec(values, digits=4):
    return [round(float(c), digits) for c in values]


def _place_json(item) -> dict:
    out = {'position': _vec(item.position, 3), 'rotation': _vec(item.rotation, 6)}
    scale = getattr(item, 'scale', UNIT)
    if tuple(scale) != UNIT:
        out['scale'] = _vec(scale, 5)
    return out


def _common_json(item, out: dict) -> dict:
    start = {k: v for k, v in getattr(item, 'start', {}).items() if START_DEFAULTS.get(k) != v}
    if start:
        out['start'] = start
    if item.script:
        out['script'] = item.script
    if item.properties:
        out['properties'] = item.properties
    return out


def object_json(item) -> dict:
    if isinstance(item, Model):
        out = {'name': item.name}
        if item.asset:
            out['asset'] = item.asset
        else:
            out.update({'mesh': item.mesh} if item.mesh else {'game': item.game})
        out.update({'collision': item.collision, 'shape': item.shape})
        if item.padding:
            out['padding'] = round(float(item.padding), 2)
        if item.block_margin != BLOCK_MARGIN:
            out['block_margin'] = round(float(item.block_margin), 2)
        out.update(_place_json(item))
        return _common_json(item, out)
    if isinstance(item, Volume):
        out = {'name': item.name, 'volume': item.kind_of, 'position': _vec(item.position, 3),
               'rotation': _vec(item.rotation, 6), 'size': _vec(item.size, 3), 'who': item.who}
        if item.once:
            out['once'] = True
        if item.prompt:
            out['prompt'] = item.prompt
        if item.cost:
            out['cost'] = item.cost
        return _common_json(item, out)
    out = {'name': item.name}
    if item.source:
        out['source'] = item.source
        for key in ('group', 'piece', 'mesh', 'game'):
            if getattr(item, key):
                out[key] = getattr(item, key)
        if item.base:
            out['base'] = True
        if item.settings:
            out['settings'] = item.settings
        if item.fields:
            out['fields'] = item.fields
    else:
        out['parts'] = [object_json(part) for part in item.parts]
        if item.library:
            out['library'] = item.library
    out.update(_place_json(item))
    return _common_json(item, out)


def _floats(values, default):
    return tuple(float(c) for c in values) if values is not None else default


def object_from_json(item: dict):
    common = {'script': str(item.get('script', '')), 'properties': dict(item.get('properties', {}))}
    place = {'position': _floats(item.get('position'), (0.0, 0.0, 0.0)),
             'rotation': _floats(item.get('rotation'), (0.0, 0.0, 0.0, 1.0))}
    if 'volume' in item:
        return Volume(str(item['name']), str(item['volume']), size=_floats(item.get('size'),
                      (100.0, 100.0, 100.0)), who=str(item.get('who', 'players')),
                      once=bool(item.get('once', False)), prompt=str(item.get('prompt', '')),
                      cost=int(item.get('cost', 0)), **place, **common)
    place['scale'] = _floats(item.get('scale'), UNIT)
    start = dict(item.get('start', {}))
    if any(key in item for key in ('mesh', 'game', 'asset')) and 'source' not in item:
        return Model(str(item['name']), mesh=str(item.get('mesh', '')),
                     game=str(item.get('game', '')), asset=str(item.get('asset', '')),
                     collision=str(item.get('collision', 'solid')),
                     shape=str(item.get('shape', 'mesh')), padding=float(item.get('padding', 0.0)),
                     block_margin=float(item.get('block_margin', BLOCK_MARGIN)),
                     start=start, **place, **common)
    return Prefab(str(item['name']), parts=[object_from_json(p) for p in item.get('parts', [])],
                  start=start, library=str(item.get('library', '')),
                  source=str(item.get('source', '')), group=str(item.get('group', '')),
                  piece=str(item.get('piece', '')), settings=dict(item.get('settings', {})),
                  fields=dict(item.get('fields', {})), mesh=str(item.get('mesh', '')),
                  game=str(item.get('game', '')), base=bool(item.get('base', False)),
                  **place, **common)


def _write_meshes(source: Path, meshes: list[Mesh]) -> tuple[list[dict], set]:
    (source / 'meshes').mkdir(parents=True, exist_ok=True)
    (source / 'textures').mkdir(parents=True, exist_ok=True)
    items, wanted = [], set()
    for mesh in meshes:
        item = _write_mesh(source, 'meshes', mesh)
        item.pop('collision', None)
        item.pop('shape', None)
        items.append(item)
        wanted.add(item['file'])
        wanted.update(item['textures'])
    return items, wanted


def _read_meshes(source: Path, data: dict) -> list[Mesh]:
    return [_read_mesh(source, item, 'solid') for item in data.get('meshes', [])]


def save(world: World, source: str | Path) -> None:
    """Write *world* into a project's source folder (format 3), removing files it no longer
    uses (prefab library files in source/prefabs are left alone)."""
    source = Path(source)
    meshes, wanted = _write_meshes(source, world.meshes)
    for folder in ('meshes', 'props', 'textures'):
        if (source / folder).is_dir():
            for old in (source / folder).iterdir():
                if old.suffix in ('.json', '.png') and f'{folder}/{old.name}' not in wanted:
                    old.unlink()
    lines = ['{', f'  "format": {FORMAT},', f'  "base": {json.dumps(world.base)},']
    if world.inherit:
        lines.append('  "inherit": true,')
    if world.removed:
        lines.append(f'  "removed": {json.dumps(sorted(world.removed))},')
    lines += _lines('meshes', meshes) + _lines('models', [object_json(m) for m in world.models])
    lines += _lines('volumes', [object_json(v) for v in world.volumes])
    lines += _lines('prefabs', [object_json(p) for p in world.prefabs], last=True) + ['}']
    (source / 'world.json').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def load(source: str | Path) -> World:
    """A project's world (world.json, format 3)."""
    source = Path(source)
    try:
        data = json.loads((source / 'world.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise WorldError(f'{source / "world.json"} not found: this map has no world yet') from None
    except (OSError, ValueError) as exc:
        raise WorldError(f'cannot read world.json: {exc}') from exc
    if data.get('format') != FORMAT:
        raise WorldError(f'world.json format {data.get("format")!r} is not supported')
    world = World(str(data.get('base', 'kino')), inherit=bool(data.get('inherit', False)),
                  removed=[str(item) for item in data.get('removed', [])],
                  meshes=_read_meshes(source, data))
    try:
        for key, target in (('models', world.models), ('volumes', world.volumes),
                            ('prefabs', world.prefabs)):
            target.extend(object_from_json(item) for item in data.get(key, []))
    except (KeyError, TypeError, ValueError) as exc:
        raise WorldError(f'world.json: {exc}') from exc
    _load_chalk_images(source, world.prefabs)
    return world


def _load_chalk_images(source: Path, prefabs) -> None:
    for _full, item in walk(prefabs):
        if not isinstance(item, Prefab):
            continue
        image = item.settings.get(CHALK_FIELD, '')
        if isinstance(image, str) and image not in ('', 'none'):
            try:
                item.chalk_texture = read_texture(_inside(source, image))
            except (OSError, ValueError) as exc:
                raise WorldError(f'{item.name}: chalk image {image}: {exc}') from exc


# The prefab library: source/prefabs/<Name>.json (+ <Name>/meshes, <Name>/textures)

def library_names(source: str | Path) -> list[str]:
    folder = Path(source) / 'prefabs'
    return sorted(p.stem for p in folder.glob('*.json')) if folder.is_dir() else []


def save_prefab(source: str | Path, prefab: Prefab, meshes: list[Mesh]) -> Path:
    """Store *prefab* (placed at the origin) and the meshes its parts use in the library."""
    if not OBJECT_NAME_RE.fullmatch(prefab.name):
        raise WorldError(f'prefab name {prefab.name!r}: use letters, digits and _')
    folder = Path(source) / 'prefabs'
    own = folder / prefab.name
    if own.is_dir():
        shutil.rmtree(own)
    own.mkdir(parents=True)
    used = meshes_used([prefab])
    items, _wanted = _write_meshes(own, [m for m in meshes if m.name in used])
    stored = copy.deepcopy(prefab)
    stored.position, stored.rotation, stored.scale = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), UNIT
    stored.library = ''
    path = folder / f'{prefab.name}.json'
    path.write_text(json.dumps({'format': FORMAT, 'meshes': items, 'prefab': object_json(stored)},
                               indent=1) + '\n', encoding='utf-8')
    return path


def load_prefab(source: str | Path, name: str) -> tuple[Prefab, list[Mesh]]:
    """A library prefab and the meshes it uses (to add to a world under their names)."""
    path = Path(source) / 'prefabs' / f'{name}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        prefab = object_from_json(data['prefab'])
        meshes = _read_meshes(path.parent / name, data)
    except (OSError, ValueError, KeyError) as exc:
        raise WorldError(f'prefab {name}: {exc}') from exc
    prefab.library = name
    return prefab, meshes


def meshes_used(items) -> set[str]:
    return {item.mesh for _full, item in walk(items) if getattr(item, 'mesh', '')}


# Format 3 checks

def validate(world: World) -> list[str]:
    """Problems that would stop the world from compiling."""
    problems = []
    if world.base not in maps.SHIPPED:
        problems.append(f'base level {world.base!r} is not one of the game\'s levels')
    meshes = {mesh.name for mesh in world.meshes}
    for mesh in world.meshes:
        _check_mesh(mesh, f'mesh {mesh.name!r}', problems)
    names: dict[str, str] = {}
    for full, item in walk(world.objects()):
        label = f'{item.kind} {full!r}'
        if not OBJECT_NAME_RE.fullmatch(item.name):
            problems.append(f'{label}: names use letters, digits and _ (at most 48, starting '
                            'with a letter)')
        key = full.lower()
        if key in names:
            problems.append(f'{full!r}: two objects have this name')
        names[key] = full
        if isinstance(item, Model):
            if bool(item.mesh or item.asset) == bool(item.game):
                problems.append(f'{label}: needs either its own mesh, an asset or a game model')
            elif item.asset and not item.mesh:
                pass    # bozkit.assets.attach() resolves it when the map builds
            elif item.mesh and item.mesh not in meshes:
                problems.append(f'{label}: mesh {item.mesh!r} does not exist')
            elif item.game:
                try:
                    Instance((0, 0, 0), model=item.game).model_ref()
                except ValueError:
                    problems.append(f'{label}: game model {item.game!r} is not <group path>#0x<hash>')
            if item.collision not in COLLISION_KINDS or item.shape not in SHAPES:
                problems.append(f'{label}: collision must be floor, solid or none and shape box or mesh')
            if not 0.0 <= item.padding <= 500.0:
                problems.append(f'{label}: box padding must be between 0 and 500 cm')
            if not 0.0 <= item.block_margin <= 500.0:
                problems.append(f'{label}: blocking margin must be between 0 and 500 cm')
        elif isinstance(item, Volume):
            if item.kind_of not in VOLUME_KINDS:
                problems.append(f'{label}: kind must be trigger, hit or use')
            if item.who not in VOLUME_WHO:
                problems.append(f'{label}: who must be players, zombies or anyone')
            if min(item.size) <= 0:
                problems.append(f'{label}: size must be above zero')
        else:
            if item.is_game and item.parts:
                problems.append(f'{label}: a game prefab has no parts')
            if item.mesh and item.mesh not in meshes:
                problems.append(f'{label}: mesh {item.mesh!r} does not exist')
            if item.base and '.' in full:
                problems.append(f'{label}: the base level\'s entities cannot be prefab parts')
    if world.inherit:   # the base level brings its floors and spawns
        return sorted(set(problems), key=problems.index)
    flat = [item for _full, item in walk(world.objects())]
    if not any(isinstance(i, Prefab) and (i.piece == 'player_spawn' or
                                          i.source.startswith('spawn_player_')) for i in flat):
        problems.append('the world needs a player spawn')
    if not any(isinstance(i, Model) and i.collision == 'floor' for i in flat):
        problems.append('the world needs a walkable model to stand on')
    return sorted(set(problems), key=problems.index)


# Format 1 and 2 -> 3

def _unique(name: str, taken: set) -> str:
    text = ''.join(c if c.isalnum() and c.isascii() else '_' for c in name).strip('_') or 'object'
    if not text[0].isalpha():
        text = 'obj_' + text
    text = text[:44]
    candidate, number = text, 1
    while candidate.lower() in taken:
        number += 1
        candidate = f'{text}_{number}'
    taken.add(candidate.lower())
    return candidate


def _start_of(script: dict) -> dict:
    full = {**SCRIPT_DEFAULTS, **script} if script else {}
    return {key: full[key] for key in START_DEFAULTS if full and full[key] != START_DEFAULTS[key]}


def from_layout(layout: Layout) -> World:
    """A world from a layout (how the templates are built): level meshes and props become models
    (sharing their mesh), placed game models become models, entities become game prefabs."""
    world = World(layout.base, inherit=layout.inherit, removed=list(layout.removed))
    taken: set = set()
    for mesh in layout.meshes + layout.props:
        world.meshes.append(dataclasses.replace(mesh, script={}))
    for mesh in layout.meshes:
        world.models.append(Model(_unique(script_of(mesh).get('name') or mesh.name, taken),
                                  mesh=mesh.name, collision=mesh.collision, shape='mesh',
                                  start=_start_of(mesh.script)))
    props = {prop.name: prop for prop in layout.props}
    for number, instance in enumerate(layout.instances):
        name = script_of(instance).get('name') or (instance.prop or f'model_{number}')
        place = {'position': tuple(instance.position), 'rotation': instance.quaternion(),
                 'scale': tuple(instance.scale), 'start': _start_of(instance.script)}
        if instance.prop:
            prop = props.get(instance.prop)
            world.models.append(Model(_unique(name, taken), mesh=instance.prop,
                                      collision=prop.collision if prop else 'solid',
                                      shape=prop.shape if prop else 'box', **place))
        else:
            world.models.append(Model(_unique(name, taken), game=instance.model,
                                      collision=instance.collision, shape=instance.shape, **place))
    for entity in layout.entities:
        base = layout.inherit and not entity.piece and not entity.group and \
            entity.source.startswith('0x')
        name = script_of(entity).get('name') or (
            f'base_{entity.source[2:]}' if base else entity.source)
        world.prefabs.append(Prefab(
            _unique(name, taken), position=tuple(entity.position), rotation=entity.quaternion(),
            scale=tuple(entity.scale), start=_start_of(entity.script), source=entity.source,
            group=entity.group, piece=entity.piece, settings=dict(entity.settings),
            fields=dict(entity.fields), mesh=entity.prop, game=entity.model, base=base,
            chalk_texture=entity.chalk_texture))
    return world


# Format 3 -> the compiler's layout

def _compose(parent, child):
    """(position, rotation, scale) of *child* (in *parent*'s space) in the world."""

    p_pos, p_rot, p_scale = parent
    c_pos, c_rot, c_scale = child
    scaled = tuple(c_pos[i] * p_scale[i] for i in range(3))
    turned = spec_fields.rotate(tuple(p_rot), scaled)
    return (tuple(p_pos[i] + turned[i] for i in range(3)), spec_fields.quat_mul(tuple(p_rot), tuple(c_rot)),
            tuple(p_scale[i] * c_scale[i] for i in range(3)))


def lower(world: World) -> Layout:
    """The compiler's layout for a format 3 world: prefabs flattened into their parts (named
    '<Prefab>.<Part>'), every object named, and objects scripts may change marked dynamic (own
    collision, tagged walkable area)."""
    layout = Layout(world.base, inherit=world.inherit, removed=list(world.removed))
    meshes = {mesh.name: mesh for mesh in world.meshes}
    variants: dict[tuple, str] = {}
    used_prop_names: set = set()

    def prop_for(mesh_name: str, collision: str, shape: str) -> str:
        key = (mesh_name, collision, shape)
        if key not in variants:
            name = mesh_name
            if name in used_prop_names:
                name = f'{mesh_name[:24]}_{iw_hash(f"{collision}{shape}{mesh_name}") & 0xffff:04x}'
            used_prop_names.add(name)
            layout.props.append(dataclasses.replace(meshes[mesh_name], name=name,
                                                    collision=collision, shape=shape, script={}))
            variants[key] = name
        return variants[key]

    def script_for(full: str, item, dynamic: bool) -> dict:
        start = {**START_DEFAULTS, **getattr(item, 'start', {})}
        dynamic = dynamic or bool(item.script) or any(
            start[k] != START_DEFAULTS[k] for k in START_DEFAULTS)
        return {'name': full, **start, 'dynamic': dynamic}

    def emit(item, transform, prefix: str, scripted_owner: bool) -> None:
        full = f'{prefix}{item.name}'
        position, rotation, scale = _compose(transform, (item.position, item.rotation,
                                                         getattr(item, 'scale', UNIT)))
        if isinstance(item, Model):
            script = script_for(full, item, scripted_owner)
            if item.mesh:
                layout.instances.append(Instance(position, prop=prop_for(
                    item.mesh, item.collision, item.shape), rotation=rotation, scale=scale,
                    script=script, padding=item.padding,
                    block_margin=item.block_margin))
            else:
                layout.instances.append(Instance(position, model=item.game, collision=item.collision,
                                                 shape=item.shape, rotation=rotation, scale=scale,
                                                 script=script, padding=item.padding,
                    block_margin=item.block_margin))
        elif isinstance(item, Volume):
            size = tuple(item.size[i] * scale[i] for i in range(3))
            layout.entities.append(Placement(VOLUME_SOURCES[item.kind_of], position, rotation=rotation,
                                             scale=tuple(c / TRIGGER_SIZE for c in size),
                                             script={'name': full}))
        elif item.is_game:
            # Player spawns are found by their own names (spawn_player_1..4); everything else is
            # called what the world calls it (a base entity's name is its own already).
            name = item.source if item.piece == 'player_spawn' else full
            layout.entities.append(Placement(
                item.source, position, group=item.group, rotation=rotation, scale=scale,
                prop=prop_for(item.mesh, 'none', 'box') if item.mesh else '', model=item.game,
                fields=dict(item.fields), piece=item.piece, settings=dict(item.settings),
                chalk_texture=item.chalk_texture,
                script=script_for(name, item, scripted_owner)))
        else:
            for part in item.parts:
                emit(part, (position, rotation, scale), full + '.', scripted_owner or bool(item.script))

    origin = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), UNIT)
    for item in world.objects():
        emit(item, origin, '', False)
    return layout


def describe(world: World) -> list[dict]:
    """What the Lua runtime (boz.prefabs) needs: every scripted object and every volume, with
    its parts, script module and property values."""
    out = []

    def owner_entry(full: str, item, owner):
        entry = {'name': full, 'kind': item.kind, 'script': _module(item.script),
                 'properties': dict(item.properties), 'owner': owner or ''}
        if isinstance(item, Volume):
            entry.update({'volume': item.kind_of, 'who': item.who, 'once': item.once,
                          'prompt': item.prompt, 'cost': item.cost})
        if isinstance(item, Prefab) and not item.is_game:
            entry['parts'] = [{'name': f'{full}.{part.name}', 'part': part.name, 'kind': part.kind}
                              for part in item.parts]
            # Every entity under it (nested prefabs flattened): what hide() and friends reach.
            entry['members'] = [name for name, member in walk(item.parts, full + '.')
                                if not (isinstance(member, Prefab) and not member.is_game)]
        return entry

    def visit(items, prefix: str, owner: str):
        for item in items:
            full = f'{prefix}{item.name}'
            if item.script or isinstance(item, Volume):
                out.append(owner_entry(full, item, owner))
            if isinstance(item, Prefab):
                visit(item.parts, full + '.', full if item.script else owner)

    visit(world.objects(), '', '')
    return out


def object_names(world: World) -> list[str]:
    """Every object's name in the game, so game events can name the map's objects
    (door_opened says which door)."""
    names = {item.source if getattr(item, 'piece', '') == 'player_spawn' else full
             for full, item in walk(world.objects())}
    return sorted(name for name in names if name)


def _module(script: str) -> str:
    """'prefabs/Vault.lua' -> 'prefabs.Vault' (what require() takes)."""
    if not script:
        return ''
    text = script[:-4] if script.endswith('.lua') else script
    return text.replace('/', '.').replace('\\', '.')


def compile_world(pack, name: str, world: World,
                  fixed: group.Group | None = None, weapons=()) -> levels.LevelFiles:
    """The game's groups for *world* under the level name *name* (format 3: lowered, then
    compiled). *weapons*: the project's bozkit.weapons.WeaponDef (edits, new and imported
    weapons). files.runtime carries the start state and the scripted objects for boz.world."""
    problems = validate(world)
    unattached = sorted({item.asset for _full, item in walk(world.objects())
                         if isinstance(item, Model) and item.asset and not item.mesh})
    if unattached:
        problems.append(f'assets {", ".join(unattached)} were not attached (bozkit.assets.attach)')
    if problems:
        raise WorldError('; '.join(problems))
    layout = lower(world)
    layout.weapons = list(weapons)
    files = _compile_layout(pack, name, layout, fixed)
    files.runtime['objects'] = describe(world)
    files.runtime['names'] = object_names(world)
    return files


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

    def find(self, cls: int, value: int, paths) -> bytes | None:
        for path in paths:
            for resource_type in self.group(path).types():
                if resource_type.class_hash == cls:
                    for resource in resource_type.resources:
                        if resource.in_group_hash == value:
                            return resource.body
        return None

    def model(self, path: str, value: int) -> bytes:
        body = self.find(levels.MODEL, value, [path])
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
                if self.find(levels.MODEL, value, [path]) is not None:
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
        for material_hash in blender_scene.model_materials(body, materials_known):
            material_body = self.find(levels.MATERIAL, material_hash, paths)
            if material_body is None:
                continue
            out[levels.MATERIAL].append((material_hash, material_body))
            try:
                textures = native.decode_material(material_body).textures
            except ValueError:
                textures = []
            for texture_hash in textures:
                texture_body = self.find(levels.TEXTURE, texture_hash, paths) if texture_hash else None
                if texture_body is not None:
                    out[levels.TEXTURE].append((texture_hash, texture_body))
        return out


# Volumes (format 3) compile to entities the compiler makes from shipped templates.
TRIGGER_SOURCE = 'boz:trigger_volume'
HIT_SOURCE = 'boz:hit_volume'
USE_SOURCE = 'boz:use_volume'
VOLUME_SOURCES = {'trigger': TRIGGER_SOURCE, 'hit': HIT_SOURCE, 'use': USE_SOURCE}
TRIGGER_TEMPLATE = 'levels/callofthedead/callofthedead_statics.group.bin'   # CSnowTrigger
HIT_TEMPLATE = 'levels/kino/kino_statics.group.bin'                         # CEasterEgg skulls
USE_TEMPLATE = 'levels/kino/kino_statics.group.bin'                         # barricade CPOI
TRIGGER_SIZE = 100.0   # centimetres: a volume's size at scale 1
HIT_SONG_FIELD = 0xc0c5b1df   # CEasterEgg's song path (unnamed in the reflection)
HIT_SONG = 'boz/hit_volume'   # no such song: the group never completes
WEAPON_FIELD = 'boz.weapon'   # a wall buy's weapon (Placement.fields)
CHALK_FIELD = 'boz.chalk'     # a wall buy's chalk (Placement.settings): '' auto, 'none', an image


def library_map(path: str) -> str:
    parts = path.split('/')
    return parts[1] if parts[0] == 'levels' and len(parts) > 2 else 'shared'


def blob_hashes(blob) -> list[int]:
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
            out += blob_hashes(prop.nested)
        for element in prop.elements or ():
            out += blob_hashes(element)
    return out


def spec_hashes(spec) -> list[int]:
    out = []
    for component in spec.components:
        if component.blob is not None:
            out += blob_hashes(component.blob)
    for _cls, _reserved, child in spec.children:
        out += spec_hashes(child)
    return out


def blob_assets(blob) -> list[tuple[int, tuple[int, int]]]:
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
            out += blob_assets(prop.nested)
        for element in prop.elements or ():
            out += blob_assets(element)
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


def _box_corners(vertices, padding=(0.0, 0.0, 0.0)):
    """The 8 corners of the vertices' bounds, grown by *padding* (per axis, in their units)."""
    low = [min(v[i] for v in vertices) - padding[i] for i in range(3)]
    high = [max(v[i] for v in vertices) + padding[i] for i in range(3)]
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
        self.models = levels.model_index(pack, [f'levels/{base}/{base}_dynamics', 'ingame/ingame'])
        for resource in self.by_class[levels.MODEL].resources:
            self.models.setdefault(resource.in_group_hash, resource.body)
        self.loaded = {INGAME, f'levels/{base}/{base}_dynamics.group.bin', self.base_statics}
        placed = next(r.body for t in levels.read_group_at(pack, levels.PLACED_TEMPLATE).types()
                      if t.class_hash == levels.ENTITY_SPEC for r in t.resources)
        self.placed_template = placed
        self.transform_template = spec_fields.component(resources.decode_entity_spec(placed),
                                                    'CIsTransform')
        self.texture_template = next(r.body for t in levels.read_group_at(pack, levels.TEXTURE_TEMPLATE).types()
                                     if t.class_hash == levels.TEXTURE for r in t.resources
                                     if levels.is_raw_texture(r.body))
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
        self._loaded = None
        self.inherited = False
        self.moved: list[group.Resource] = []   # an inherited level's own entities, moved
        self.wall_buys: list = []                  # (placement, spec) of placed wall buys
        self.dirty: list[tuple[float, float, float, float]] = []   # XZ metres, for the navmesh
        # Objects scripts change: their own collision, tagged walkable areas, start state.
        self.script_collision: dict[str, tuple[list, list]] = {}
        self.blockers: list = []                   # door_footprints entries tagged by script name
        self.blocker_points: dict = {}             # name hash -> (footprint points, below, grow)
        self.player_radius = _player_radius(statics)
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

    def copy_model(self, path: str, value: int) -> int:
        """Bring a game model (and what it uses) into the map; returns its name there (its own,
        unless the map already had a different model of that name)."""
        self.repack([value], path)
        name = self._bundle.name_of(path, value) if path else value
        if name not in self.models:
            body = self._bundle.present().get((levels.MODEL, name))
            if body is None and path:
                entry = next((e for e in self._bundle.registry.entries(value)
                              if e.cls == levels.MODEL and e.path == path), None)
                body = entry.resource.body if entry else None
            if body is not None:
                self.models[name] = body
        return name

    # Repacking: whatever a placed entity or model uses comes with it from its own map.

    def bundle(self):
        """The bozkit.bundle.Bundle that brings resources of any map into this one."""
        from . import bundle
        if getattr(self, '_bundle', None) is None:
            groups = dict(getattr(self, 'groups', None) or {})
            groups[f'{self.name}_statics.group.bin'] = self.statics
            self._bundle = bundle.Bundle(bundle.Registry.of(self.pack), groups, self.name)
        return self._bundle

    def repack(self, hashes, source: str) -> int:
        """Copy the resources *hashes* name (and what they use, transitively) from the game's
        groups into the map, unless it already has them (bozkit.bundle: any map's, weapon groups
        too; clashing names get names of their own). Returns how many."""
        bundle = self.bundle()
        copied = bundle.add(hashes, prefer=source)
        for cls, name, _path, _target in bundle.copied[-copied:] if copied else []:
            if cls == levels.MODEL:
                self.models[name] = bundle.present()[(cls, name)]
        self._loaded = None
        return copied

    def _mark(self, points) -> None:
        if points:
            xs = [p[0] / 100 for p in points]
            zs = [p[2] / 100 for p in points]
            self.dirty.append((min(xs) - 1, min(zs) - 1, max(xs) + 1, max(zs) + 1))

    def entity(self, entity: Placement, move_existing: bool) -> None:
        from . import reflect, resources

        if entity.source == TRIGGER_SOURCE:
            self._trigger_volume(entity)
            return
        if entity.source in (HIT_SOURCE, USE_SOURCE):
            self._template_volume(entity)
            return
        in_base = not entity.group or entity.group == self.base_statics
        existing = self.specs.get(entity.hash) if in_base else None
        rotation, scale = entity.quaternion(), tuple(entity.scale)
        if existing is not None and move_existing and not entity.piece and entity.hash not in self.used:
            # An inherited level's own entity: move it where the world puts it.
            self.used.add(entity.hash)
            spec = resources.decode_entity_spec(existing.body)
            old = spec_fields.local_transform(spec)[0]
            self._configure(spec, entity, rotation, scale)
            existing.body = resources.encode_entity_spec(spec)
            self._mark([old, entity.position])
            self.moved.append(existing)
            if entity.script and script_of(entity)['dynamic']:
                self._script_entity(entity, existing, spec)
            return
        if existing is not None:
            body = existing.body
        else:
            if in_base:
                raise WorldError(f'{self.base} has no entity {entity.source!r}')
            body = self.game.find(levels.ENTITY_SPEC, entity.hash, [entity.group])
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
            named = spec_fields.component(spec, 'CIsNamed')
            prop = spec_fields.prop(named.blob, 'name') if named and named.blob else None
            if prop is not None:
                reflect.set_typed_value(prop, copy_name)
        door = spec_fields.component(spec, 'CDoor')
        if door is not None and door.blob is not None and not (self.inherited and in_base):
            # A door unlocks areas of its own map: generated maps have one area, and another
            # map's areas are not in this one, so it unlocks none.
            areas = spec_fields.prop(door.blob, 'm_AreasUnlock')
            if areas is not None:
                areas.raw = struct.pack('<I', 0)
        if spec_fields.component(spec, 'CIsTransform') is None:
            # Templates (in ingame) have no transform of their own; placed copies need one.
            spec.components.insert(0, copy.deepcopy(self.transform_template))
        self._configure(spec, entity, rotation, scale)
        resource = group.Resource(None, key, resources.encode_entity_spec(spec))
        if entity.group and entity.group not in self.loaded:
            # Everything it uses comes with it from its own map (models, textures, animations,
            # state machines, sounds), unless the level already has them.
            self.repack(spec_hashes(spec), entity.group)
        if spec_fields.component(spec, 'CSpawnPoint'):
            self.zombie_spawns.append(key)
        if spec_fields.component(spec, 'CWeaponChalkOutline') is not None:
            self.wall_buys.append((entity, spec))
            poi = spec_fields.component(spec, 'CPOI')
            if poi is not None and poi.blob is not None:
                # Usable from either side, as doors are: a wall buy placed facing the wall
                # would otherwise have no prompt.
                prop = spec_fields.prop(poi.blob, 'm_BiDirection')
                if prop is None:
                    prop = reflect.Property(iw_hash('CPOI'), iw_hash('bool'),
                                            iw_hash('m_BiDirection'), b'')
                    poi.blob.properties.append(prop)
                reflect.set_typed_value(prop, True)
                resource.body = resources.encode_entity_spec(spec)
        self.kept.append(resource)
        self.added.append(resource)
        self._mark([entity.position])
        if entity.script and script_of(entity)['dynamic']:
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
                if spec_fields.component(spec, 'CSnowTrigger') is not None and spec.children:
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
        spec_fields.set_transform(spec, entity.position, entity.quaternion())
        box = spec_fields.component(spec, 'CIsCollisionBox')
        half = [TRIGGER_SIZE / 2 * abs(c) for c in entity.scale]
        reflect.set_typed_value(spec_fields.prop(box.blob, 'm_halfAxis'), half)
        for prop in box.blob.properties:
            # m_Offset and an unnamed offset (0x3f9a899b, non-zero in the snow boxes): centred.
            if prop.name_hash in (iw_hash('m_Offset'), 0x3f9a899b):
                reflect.set_typed_value(prop, [0.0, 0.0, 0.0])
        ghost = spec_fields.prop(box.blob, 'm_Ghost')
        if ghost is None:
            ghost = reflect.Property(iw_hash('CIsCollisionObject'), iw_hash('bool'),
                                     iw_hash('m_Ghost'), b'')
            box.blob.properties.append(ghost)
        reflect.set_typed_value(ghost, True)
        resource = group.Resource(None, iw_hash(name), resources.encode_entity_spec(spec))
        self.kept.append(resource)
        # No box of its own in the collision or the navmesh, so the walkable area around it is
        # not rebuilt (a rebuilt tile is never quite as good as the game's own).
        self.own.add(id(resource))
        self.script(entity)

    def _template_spec(self, path: str, component: str):
        from . import resources

        for resource_type in group.parse(self.pack.read(path)).types():
            if resource_type.class_hash != levels.ENTITY_SPEC:
                continue
            for item in resource_type.resources:
                spec = resources.decode_entity_spec(item.body)
                if spec_fields.component(spec, component) is not None:
                    return spec
        raise WorldError(f'the game has no {component} entity to copy ({path})')

    def _template_volume(self, entity: Placement) -> None:
        """A Hit volume (a musical easter egg skull: health, a collision sphere, reports
        weapon hits) or a Use volume (a barricade's point of interest without the barricade:
        the game shows no prompt for it, scripts do)."""
        from . import reflect, resources

        size = max(abs(c) for c in entity.scale) * TRIGGER_SIZE
        if entity.source == HIT_SOURCE:
            spec = self._template_spec(HIT_TEMPLATE, 'CEasterEgg')
            sphere = spec_fields.component(spec, 'CIsCollisionSphere')
            radius = spec_fields.prop(sphere.blob, 'm_radius') if sphere and sphere.blob else None
            if radius is not None:
                reflect.set_typed_value(radius, size / 2)
            # The musical easter egg manager groups skulls by song: a song of its own keeps the
            # volume out of the level's easter egg (boz.objects reports the hit and skips it).
            egg = spec_fields.component(spec, 'CEasterEgg')
            for prop in egg.blob.properties if egg and egg.blob else []:
                if prop.name_hash == HIT_SONG_FIELD:
                    reflect.set_typed_value(prop, HIT_SONG)
        else:
            barricade = self._template_spec(USE_TEMPLATE, 'CBarricade')
            keep = {iw_hash(n) for n in ('CIsTransform', 'CIsNamed', 'CPOI', 'CIsBroadcaster')}
            spec = copy.deepcopy(barricade)
            spec.components = [c for c in spec.components if c.type_hash in keep]
            spec.children = []
            poi = spec_fields.component(spec, 'CPOI')
            # The game offers a point of interest only within its reach (m_MaxDistance, from the
            # player to its centre), height (m_MaxYDistance) and viewing cone (m_ViewingAngle
            # around its forward axis, both ways with m_BiDirection). A Use volume works from
            # every side: no cone, reach past its edge by an arm's length, the height of its box.
            for field, kind, value in (('m_MaxDistance', 'float', size / 2 + 100.0),
                                       ('m_MaxYDistance', 'float', size / 2 + 100.0),
                                       ('m_HeightOffset', 'float', 0.0),
                                       ('m_AngleDistanceOffset', 'float', 0.0),
                                       ('m_ViewingAngle', 'float', 360.0),
                                       ('m_BiDirection', 'bool', True),
                                       ('m_IsReverseViewAngle', 'bool', False)):
                prop = spec_fields.prop(poi.blob, field)
                if prop is None:
                    prop = reflect.Property(iw_hash('CPOI'), iw_hash(kind), iw_hash(field), b'')
                    poi.blob.properties.append(prop)
                reflect.set_typed_value(prop, value)
        spec = copy.deepcopy(spec)
        self.copies += 1
        name = script_of(entity).get('name') or f'{self.name}_volume_{self.copies}'
        self._name(spec, name)
        spec_fields.set_transform(spec, entity.position, entity.quaternion())
        resource = group.Resource(None, iw_hash(name), resources.encode_entity_spec(spec))
        self.kept.append(resource)
        self.own.add(id(resource))    # nothing walkable changes: its navmesh tiles stay as shipped

    def _script_entity(self, entity: Placement, resource, spec) -> None:
        """A scripted entity: no baked box (its own collision is switched instead); a blocking
        one tags the walkable area under it with its name."""
        from . import native

        self.scripted.add(id(resource))
        corners = []
        for box in levels.prop_boxes(spec, self.models):
            corners += box
        model = spec_fields.model_reference(spec)
        if not corners and model in self.models:
            chain = [spec_fields.local_transform(spec)]
            corners = [spec_fields.apply_chain(chain, c)
                       for c in _box_corners(native.decode_model(self.models[model]).vertices)]
        if not corners:
            corners = [tuple(entity.position)]
        self.script(entity, corners)

    def _configure(self, spec, entity: Placement, rotation, scale) -> None:
        """Transform, custom model and field overrides of a placed entity."""
        from . import reflect

        spec_fields.set_transform(spec, entity.position, rotation)
        spec_fields.scale_by(spec, scale)   # relative: weapons and wall buys have their own scale
        if entity.prop:
            self._draw_model(spec, iw_hash(f'{self.name}_prop_{entity.prop}'))
        elif entity.model:
            path, model_hash = Instance((0.0, 0.0, 0.0), model=entity.model).model_ref()
            model_hash = self.copy_model(path, model_hash)
            self._draw_model(spec, model_hash)
        for key, value in entity.fields.items():
            if key == WEAPON_FIELD:
                self._set_weapon(spec, entity, str(value))
                continue
            component_name, _, field_name = key.partition('.')
            component = spec_fields.component(spec, component_name)
            prop = spec_fields.prop(component.blob, field_name) if component and component.blob \
                else None
            if isinstance(value, (list, tuple)):
                # A list of names (the mystery box's weapon pool): std::list<unsigned int>.
                from . import toolkit as toolkit_module
                if component is None or component.blob is None:
                    raise WorldError(f'entity {entity.source!r} has no field {key}')
                if prop is None:
                    prop = reflect.Property(iw_hash(component_name),
                                            iw_hash('std::list<unsigned int>'), iw_hash(field_name),
                                            b'')
                    component.blob.properties.append(prop)
                prop.raw = toolkit_module.encode_hash_list(
                    [int(v, 16) if str(v).startswith('0x') else iw_hash(str(v)) for v in value])
                prop.nested = prop.elements = None
                continue
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

        renderable = spec_fields.component(spec, 'CIsRenderableModel')
        if renderable is None:
            template = spec_fields.component(resources.decode_entity_spec(self.placed_template),
                                         'CIsRenderableModel')
            renderable = copy.deepcopy(template)
            at = next((i + 1 for i, c in enumerate(spec.components)
                       if c.type_hash == iw_hash('CIsTransform')), 0)
            spec.components.insert(at, renderable)
        for element in spec_fields.prop(renderable.blob, 'assets').elements:
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
                      if spec_fields.component(c, 'CIsRenderableModel') is not None), None)
        if child is None:
            raise WorldError(f'entity {entity.source!r} has no weapon display to change')
        renderable = spec_fields.component(child, 'CIsRenderableModel').blob
        skel_prop = spec_fields.prop(renderable, 'skel')
        if skel_prop is not None and skel:
            reflect.set_typed_value(skel_prop, skel)
        for element in spec_fields.prop(renderable, 'assets').elements:
            for prop in element.properties:
                if prop.name_hash in (iw_hash('name'), iw_hash('Name')):
                    reflect.set_typed_value(prop, name_hash)
                elif prop.name_hash == iw_hash('model'):
                    reflect.set_typed_value(prop, model)
                elif prop.name_hash == iw_hash('skin'):
                    reflect.set_typed_value(prop, skin)

    def _weapon_display(self, name_hash: int):
        """(skeleton, model, skin) a wall buy shows for a weapon of the level's weapons group
        (with the project's weapons applied: new weapons show their base's model)."""
        from . import reflect, resources

        name_hash = getattr(self, 'weapon_aliases', {}).get(name_hash, name_hash)
        # A shipped wall buy of the same weapon shows exactly what the game expects (unless the
        # weapon has a model of its own: then its own low-detail model, below).
        own = name_hash in getattr(self, 'weapon_own_models', set())
        for resource in [] if own else self.by_class[levels.ENTITY_SPEC].resources + [
                r for t in self.game.group(self.base_statics).types()
                if t.class_hash == levels.ENTITY_SPEC for r in t.resources]:
            try:
                spec = resources.decode_entity_spec(resource.body)
            except (ValueError, struct.error):
                continue
            if spec_fields.component(spec, 'CWeaponChalkOutline') is None:
                continue
            for _cls, _reserved, child in spec.children:
                renderable = spec_fields.component(child, 'CIsRenderableModel')
                if renderable is None or renderable.blob is None:
                    continue
                for name, (model, skin) in blob_assets(renderable.blob):
                    if name == name_hash:
                        skel = spec_fields.prop(renderable.blob, 'skel')
                        return (reflect.typed_value(skel) if skel is not None else 0), model, skin
        gear = maps.gear(self.base)
        weapons = getattr(self, 'weapon_group', None)
        if weapons is None:
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
                skel = spec_fields.prop(blob, 'skel')
                skel = reflect.typed_value(skel) if skel is not None else 0
                found = []
                for prop in blob.properties:
                    for nested in ([prop.nested] if prop.nested else []):
                        found += blob_assets(nested)
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
        spec_fields.set_transform(spec, position, rotation)
        spec_fields.set_transform(spec, scale=scale)
        if named:
            self._name(spec, entity_name)
        renderable = spec_fields.component(spec, 'CIsRenderableModel').blob
        for element in spec_fields.prop(renderable, 'assets').elements:
            for prop in element.properties:
                if prop.name_hash in (iw_hash('Name'), iw_hash('model')):
                    reflect.set_typed_value(prop, model_hash)
        resource = group.Resource(None, iw_hash(entity_name), resources.encode_entity_spec(spec))
        self.kept.append(resource)
        self.own.add(id(resource))

    def _name(self, spec, name: str) -> None:
        """Give an entity spec the CIsNamed name boz.objects finds it by."""
        from . import reflect, resources

        named = spec_fields.component(spec, 'CIsNamed')
        if named is None:
            template = next(c for r in self.by_class[levels.ENTITY_SPEC].resources
                            for c in resources.decode_entity_spec(r.body).components
                            if c.type_hash == iw_hash('CIsNamed') and c.blob is not None)
            named = copy.deepcopy(template)
            spec.components.insert(1, named)
        reflect.set_typed_value(spec_fields.prop(named.blob, 'name'), name)

    def script(self, item, footprint_points=None, margin: float = BLOCK_MARGIN) -> str:
        """Record a scripted object's start state; returns its script name ('' for none)."""
        script = script_of(item)
        name = script.get('name', '')
        if not name:
            return ''
        if not script['visible']:
            self.runtime['hidden'].append(name)
        if not script['collision']:
            self.runtime['no_collision'].append(name)
        if script['blocks'] and script['dynamic']:
            self.runtime['blocked'].append(name)
            if footprint_points:
                # A little below it: the floor it stands on is what gets tagged. The area is the
                # object's collision footprint (its box with padding), so they match.
                # The margin is the gap to the player's body: the area also reaches the player's
                # radius past it, as shipped floor stops that far from walls.
                grow = margin / 100 + self.player_radius
                self.blockers.append(_tag_area(iw_hash(name), footprint_points, below=0.3,
                                               grow=grow))
                self.blocker_points[iw_hash(name)] = (footprint_points, 0.3, grow)
        return name

    def collide(self, vertices, triangles, kind: str, shape: str, position=None,
                rotation=(0.0, 0.0, 0.0, 1.0), scale=UNIT, script: str = '',
                padding: float = 0.0) -> list:
        """Add collision; a scripted object's goes into its own collision entity. Returns the
        world-space points used."""

        if kind == 'none':
            return []
        chain = [(tuple(position), tuple(rotation), tuple(scale))] if position else []
        # Padding is in world centimetres: in the model's own units it is divided by its scale.
        local_padding = tuple(padding / abs(scale[i]) if scale[i] else 0.0 for i in range(3))
        if script:
            solid, single = self.script_collision.setdefault(script, ([], []))
            if shape == 'box':
                points = [spec_fields.apply_chain(chain, c) for c in _box_corners(vertices, local_padding)]
                single.extend(levels.box_triangles(len(solid)))
            else:
                points = [spec_fields.apply_chain(chain, tuple(map(float, v))) if chain
                          else tuple(map(float, v)) for v in vertices]
                single.extend((a + len(solid), b + len(solid), c + len(solid))
                              for a, b, c in triangles)
            solid.extend(points)
            # Not marked for a navmesh rebuild: its walkable area is tagged (navcut), not cut.
            return points
        before = len(self.single)
        if shape == 'box':
            points = [spec_fields.apply_chain(chain, c) for c in _box_corners(vertices, local_padding)]
            self.single.extend(levels.box_triangles(len(self.solid)))
            self.solid.extend(points)
        else:
            offset = len(self.solid)
            points = [spec_fields.apply_chain(chain, tuple(map(float, v))) if chain
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
            weapon = chalk.weapon_of(spec)
            weapon_key = weapon
            if isinstance(weapon, int):
                weapon_key = getattr(self, 'weapon_aliases', {}).get(weapon, weapon)
            own = weapon_key in getattr(self, 'weapon_own_models', set())
            decal = decals.get(weapon_key) if not entity.chalk_texture and not own else None
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
        gear = maps.gear(self.base)
        body = self.game.find(levels.MODEL, display[1], [f'ingame/weapons/weapons_{gear}.group.bin'])
        if body is None and getattr(self, 'weapon_group', None) is not None:
            # An imported weapon's model is in the map's own weapons group.
            body = next((r.body for t in self.weapon_group.types() if t.class_hash == levels.MODEL
                         for r in t.resources if r.in_group_hash == display[1]), None)
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
        body = self.game.find(levels.MODEL, template.model, paths)
        if body is None:
            return False
        quad = native.decode_model(body)
        known = {r.in_group_hash for p in paths for t in self.game.group(p).types()
                 if t.class_hash == levels.MATERIAL for r in t.resources}
        refs = scene.model_materials(body, known)
        material_body = self.game.find(levels.MATERIAL, refs[0], paths) if refs else None
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

    def build_props(self, world: Layout) -> None:
        for prop in world.props:
            self.build(prop, f'{self.name}_prop_{prop.name}')

    def contents(self, world: Layout) -> None:
        """The world's own meshes and instances (props are built first: build_props)."""
        from . import native

        name = self.name
        for mesh in world.meshes:
            model_name = f'{name}_{mesh.name}'
            script = script_of(mesh).get('name', '')
            dynamic = script if script_of(mesh).get('dynamic', True) else ''
            self.build(mesh, model_name)
            self.place(script or model_name, iw_hash(model_name), (0, 0, 0), named=bool(script))
            points = self.collide(mesh.vertices, mesh.triangles, mesh.collision, 'mesh',
                                  script=dynamic)
            self.script(mesh, points or [tuple(map(float, v)) for v in mesh.vertices])
        props = {prop.name: prop for prop in world.props}
        for number, instance in enumerate(world.instances):
            rotation, scale = instance.quaternion(), tuple(instance.scale)
            script = script_of(instance).get('name', '')
            dynamic = script if script_of(instance).get('dynamic', True) else ''
            if instance.prop:
                prop = props[instance.prop]
                self.place(script or f'{name}_prop_{prop.name}_{number}',
                           iw_hash(f'{name}_prop_{prop.name}'), instance.position, rotation, scale,
                           named=bool(script))
                points = self.collide(prop.vertices, prop.triangles, prop.collision, prop.shape,
                                      instance.position, rotation, scale, script=dynamic,
                                      padding=instance.padding)
            else:
                path, model_hash = instance.model_ref()
                model_hash = self.copy_model(path, model_hash)
                self.place(script or f'{name}_model_{number}', model_hash, instance.position,
                           rotation, scale, named=bool(script))
                decoded = native.decode_model(self.models[model_hash])
                points = self.collide(decoded.vertices, decoded.triangles, instance.collision,
                                      instance.shape, instance.position, rotation, scale,
                                      script=dynamic, padding=instance.padding)
            self.script(instance, points, instance.block_margin)

    def script_collisions(self) -> None:
        """A collision entity (<name>_collision, a copy of the level's) for each scripted object
        with collision, so boz.objects can switch it."""
        from . import collision, resources

        if not self.script_collision:
            return
        # The level's own collision entity (kept in an inherited level; a generated level adds
        # it after this, from the base level's statics).
        candidates = list(self.kept) + list(self.by_class[levels.ENTITY_SPEC].resources)
        source = next((r for r in candidates if any(
            c.class_hash == resources.COLLISION_MESH_SPEC
            for c in resources.decode_entity_spec(r.body).components)), None)
        if source is None:
            raise WorldError(f'{self.base} has no collision entity to copy')
        for name, (solid, single) in sorted(self.script_collision.items()):
            spec = resources.decode_entity_spec(source.body)
            spec_fields.set_transform(spec, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
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
            if spec_fields.component(spec, 'CDoor') is not None:
                continue   # doors gate the navmesh (door_footprints), they do not cut it
            for box in levels.prop_boxes(spec, self.models):
                self.single += levels.box_triangles(len(self.solid))
                self.blocking += [1] * 12
                self.solid += box
                self._mark(box)

    def door_footprints(self, resources_list, blockers: bool = True) -> list:
        """(name hash, XZ footprint in metres, min y, max y) of each door (its collision boxes
        and its model), for navbuild; with the areas of blocking objects unless *blockers* is
        false."""
        from . import native, resources

        doors = []
        for resource in resources_list:
            spec = resources.decode_entity_spec(resource.body)
            if spec_fields.component(spec, 'CDoor') is None:
                continue
            own = spec_fields.value(spec_fields.component_blob(spec, 'CIsNamed'), 'name', None)
            name_hash = iw_hash(own) if isinstance(own, str) else resource.in_group_hash
            corners = [c for box in levels.prop_boxes(spec, self.models) for c in box]
            # Debris and boats are bigger than their collision slab: the whole model is shut.
            model = spec_fields.model_reference(spec)
            if model in self.models:
                vertices = native.decode_model(self.models[model]).vertices
                chain = [spec_fields.local_transform(spec)]
                corners += [spec_fields.apply_chain(chain, c) for c in _box_corners(vertices)]
            if not corners:
                continue
            doors.append(_tag_area(name_hash, corners))
        return doors + (self.blockers if blockers else [])

    def build_navmesh(self, build) -> bytes:
        """Run *build* (doors -> navmesh body) until every blocking object's area made it into
        the navmesh: Recast drops regions under its minimum size (a thin wall in a tight spot),
        so a missing one is grown and the navmesh built again. One still missing is reported in
        runtime['warnings'] (its spot stays walkable)."""
        body = build()
        for extra in (0.3, 0.6, 1.2):
            missing = set(self.blocker_points) - _navmesh_tags(body)
            if not missing:
                return body
            self.blockers = [_tag_area(h, self.blocker_points[h][0], below=self.blocker_points[h][1],
                                       grow=self.blocker_points[h][2] + extra) if h in missing else entry
                             for entry in self.blockers for h in (entry[0],)]
            body = build()
        missing = set(self.blocker_points) - _navmesh_tags(body)
        if missing:
            self.runtime.setdefault('warnings', []).append(
                f'{len(missing)} blocking objects have no walkable floor under them to block')
        return body

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


TAG_GROW = 0.1   # metres a door's tagged area reaches past its collision on every side


def _player_radius(statics) -> float:
    """The level navmesh's agent radius (metres), else PLAYER_RADIUS."""
    from . import navbuild, navigation

    for resource_type in statics.types():
        if resource_type.class_hash == levels.NAVMESH and resource_type.resources:
            try:
                return navbuild.Settings.from_raw(
                    navigation.decode(resource_type.resources[0].body).config.raw).agent_radius
            except (ValueError, struct.error):
                break
    return PLAYER_RADIUS


def _navmesh_tags(body: bytes) -> set[int]:
    """The name hashes navmesh polygons are tagged with."""
    from . import navigation

    tags = set()
    for tile in navigation.decode(body).tiles:
        for poly in navigation.decode_tile(tile.data).polys:
            if poly.extra:
                tags.add(poly.extra)
    return tags


def _tag_area(name_hash: int, corners, below: float = 0.0, grow: float = TAG_GROW) -> tuple:
    """(name hash, XZ hull in metres, min y, max y) of points in centimetres: a navmesh area
    tagged with the name (doors, and objects scripts open and close). The outline is grown
    evenly on every side (a circle swept around the hull), so a thin wall still tags a strip
    wide enough for the navmesh to keep (a narrow one is dropped when regions are built)."""
    import math

    points = [(x / 100, z / 100) for x, _y, z in corners]
    swept = [(x + grow * math.cos(angle), z + grow * math.sin(angle))
             for x, z in points for angle in (i * math.pi / 8 for i in range(16))]
    ys = [y / 100 for _x, y, _z in corners]
    return (name_hash, _hull(swept), min(ys) - below, max(ys))


def _compile_layout(pack, name: str, world: Layout,
                    fixed: group.Group | None = None) -> levels.LevelFiles:
    """The game's groups for *world* under the level name *name*.

    A generated world gets the base level's weapons, arms, rounds, zombie types, sounds and
    cameras, the world's own models, props and entities, and a collision mesh and navmesh built
    from them (no rooms). An inherited world (``inherit``) is the whole base level, rooms and
    all, with the world's additions and moved entities; only the navmesh tiles near changes are
    rebuilt.
    """
    problems = _validate_layout(world)
    if problems:
        raise WorldError('; '.join(problems))
    if world.inherit:
        return _compile_inherited(pack, name, world, fixed)
    from . import navbuild, resources

    base = world.base
    files = levels.common_files(pack, name, base, fixed)
    statics = levels.read_group_at(pack, f'levels/{base}/{base}_statics')
    levels.rename_level_resource(statics, base, name)
    level = _Level(pack, name, base, statics)
    level.groups = files.groups
    _apply_weapons(pack, files, name, base, level, world.weapons)
    by_class = level.by_class
    for resource in by_class[levels.ENTITY_SPEC].resources:  # cameras: intro and main
        if spec_fields.component(resources.decode_entity_spec(resource.body), 'CIsCamera'):
            level.kept.append(resource)
    level.build_props(world)
    for entity in world.entities:
        level.entity(entity, move_existing=False)

    # The starting area lists the zombie spawns that are in the world.
    level_blob = resources.decode_reflected(by_class[levels.LEVEL].resources[0].body)
    (start_area,) = struct.unpack_from('<I', spec_fields.prop(level_blob, 'm_StartingArea').raw)
    areas = [r for r in by_class[levels.AREA].resources if r.in_group_hash == start_area]
    if not areas:
        raise WorldError(f'{base} has no starting area')
    area_blob = resources.decode_reflected(areas[0].body)
    spawns = level.zombie_spawns
    spec_fields.prop(area_blob, 'm_SpawnPoints').raw = struct.pack(
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
    template = navmesh.body
    navmesh.body = level.build_navmesh(lambda: navbuild.build(
        template, [(x / 100, y / 100, z / 100) for x, y, z in level.solid], level.single,
        blocking=level.blocking, doors=level.door_footprints(level.kept)))

    files.groups[f'{name}.group.bin'] = levels.renamed(
        levels.read_group_at(pack, f'levels/{base}/{base}'), name,
        [levels.Child(f'levels/{base}//{base}_dynamics.group', f'{base}_dynamics'),
         levels.Child(f'levels/{name}//{name}_statics.group', f'{name}_statics')])
    without_children = levels.renamed(statics, f'{name}_statics')
    without_children.sections = [x for x in without_children.sections if x.hash != levels.CHILDREN]
    files.groups[f'{name}_statics.group.bin'] = without_children
    files.runtime = level.runtime
    return files


def _apply_weapons(pack, files, name: str, base: str, level, defs) -> None:
    """The project's weapon edits, new and imported weapons, in the map's weapons, projectiles
    and arms groups (before anything is placed, so wall buys can sell them)."""
    from . import weapons as weapons_module

    if not defs:
        return
    groups = {'weapons': files.groups[f'weapons_{name}.group.bin'],
              'projectiles': files.groups[f'weapon_projectiles_{name}.group.bin'],
              'arms': files.groups[f'arms_{name}.group.bin']}
    try:
        result = weapons_module.apply(pack, groups, base, list(defs), bundle=level.bundle())
    except weapons_module.WeaponError as exc:
        raise WorldError(str(exc)) from None
    level.weapon_group = groups['weapons']
    level.weapon_aliases = result['aliases']
    level.weapon_own_models = result.get('own_models', set())
    level.runtime.setdefault('warnings', []).extend(result['warnings'])


def _compile_inherited(pack, name: str, world: Layout, fixed) -> levels.LevelFiles:
    from . import blender_scene as scene
    from . import navbuild, resources

    base = world.base
    files = levels.clone_level(pack, name, base, fixed)
    statics = files.groups[f'{name}_statics.group.bin']
    level = _Level(pack, name, base, statics)
    level.groups = files.groups
    _apply_weapons(pack, files, name, base, level, world.weapons)
    level.inherited = True
    removed = {int(value, 16) if value.startswith('0x') else iw_hash(value) for value in world.removed}
    level.kept = []
    for resource in level.by_class[levels.ENTITY_SPEC].resources:
        if resource.in_group_hash in removed:
            # Taken out in the editor: its navmesh tiles are rebuilt without it.
            level._mark([spec_fields.local_transform(resources.decode_entity_spec(resource.body))[0]])
            continue
        level.kept.append(resource)
    level.build_props(world)
    for entity in world.entities:
        level.entity(entity, move_existing=True)
    level.contents(world)
    level.add_chalks()
    level.entity_boxes(level.added)
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
    # Collision of objects scripts change comes after the navmesh input: their walkable area is
    # a tagged one the script opens and closes, not a hole cut around them.
    level.script_collisions()
    level.finish_entities()
    if level.solid:
        # The world's own collision: a copy of the level's collision entity, at the origin.
        source = next((r for r in level.kept if any(
            c.class_hash == resources.COLLISION_MESH_SPEC
            for c in resources.decode_entity_spec(r.body).components)), None)
        if source is None:
            raise WorldError(f'{base} has no collision entity to copy')
        spec = resources.decode_entity_spec(source.body)
        spec_fields.set_transform(spec, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        added = group.Resource(None, iw_hash(f'{name}_world_collision'),
                               resources.encode_entity_spec(spec))
        level.set_collision(added)
        level.kept.append(added)
        level.finish_entities()
    navmesh = level.by_class[levels.NAVMESH].resources[0]
    if navmesh_input is not None:
        # Geometry changed: Recast rebuilds the tiles around it (added doors gate theirs).
        vertices, triangles = navmesh_input
        offset = len(vertices)
        vertices = list(vertices) + [(x / 100, y / 100, z / 100) for x, y, z in level.solid]
        triangles = list(triangles) + [(a + offset, b + offset, c + offset)
                                       for a, b, c in level.single]
        blocking = [0] * len(navmesh_input[1]) + level.blocking
        navmesh.body = navbuild.rebuild(
            navmesh.body, vertices, triangles, dirty=level.dirty, blocking=blocking,
            doors=level.door_footprints(level.added + level.moved, blockers=False))[0]
    if level.blockers:
        # Blocking objects: their floor is cut out of the tiles as they are and tagged, so the
        # rest of each tile stays the game's own (a Recast rebuild loses some of the designers'
        # floor, Kino's stairs among it).
        from . import navcut
        navmesh.body, tagged = navcut.cut_areas(navmesh.body, level.blockers)
        missing = set(level.blocker_points) - tagged
        if missing:
            level.runtime.setdefault('warnings', []).append(
                f'{len(missing)} blocking objects have no walkable floor under them to block')
    files.runtime = level.runtime
    return files
