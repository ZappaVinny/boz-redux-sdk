"""Effects and projectiles: what the game can spawn, carrying the ones a map uses into it, and the
names scripts use for them (boz.effects).

How the game spawns them (Ghidra): CSpawnManager spawns any entity spec by hash at a position
and rotation (Entity_CreateFromSpec, then the CIsTransform's position +0xa8 and rotation +0x98,
x y z w); CIwResManager finds the spec in any loaded group, so a map can carry the ones it uses
in its own groups. Effects are entity specs that draw particles (CIsRenderableGFXEmitter); the
game's shared ones are in ingame/effects/visualeffects and ingame/ingame (the Gersch device's
gersch_Effect among them), every map loads both. Projectiles are entity specs with a
CProjectileEntity, in each map's weapon_projectiles group; their behaviourType decides what they
do:

  1  thrown with a lifetime (grenades)
  2  a bolt: ray-casts every frame and explodes where it hits (ray gun, launchers)
  4  a device zombies are drawn to (monkey bomb), registered with CProjectileManager
  6  a Gersch device (black hole): once it rests it sends itself SUBJECT_SPAWN_GERSCH_EFFECT,
     spawns gersch_Effect, plays gersch_opens and gersch_loop, and lives 8000 ms (its +0xc0);
     zombies within 5000 units walk into it and die within m_proximityRadius x 100; a player
     inside is sent to a Gersch teleport point (none: nothing happens); it ends with
     gersch_shuts

Some of what a projectile uses is played by name, not referenced by its data (the Gersch
sounds): RUNTIME_SOUNDS lists those per behaviour, carried with it.

Project file: source/effects.json {"effects": [{"name", "kind", "level", "hash"}]}: each effect
the map uses under the project's own name (what scripts call it).
"""
from __future__ import annotations

import copy
import json
import re
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .hashing import iw_hash

ENTITY_SPEC = iw_hash('CIsEntitySpec')
PROJECTILE = iw_hash('CProjectileEntity')
EMITTER = iw_hash('CIsRenderableGFXEmitter')
TRANSFORM = iw_hash('CIsTransform')
BONE_ATTACHMENT = iw_hash('CIsBoneAttachment')
CHARACTERS = {iw_hash(n) for n in ('CHealth', 'CAIControllerZombie', 'CPlayerController', 'CIsAnimator')}
SHARED_EFFECT_GROUPS = ('ingame/effects/visualeffects.group.bin', 'ingame/ingame.group.bin')
BEHAVIOURS = {0: 'Plain', 1: 'Thrown (lifetime)', 2: 'Bolt (explodes on impact)',
              3: 'Projectile', 4: 'Lure (zombies drawn to it)', 5: 'Projectile',
              6: 'Black hole (Gersch device)'}
RUNTIME_SOUNDS = {6: ('gersch_opens', 'gersch_loop', 'gersch_shuts', 'gersch_teleport')}
TRIGGERS = {6: ('open',), 1: ('explode',), 2: ('explode',)}
NAME_RE = re.compile(r'[a-z][a-z0-9_]{0,31}')
TEXTURE_CLASSES = {iw_hash('CIwTexture')}
SOUND_DATA, SOUND_SPEC = iw_hash('CIwSoundData'), iw_hash('CIwSoundSpec')


class EffectError(ValueError):
    pass


# --- What the game has ------------------------------------------------------------------------

@dataclass
class Entry:
    kind: str           # "effect" or "projectile"
    level: str          # '' for the shared groups every map loads
    group: str          # the group it is in
    hash: int
    label: str
    behaviour: int = 0  # projectiles: CProjectileEntity behaviourType
    users: list = field(default_factory=list)   # the weapons that fire it

    @property
    def key(self) -> str:
        return f'{self.level or "shared"}:0x{self.hash:08x}'


def _types_of(spec) -> set:
    found = {c.type_hash for c in spec.components}
    for _cls, _reserved, child in spec.children:
        found |= _types_of(child)
    return found


def _has_emitter_spec(spec) -> bool:
    """Whether the spec's particle emitter names what it draws (CIwGFXEmitterSpec)."""
    for component in spec.components:
        if component.type_hash == EMITTER and component.blob is not None:
            for prop in component.blob.properties:
                if prop.name_hash == iw_hash('emitterSpec') and prop.raw and prop.raw != bytes(4):
                    return True
    return False


def behaviour_of(spec) -> int:
    for component in spec.components:
        if component.type_hash == PROJECTILE and component.blob is not None:
            for prop in component.blob.properties:
                if prop.name_hash == iw_hash('behaviourType') and len(prop.raw or b'') >= 4:
                    return struct.unpack_from('<I', prop.raw, 0)[0]
    return 0


