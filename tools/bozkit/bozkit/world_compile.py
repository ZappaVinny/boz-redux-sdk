"""The world compiler: a map project's world (bozkit.world) as the game's groups. A generated
world gets the base level's weapons, arms, rounds and cameras plus the world's own models, props,
entities, collision and navmesh; an inherited world is the whole base level with the world's
additions (only the navmesh tiles near changes are rebuilt)."""
from __future__ import annotations

import copy
import struct

from . import group, levels, maps, spec_fields
from .hashing import iw_hash
from .world import (BLOCK_MARGIN, CHALK_FIELD, HIT_SOURCE, INGAME, Instance, Layout, Mesh, Model,
                    PLAYER_RADIUS, Placement, TRIGGER_SIZE, TRIGGER_SOURCE, Texture, UNIT,
                    USE_SOURCE, WEAPON_FIELD, World, WorldError, describe, lower, object_names,
                    script_of, validate, validate_layout, walk)

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
    files.runtime['names'] = sorted(set(object_names(world)) |
                                    set(files.runtime.get('aliases', {}).values()))
    return files


class GameModels:
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


TRIGGER_TEMPLATE = 'levels/callofthedead/callofthedead_statics.group.bin'   # CSnowTrigger
HIT_TEMPLATE = 'levels/kino/kino_statics.group.bin'                         # CEasterEgg skulls
USE_TEMPLATE = 'levels/kino/kino_statics.group.bin'                         # barricade CPOI
HIT_SONG_FIELD = 0xc0c5b1df   # CEasterEgg's song path (unnamed in the reflection)
HIT_SONG = 'boz/hit_volume'   # no such song: the group never completes

# Entities find each other by name (how-the-game-works, Entity links and areas). Placed game
# prefabs are renamed (scripts find them by their world names), so the compiler points these
# links at the names the entities have in the map.
POWER_SWITCH = 'PowerSwitch'   # DefaultPowerSwitchName: the level listens to the switch so named
POWER_LINK = 'powerSwitch'     # perks, Pack-a-Punch, doors, trap switches, teleporters, screens
LIST_LINKS = (('CTrapSwitch', 'traps'), ('CDoor', 'm_Siblings'))


def rewire_links(spec, home: str, renames: dict, present: set, power: int) -> bool:
    """Point a placed entity's links at this map's entities. A link to an entity the map has
    stays; one to an entity placed from the same group (*home*) under a new name (*renames*:
    (group, old name hash) -> name hash) follows it; otherwise a power link goes to the map's
    power switch (*power*, 0: none) and a list entry is dropped. Returns whether it changed."""
    from . import toolkit

    no_power = iw_hash(toolkit.NO_POWER)

    def resolve(value):
        return value if value in present else renames.get((home, value))

    changed = False
    for component in spec.components:
        prop = spec_fields.prop(component.blob, POWER_LINK) if component.blob else None
        if prop is None or len(prop.raw) != 4:
            continue
        (value,) = struct.unpack('<I', prop.raw)
        if not value or value == no_power:
            continue    # works without power (boz.world powers perks marked boz_no_power)
        new = resolve(value) or power
        if new and new != value:
            prop.raw = struct.pack('<I', new)
            prop.nested = prop.elements = None
            changed = True
    for component_name, field_name in LIST_LINKS:
        blob = spec_fields.component_blob(spec, component_name)
        prop = spec_fields.prop(blob, field_name)
        if prop is None:
            continue
        values = toolkit.hash_list(prop.raw)
        new_values = [new for new in map(resolve, values) if new]
        if new_values != values:
            prop.raw = toolkit.encode_hash_list(new_values)
            prop.nested = prop.elements = None
            changed = True
    return changed


def set_level_boxes(level_blob, boxes: list[int]) -> None:
    """The level's mystery box fields for the map's own boxes (name hashes, in placing order):
    the box starts at the first, and no box is avoided. Left as they were, they name the base
    level's boxes, and a map with a box or Pack-a-Punch crashes as it loads."""
    from . import reflect

    avoid = spec_fields.prop(level_blob, 'MysteryBoxAvoid')
    start = spec_fields.prop(level_blob, 'MysteryBoxStart')
    if avoid is not None:
        avoid.raw = struct.pack('<I', 0)
    if boxes:
        if start is None:
            start = reflect.Property(level_blob.class_hash, iw_hash('unsigned int'),
                                     iw_hash('MysteryBoxStart'), b'')
            level_blob.properties.append(start)
        start.raw = struct.pack('<I', boxes[0])
    elif start is not None:
        start.raw = struct.pack('<I', 0)


