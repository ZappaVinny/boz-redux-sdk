"""A map project's world source and the compiler that turns it into the game's groups.

The source lives in the project's ``source/`` folder, as files the editor writes and people can
read::

    source/world.json        what the world is made of (below)
    source/meshes/<n>.json   a mesh: vertices (centimetres, Y up), UVs, triangles
    source/textures/<n>.png  a mesh's texture (power-of-two sides, at most 1024)

``world.json``::

    {"format": 1,
     "base": "kino",                         shipped level giving rounds, zombies, sounds, cameras
     "meshes": [{"name": "floor", "file": "meshes/floor.json", "texture": "textures/floor.png",
                 "collision": "floor", "double_sided": true}],
     "entities": [{"source": "spawn_player_1", "position": [0, 5, 0], "yaw": 0}]}

A mesh's triangles are in the game's winding; ``double_sided`` also draws their backs.
``collision`` is ``floor`` (walked on), ``solid`` (blocks) or ``none``: floor and solid meshes go
into the level's collision, and the navmesh is built on top of it. Entities are copies of the
base level's entities, by name or ``0x`` hash, moved to ``position`` and turned by ``yaw``
(degrees about Y). Props among them get a solid box in the collision and navmesh.
"""
from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import group, levels
from .hashing import iw_hash

FORMAT = 1
COLLISION_KINDS = ('floor', 'solid', 'none')
NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
MAX_TEXTURE = 1024


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
    name: str
    vertices: list[tuple[int, int, int]]
    uvs: list[tuple[float, float]]
    triangles: list[tuple[int, int, int]]
    texture: Texture
    collision: str = 'floor'
    double_sided: bool = False

    def model_triangles(self) -> list[tuple[int, int, int]]:
        if not self.double_sided:
            return list(self.triangles)
        return list(self.triangles) + [(a, c, b) for a, b, c in self.triangles]


@dataclass
class Placement:
    source: str                              # base level entity name, or 0x hash
    position: tuple[float, float, float]
    yaw: float = 0.0

    @property
    def hash(self) -> int:
        return int(self.source, 16) if self.source.startswith('0x') else iw_hash(self.source)


@dataclass
class World:
    base: str = 'kino'
    meshes: list[Mesh] = field(default_factory=list)
    entities: list[Placement] = field(default_factory=list)


# Files


def save(world: World, source: str | Path) -> None:
    """Write *world* into a project's source folder (replacing its meshes and textures)."""
    from PIL import Image

    source = Path(source)
    for folder in ('meshes', 'textures'):
        (source / folder).mkdir(parents=True, exist_ok=True)
        for old in (source / folder).iterdir():
            if old.suffix in ('.json', '.png') and old.stem not in {m.name for m in world.meshes}:
                old.unlink()
    meshes = []
    for mesh in world.meshes:
        (source / 'meshes' / f'{mesh.name}.json').write_text(json.dumps({
            'vertices': [list(v) for v in mesh.vertices],
            'uvs': [[round(u, 6), round(v, 6)] for u, v in mesh.uvs],
            'triangles': [list(t) for t in mesh.triangles]}, separators=(',', ':')) + '\n',
            encoding='utf-8')
        image = Image.frombytes('RGBA', (mesh.texture.width, mesh.texture.height),
                                mesh.texture.bgra, 'raw', 'BGRA')
        image.save(source / 'textures' / f'{mesh.name}.png')
        meshes.append({'name': mesh.name, 'file': f'meshes/{mesh.name}.json',
                       'texture': f'textures/{mesh.name}.png', 'collision': mesh.collision,
                       'double_sided': mesh.double_sided})
    # One line per mesh and entity, so the file stays readable and diffs stay small.
    lines = ['{', f'  "format": {FORMAT},', f'  "base": {json.dumps(world.base)},', '  "meshes": [']
    lines += [f'    {json.dumps(item)}' + (',' if i < len(meshes) - 1 else '')
              for i, item in enumerate(meshes)]
    lines += ['  ],', '  "entities": [']
    lines += [f'    {json.dumps({"source": e.source, "position": list(e.position), "yaw": e.yaw})}'
              + (',' if i < len(world.entities) - 1 else '') for i, e in enumerate(world.entities)]
    lines += ['  ]', '}']
    (source / 'world.json').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _inside(source: Path, relative: str) -> Path:
    path = (source / relative).resolve()
    if source.resolve() not in path.parents:
        raise WorldError(f'{relative} is outside the source folder')
    return path


