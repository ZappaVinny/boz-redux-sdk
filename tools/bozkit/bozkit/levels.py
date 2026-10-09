"""Levels the game does not ship: what makes a level loadable, and writing one into a client mod.

How the game loads a level called ``<name>`` (``StartLevel <name>`` in the front end's console or
the menus; the name is not checked against any list):

1. ``CGameStateIngame`` loads ``fixed``'s ``CResolutionSpecificString`` ``loading-<name>`` (the
   loading screen's group; without it the game crashes), then one resource config of four groups:
   ``ingame/sound/snd_player_<character>``, ``ingame/weapons/weapons_<name>``,
   ``ingame/characters/arms/arms_<name>`` and ``levels/<name>/<name>``.
2. ``CLevelManager`` takes the ``CLevel`` named ``<name>`` from that group or its children.
3. ``Level_Load`` uses the groups named ``<name>_sectors`` (rooms, portals, occluders; optional)
   and ``<name>_statics`` (every ``CIsEntitySpec`` becomes an entity), spawns the player at
   ``spawn_player_1``, and takes the ``CIsNavMesh`` named ``NavMesh``.

A group lists its children by path, so a new level can reuse shipped groups by listing them as
children (its rooms, for example). Not everything is looked up through children: the weapon
manager reads the groups named ``weapons_<name>`` and ``weapon_projectiles_<name>`` themselves
(the fallback ``weapon_projectiles_common`` is not shipped), so those are renamed copies. The
client finds a mod's new files by base name, so everything goes flat into the mod's ``assets``
folder.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import derbh, group
from .hashing import iw_hash

CHILDREN = 0x3B495DC0  # section listing child groups; its name string is not in the game
LEVEL = iw_hash('CLevel')
RESOLUTION_STRING = iw_hash('CResolutionSpecificString')
HEADER = bytes((0x3D, 0x03, 0x07, 0x01, 0x00, 0x00))
SHIPPED_LEVELS = ('kino', 'ascension', 'callofthedead', 'tutorial')
PACK = 'blackops_etc.dz'


class LevelError(ValueError):
    pass


@dataclass
class Child:
    path: str        # as the game writes it, e.g. "levels/kino//kino_statics.group"
    name: str        # the child group's own name (hashed in the entry)
    flags: bytes = b'\0\0\0\0\0\x10\0\0'


def check_name(name: str) -> str:
    """A level name the game's fixed 160-byte buffers and file paths accept."""
    if not name or len(name) > 40 or not all(c.islower() or c.isdigit() or c == '_' for c in name):
        raise LevelError('level names use lowercase letters, digits and _ (at most 40)')
    if name in SHIPPED_LEVELS:
        raise LevelError(f'{name} is one of the game\'s own levels')
    return name


def children(source: group.Group) -> list[tuple[str, int, bytes]]:
    """(path, name hash, flags) of each child group, in order."""
    for section in source.sections:
        if section.hash == CHILDREN:
            data, out, p = section.payload, [], 1
            for _ in range(data[0]):
                end = data.index(b'\0', p)
                path = data[p:end].decode('latin-1')
                flags = data[end + 1:end + 9]
                (name_hash,) = struct.unpack_from('<I', data, end + 9)
                out.append((path, name_hash, flags))
                p = end + 13
            if p != len(data):
                raise LevelError(f'{source.name}: {len(data) - p} bytes after the child list')
            return out
    return []


def _children_payload(entries: list[Child]) -> bytes:
    if len(entries) > 255:
        raise LevelError('a group can list at most 255 children')
    out = bytearray([len(entries)])
    for child in entries:
        out += child.path.encode('latin-1') + b'\0' + child.flags
        out += struct.pack('<I', iw_hash(child.name))
    return bytes(out)


def _members_payload(name: str, flags: int = 0) -> bytes:
    return name.encode('latin-1') + b'\0' + struct.pack('<I', flags)


def members_flags(source: group.Group) -> int:
    for section in source.sections:
        if section.hash == group.MEMBERS:
            end = section.payload.index(b'\0')
            return struct.unpack_from('<I', section.payload, end + 1)[0]
    return 0