def _parsed(read, path):
    from . import group as group_module
    raw = read(path)
    return group_module.parse(raw) if isinstance(raw, (bytes, bytearray)) else raw


def catalog(read, names, known: dict | None = None) -> list[Entry]:
    """Every effect and projectile of the game: the shared effects, each map's own effect groups
    and each map's projectiles (labelled by the weapons that fire them)."""
    from . import levels, resources, weapons
    known = dict(weapons._names() if known is None else known)
    names = list(names)
    out = []

    def specs(parsed):
        for t in parsed.types():
            if t.class_hash == ENTITY_SPEC:
                for r in t.resources:
                    try:
                        yield r.in_group_hash, resources.decode_entity_spec(r.body)
                    except (ValueError, struct.error):
                        continue

    effect_groups = [(p, '') for p in SHARED_EFFECT_GROUPS if p in names]
    effect_groups += [(p, p.split('/')[1]) for p in names
                      if p.startswith('levels/') and p.rsplit('/', 1)[-1].startswith('effects')]
    for path, level in effect_groups:
        mixed = path == 'ingame/ingame.group.bin'      # also players, spawners, ...: emitters only
        for h, spec in specs(_parsed(read, path)):
            types = _types_of(spec)
            if TRANSFORM not in {c.type_hash for c in spec.components} or \
                    BONE_ATTACHMENT in {c.type_hash for c in spec.components}:
                continue         # a part of another effect (or of a bone): not on its own
            top = {c.type_hash for c in spec.components}
            if EMITTER in top and not _has_emitter_spec(spec):
                continue         # an emitter template (base_emitter): nothing to draw, it crashes
            if mixed and (EMITTER not in top or top & CHARACTERS):
                continue         # ingame also holds zombies, players and pickups
            if PROJECTILE not in types and (EMITTER in types or not mixed):
                out.append(Entry('effect', level, path, h, known.get(h, f'0x{h:08x}')))
    for path in names:
        found = re.fullmatch(r'ingame/weapons/weapon_projectiles_(\w+)\.group\.bin', path)
        if not found:
            continue
        level = found.group(1)
        users = {}
        try:
            for weapon in weapons.read_level(_LevelReader(read), level):
                projectile = weapon.values.get('m_projectileName')
                if projectile:
                    users.setdefault(projectile, []).append(weapon.label)
        except (weapons.WeaponError, KeyError, OSError, ValueError):
            pass
        for h, spec in specs(_parsed(read, path)):
            if PROJECTILE not in _types_of(spec):
                continue
            label = known.get(h) or (f'{users[h][0]} projectile' if h in users else f'0x{h:08x}')
            out.append(Entry('projectile', level, path, h, label, behaviour_of(spec),
                             users.get(h, [])))
    out.sort(key=lambda e: (e.kind, e.level, e.label.lower()))
    return out


class _LevelReader:
    """Something with read() for bozkit.weapons.read_level from a read function."""
    def __init__(self, read):
        self.read = read


# --- The project's effects --------------------------------------------------------------------

@dataclass
class Used:
    name: str           # what scripts call it
    kind: str
    level: str          # '' = shared (every map has it)
    hash: int
    behaviour: int = 0
    hidden: bool = False      # its own model taken out (a black hole without the device)
    anchored: bool = False    # its physics taken out: it stays where it is spawned

    @property
    def changed(self) -> bool:
        return self.hidden or self.anchored

    @property
    def spawn_hash(self) -> int:
        """What scripts spawn: the game's spec, or the map's own changed copy of it."""
        return iw_hash(f'boz_effect_{self.name}') if self.changed else self.hash


def path(source: Path) -> Path:
    return Path(source) / 'effects.json'