def load(source: str | Path) -> World:
    from PIL import Image

    source = Path(source)
    try:
        data = json.loads((source / 'world.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise WorldError(f'{source / "world.json"} not found: this map has no world yet') from None
    except (OSError, ValueError) as exc:
        raise WorldError(f'cannot read world.json: {exc}') from exc
    if data.get('format') != FORMAT:
        raise WorldError(f'world.json format {data.get("format")!r} is not supported')
    world = World(str(data.get('base', 'kino')))
    for item in data.get('meshes', []):
        name = str(item.get('name', ''))
        try:
            geometry = json.loads(_inside(source, item['file']).read_text(encoding='utf-8'))
            image = Image.open(_inside(source, item['texture'])).convert('RGBA')
        except (KeyError, OSError, ValueError) as exc:
            raise WorldError(f'mesh {name!r}: {exc}') from exc
        texture = Texture(image.width, image.height, image.tobytes('raw', 'BGRA'))
        world.meshes.append(Mesh(
            name, [tuple(int(round(c)) for c in v) for v in geometry['vertices']],
            [tuple(map(float, uv)) for uv in geometry['uvs']],
            [tuple(map(int, t)) for t in geometry['triangles']], texture,
            str(item.get('collision', 'floor')), bool(item.get('double_sided', False))))
    for item in data.get('entities', []):
        world.entities.append(Placement(str(item['source']),
                                        tuple(float(c) for c in item['position']),
                                        float(item.get('yaw', 0.0))))
    return world


def validate(world: World) -> list[str]:
    """Problems that would stop the world from compiling."""
    problems = []
    if world.base not in levels.SHIPPED_LEVELS:
        problems.append(f'base level {world.base!r} is not one of the game\'s levels')
    names = [mesh.name for mesh in world.meshes]
    for mesh in world.meshes:
        label = f'mesh {mesh.name!r}'
        if not NAME_RE.fullmatch(mesh.name):
            problems.append(f'{label}: names use a-z, 0-9 and _ (at most 32, starting with a letter)')
        if names.count(mesh.name) > 1:
            problems.append(f'{label}: two meshes have this name')
        if mesh.collision not in COLLISION_KINDS:
            problems.append(f'{label}: collision must be floor, solid or none')
        if len(mesh.uvs) != len(mesh.vertices):
            problems.append(f'{label}: needs one UV per vertex')
        if len(mesh.vertices) > 0xFFFF:
            problems.append(f'{label}: more than 65535 vertices; split it')
        if any(not -32768 <= c <= 32767 for v in mesh.vertices for c in v):
            problems.append(f'{label}: vertices must stay within ±327 m of the origin')
        if any(i >= len(mesh.vertices) or i < 0 for t in mesh.triangles for i in t):
            problems.append(f'{label}: a triangle uses a vertex that does not exist')
        try:
            mesh.texture.check(label)
        except WorldError as exc:
            problems.append(str(exc))
    sources = [entity.hash for entity in world.entities]
    for entity in world.entities:
        if sources.count(entity.hash) > 1:
            problems.append(f'entity {entity.source!r} is placed more than once')
    if not any(entity.source.startswith('spawn_player_') for entity in world.entities):
        problems.append('the world needs a player spawn (spawn_player_1)')
    if not any(mesh.collision == 'floor' for mesh in world.meshes):
        problems.append('the world needs a floor mesh to walk on')
    return sorted(set(problems), key=problems.index)


# Templates


def _quads(quads, double_sided: bool = True):
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
    floor = Mesh('floor', vertices, uvs, triangles, _arena_texture(), 'floor', True)
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
    mesh = Mesh('arena', vertices, uvs, triangles, _arena_texture(), 'floor', True)
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
    """The starting world of a map template: 'empty' or 'debug' (needs the game's data)."""
    if template == 'empty':
        return empty_world()
    if template == 'debug':
        if pack is None:
            raise WorldError('the debug arena needs the game data (build the asset library)')
        return arena_world(pack)
    raise WorldError(f'original-map templates ({template}) arrive with the editor')


# Compiling


def compile_world(pack, name: str, world: World,
                  fixed: group.Group | None = None) -> levels.LevelFiles:
    """The game's groups for *world* under the level name *name*: the base level's weapons,
    arms, rounds, zombies, sounds and cameras, the world's own models, textures and placed
    entities, a collision mesh and a navmesh built from them. No rooms (sectors)."""
    from . import collision, native, navbuild, reflect, resources

    problems = validate(world)
    if problems:
        raise WorldError('; '.join(problems))
    base = world.base
    files = levels.common_files(pack, name, base, fixed)
    statics = levels._read(pack, f'levels/{base}/{base}_statics')
    levels.rename_level_resource(statics, base, name)
    by_class = {t.class_hash: t for t in statics.types()}
    specs = {}
    for resource in by_class[levels.ENTITY_SPEC].resources:
        specs.setdefault(resource.in_group_hash, resource)

    kept = []
    for resource in by_class[levels.ENTITY_SPEC].resources:  # cameras: intro and main
        if levels._component(resources.decode_entity_spec(resource.body), 'CIsCamera'):
            kept.append(resource)
    zombie_spawns = []
    for entity in world.entities:
        resource = specs.get(entity.hash)
        if resource is None:
            raise WorldError(f'{base} has no entity {entity.source!r}')
        spec = resources.decode_entity_spec(resource.body)
        levels._set_transform(spec, entity.position, levels._yaw(entity.yaw))
        resource.body = resources.encode_entity_spec(spec)
        if levels._component(spec, 'CSpawnPoint'):
            zombie_spawns.append(entity.hash)
        kept.append(resource)

    # The starting area lists the zombie spawns that are in the world.
    level_blob = resources.decode_reflected(by_class[levels.LEVEL].resources[0].body)
    (start_area,) = struct.unpack_from('<I', levels._blob_prop(level_blob, 'm_StartingArea').raw)
    areas = [r for r in by_class[levels.AREA].resources if r.in_group_hash == start_area]
    if not areas:
        raise WorldError(f'{base} has no starting area')
    area_blob = resources.decode_reflected(areas[0].body)
    levels._blob_prop(area_blob, 'm_SpawnPoints').raw = struct.pack(
        f'<I{len(zombie_spawns)}I', len(zombie_spawns), *zombie_spawns)
    areas[0].body = resources.encode_reflected(area_blob)
    by_class[levels.AREA].resources = areas

    texture_template = next(r.body for t in levels._read(pack, levels.TEXTURE_TEMPLATE).types()
                            if t.class_hash == levels.TEXTURE for r in t.resources
                            if levels._raw_texture(r.body))
    material_template = native.decode_material(by_class[levels.MATERIAL].resources[0].body)
    placed_template = next(r.body for t in levels._read(pack, levels.PLACED_TEMPLATE).types()
                           if t.class_hash == levels.ENTITY_SPEC for r in t.resources)
    model_type = by_class.get(levels.MODEL)
    if model_type is None:
        # Shipped groups list materials before the models that use them.
        model_type = group.ResourceType(levels.MODEL, 1, 1)
        types = statics.sections[[s.hash for s in statics.sections].index(group.RESOURCES)].types
        types.insert(types.index(by_class[levels.MATERIAL]) + 1, model_type)

    def add(resource_type, key_name: str, body: bytes) -> None:
        key = iw_hash(key_name)
        resource_type.resources.append(group.Resource(
            None if resource_type.names_omitted else key, key, body))

    solid: list[tuple[float, float, float]] = []
    single: list[tuple[int, int, int]] = []
    for mesh in world.meshes:
        model_name = f'{name}_{mesh.name}'
        texture_name, material_name = f'{model_name}_tex', f'{model_name}_mat'
        add(by_class[levels.TEXTURE], texture_name, native.build_texture(
            mesh.texture.width, mesh.texture.height, mesh.texture.bgra, texture_template))
        material = native.Material(False, 0, material_template.unknown,
                                   [(255, 255, 255, 255)] * 3 + [(0, 0, 0, 10)],
                                   [iw_hash(texture_name), 0, 0, 0], material_template.trailer)
        add(by_class[levels.MATERIAL], material_name, native.encode_material(material))
        model_type.resources.append(group.Resource(None, iw_hash(model_name), native.build_model(
            mesh.vertices, mesh.uvs, mesh.model_triangles(), [iw_hash(material_name)])))
        spec = resources.decode_entity_spec(placed_template)
        levels._set_transform(spec, (0, 0, 0), (0, 0, 0, 1))
        renderable = levels._component(spec, 'CIsRenderableModel').blob
        for element in levels._blob_prop(renderable, 'assets').elements:
            for prop in element.properties:
                if prop.name_hash in (iw_hash('Name'), iw_hash('model')):
                    reflect.set_typed_value(prop, iw_hash(model_name))
        kept.append(group.Resource(None, iw_hash(model_name), resources.encode_entity_spec(spec)))
        if mesh.collision != 'none':
            offset = len(solid)
            solid += [tuple(map(float, v)) for v in mesh.vertices]
            single += [(a + offset, b + offset, c + offset) for a, b, c in mesh.triangles]

    # Shipped levels bake props into their collision and navmesh; here every prop gets a box.
    models = levels._model_index(pack, [f'levels/{base}/{base}_dynamics', 'ingame/ingame'])
    for resource in kept:
        for box in levels.prop_boxes(resources.decode_entity_spec(resource.body), models):
            single += levels.box_triangles(len(solid))
            solid += box
    collision_key = iw_hash('COLLISION')
    if collision_key not in specs:
        raise WorldError(f'{base} has no COLLISION entity')
    spec = resources.decode_entity_spec(specs[collision_key].body)
    component = spec.components[-1]
    mesh_data = collision.decode(component.extra)
    mesh_data.vertices = solid
    mesh_data.indices = [i for t in single for i in t]
    mesh_data.materials = bytes(len(single))
    component.extra = collision.encode(mesh_data)
    specs[collision_key].body = resources.encode_entity_spec(spec)
    kept.append(specs[collision_key])

    by_class[levels.ENTITY_SPEC].resources = kept
    navmesh = by_class[levels.NAVMESH].resources[0]
    navmesh.body = navbuild.build(navmesh.body, [(x / 100, y / 100, z / 100) for x, y, z in solid],
                                  single)

    files.groups[f'{name}.group.bin'] = levels.renamed(
        levels._read(pack, f'levels/{base}/{base}'), name,
        [levels.Child(f'levels/{base}//{base}_dynamics.group', f'{base}_dynamics'),
         levels.Child(f'levels/{name}//{name}_statics.group', f'{name}_statics')])
    without_children = levels.renamed(statics, f'{name}_statics')
    without_children.sections = [s for s in without_children.sections if s.hash != levels.CHILDREN]
    files.groups[f'{name}_statics.group.bin'] = without_children
    return files