def window_links(navmesh_body: bytes, barricade: int, home, placed) -> list[tuple]:
    """The off-mesh links zombies climb through a barricade by: shipped levels have one per
    barricade, its user id the barricade's name hash, from 1 m outside to 1 m inside. *home* and
    *placed* are (position cm, rotation xyzw) of the barricade in its level and in the map; the
    links come back moved with it, in metres, as navbuild.build takes them (user still the
    barricade's home name). None found: one generated through it along its local Z."""
    from . import navigation

    found = []
    mesh = navigation.decode(navmesh_body)
    for tile in mesh.tiles:
        for start, end, radius, _extra, _poly, flags, _side, user in \
                navigation.decode_tile(tile.data).off_mesh:
            if user == barricade:
                found.append((start, end, radius, bool(flags & 1)))
    home_position, home_rotation = home
    position, rotation = placed
    undo = (-home_rotation[0], -home_rotation[1], -home_rotation[2], home_rotation[3])

    def move(point_m):
        local = spec_fields.rotate(undo, tuple(point_m[i] * 100 - home_position[i]
                                               for i in range(3)))
        turned = spec_fields.rotate(tuple(rotation), local)
        return tuple((position[i] + turned[i]) / 100 for i in range(3))

    if not found:
        outside, inside = (tuple((home_position[i] + offset[i]) / 100 for i in range(3))
                           for offset in (spec_fields.rotate(tuple(home_rotation), (0.0, 0.0, side))
                                          for side in (-WINDOW_REACH, WINDOW_REACH)))
        found = [(outside, inside, WINDOW_RADIUS, False)]
    return [(move(start), move(end), radius, both, barricade) for start, end, radius, both in found]