def make_group(name: str, entries: list[Child] = (), types: list[group.ResourceType] = (),
               flags: int = 0) -> group.Group:
    """A group with a name, child groups and resources, in the game's section order."""
    sections = [group.Section(group.MEMBERS, _members_payload(name, flags))]
    if entries:
        sections.append(group.Section(CHILDREN, _children_payload(list(entries))))
    sections.append(group.Section(group.RESOURCES, b'', list(types)))
    return group.Group(HEADER, sections)


def renamed(source: group.Group, name: str, entries: list[Child] | None = None) -> group.Group:
    """*source* under another group name, optionally with other children; resources unchanged."""
    sections = []
    for section in source.sections:
        if section.hash == group.MEMBERS:
            section = group.Section(group.MEMBERS, _members_payload(name, members_flags(source)))
        elif section.hash == CHILDREN and entries is not None:
            section = group.Section(CHILDREN, _children_payload(entries))
        sections.append(section)
    if entries and not any(s.hash == CHILDREN for s in source.sections):
        sections.insert(1, group.Section(CHILDREN, _children_payload(entries)))
    return group.Group(source.header, sections, source.trailer)


def _resource_type(target: group.Group, class_hash: int) -> group.ResourceType | None:
    for resource_type in target.types():
        if resource_type.class_hash == class_hash:
            return resource_type
    return None


def rename_level_resource(statics: group.Group, old: str, new: str) -> None:
    """Point the statics group's ``CLevel`` at the new level name (names are omitted, so the
    in-group hash is the name)."""
    levels = _resource_type(statics, LEVEL)
    found = [r for r in levels.resources if r.in_group_hash == iw_hash(old)] if levels else []
    if not found:
        raise LevelError(f'{statics.name} has no CLevel named {old}')
    for resource in found:
        resource.in_group_hash = iw_hash(new)
        if resource.name_hash is not None:
            resource.name_hash = iw_hash(new)


def add_loading_screen(fixed: group.Group, template: str, new: str) -> None:
    """Add ``loading-<new>`` to ``fixed`` as a copy of ``loading-<template>`` (same screen)."""
    strings = _resource_type(fixed, RESOLUTION_STRING)
    if strings is None:
        raise LevelError('fixed has no CResolutionSpecificString resources')
    by_hash = {r.in_group_hash: r for r in strings.resources}
    source = by_hash.get(iw_hash(f'loading-{template}'))
    if source is None:
        raise LevelError(f'fixed has no loading-{template}')
    if iw_hash(f'loading-{new}') in by_hash:
        by_hash[iw_hash(f'loading-{new}')].body = source.body
        return
    key = iw_hash(f'loading-{new}')
    strings.resources.append(group.Resource(None if strings.names_omitted else key, key,
                                            source.body))


# Game data ------------------------------------------------------------------------------------


def game_pack(client_root: str | Path) -> derbh.Pack:
    """The client's level data pack (read in place; nothing is extracted)."""
    archive = Path(client_root).expanduser().resolve() / 'assets' / PACK
    if not archive.exists():
        raise LevelError(f'{archive} not found; set up the client\'s game files first')
    return derbh.Pack(archive)


def _read(pack: derbh.Pack, relative: str) -> group.Group:
    try:
        return group.parse(pack.read(f'{relative}.group.bin'))
    except KeyError:
        raise LevelError(f'{relative}.group.bin is not in the game pack') from None


def read_group(path: str | Path) -> group.Group | None:
    """A group file, or None when it does not exist."""
    path = Path(path)
    return group.parse(path.read_bytes()) if path.is_file() else None


# New levels -----------------------------------------------------------------------------------


@dataclass
class LevelFiles:
    """Groups of a new level by file name (all flat in a mod's assets folder)."""
    name: str
    groups: dict[str, group.Group] = field(default_factory=dict)

    def write(self, assets: str | Path) -> list[Path]:
        assets = Path(assets)
        assets.mkdir(parents=True, exist_ok=True)
        written = []
        for file_name, value in sorted(self.groups.items()):
            path = assets / file_name
            path.write_bytes(group.encode(value))
            written.append(path)
        return written


def _copy(pack: derbh.Pack, name: str, folder: str, template_group: str) -> group.Group:
    """``<folder>/<template_group>`` renamed to *name*. The game reads weapons from the group
    named ``weapons_<level>`` itself, not its children, so these are copies, not wrappers."""
    return renamed(_read(pack, f'{folder}/{template_group}'), name)


