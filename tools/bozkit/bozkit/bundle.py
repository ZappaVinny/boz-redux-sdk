"""Map-agnostic assets: every resource of the game one by one, and a bundle of everything a map
uses, wherever it comes from.

The game finds resources by name in whatever groups are loaded (CIwResManager), so a map can use
anything from any other map as long as the map's own groups carry it. The registry indexes every
resource of every group (class, name, group, body) and what it refers to:

- by data: an entity spec's hash-typed properties, a model's materials, a material's textures,
  a reflected resource's hashes, and for other binary resources (skins, skeletons, animations,
  state machines, sound specs and sequences) every word that names a game resource;
- by code: names a class's functions hash or play at run time (the game definition's runtime
  names, from tools/ghidra/ExportBozRuntimeNames.java): a spec with a CProjectileEntity brings
  gersch_Effect and the Gersch sounds, which nothing in its data names.

A bundle walks that closure from a map's roots (its placed entities, weapons, effects, sounds,
zombie looks) and copies what the map's loaded groups do not already hold into the map's own
groups: projectile specs (and what they use) into weapon_projectiles_<map>, weapon specs into
weapons_<map> (the game reads those groups' own resources), the rest into the statics group.

Names are not unique across groups (every weapon has models named Base and LOD1): a resource
whose name the map already holds with a different body gets a name of its own
(boz_<group>_<name>), and the copied resources that use it are changed to that name. Names are
not unique across classes either (Ascension's PackAPunch is a model, a skin and a spec), so a
use is only renamed for the class it means.

What a resource can find while it loads (a model its materials, a skin its skeleton and model)
is not every loaded group: CIwResGroup lookups (FUN_4a234434) search the group, its children and
the shared groups (members flag 1: ingame, snd_player_*, the sectors and their rooms), and
CIwResManager_GetResHashed only the groups loaded with the current one. The map loads ingame,
then weapons_<map> (its child weapon_projectiles_<map> first), arms_<map> and <map> (its children
in order: the base dynamics, then <map>_statics); see Bundle.visible. A resource another of the
map's groups holds is copied again into each group that cannot see it.
"""
from __future__ import annotations

import struct
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import group as group_module
from .hashing import iw_hash

ENTITY_SPEC = iw_hash('CIsEntitySpec')
MODEL = iw_hash('CIwModel')
MATERIAL = iw_hash('CIwMaterial')
TEXTURE = iw_hash('CIwTexture')
PROJECTILE = iw_hash('CProjectileEntity')
PLAYER_WEAPON = iw_hash('CPlayerWeapon')
# Level structure: never copied from another map (the map has its own).
NOT_COPIED = {iw_hash(n) for n in ('CLevel', 'CArea', 'CIsNavMesh', 'CIsPortal', 'CIsOccluder',
                                   'CWave', 'CScoreConfig', 'CResolutionSpecificString')}
# Groups every Zombies map loads (and their children).
ALWAYS_LOADED = ('ingame/ingame.group.bin', 'shared/shared.group.bin',
                 'ingame/effects/visualeffects.group.bin')
# Resources load in group order and some find others by name while loading (a skin its skeleton
# and model), so new types go in the shipped order.
SKELETON, SKIN = iw_hash('CIwAnimSkel'), iw_hash('CIwAnimSkin')
LOAD_ORDER = [TEXTURE, MATERIAL, MODEL, SKELETON, SKIN, iw_hash('CIwAnim'),
              iw_hash('CIsAnimStateMachine')]


class BundleError(ValueError):
    pass


@dataclass
class Entry:
    cls: int
    hash: int
    path: str
    resource: group_module.Resource
    like: group_module.ResourceType


def runtime_names() -> dict[int, list[int]]:
    """{class hash: [name hashes]} from the game definition's runtime names."""
    from .schema import gamedef_file
    for path in (gamedef_file('runtime'), Path(__file__).with_name('runtime_names.toml')):
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding='utf-8'))
            return {iw_hash(c['name']): [iw_hash(n) for n in c.get('names', [])]
                    for c in data.get('class', [])}
    return {}


_REGISTRIES: dict = {}


