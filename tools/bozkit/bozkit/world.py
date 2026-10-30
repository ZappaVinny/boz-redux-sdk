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
entities); see the Format 3 section. bozkit.world_compile lowers a world into a Layout (level
meshes, props, instances, entities) and turns that into the game's groups.
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

from . import levels, maps, png, spec_fields
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
                                                       + '\n', encoding='utf-8', newline='\n')
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


def validate_layout(world: Layout) -> list[str]:
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
    (source / 'world.json').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


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
                               indent=1) + '\n', encoding='utf-8', newline='\n')
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


# Volumes compile to entities made from shipped templates (bozkit.world_compile).
TRIGGER_SOURCE = 'boz:trigger_volume'
HIT_SOURCE = 'boz:hit_volume'
USE_SOURCE = 'boz:use_volume'
VOLUME_SOURCES = {'trigger': TRIGGER_SOURCE, 'hit': HIT_SOURCE, 'use': USE_SOURCE}
TRIGGER_SIZE = 100.0   # centimetres: a volume's size at scale 1
WEAPON_FIELD = 'boz.weapon'   # a wall buy's weapon (Placement.fields)
CHALK_FIELD = 'boz.chalk'     # a wall buy's chalk (Placement.settings): '' auto, 'none', an image