def common_files(pack: derbh.Pack, name: str, template: str = 'kino',
                 fixed: group.Group | None = None) -> LevelFiles:
    """The groups every new level needs besides its own content: its loading screen entry in
    ``fixed`` (pass an already edited ``fixed`` to add to it) and the weapons and arms groups,
    which are renamed copies of the template level's."""
    files = LevelFiles(check_name(name))
    fixed = fixed or _read(pack, 'fixed/fixed')
    add_loading_screen(fixed, template, name)
    files.groups['fixed.group.bin'] = fixed
    projectiles = f'weapon_projectiles_{name}'
    weapons = _copy(pack, f'weapons_{name}', 'ingame/weapons', f'weapons_{template}')
    weapon_children = []
    for path, name_hash, flags in children(weapons):
        if name_hash != iw_hash(f'weapon_projectiles_{template}'):
            raise LevelError(f'weapons_{template} has an unexpected child {path}')
        weapon_children.append(Child(f'ingame/weapons//{projectiles}.group', projectiles, flags))
    files.groups[f'weapons_{name}.group.bin'] = renamed(weapons, f'weapons_{name}',
                                                        weapon_children)
    files.groups[f'{projectiles}.group.bin'] = _copy(pack, projectiles, 'ingame/weapons',
                                                     f'weapon_projectiles_{template}')
    files.groups[f'arms_{name}.group.bin'] = _copy(pack, f'arms_{name}',
                                                   'ingame/characters/arms', f'arms_{template}')
    return files


def clone_level(pack: derbh.Pack, name: str, template: str = 'kino',
                fixed: group.Group | None = None) -> LevelFiles:
    """A copy of a shipped level under a new name: proves the game loads a level it does not
    know. Rooms and dynamic models stay the template's own groups (listed as children)."""
    files = common_files(pack, name, template, fixed)
    folder = f'levels/{template}'
    root = _read(pack, f'{folder}/{template}')
    statics = _read(pack, f'{folder}/{template}_statics')
    sectors = _read(pack, f'{folder}/{template}_sectors')

    def child(level_name: str, suffix: str) -> Child:
        return Child(f'levels/{level_name}//{level_name}{suffix}.group', f'{level_name}{suffix}')

    root_children = []
    for path, name_hash, flags in children(root):
        if name_hash == iw_hash(f'{template}_statics'):
            root_children.append(child(name, '_statics'))
        else:
            own = Path(path.replace('//', '/')).name.removesuffix('.group')
            if iw_hash(own) != name_hash:
                raise LevelError(f'{path}: child name does not match its file name')
            root_children.append(Child(path, own, flags))
    statics_children = [child(name, '_sectors') if h == iw_hash(f'{template}_sectors')
                        else Child(p, '', f) for p, h, f in children(statics)]
    if any(not c.name for c in statics_children):
        raise LevelError(f'{template}_statics has children other than its sectors group')
    rename_level_resource(statics, template, name)

    files.groups[f'{name}.group.bin'] = renamed(root, name, root_children)
    files.groups[f'{name}_statics.group.bin'] = renamed(statics, f'{name}_statics',
                                                        statics_children)
    files.groups[f'{name}_sectors.group.bin'] = renamed(sectors, f'{name}_sectors')
    return files


# Generated levels -----------------------------------------------------------------------------

ENTITY_SPEC = iw_hash('CIsEntitySpec')
AREA = iw_hash('CArea')
NAVMESH = iw_hash('CIsNavMesh')
MODEL = iw_hash('CIwModel')
MATERIAL = iw_hash('CIwMaterial')
TEXTURE = iw_hash('CIwTexture')
TEXTURE_TEMPLATE = 'ingame/ingame'  # has raw (uncompressed) textures to copy a header from
PLACED_TEMPLATE = 'levels/kino/lobby_shared'


@dataclass
class Arena:
    """A walled, square test arena centred on the origin (centimetres, Y up)."""
    half_size: int = 1200
    wall_height: int = 300
    cell: int = 200          # floor and wall quads (one texture repeat each)


def _blob_prop(blob, name: str):
    return next((p for p in blob.properties if p.name_hash == iw_hash(name)), None)


def _component(spec, type_name: str):
    return next((c for c in spec.components if c.type_hash == iw_hash(type_name)), None)