class Registry:
    """Every resource of the game's groups, by name hash."""

    def __init__(self, read, paths) -> None:
        self.read = read
        self.paths = [p for p in paths if p.endswith('.group.bin')]
        self.groups: dict[str, group_module.Group] = {}
        self.by_hash: dict[int, list[Entry]] = {}
        for path in self.paths:
            parsed = self.group(path)
            if parsed is None:
                continue
            for resource_type in parsed.types():
                for resource in resource_type.resources:
                    self.by_hash.setdefault(resource.in_group_hash, []).append(
                        Entry(resource_type.class_hash, resource.in_group_hash, path, resource, resource_type))
        self.material_ids = {h for h, items in self.by_hash.items() if any(e.cls == MATERIAL for e in items)}
        self.runtime = runtime_names()

    @classmethod
    def of(cls, pack) -> 'Registry':
        """The registry of a game pack (built once per pack)."""
        key = id(pack)
        found = _REGISTRIES.get(key)
        if found is None or found[0] is not pack:
            names = pack.names() if hasattr(pack, 'names') else []
            found = _REGISTRIES[key] = (pack, cls(pack.read, names))
        return found[1]

    def group(self, path: str):
        if path not in self.groups:
            try:
                self.groups[path] = group_module.read_parsed(self.read, path)
            except (KeyError, OSError, ValueError):
                self.groups[path] = None
        return self.groups[path]

    def entries(self, value: int) -> list[Entry]:
        return self.by_hash.get(value, [])

    def references(self, entry: Entry, body: bytes | None = None) -> list[int]:
        """The names *entry* uses (its data, and its classes' runtime names)."""
        return [value for value, _classes in self.typed_references(entry, body)]

    def typed_references(self, entry: Entry, body: bytes | None = None) -> list[tuple[int, frozenset | None]]:
        """(name, the classes it can be) of each name *entry* uses; None: any class."""
        found = self._references(entry, body)
        classes = USES.get(entry.cls)
        return [(value, classes) for value in found if value]     # 0: no name (an empty link)

    def _references(self, entry: Entry, body: bytes | None = None) -> list[int]:
        from . import native, reflect, resources
        body = entry.resource.body if body is None else body
        out: list[int] = []
        if entry.cls == TEXTURE:
            return out
        if entry.cls == MODEL:
            from . import blender_scene
            try:
                return list(blender_scene.model_materials(body, self.material_ids))
            except Exception:   # noqa: BLE001 - unreadable model: nothing to follow
                return out
        if entry.cls == MATERIAL:
            try:
                return list(native.decode_material(body).textures)
            except ValueError:
                return out
        if entry.cls == ENTITY_SPEC:
            from . import world_compile
            try:
                spec = resources.decode_entity_spec(body)
            except Exception:   # noqa: BLE001
                return self._words(body)
            out = world_compile.spec_hashes(spec)
            for component in _components(spec):
                out += self.runtime.get(component.type_hash, [])
            return [h for h in out if h in self.by_hash]
        if reflect.is_blob(body, 4) or reflect.is_blob(body):
            from . import world_compile
            blob = resources.decode_reflected(body)
            if blob is not None:
                return [h for h in world_compile.blob_hashes(blob) if h in self.by_hash]
        return self._words(body)

    def _words(self, body: bytes) -> list[int]:
        """Every word of a binary resource that names a game resource (small ones also unaligned:
        state machines store names unaligned)."""
        known = self.by_hash
        if len(body) <= 0x10000:
            return [w for w in (struct.unpack_from('<I', body, o)[0] for o in range(len(body) - 3)) if w in known]
        return [w for (w,) in struct.iter_unpack('<I', body[:len(body) // 4 * 4]) if w in known]

    def specs(self, kind: str | None = None) -> list[Entry]:
        """Entity specs (kind "projectile": with a CProjectileEntity)."""
        from . import resources
        out = []
        for items in self.by_hash.values():
            for entry in items:
                if entry.cls != ENTITY_SPEC:
                    continue
                if kind == 'projectile':
                    try:
                        spec = resources.decode_entity_spec(entry.resource.body)
                    except Exception:   # noqa: BLE001
                        continue
                    if not any(c.type_hash == PROJECTILE for c in _components(spec)):
                        continue
                out.append(entry)
        return out


# The classes a resource's names can be, where its format says (anything else: any class).
USES = {MODEL: frozenset({MATERIAL}), MATERIAL: frozenset({TEXTURE}),
        SKIN: frozenset({MODEL, SKELETON})}


# Fields that name entities of the map (resolved by their CIsNamed names when it runs), not
# resources: never followed or renamed.
LINK_FIELDS = {iw_hash(n) for n in ('powerSwitch', 'traps', 'm_Siblings', 'm_AreasUnlock')}


def _kept_words(cls: int, body: bytes) -> tuple[set[int], set[int]]:
    """(words that are a spec's own structure: class, type and field name hashes, which a
    rename must not touch (powerSwitch hashes as PowerSwitch); names in link fields)."""
    from . import resources
    structure: set[int] = set()
    links: set[int] = set()
    if cls != ENTITY_SPEC:
        return structure, links
    try:
        spec = resources.decode_entity_spec(body)
    except Exception:   # noqa: BLE001 - unreadable spec: nothing kept
        return structure, links

    def blob(item) -> None:
        structure.add(item.class_hash)
        for prop in item.properties:
            structure.update((prop.owner_hash, prop.type_hash, prop.name_hash))
            if prop.name_hash in LINK_FIELDS and prop.raw:
                count = len(prop.raw) // 4
                values = struct.unpack(f'<{count}I', prop.raw[:count * 4])
                links.update(values[1:] if count > 1 and values[0] == count - 1 else values)
            if prop.nested is not None:
                blob(prop.nested)
            for element in prop.elements or ():
                blob(element)

    for component in _components(spec):
        structure.update((component.class_hash, component.type_hash))
        for item in component.blobs:
            blob(item)
    links.discard(0)
    return structure, links


def _components(spec):
    yield from spec.components
    for _cls, _reserved, child in spec.children:
        yield from _components(child)


def _spec_kind(body: bytes) -> str:
    from . import resources
    try:
        spec = resources.decode_entity_spec(body)
    except Exception:   # noqa: BLE001
        return ''
    types = {c.type_hash for c in _components(spec)}
    if PROJECTILE in types:
        return 'projectile'
    if PLAYER_WEAPON in types:
        return 'weapon'
    return ''


def _library_map(path: str) -> str:
    from . import library
    return library.map_of(path)


class Bundle:
    """What a map's groups carry: add roots, and their closure is copied in."""

    def __init__(self, registry: Registry, groups: dict, map_name: str) -> None:
        self.registry, self.groups, self.map_name = registry, groups, map_name
        self.statics = groups.get(f'{map_name}_statics.group.bin')
        self.copied: list[tuple[int, int, str, str]] = []     # (class, hash, from path, into file)
        self.renamed: dict[tuple[str, int], int] = {}         # (source path, hash) -> new hash
        self._present: dict[tuple[int, int], bytes] | None = None
        self._where: dict[tuple[int, int], list[tuple[str, bytes]]] = {}   # what holds each
        self._order: dict[str, tuple[int, str, bool]] | None = None
        self._done: dict[tuple[str, int, int], int] = {}
        self._busy: set[tuple[str, int, int]] = set()
        self._own: set | None = None

    # What the map already has --------------------------------------------------------------

    def loaded_paths(self) -> set[str]:
        """The game's groups the map loads: the shared ones, and the children of the map's own
        groups and of those (the base level's rooms and dynamics, ...)."""
        from . import levels
        todo = list(ALWAYS_LOADED)
        for parsed in self.groups.values():
            todo += [path.replace('//', '/').removeprefix('./') + '.bin' if not path.endswith('.bin') else path
                     for path, _h, _f in levels.children(parsed)]
        seen: set[str] = set()
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            parsed = self.registry.group(path)
            if parsed is None:
                continue
            todo += [p.replace('//', '/') + ('.bin' if not p.endswith('.bin') else '')
                     for p, _h, _f in levels.children(parsed)]
        return {p for p in seen if self.registry.group(p) is not None}

    def own(self) -> set[tuple[int, int]]:
        """(class, name) of what the map's own groups hold (worked out once per add)."""
        if self._own is None:
            self._own = set()
            for parsed in self.groups.values():
                for resource_type in parsed.types():
                    self._own.update((resource_type.class_hash, r.in_group_hash) for r in resource_type.resources)
        return self._own

    def present(self) -> dict[tuple[int, int], bytes]:
        if self._present is None:
            self._present, self._where = {}, {}
            places = [(file_name, parsed) for file_name, parsed in self.groups.items()]
            places += [(path, self.registry.group(path)) for path in sorted(self.loaded_paths())]
            for place, parsed in places:
                for resource_type in parsed.types():
                    for resource in resource_type.resources:
                        key = (resource_type.class_hash, resource.in_group_hash)
                        self._present.setdefault(key, resource.body)
                        self._where.setdefault(key, []).append((place, resource.body))
        return self._present

    # What a group can see while it loads ------------------------------------------------------

    def _child_place(self, path: str) -> str:
        """A child entry's group: one of the map's own files, or a game group's pack path."""
        relative = path.replace('//', '/').removeprefix('./')
        relative = relative if relative.endswith('.bin') else relative + '.bin'
        own = Path(relative).name
        return own if own in self.groups else relative

    def load_order(self) -> dict[str, tuple[int, str, bool]]:
        """{group: (when it loads, the top-level group it loads with, shared)} for the groups a
        map loads: ingame, the map's weapons, arms and level groups, children before their
        parent (a group loads its children first)."""
        if self._order is None:
            from . import levels
            order: dict[str, tuple[int, str, bool]] = {}

            def visit(place: str, top: str, shared: bool) -> None:
                if place in order:
                    return
                parsed = self.groups.get(place) if place in self.groups else self.registry.group(place)
                if parsed is None:
                    return
                order[place] = (-1, top, False)              # cycles stop here
                shared = shared or place in ALWAYS_LOADED or bool(levels.members_flags(parsed) & 1)
                for path, _name_hash, _flags in levels.children(parsed):
                    visit(self._child_place(path), top, shared)
                order[place] = (len([v for v in order.values() if v[0] >= 0]), top, shared)

            name = self.map_name
            # fixed (shared) is loaded when the game starts; the map may carry its own copy.
            tops = ['fixed.group.bin', *ALWAYS_LOADED, f'weapons_{name}.group.bin',
                    f'arms_{name}.group.bin', f'{name}.group.bin']
            for top in tops:
                visit(top, top, False)
            # The map's own groups as the game lists them, also when a caller's set lacks the
            # parent (projectiles load with the weapons, the statics with the level).
            for own, top in ((f'weapon_projectiles_{name}.group.bin', f'weapons_{name}.group.bin'),
                             (f'{name}_statics.group.bin', f'{name}.group.bin')):
                if own in self.groups and own not in order:
                    visit(own, top, False)
            self._order = {k: v for k, v in order.items() if v[0] >= 0}
        return self._order

    def visible(self, place: str, target: str) -> bool:
        """Whether resources of *target* (one of the map's files) find those of *place* while
        they load: the same group, a shared group loaded before it, or a game group loaded
        before it with the same top-level group (the base dynamics for the statics). The map's
        other own groups of the same top-level group never count: which of a parent and its
        child reads its resources first does not matter then."""
        if place == target:
            return True
        order = self.load_order()
        if target not in order:
            return True               # not a group the game loads by itself: as before
        if place not in order:
            return False
        when, top, shared = order[place]
        target_when, target_top, _ = order[target]
        if top == target_top:
            return when < target_when and place not in self.groups
        return when < target_when and shared

    def _seen_from(self, cls: int, name: int, target: str, body: bytes | None = None) -> bool:
        self.present()
        return any(self.visible(place, target) and (body is None or held == body)
                   for place, held in self._where.get((cls, name), []))

    # Copying ---------------------------------------------------------------------------------

    def target_for(self, entry: Entry, body: bytes, parent_target: str | None) -> str:
        if entry.cls == ENTITY_SPEC:
            kind = _spec_kind(body)
            if kind == 'projectile':
                return f'weapon_projectiles_{self.map_name}.group.bin'
            if kind == 'weapon':
                return f'weapons_{self.map_name}.group.bin'
            # Never the statics group: the level makes an entity of every spec there.
            return f'weapon_projectiles_{self.map_name}.group.bin'
        if parent_target:
            return parent_target
        return f'{self.map_name}_statics.group.bin'

    def resolve(self, value: int, prefer: str | None) -> list[Entry]:
        """The resources named *value* to copy, one per class: from the group *prefer* first,
        then its map, then the shared groups, then any."""
        candidates = [e for e in self.registry.entries(value) if e.cls not in NOT_COPIED]
        if not candidates:
            return []
        same_map = _library_map(prefer) if prefer else None
        candidates.sort(key=lambda e: (e.path != prefer, _library_map(e.path) != same_map,
                                       e.path not in ALWAYS_LOADED, e.path))
        chosen: dict[int, Entry] = {}
        for entry in candidates:
            chosen.setdefault(entry.cls, entry)
        return list(chosen.values())

    def add(self, roots, prefer: str | None = None, target: str | None = None,
            names: dict[int, int] | None = None) -> int:
        """Copy *roots* (name hashes) and everything they use into the map, unless the map
        already has them. *prefer* is the group to take them from first; *target* forces the
        map file they go into. Returns how many resources were copied."""
        before = len(self.copied)
        self._own = None            # other steps may have added to the map's groups
        for value in roots:
            for entry in self.resolve(value, prefer):
                self._copy(entry, target, top=True)
        return len(self.copied) - before

    def name_of(self, path: str, value: int) -> int:
        """The name a resource of *path* has in the map (its own unless it was renamed)."""
        return self.renamed.get((path, value), value)

    def _copy(self, entry: Entry, parent_target: str | None, top: bool = False) -> int:
        """Copy one resource (after what it uses) where *parent_target* can see it; returns the
        name it has in the map."""
        key = (entry.path, entry.cls, entry.hash)
        body = entry.resource.body
        target = self.target_for(entry, body, parent_target)
        if key in self._done:
            name = self._done[key]
            if key in self._busy or self._seen_from(entry.cls, name, target):
                return name
            # Copied for a group this one cannot see: copied again below.
        else:
            present = self.present()
            existing = present.get((entry.cls, entry.hash))
            name = entry.hash
            if existing is not None and existing != body:
                # Same name, different resource: this one gets a name of its own.
                stem = Path(entry.path).name.removesuffix('.group.bin')
                name = iw_hash(f'boz_{stem}_{entry.hash:08x}')
                self.renamed[(entry.path, entry.hash)] = name
            self._done[key] = name
            if self._seen_from(entry.cls, name, target, body):
                if (entry.cls, name) in self.own():
                    # Already in the map (put there by another step): what it uses may not be.
                    self._busy.add(key)
                    for value, classes in self._uses(entry):
                        for child in self._children(value, classes, entry.path):
                            self._copy(child, target)
                    self._busy.discard(key)
                return name
        self._busy.add(key)               # cycles resolve to this name
        # What it uses first, so a renamed one can be pointed at.
        patched = bytearray(body)
        kept = _kept_words(entry.cls, body)
        for value, classes in self._uses(entry):
            if value in kept[1]:
                continue                  # a link names an entity of the map, not a resource
            copies = [(child, self._copy(child, target)) for child in self._children(value, classes, entry.path)]
            new = next((n for _child, n in copies if n != value), None)
            if new is None or value in kept[0]:
                continue
            # Renamed for one class: every class the name can mean here gets that name, so the
            # use finds the right one whichever class it means.
            for child, have in copies:
                if have != new:
                    self._copy_as(child, have, new, target)
            _replace_word(patched, value, new)
        self._busy.discard(key)
        self._write(target, entry, name, bytes(patched))
        return name

    def _copy_as(self, entry: Entry, have: int, new: int, target: str) -> None:
        """A copy of *entry* (in the map as *have*) under the name *new* where *target* sees it."""
        if self._seen_from(entry.cls, new, target):
            return
        body = next((held for place, held in self._where.get((entry.cls, have), [])
                     if self.visible(place, target)), entry.resource.body)
        self._write(target, entry, new, body)

    def _uses(self, entry: Entry):
        return dict.fromkeys(self.registry.typed_references(entry)).keys()

    def _children(self, value: int, classes, prefer: str) -> list[Entry]:
        return [child for child in self.resolve(value, prefer) if classes is None or child.cls in classes]

    def _write(self, target_file: str, entry: Entry, name: int, body: bytes) -> None:
        target = self.groups.get(target_file) or self.statics
        if target is None:
            raise BundleError(f'the map has no group {target_file}')
        resource_type = _type_in(target, entry.cls, entry.like)
        resource_type.resources.append(group_module.Resource(
            None if resource_type.names_omitted else (entry.resource.name_hash if entry.resource.name_hash is not None
                                                      and entry.resource.name_hash != entry.hash else name),
            name, body))
        self.present().setdefault((entry.cls, name), body)
        self._where.setdefault((entry.cls, name), []).append((target_file, body))
        self.own().add((entry.cls, name))
        self.copied.append((entry.cls, name, entry.path, target_file))


def _replace_word(body: bytearray, old: int, new: int) -> None:
    old_bytes, new_bytes = struct.pack('<I', old), struct.pack('<I', new)
    start = 0
    while True:
        index = body.find(old_bytes, start)
        if index < 0:
            return
        body[index:index + 4] = new_bytes
        start = index + 4


def _type_in(target: group_module.Group, cls: int, like: group_module.ResourceType) -> group_module.ResourceType:
    for resource_type in target.types():
        if resource_type.class_hash == cls:
            return resource_type
    resource_type = group_module.ResourceType(cls, like.names_omitted, like.has_size)
    section = next((s for s in target.sections if s.hash == group_module.RESOURCES), None)
    if section is None:
        raise BundleError('the group has no resources section')
    types = section.types
    if cls in LOAD_ORDER:
        rank = LOAD_ORDER.index(cls)
        earlier = [i for i, t in enumerate(types) if t.class_hash in LOAD_ORDER and LOAD_ORDER.index(t.class_hash) < rank]
        later = [i for i, t in enumerate(types) if t.class_hash in LOAD_ORDER and LOAD_ORDER.index(t.class_hash) > rank]
        index = earlier[-1] + 1 if earlier else (later[0] if later else len(types))
    else:
        specs = [i for i, t in enumerate(types) if t.class_hash == ENTITY_SPEC]
        index = specs[0] if specs else len(types)
    types.insert(index, resource_type)
    return resource_type


# What a script can name and use by name: specs (spawn), sounds and sequences (play), screen
# effects, fogs and camera shakes.
SCRIPT_CLASSES = {ENTITY_SPEC, iw_hash('CIwSoundSpec'), iw_hash('CSoundSequence'),
                  iw_hash('CFullscreenFXConfig'), iw_hash('CIwFogConfig'), iw_hash('CCameraShakeConfig')}


# Standard-library calls that use a resource by a name the script never writes.
LIBRARY_CALLS = {'spawn_george': ['george_romero']}


def script_names(scripts: Path, registry: Registry, names: dict[int, str] | None = None) -> list[int]:
    """Resources a project's Lua names: string literals that are the name (or "0x..." hash) of an
    entity spec, sound spec, sound sequence, full-screen effect, fog or camera shake. The build
    bundles them, so scripts can spawn and play anything of any map."""
    import re
    if not scripts or not Path(scripts).is_dir():
        return []
    specs = {h for h, items in registry.by_hash.items() if any(e.cls in SCRIPT_CLASSES for e in items)}
    found: list[int] = []
    literal = re.compile(r'"([A-Za-z0-9_]{2,64})"|\'([A-Za-z0-9_]{2,64})\'')
    for file in sorted(Path(scripts).rglob('*.lua')):
        if 'boz' in file.relative_to(scripts).parts[:1]:
            continue                       # the standard library's own copy
        text = file.read_text(encoding='utf-8', errors='replace')
        for call, used in LIBRARY_CALLS.items():
            if re.search(r'\b' + call + r'\s*\(', text):
                for name in used:
                    value = iw_hash(name)
                    if value in specs and value not in found:
                        found.append(value)
        for match in literal.finditer(text):
            word = match.group(1) or match.group(2)
            if word.lower().startswith('0x'):
                try:
                    value = int(word, 16)
                except ValueError:
                    continue
            else:
                value = iw_hash(word)
            if value in specs and value not in found:
                found.append(value)
    return found