WINDOW_REACH = 100.0   # cm: a shipped window link starts and ends this far either side
WINDOW_RADIUS = 0.4    # metres: every shipped window link's radius


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
        self.game = GameModels(pack)
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
        # Placed entities' links (rewire_links): their groups and their names in the map.
        self.homes: dict[int, str] = {}            # id() of an added resource -> its group
        self.renames: dict[tuple[str, int], int] = {}   # (group, name hash) -> name in the map
        self.power = 0                             # the map's power switch (new maps)
        self.boxes: list[int] = []                 # placed mystery boxes, in order
        self.pack_a_punch = False                  # a Pack-a-Punch was placed
        self.window_spawns: list = []              # (name, position) of window zombie spawns
        self.barricades: list = []   # (placement, home name, group, home position and rotation)

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
        spec = resources.decode_entity_spec(body)
        power = spec_fields.component(spec, 'CPowerSwitch') is not None and not self.inherited
        if power and self.power:
            self.runtime.setdefault('warnings', []).append(
                f'{script or entity.source}: only the first power switch turns the power on')
        if power and not self.power:
            # The level listens to the switch called PowerSwitch, and powered things link to it
            # by that name: a new map's switch is called that, and scripts still reach it by
            # its world name (boz.objects aliases).
            copy_name = POWER_SWITCH
            key = self.power = iw_hash(POWER_SWITCH)
            if script and script.lower() != POWER_SWITCH.lower():
                self.runtime.setdefault('aliases', {})[script] = POWER_SWITCH
        elif script and script.lower() != entity.source.lower():
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
        home = entity.group or self.base_statics
        self.renames[(home, entity.hash)] = key
        if spec_fields.component(spec, 'CBarricade') is not None:
            self.barricades.append((entity, entity.hash, home, spec_fields.local_transform(spec)[:2]))
        if spec_fields.component(spec, 'CMysteryBox') is not None:
            self.boxes.append(key)
        if spec_fields.component(spec, 'CPackAPunch') is not None:
            self.pack_a_punch = True
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
            if entity.piece == 'zombie_window':
                self.window_spawns.append((script_of(entity).get('name') or entity.source,
                                           tuple(entity.position)))
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
        self.homes[id(resource)] = home
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

    def build(self, mesh: Mesh, model_name: str, scale: float = 1.0) -> None:
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
                 native.build_model(mesh.vertices, mesh.uvs, triangles, materials, faces,
                                    scale=scale))

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
        largest = {}
        for instance in world.instances:
            if instance.prop:
                largest[instance.prop] = max(largest.get(instance.prop, 1.0),
                                             *(abs(s) for s in instance.scale))
        for prop in world.props:
            self.build(prop, f'{self.name}_prop_{prop.name}', largest.get(prop.name, 1.0))

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

    def rewire_links(self) -> None:
        """Point the placed entities' links at the names entities have in the map (after every
        entity is placed; see rewire_links)."""
        from . import resources

        present = {r.in_group_hash for r in self.kept}
        for resource in self.added:
            home = self.homes.get(id(resource))
            if home is None:
                continue
            spec = resources.decode_entity_spec(resource.body)
            if rewire_links(spec, home, self.renames, present, self.power):
                resource.body = resources.encode_entity_spec(spec)
        self.link_trap_switches()

    def link_trap_switches(self) -> None:
        """A placed trap switch whose own traps are not in the map (another trap was placed,
        say Kino's electro switch with the Firepit) runs the trap nearest to it."""
        from . import resources, toolkit

        traps, switches = [], []
        for resource in self.added:
            spec = resources.decode_entity_spec(resource.body)
            if spec_fields.component(spec, 'CTrapSwitch') is not None:
                switches.append((resource, spec))
            elif spec_fields.component(spec, 'CTrap') is not None:
                traps.append((resource.in_group_hash, spec_fields.local_transform(spec)[0]))
        if not traps:
            return
        for resource, spec in switches:
            prop = spec_fields.prop(spec_fields.component_blob(spec, 'CTrapSwitch'), 'traps')
            if prop is None or toolkit.hash_list(prop.raw):
                continue
            where = spec_fields.local_transform(spec)[0]
            nearest = min(traps, key=lambda trap: sum((a - b) ** 2 for a, b in zip(trap[1], where)))
            prop.raw = toolkit.encode_hash_list([nearest[0]])
            prop.nested = prop.elements = None
            resource.body = resources.encode_entity_spec(spec)

    def window_links(self) -> list[tuple]:
        """The off-mesh links zombies climb through the placed barricades by, taken from their
        own levels' navmeshes (window_links), for navbuild.build."""
        links = []
        for entity, value, home, home_transform in self.barricades:
            navmesh = next((r.body for t in self.game.group(home).types()
                            if t.class_hash == levels.NAVMESH for r in t.resources), None)
            if navmesh is None:
                continue
            placed = (tuple(entity.position), entity.quaternion())
            for start, end, radius, both, _user in window_links(navmesh, value, home_transform,
                                                                 placed):
                links.append((start, end, radius, both, self.renames[(home, value)]))
        # Window zombies climb in through a barricade's window crossing: a window spawn with no
        # barricade near it is never used.
        for name, where in self.window_spawns:
            if not any(sum((a - b) ** 2 for a, b in zip(where, entity.position))
                       <= SPAWN_TO_BARRICADE ** 2
                       for entity, _value, _home, _transform in self.barricades):
                self.runtime.setdefault('warnings', []).append(
                    f'window zombie spawn {name} has no window barricade within '
                    f'{SPAWN_TO_BARRICADE / 100:g} m: zombies cannot climb in there')
        return links


SPAWN_TO_BARRICADE = 600.0   # centimetres from a window zombie spawn to its barricade, at most
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
    problems = validate_layout(world)
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
    level.rewire_links()

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
    if level.pack_a_punch and not level.boxes:
        # The game's box and Pack-a-Punch manager looks up the boxes unchecked once anything is
        # registered with it (FUN_4a12d080): with no box the level crashes as it loads.
        raise WorldError('Pack-a-Punch needs a mystery box in the map')
    set_level_boxes(level_blob, level.boxes)
    by_class[levels.LEVEL].resources[0].body = resources.encode_reflected(level_blob)

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
        blocking=level.blocking, doors=level.door_footprints(level.kept),
        links=level.window_links()))

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
    level.rewire_links()
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