def _set_transform(spec, position, rotation=None) -> None:
    from . import reflect

    blob = _component(spec, 'CIsTransform').blob
    reflect.set_typed_value(_blob_prop(blob, 'm_localPosition'), tuple(map(float, position)))
    if rotation is not None:
        reflect.set_typed_value(_blob_prop(blob, 'm_localRotation'), tuple(map(float, rotation)))


def _yaw(degrees: float) -> tuple[float, float, float, float]:
    """Quaternion (x, y, z, w) turning by *degrees* about Y."""
    import math
    half = math.radians(degrees) / 2
    return (0.0, math.sin(half), 0.0, math.cos(half))


def _raw_texture(body: bytes) -> bool:
    from . import native

    try:
        return native.texture_layout(body).pixel_format == 0x0E
    except ValueError:
        return False


def arena_geometry(arena: Arena):
    """Floor and inside walls as quads: (vertices, uvs, triangles) with every quad textured once.
    Triangles are double-sided (both windings) so culling cannot hide them. UVs: floor uses the
    top half of the texture, walls the bottom half."""
    vertices, uvs, triangles = [], [], []
    h, c, top = arena.half_size, arena.cell, arena.wall_height

    def quad(a, b, cc, d, v0):
        base = len(vertices)
        vertices.extend([a, b, cc, d])
        uvs.extend([(0.0, v0), (1.0, v0), (1.0, v0 + 0.5), (0.0, v0 + 0.5)])
        triangles.extend([(base, base + 1, base + 2), (base, base + 2, base + 3),
                          (base, base + 2, base + 1), (base, base + 3, base + 2)])

    steps = range(-h, h, c)
    for x in steps:
        for z in steps:
            quad((x, 0, z), (x + c, 0, z), (x + c, 0, z + c), (x, 0, z + c), 0.0)
    for s in steps:
        for y in range(0, top, c):
            y2 = min(y + c, top)
            quad((s, y, -h), (s + c, y, -h), (s + c, y2, -h), (s, y2, -h), 0.5)
            quad((s, y, h), (s + c, y, h), (s + c, y2, h), (s, y2, h), 0.5)
            quad((-h, y, s), (-h, y, s + c), (-h, y2, s + c), (-h, y2, s), 0.5)
            quad((h, y, s), (h, y, s + c), (h, y2, s + c), (h, y2, s), 0.5)
    return vertices, uvs, triangles