def load(source: Path) -> list[Used]:
    try:
        data = json.loads(path(source).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise EffectError(f'effects.json: {exc}') from None
    out = []
    for item in data.get('effects', []):
        value = item.get('hash', 0)
        out.append(Used(str(item['name']), str(item.get('kind', 'effect')), str(item.get('level', '')),
                        int(value, 16) if isinstance(value, str) else int(value),
                        int(item.get('behaviour', 0)), bool(item.get('hidden', False)),
                        bool(item.get('anchored', False))))
    return out


def save(source: Path, used: list[Used]) -> None:
    for item in used:
        if not NAME_RE.fullmatch(item.name):
            raise EffectError(f'effect name {item.name!r}: use a-z, 0-9 and _ (at most 32, '
                              'starting with a letter)')
    if len({u.name for u in used}) != len(used):
        raise EffectError('two effects share a name')
    if not used:
        path(source).unlink(missing_ok=True)
        return
    path(source).parent.mkdir(parents=True, exist_ok=True)
    path(source).write_text(json.dumps({'effects': [
        dict(asdict(u), hash=f'0x{u.hash:08x}') for u in used]}, indent=2) + '\n',
        encoding='utf-8', newline='\n')


def runtime(used: list[Used]) -> list[dict]:
    """What boz.effects knows at level start: each effect's name, hash, kind, behaviour and the
    triggers it answers."""
    return [{'name': u.name, 'hash': u.spawn_hash, 'kind': u.kind, 'behaviour': u.behaviour,
             'triggers': list(TRIGGERS.get(u.behaviour, ()))} for u in used]


# --- Building ---------------------------------------------------------------------------------

def _add_like(target, source_type, resource) -> None:
    """Add *resource* to *target* in a resource type made like *source_type* (the same class,
    and whether each resource names its own class, as sound data and specs do)."""
    from . import group as group_module
    for t in target.types():
        if t.class_hash == source_type.class_hash:
            t.resources.append(copy.copy(resource))
            return
    for section in target.sections:
        if section.types is not None:
            section.types.append(group_module.ResourceType(
                source_type.class_hash, source_type.names_omitted, source_type.has_size,
                [copy.copy(resource)]))
            return
    raise EffectError('the target group has no resource section')


def _references(body: bytes, wanted: set) -> set:
    found = set()
    for shift in range(4):
        count = (len(body) - shift) // 4
        if count > 0:
            found |= wanted.intersection(struct.unpack_from(f'<{count}I', body, shift))
    return found


def carry(read, used: Used, target, groups: dict) -> int:
    """Copy an effect or projectile of another map, with everything it refers to by hash (and the
    sounds its behaviour plays by name), into *target* (the map's projectiles group). Resources
    any of the map's *groups* or the shared groups already hold are not copied. Returns how many
    resources were copied."""
    gear = used.level
    paths = []
    if used.kind == 'projectile':
        paths.append(f'ingame/weapons/weapon_projectiles_{gear}.group.bin')
    paths += [f'levels/{gear}/effects.group.bin', f'levels/{gear}/effects_shared.group.bin',
              f'levels/{gear}/{gear}_statics.group.bin']
    index = {}
    for p in paths:
        try:
            parsed = _parsed(read, p)
        except (KeyError, OSError, ValueError):
            continue
        for t in parsed.types():
            for r in t.resources:
                index.setdefault(r.in_group_hash, []).append((t, r))
    if used.hash not in index:
        raise EffectError(f'{used.name}: {gear} has no effect 0x{used.hash:08x}')
    present = set()
    for parsed in list(groups.values()) + [_parsed(read, p) for p in SHARED_EFFECT_GROUPS]:
        present |= {(t.class_hash, r.in_group_hash) for t in parsed.types() for r in t.resources}
    seeds = {used.hash} | {iw_hash(n) for n in RUNTIME_SOUNDS.get(used.behaviour, ())}
    wanted = set(index)
    todo, done = [h for h in seeds if h in index], set()
    while todo:
        current = todo.pop()
        if current in done:
            continue
        done.add(current)
        for t, r in index[current]:
            if (t.class_hash, current) in present or t.class_hash in TEXTURE_CLASSES:
                continue
            todo.extend(_references(r.body, wanted) - done)
    copied = 0
    for current in done:
        for t, r in index[current]:
            if (t.class_hash, current) in present:
                continue
            _add_like(target, t, r)
            present.add((t.class_hash, current))
            copied += 1
    return copied


MODEL_COMPONENTS = {iw_hash('CIsRenderableModel')}
PHYSICS_COMPONENTS = {iw_hash(n) for n in ('CIsRigidBody', 'CIsCollisionSphere')}


def changed_spec(body: bytes, used: Used) -> bytes:
    """A copy of an entity spec without what *used* leaves out: its model (hidden) and its rigid
    body and collision (anchored: no gravity, it stays where it is spawned; a projectile without
    a rigid body skips its physics: Projectile_UpdateFlight, Projectile_UpdateGersch and
    Projectile_Impact all check for it)."""
    from . import resources
    spec = resources.decode_entity_spec(body)
    drop = (MODEL_COMPONENTS if used.hidden else set()) | (PHYSICS_COMPONENTS if used.anchored else set())

    def strip(s):
        s.components = [c for c in s.components if c.type_hash not in drop]
        for _cls, _reserved, child in s.children:
            strip(child)
    strip(spec)
    return resources.encode_entity_spec(spec)


def _find_spec(read, used: Used, groups: dict) -> tuple | None:
    """(resource type, resource) of an effect's spec: in the map's groups (carried in or the base
    map's), else in the shared groups or its own map's."""
    paths = list(SHARED_EFFECT_GROUPS)
    if used.level:
        paths += [f'ingame/weapons/weapon_projectiles_{used.level}.group.bin',
                  f'levels/{used.level}/effects.group.bin', f'levels/{used.level}/effects_shared.group.bin']
    for parsed in list(groups.values()) + [p for p in (_safe(read, q) for q in paths) if p is not None]:
        for t in parsed.types():
            if t.class_hash == ENTITY_SPEC:
                for r in t.resources:
                    if r.in_group_hash == used.hash:
                        return t, r
    return None


def _safe(read, path):
    try:
        return _parsed(read, path)
    except (KeyError, OSError, ValueError):
        return None


def _source_group(used: Used) -> str | None:
    """The group an effect of the catalog is taken from first."""
    if not used.level:
        return None
    if used.kind == 'projectile':
        return f'ingame/weapons/weapon_projectiles_{used.level}.group.bin'
    return f'levels/{used.level}/effects.group.bin'


def apply(read, source: Path, groups: dict, map_name: str, base: str, pack=None,
          scripts: Path | None = None) -> list[dict]:
    """Put the project's effects in the map and return the runtime list for boz.effects.

    With the game *pack*, everything goes through bozkit.bundle: each effect (from any map) and
    every effect or projectile the project's *scripts* name ("0x..." or its game name) comes
    with everything it uses, so scripts can spawn anything; changed ones (hidden, anchored) get
    the map's own copy. Without it, effects of other maps than *base* are carried (carry)."""
    used = load(source)
    from . import levels
    target = groups.get(f'weapon_projectiles_{map_name}.group.bin')
    extra: list[dict] = []
    if pack is not None:
        from . import bundle as bundle_module, weapons
        registry = bundle_module.Registry.of(pack)
        bundle = bundle_module.Bundle(registry, groups, map_name)
        for item in used:
            bundle.add([item.hash], prefer=_source_group(item))
            spawned = next((v for (_path, h), v in bundle.renamed.items() if h == item.hash), None)
            if spawned and not item.changed:
                item.hash = spawned            # the map holds it under a name of its own
        known = {u.hash for u in used}
        names = weapons._names()
        for value in bundle_module.script_names(scripts, registry) if scripts else []:
            if value in known:
                continue
            bundle.add([value])
            entry = next((e for e in registry.entries(value) if e.cls == ENTITY_SPEC), None)
            if entry is None:
                continue          # a sound, sequence, screen effect or fog: bundled, not an effect
            behaviour, kind = 0, 'effect'
            if entry is not None:
                from . import resources
                try:
                    spec = resources.decode_entity_spec(entry.resource.body)
                    if PROJECTILE in _types_of(spec):
                        kind, behaviour = 'projectile', behaviour_of(spec)
                except (ValueError, struct.error):
                    pass
            extra.append({'name': names.get(value, f'0x{value:08x}'), 'hash': value, 'kind': kind,
                          'behaviour': behaviour, 'triggers': list(TRIGGERS.get(behaviour, ()))})
    else:
        gear = levels.GEAR.get(base, base) if hasattr(levels, 'GEAR') else base
        for item in used:
            if not item.level or item.level in (base, gear):
                continue
            if target is None:
                raise EffectError(f'{item.name}: the map has no projectiles group to carry it into')
            carry(read, item, target, groups)
    for item in used:            # changed ones: the map's own copy of the spec, under its name
        if not item.changed:
            continue
        if target is None:
            raise EffectError(f'{item.name}: the map has no projectiles group for its copy')
        found = _find_spec(read, item, groups)
        if found is None:
            raise EffectError(f'{item.name}: no effect 0x{item.hash:08x} to copy')
        source_type, resource = found
        copy_of = copy.copy(resource)
        copy_of.in_group_hash = item.spawn_hash
        if copy_of.name_hash is not None:
            copy_of.name_hash = item.spawn_hash
        copy_of.body = changed_spec(resource.body, item)
        for t in target.types():
            if t.class_hash == ENTITY_SPEC:
                t.resources = [r for r in t.resources if r.in_group_hash != item.spawn_hash]
        _add_like(target, source_type, copy_of)
    return runtime(used) + extra