def arena_texture(size: int = 128) -> bytes:
    """BGRA texels: a grey checker floor tile over a brick-red wall tile (each size x size/2)."""
    out = bytearray()
    half = size // 2
    for y in range(size):
        for x in range(size):
            if y < half:
                light = ((x * 4 // size) + (y * 2 // half)) % 2
                edge = x % (size // 4) == 0 or y % (half // 2) == 0
                grey = 70 if edge else (150 if light else 120)
                out += bytes((grey, grey, grey, 255))
            else:
                row = (y - half) // (half // 4)
                mortar = (y - half) % (half // 4) == 0 or \
                    (x + (row % 2) * (size // 8)) % (size // 4) == 0
                out += bytes((80, 80, 85, 255) if mortar else (60, 70, 150, 255))
    return bytes(out)


def _model_index(pack: derbh.Pack, paths) -> dict[int, bytes]:
    models = {}
    for path in paths:
        for resource_type in _read(pack, path).types():
            if resource_type.class_hash == MODEL:
                for resource in resource_type.resources:
                    models.setdefault(resource.in_group_hash, resource.body)
    return models


def prop_boxes(spec, models: dict[int, bytes]) -> list[list[tuple[float, float, float]]]:
    """Solid boxes of a placed prop in world centimetres, eight corners each: its collision
    boxes (not ghost ones), or else the bounds of the model it draws. Shipped levels bake props
    into the level collision and navmesh; a generated level adds these boxes instead."""
    from . import blender_scene as scene
    from . import native

    chain = [scene._local_transform(spec)]

    def corners(centre, half):
        return [scene._native_apply(chain, tuple(centre[i] + (half[i] if c >> i & 1 else -half[i])
                                                 for i in range(3))) for c in range(8)]

    boxes = []
    for component in spec.components:
        blob = component.blob
        if component.type_hash != scene.COLLISION_BOX or not blob or \
                scene._blob_value(blob, 'm_Ghost', False):
            continue
        half = scene._blob_value(blob, 'm_halfAxis', [0.0, 0.0, 0.0])
        centre = scene._blob_value(blob, 'm_Offset', None) or \
            scene._blob_value(blob, 'm_boxCentre', [0.0, 0.0, 0.0])
        boxes.append(corners(centre, half))
    if boxes:
        return boxes
    model = scene._model_reference(spec)
    if model is None or model not in models:
        return []
    vertices = native.decode_model(models[model]).vertices
    low = [min(v[i] for v in vertices) for i in range(3)]
    high = [max(v[i] for v in vertices) for i in range(3)]
    return [corners([(lo + hi) / 2 for lo, hi in zip(low, high)],
                    [(hi - lo) / 2 for lo, hi in zip(low, high)])]


def box_triangles(base: int) -> list[tuple[int, int, int]]:
    """The 12 outward-facing triangles of eight box corners (corner bit i = +axis i), in the
    game's winding (the reverse of Recast's)."""
    from . import blender_scene as scene

    return [(base + a, base + c, base + b) for a, b, c in scene._BOX_FACES]


def generate_arena(pack: derbh.Pack, name: str, arena: Arena | None = None,
                   template: str = 'kino', fixed: group.Group | None = None) -> LevelFiles:
    """A level with its own geometry: a walled arena with a generated model, texture, collision
    and navmesh. Game objects come from the template level as ready-made pieces: the player
    spawns, the starting area's zombie spawns (moved into the arena), Juggernog and the power
    switch; the template's rounds, zombies, sounds and cameras stay. No rooms (sectors)."""
    from . import collision, native, navbuild, reflect, resources

    arena = arena or Arena()
    files = common_files(pack, name, template, fixed)
    statics = _read(pack, f'levels/{template}/{template}_statics')
    rename_level_resource(statics, template, name)
    by_class = {t.class_hash: t for t in statics.types()}
    specs = {r.in_group_hash: r for r in by_class[ENTITY_SPEC].resources}
    level_blob = resources.decode_reflected(by_class[LEVEL].resources[0].body)
    start_area = _blob_prop(level_blob, 'm_StartingArea')
    (start_area,) = struct.unpack_from('<I', start_area.raw)
    areas = [r for r in by_class[AREA].resources if r.in_group_hash == start_area]
    if not areas:
        raise LevelError(f'{template} has no starting area')
    area_blob = resources.decode_reflected(areas[0].body)
    raw = _blob_prop(area_blob, 'm_SpawnPoints').raw
    spawn_points = list(struct.unpack_from(f'<{struct.unpack_from("<I", raw)[0]}I', raw, 4))
    by_class[AREA].resources = areas

    kept = []
    h, inset = arena.half_size, 120

    def keep(key, position=None, rotation=None):
        resource = specs[key]
        if position is not None:
            spec = resources.decode_entity_spec(resource.body)
            _set_transform(spec, position, rotation)
            resource.body = resources.encode_entity_spec(spec)
        kept.append(resource)

    # Cameras (intro and main). Unnamed entities share hash 0, so walk the list.
    for resource in by_class[ENTITY_SPEC].resources:
        spec = resources.decode_entity_spec(resource.body)
        if _component(spec, 'CIsCamera'):
            kept.append(resource)
    # Player spawns around the middle, facing +Z.
    for number, (x, z) in enumerate(((-100, -100), (100, -100), (-100, 100), (100, 100)), 1):
        keep(iw_hash(f'spawn_player_{number}'), (x, 5, z), _yaw(0))
    # Zombie spawns: window spawns at the wall middles, dogs and crawlers spread around.
    ring = [(0, h - inset), (0, -h + inset), (h - inset, 0), (-h + inset, 0),
            (h - inset, h - inset), (-h + inset, h - inset), (h - inset, -h + inset),
            (-h + inset, -h + inset), (h // 2, h - inset), (-h // 2, -h + inset),
            (h - inset, h // 2), (-h + inset, -h // 2)]
    for index, key in enumerate(spawn_points):
        spec = resources.decode_entity_spec(specs[key].body)
        kind = _component(spec, 'CSpawnPoint').blob
        spawn_type = struct.unpack_from('<I', _blob_prop(kind, 'spawnType').raw)[0]
        x, z = ring[index % len(ring)]
        y = arena.wall_height if spawn_type == iw_hash('hole') else 0
        keep(key, (x, y, z), _yaw(0))
    keep(iw_hash('Juggernog'), (-h + 200, 0, -400), _yaw(90))
    keep(iw_hash('powerSwitch'), (h - 60, 0, 0), _yaw(-90))

    # Geometry: one model, its material and texture, drawn by one placed entity.
    vertices, uvs, triangles = arena_geometry(arena)
    model_name, material_name, texture_name = f'{name}_arena', f'{name}_arena_mat', \
        f'{name}_arena_tex'
    texture_template = next(r.body for t in _read(pack, TEXTURE_TEMPLATE).types()
                            if t.class_hash == TEXTURE for r in t.resources
                            if _raw_texture(r.body))
    texture = native.build_texture(128, 128, arena_texture(128), texture_template)
    material_template = native.decode_material(by_class[MATERIAL].resources[0].body)
    material = native.Material(False, 0, material_template.unknown,
                               [(255, 255, 255, 255)] * 3 + [(0, 0, 0, 10)],
                               [iw_hash(texture_name), 0, 0, 0], material_template.trailer)
    by_class[TEXTURE].resources.append(group.Resource(
        None if by_class[TEXTURE].names_omitted else iw_hash(texture_name),
        iw_hash(texture_name), texture))
    by_class[MATERIAL].resources.append(group.Resource(
        None if by_class[MATERIAL].names_omitted else iw_hash(material_name),
        iw_hash(material_name), native.encode_material(material)))
    model = native.build_model(vertices, uvs, triangles, [iw_hash(material_name)])
    model_type = by_class.get(MODEL)
    if model_type is None:
        # Shipped groups list materials before the models that use them.
        model_type = group.ResourceType(MODEL, 1, 1)
        types = statics.sections[[s.hash for s in statics.sections].index(group.RESOURCES)].types
        types.insert(types.index(by_class[MATERIAL]) + 1, model_type)
    model_type.resources.append(group.Resource(None, iw_hash(model_name), model))

    placed = next(r.body for t in _read(pack, PLACED_TEMPLATE).types()
                  if t.class_hash == ENTITY_SPEC for r in t.resources)
    spec = resources.decode_entity_spec(placed)
    _set_transform(spec, (0, 0, 0), (0, 0, 0, 1))
    for element in _blob_prop(_component(spec, 'CIsRenderableModel').blob, 'assets').elements:
        for prop in element.properties:
            if prop.name_hash in (iw_hash('Name'), iw_hash('model')):
                reflect.set_typed_value(prop, iw_hash(model_name))
    kept.append(group.Resource(None, iw_hash(model_name), resources.encode_entity_spec(spec)))

    # Collision: the floor and walls, one winding (the game's), in the collision entity, plus a
    # solid box for every prop (shipped levels bake props into their collision and navmesh).
    collision_key = iw_hash('COLLISION')
    spec = resources.decode_entity_spec(specs[collision_key].body)
    component = spec.components[-1]
    mesh = collision.decode(component.extra)
    # The first two triangles of each quad face down by Recast's convention, the game's winding.
    single = [t for i, t in enumerate(triangles) if i % 4 < 2]
    solid = [tuple(map(float, v)) for v in vertices]
    models = _model_index(pack, [f'levels/{template}/{template}_dynamics', 'ingame/ingame'])
    for resource in kept:
        for box in prop_boxes(resources.decode_entity_spec(resource.body), models):
            single += box_triangles(len(solid))
            solid += box
    mesh.vertices = solid
    mesh.indices = [i for t in single for i in t]
    mesh.materials = bytes(len(single))
    component.extra = collision.encode(mesh)
    specs[collision_key].body = resources.encode_entity_spec(spec)
    kept.append(specs[collision_key])

    by_class[ENTITY_SPEC].resources = kept
    navmesh = by_class[NAVMESH].resources[0]
    navmesh.body = navbuild.build(navmesh.body,
                                  [(x / 100, y / 100, z / 100) for x, y, z in solid], single)

    files.groups[f'{name}.group.bin'] = renamed(
        _read(pack, f'levels/{template}/{template}'), name,
        [Child(f'levels/{template}//{template}_dynamics.group', f'{template}_dynamics'),
         Child(f'levels/{name}//{name}_statics.group', f'{name}_statics')])
    without_children = renamed(statics, f'{name}_statics')
    without_children.sections = [s for s in without_children.sections if s.hash != CHILDREN]
    files.groups[f'{name}_statics.group.bin'] = without_children
    return files
