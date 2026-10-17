"""Weapons of a map project: the game's CPlayerWeapon data, project edits, new and imported
weapons, applied to the map's weapons groups when it builds.

A level's weapons live in ``ingame/weapons/weapons_<level>`` (one entity spec per weapon, its
models, skins, skeletons, animations and animation state machines), with the first-person arms in
``ingame/characters/arms/arms_<level>`` and projectiles in ``weapon_projectiles_<level>``. A map
project builds renamed copies of its base level's (bozkit.levels.common_files); this module
changes those copies.

Project files (``source/weapons/``):

    index.json        {"weapons": ["colt45", "mp40", ...], "start": "colt45", "start_reserve": 40}:
                      the weapons the editor lists, the wall-buy picker and the box pool offer
                      (the level keeps every weapon the game needs either way), and the weapon
                      players start with and its spare rounds (WeaponManager_GiveStartWeapons
                      gives the PlayerStartWeapon cvar's weapon with PlayerStartAmmo, then the
                      knife and two frag grenades; a missing weapon crashes the game there)
    <name>.json       a weapon with changes: {"name", "base", "level", "fields", "script"}
                      - base: the game weapon it starts from (its name, or itself)
                      - level: where base comes from ('' = the map's own weapons); another level's
                        weapon is imported with everything it references
                      - fields: changed values by key (FIELDS); "Upgrade" holds a weapon name

How the game uses the fields (Ghidra names in the game definition): CPlayerWeapon::CreateBehaviour
makes the fire mode from ``behaviour``; automatic modes fire at ``autoROF`` rounds per minute,
single-shot weapons as fast as their fire animation (the bullet and the end of a reload are
animation events); CWeaponManager::UpdateSpread scales the spread by the crouched/prone
modifiers and Deadshot; the constructor's defaults apply to fields a weapon leaves unset.
"""
from __future__ import annotations

import copy
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import iw_hash
from . import maps

ENTITY_SPEC = iw_hash('CIsEntitySpec')
PLAYER_WEAPON = iw_hash('CPlayerWeapon')
TEXTURE_CLASSES = {iw_hash('CIwTexture')}
NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,47}$')


class WeaponError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    key: str            # field name, or "<struct field>.<inner field>"
    label: str
    group: str
    kind: str           # int, float, bool, enum, weapon, sound, readonly
    unit: str = ''
    description: str = ''
    default: object = 0
    options: tuple = ()          # enum: ((value, label), ...)
    confirmed: bool = True       # meaning proven in the code (else: from the shipped data)


BEHAVIOURS = ((0, 'Melee / no gun'), (1, 'Single shot'), (2, 'Automatic'), (3, 'Burst'),
              (4, 'Shotgun'), (5, 'Automatic shotgun'), (6, 'Revolver'), (7, 'Grenade'),
              (8, 'Special grenade'), (9, 'Launcher'), (10, 'Death Machine'), (11, 'Claymore'),
              (12, 'Monkey bomb'), (15, 'Thundergun'), (16, 'V-R11'), (17, 'Wunderwaffe'))
CROSSHAIRS = ((0, 'None'), (1, 'Standard'), (2, 'Launcher'), (3, 'Minigun'), (4, 'Thundergun'))
RECOILS = ((0, 'None'), (1, 'Light'), (2, 'Medium'), (3, 'Heavy'))
AMMO_ICONS = ((0, 'None'), (1, 'Rifle'), (3, 'Shotgun shells'), (4, 'Grenade launcher'),
              (8, 'Belt / large'), (9, 'Pistol'), (10, 'Grenade'), (11, 'Claymore'),
              (12, 'Monkey bomb'))

FIELDS = (
    # Firing
    Field('behaviour', 'Fire mode', 'Firing', 'enum', '',
          'How the weapon fires (CPlayerWeapon::CreateBehaviour). Automatic, Automatic shotgun and '
          'Death Machine keep firing while the trigger is held.', 1, BEHAVIOURS),
    Field('autoROF', 'Fire rate', 'Firing', 'int', 'rounds/min',
          'Automatic modes only (MP40 535, AK-74u 750). Single-shot weapons fire as fast as their '
          'fire animation plays.', 0),
    Field('semiBurst', 'Burst size', 'Firing', 'int', 'rounds', 'Rounds per trigger pull (Burst).',
          0, confirmed=False),
    Field('requiresADS', 'Fires only when aiming', 'Firing', 'bool', '',
          'The trigger does nothing unless the player aims down sights.', False),
    Field('autoAim', 'Aim assist', 'Firing', 'bool', '',
          'The crosshair is pulled toward zombies.', True, confirmed=False),
    Field('recoil', 'Recoil', 'Firing', 'enum', '', 'How much the view kicks per shot.', 0,
          RECOILS, confirmed=False),
    # Ammo
    Field('m_clipSize', 'Clip', 'Ammo', 'int', 'rounds', 'Rounds in one magazine.', 0),
    Field('m_ammoSize', 'Reserve', 'Ammo', 'int', 'rounds',
          'Spare rounds carried besides the clip (Colt: 8 + 80).', 0),
    Field('loopedReload', 'Reloads one at a time', 'Ammo', 'bool', '',
          'Rounds go in one by one and the reload can be cut short (pump shotguns).', False),
    Field('doubleShellReload', 'Two shells per step', 'Ammo', 'bool', '',
          'A looped reload loads two shells each step.', False, confirmed=False),
    Field('flipClipReload', 'Taped magazines', 'Ammo', 'bool', '',
          'Every other reload uses the second (flipped) magazine animation.', False),
    Field('lightningBoltPickup', 'Ammo pickup when empty', 'Ammo', 'bool', '',
          'When the weapon runs dry the pickup manager is told (shipped weapons leave it off).',
          False, confirmed=False),
    # Damage
    Field('m_damage.m_headDamage', 'Head', 'Damage', 'int', 'points',
          'Damage of a hit to the head (MP40 400).', 0),
    Field('m_damage.m_torsoDamage', 'Torso', 'Damage', 'int', 'points',
          'Damage of a hit to the body (MP40 100).', 0),
    Field('m_damage.m_limbDamage', 'Limbs', 'Damage', 'int', 'points',
          'Damage of a hit to an arm or leg (MP40 100).', 0),
    Field('m_falloff.m_startDistance', 'Falloff starts', 'Damage', 'int', 'cm',
          'Full damage up to this distance (shotguns 400, Thundergun 1200).', 0),
    Field('m_falloff.m_endDistance', 'Falloff ends', 'Damage', 'int', 'cm',
          'Distance where damage reaches the falloff damage (shotguns 800).', 0),
    Field('m_falloff.m_damageMod', 'Falloff damage', 'Damage', 'int', '%',
          'Damage left at the end distance (shotguns 50).', 0, confirmed=False),
    Field('m_penetration.m_penetrationRating', 'Penetration', 'Damage', 'int', '',
          'How far bullets go through zombies and thin surfaces (rifles 10, shotguns 15).', 1,
          confirmed=False),
    Field('m_penetration.m_damageFalloff', 'Penetration loss', 'Damage', 'float', '%',
          'Damage lost each time a bullet goes through something (30 to 50).', 0.0,
          confirmed=False),
    Field('m_penetration.m_damageMin', 'Penetration minimum', 'Damage', 'int', 'points',
          'Damage never drops below this after going through things.', 0, confirmed=False),
    Field('incendiaryRounds', 'Fire rounds', 'Damage', 'bool', '',
          'Hits set zombies on fire (Hades, the upgraded Olympia).', False, confirmed=False),
    Field('m_meleeRange', 'Melee range', 'Damage', 'float', 'm',
          'Reach of a melee weapon (knives 1.5).', 0.0, confirmed=False),
    # Accuracy
    Field('m_accuracy.m_spreadMin', 'Spread, steady', 'Accuracy', 'float', '',
          'Bullet spread when still and not firing (crosshair size; Colt 0.28).', 0.0),
    Field('m_accuracy.m_spreadMax', 'Spread, moving', 'Accuracy', 'float', '',
          'Bullet spread at its widest, while moving or firing (Colt 0.525).', 1.0),
    Field('m_accuracy.m_modCrouched', 'Crouched', 'Accuracy', 'float', 'x',
          'Spread multiplier while crouched (0.85: 15% tighter).', 1.0),
    Field('m_accuracy.m_modProne', 'Prone', 'Accuracy', 'float', 'x',
          'Spread multiplier while prone.', 1.0),
    Field('m_accuracy.m_crosshairType', 'Crosshair', 'Accuracy', 'enum', '',
          'The crosshair drawn for this weapon.', 1, CROSSHAIRS),
    # Aiming
    Field('m_ADSFoV', 'Aiming field of view', 'Aiming', 'float', 'degrees',
          'Field of view while aiming down sights (MP40 40, AK-74u 30); 0 keeps the normal view.',
          0.0),
    # Projectile
    Field('m_projectileName', 'Projectile', 'Projectile', 'readonly', '',
          'What a launcher or grenade throws (an entity of weapon_projectiles).', 0),
    Field('m_projectileLaunchForce', 'Launch force', 'Projectile', 'float', '',
          'Speed the projectile leaves with (Thundergun 3000).', 0.0, confirmed=False),
    # Pack-a-Punch and the box
    Field('Upgrade', 'Pack-a-Punch result', 'Pack-a-Punch', 'weapon', '',
          'The weapon Pack-a-Punch turns this one into (none: it cannot be upgraded).', 0),
    Field('m_playPAPSound', 'Pack-a-Punch sound', 'Pack-a-Punch', 'bool', '',
          'Plays the upgraded-weapon sound when fired.', False, confirmed=False),
    Field('isUnique', 'Once per game', 'Pack-a-Punch', 'bool', '',
          'The mystery box gives it only once (Thundergun).', False, confirmed=False),
    Field('crappyWeapon', 'Weak weapon', 'Pack-a-Punch', 'bool', '',
          'Marked as a poor weapon (set on the CZ75 only).', False, confirmed=False),
    # HUD
    Field('ammoIcon', 'Ammo icon', 'HUD', 'enum', '', 'The ammo symbol on the HUD.', 0, AMMO_ICONS),
    # Sounds
    Field('fireSoundSequence', 'Fire', 'Sounds', 'sound', '', 'Played on every shot.', 0),
    Field('m_fireLastBulletSoundSequence', 'Last round', 'Sounds', 'sound', '',
          'Played on the last round of a clip.', 0),
    Field('fireEmptySound', 'Empty click', 'Sounds', 'sound', '', 'Firing with no ammo.', 0),
    Field('reloadSoundSequence', 'Reload', 'Sounds', 'sound', '', 'A full reload.', 0),
    Field('reloadPartialSequence', 'Reload (rounds left)', 'Sounds', 'sound', '',
          'A reload with rounds still in the clip.', 0),
    Field('buySound', 'Bought', 'Sounds', 'sound', '', 'Played when it is bought.', 0),
    Field('playerBuySound', 'Bought (player)', 'Sounds', 'sound', '',
          'The buyer\'s own purchase sound.', 0),
    Field('muzzleFlash', 'Muzzle flash', 'Firing', 'effect', '', 'The muzzle flash effect.', 0),
)
FIELD_BY_KEY = {f.key: f for f in FIELDS}
GROUPS = tuple(dict.fromkeys(f.group for f in FIELDS))


# --- Reading weapon entity specs -----------------------------------------------------------

def _weapon_blob(spec):
    for component in spec.components:
        if component.type_hash == PLAYER_WEAPON and component.blob is not None:
            return component.blob
    return None


def _prop(blob, name: str):
    from . import levels
    return levels._blob_prop(blob, name) if blob is not None else None


def get_value(blob, key: str):
    """A field's value in a CPlayerWeapon blob, or None when the weapon leaves it unset."""
    from . import reflect

    outer, _, inner = key.partition('.')
    prop = _prop(blob, outer)
    if prop is None:
        return None
    if inner:
        if prop.nested is None:
            return None
        prop = _prop(prop.nested, inner)
        if prop is None:
            return None
    value = reflect.typed_value(prop)
    if value is None and len(prop.raw) == 4:
        value = struct.unpack('<I', prop.raw)[0]   # enums
    return value


def value_or_default(blob, key: str):
    value = get_value(blob, key)
    return FIELD_BY_KEY[key].default if value is None and key in FIELD_BY_KEY else value


_TYPE_OF = {'int': 'unsigned int', 'float': 'float', 'bool': 'bool', 'weapon': 'unsigned int',
            'sound': 'unsigned int'}
_ENUM_TYPES = {'behaviour': 'CParsableEnumManager::WeaponBehaviourType',
               'recoil': 'CParsableEnumManager::RecoilType',
               'ammoIcon': 'CParsableEnumManager::WeaponAmmoIconType',
               'm_accuracy.m_crosshairType': 'CParsableEnumManager::CrosshairType'}
_STRUCTS = {'m_damage': 'CWeaponDamage', 'm_falloff': 'CWeaponFalloff',
            'm_penetration': 'CWeaponPenetration', 'm_accuracy': 'CWeaponAccuracy'}


def set_value(blob, key: str, value) -> None:
    """Set a field in a CPlayerWeapon blob, adding it (and its struct) when the weapon left it at
    the default."""
    from . import reflect

    spec = FIELD_BY_KEY.get(key)
    if spec is None or spec.kind == 'readonly':
        raise WeaponError(f'{key} cannot be changed')
    outer, _, inner = key.partition('.')
    holder, owner = blob, PLAYER_WEAPON
    if inner:
        prop = _prop(blob, outer)
        if prop is None:
            nested = reflect.Blob(iw_hash(_STRUCTS[outer]))
            prop = reflect.Property(PLAYER_WEAPON, iw_hash(_STRUCTS[outer]), iw_hash(outer), b'',
                                    nested=nested)
            blob.properties.append(prop)
        if prop.nested is None:
            prop.nested = reflect.Blob(iw_hash(_STRUCTS[outer]))
        holder, owner, name = prop.nested, iw_hash(_STRUCTS[outer]), inner
    else:
        name = outer
    target = _prop(holder, name)
    type_name = _ENUM_TYPES.get(key) or _TYPE_OF.get(spec.kind, 'unsigned int')
    if target is None:
        target = reflect.Property(owner, iw_hash(type_name), iw_hash(name), b'')
        holder.properties.append(target)
    if key in _ENUM_TYPES:
        target.raw = struct.pack('<I', int(value))
        target.nested = target.elements = None
        return
    if spec.kind == 'bool':
        value = bool(value)
    elif spec.kind == 'float':
        value = float(value)
    elif spec.kind in ('weapon', 'sound', 'int'):
        value = _hash_of(value) if spec.kind == 'weapon' else int(value)
    reflect.set_typed_value(target, value)


def _hash_of(value) -> int:
    if isinstance(value, int):
        return value
    if not value:
        return 0
    return int(value, 16) if str(value).startswith('0x') else iw_hash(str(value))


@dataclass
class GameWeapon:
    name: str           # its name ("mp40"), or "0x..." when the game only keeps the hash
    name_hash: int
    level: str
    values: dict        # field key -> value (unset fields at their defaults)
    label: str = ''     # what the editor shows ("mp40", "mp40 (upgraded)")


def weapons_group_path(level: str) -> str:
    return f'ingame/weapons/weapons_{maps.gear(level)}.group.bin'


_KNOWN: dict[int, str] | None = None


def _names() -> dict[int, str]:
    """Names by hash: bozkit's dictionary (the game definition and the names cache) first, then
    the asset library's strings."""
    global _KNOWN
    if _KNOWN is None:
        from .schema import Names
        _KNOWN = dict(Names().names)
        try:
            from . import library
            for line in (library.library_dir() / 'names.txt').read_text(
                    encoding='latin-1').splitlines():
                if line:
                    _KNOWN.setdefault(iw_hash(line), line)
        except Exception:   # noqa: BLE001 - no library
            pass
    return _KNOWN


def name_for(name_hash: int, resource_name: int | None, known: dict) -> str:
    return known.get(name_hash) or f'0x{name_hash:08x}'


def read_level(game, level: str) -> list[GameWeapon]:
    """The weapons of a level's weapons group (the game's own data)."""
    from . import group as group_module

    parsed = group_module.read_parsed(game.read, weapons_group_path(level))
    return read_group(parsed, level)


def read_group(parsed, level: str = '', extra_names=()) -> list[GameWeapon]:
    from . import resources

    known = dict(_names())
    for name in extra_names:
        known[iw_hash(name)] = name
    out = []
    for resource_type in parsed.types():
        if resource_type.class_hash != ENTITY_SPEC:
            continue
        for resource in resource_type.resources:
            try:
                spec = resources.decode_entity_spec(resource.body)
            except (ValueError, struct.error):
                continue
            blob = _weapon_blob(spec)
            if blob is None:
                continue
            values = {f.key: value_or_default(blob, f.key) for f in FIELDS}
            upgrade = values.get('Upgrade') or 0
            values['Upgrade'] = name_for(upgrade, None, known) if upgrade else ''
            name = name_for(resource.in_group_hash, resource.name_hash, known)
            out.append(GameWeapon(name, resource.in_group_hash, level, values, name))
    # Unnamed weapons are mostly Pack-a-Punch results: label them after the weapon upgrading.
    upgrades = {w.values.get('Upgrade'): w.name for w in out if w.values.get('Upgrade')}
    for weapon in out:
        if weapon.name.startswith('0x') and weapon.name in upgrades:
            weapon.label = f'{upgrades[weapon.name]} (upgraded)'
    return out


# The game's weapon specs that are not weapons a player buys: the perk drink (perkcola_*) and the
# last-stand pistols (*_laststand*). Of the melee weapons (behaviour 0) only the Bowie knife is
# bought (from the wall).
NOT_BOUGHT_PREFIX, NOT_BOUGHT_PART = 'perkcola', 'laststand'
BOUGHT_MELEE = {'knife_bowie'}


def is_gun(weapon: GameWeapon) -> bool:
    """Weapons players buy and carry (not perk bottles, last-stand pistols or knives)."""
    name = weapon.name.lower()
    if name.startswith(NOT_BOUGHT_PREFIX) or NOT_BOUGHT_PART in name:
        return False
    return weapon.values.get('behaviour') != 0 or name in BOUGHT_MELEE


# --- Project files -------------------------------------------------------------------------

@dataclass
class WeaponDef:
    name: str
    base: str = ''
    level: str = ''
    fields: dict = field(default_factory=dict)
    script: str = ''
    model: dict = field(default_factory=dict)    # your own model (bozkit.weapon_model)
    arms: dict = field(default_factory=dict)     # where the arms sit: {"location", "rotation"}
    display: str = ''                            # its name in game prompts ('' = the game's own)
    sounds: dict = field(default_factory=dict)   # {sound field: project sound}: its own sounds
    icon: dict = field(default_factory=dict)     # HUD picture: {"like": weapon} / {"image": file}
    sound_data: dict = field(default_factory=dict, compare=False, repr=False)  # attach_models
    model_data: tuple | None = field(default=None, compare=False, repr=False)   # attach_models
    clips: dict = field(default_factory=dict, compare=False, repr=False)      # attach_models

    @property
    def source(self) -> str:
        return self.base or self.name


def weapons_dir(source: Path) -> Path:
    return Path(source) / 'weapons'


def load_index(source: Path) -> list[str] | None:
    data = _index_data(source)
    if 'weapons' not in data:
        return None
    return [str(name) for name in data.get('weapons', [])]


DEFAULT_START = 'colt45'
DEFAULT_START_RESERVE = 40   # PlayerStartAmmo's default


def _index_data(source: Path) -> dict:
    path = weapons_dir(source) / 'index.json'
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeaponError(f'{path}: {exc}') from exc


def _write_index(source: Path, data: dict) -> Path:
    folder = weapons_dir(source)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'index.json'
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    return path


def save_index(source: Path, names: list[str]) -> Path:
    data = _index_data(source)
    data['weapons'] = list(dict.fromkeys(names))
    return _write_index(source, data)


def load_start(source: Path) -> tuple[str, int]:
    """(the weapon players start with, its spare rounds)."""
    data = _index_data(source)
    return (str(data.get('start') or DEFAULT_START),
            int(data.get('start_reserve', DEFAULT_START_RESERVE)))


def save_start(source: Path, name: str, reserve: int) -> Path:
    data = _index_data(source)
    data.setdefault('weapons', [])
    data['start'] = name
    data['start_reserve'] = max(0, int(reserve))
    return _write_index(source, data)


def load_defs(source: Path) -> list[WeaponDef]:
    folder = weapons_dir(source)
    out = []
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        if path.name == 'index.json':
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise WeaponError(f'{path}: {exc}') from exc
        out.append(WeaponDef(str(data.get('name') or path.stem), str(data.get('base', '')),
                             str(data.get('level', '')), dict(data.get('fields', {})),
                             str(data.get('script', '')), dict(data.get('model', {})),
                             dict(data.get('arms', {})), str(data.get('display', '')),
                             dict(data.get('sounds', {})), dict(data.get('icon', {}))))
    return out


def save_def(source: Path, weapon: WeaponDef) -> Path:
    if not NAME_RE.fullmatch(weapon.name) and not weapon.name.startswith('0x'):
        raise WeaponError(f'weapon name {weapon.name!r}: use letters, digits and _')
    for key in weapon.fields:
        if key not in FIELD_BY_KEY:
            raise WeaponError(f'{weapon.name}: unknown field {key}')
    folder = weapons_dir(source)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{weapon.name}.json'
    data = {'name': weapon.name, 'base': weapon.base if weapon.base != weapon.name else '',
            'level': weapon.level, 'fields': dict(sorted(weapon.fields.items())),
            'script': weapon.script}
    if weapon.model:
        data['model'] = weapon.model
    if weapon.arms:
        data['arms'] = weapon.arms
    if weapon.display:
        data['display'] = weapon.display
    if weapon.sounds:
        data['sounds'] = dict(sorted(weapon.sounds.items()))
    if weapon.icon:
        data['icon'] = weapon.icon
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    return path


def delete_def(source: Path, name: str) -> None:
    path = weapons_dir(source) / f'{name}.json'
    if path.is_file():
        path.unlink()


def default_index(game_weapons: list[GameWeapon], template: str) -> list[str]:
    """The weapons a new project lists: the Colt for an empty map, else every gun of its base."""
    if template in ('empty', ''):
        return [DEFAULT_START]
    return [w.name for w in game_weapons if is_gun(w)]


def validate(defs: list[WeaponDef], available: set[str]) -> list[str]:
    problems = []
    seen = set()
    for weapon in defs:
        if weapon.name in seen:
            problems.append(f'weapon {weapon.name} is defined twice')
        seen.add(weapon.name)
        if not weapon.level and weapon.source not in available:
            problems.append(f'weapon {weapon.name}: the level has no weapon {weapon.source}')
        for key, value in weapon.fields.items():
            spec = FIELD_BY_KEY.get(key)
            if spec is None:
                problems.append(f'weapon {weapon.name}: unknown field {key}')
            elif spec.kind == 'readonly':
                problems.append(f'weapon {weapon.name}: {spec.label} cannot be changed')
    return problems


# --- Applying to a map's groups ------------------------------------------------------------

def _entity_specs(parsed):
    for resource_type in parsed.types():
        if resource_type.class_hash == ENTITY_SPEC:
            return resource_type
    return None


def _add(parsed, class_hash: int, resource) -> None:
    from . import group as group_module

    for resource_type in parsed.types():
        if resource_type.class_hash == class_hash:
            resource_type.resources.append(resource)
            return
    for section in parsed.sections:
        if section.types is not None:
            names_omitted = section.types[0].names_omitted if section.types else 0
            section.types.append(group_module.ResourceType(class_hash, names_omitted, 1, [resource]))
            return
    raise WeaponError('weapons group has no resource section')


def _hashes(parsed) -> set[int]:
    return {r.in_group_hash for t in parsed.types() for r in t.resources}


def _bring(bundle, weapon: 'WeaponDef', groups: dict) -> list[str]:
    """Bring a weapon of another level into the map with everything it uses (bozkit.bundle): its
    spec, and the state machines it names by text (m_weaponAsm into the weapons group, m_armsAsm
    into the arms group, where the game's own are). Returns warnings."""
    from . import resources
    gear = maps.gear(weapon.level)
    source = _hash_of(weapon.source)
    weapons_file = next(f for f, g in bundle.groups.items() if g is groups['weapons'])
    arms_file = next(f for f, g in bundle.groups.items() if g is groups['arms'])
    bundle.add([source], prefer=weapons_group_path(weapon.level))
    resource = next((r for r in _entity_specs(groups['weapons']).resources if r.in_group_hash == source), None)
    if resource is None:
        raise WeaponError(f'{weapon.level} has no weapon {weapon.source}')
    blob = _weapon_blob(resources.decode_entity_spec(resource.body))
    for field_name, target, prefer in (('m_weaponAsm', weapons_file, weapons_group_path(weapon.level)),
                                       ('m_armsAsm', arms_file, f'ingame/characters/arms/arms_{gear}.group.bin')):
        value = get_value(blob, field_name)
        if isinstance(value, str) and value:
            bundle.add([iw_hash(value)], prefer=prefer, target=target)
    return []


def apply(game, groups: dict, base_level: str, defs: list[WeaponDef], bundle=None) -> dict:
    """Apply a project's weapons to a map's groups. *groups*: 'weapons', 'projectiles', 'arms' ->
    parsed groups (changed in place); *bundle* (a bozkit.bundle.Bundle over the map's files)
    brings weapons of other levels. Returns {"aliases": {new hash: base hash}, "warnings": [...]}.
    """
    from . import resources

    warnings = []
    aliases = {}
    weapons_group = groups['weapons']
    base_gear = maps.gear(base_level)
    # 1. Weapons of other levels.
    for weapon in defs:
        if weapon.level and maps.gear(weapon.level) != base_gear:
            if bundle is None:
                raise WeaponError(f'weapon {weapon.name}: weapons of other maps need the game')
            warnings += _bring(bundle, weapon, groups)
    specs = _entity_specs(weapons_group)
    by_hash = {r.in_group_hash: r for r in specs.resources}
    # 2. New weapons: copies of their base under a new name.
    for weapon in defs:
        new_hash = _hash_of(weapon.name)
        base_hash = _hash_of(weapon.source)
        if new_hash == base_hash:
            continue
        if base_hash not in by_hash:
            raise WeaponError(f'weapon {weapon.name}: no weapon {weapon.source} to copy')
        if new_hash in by_hash:
            raise WeaponError(f'weapon {weapon.name}: the level already has a weapon by that name')
        spec = resources.decode_entity_spec(by_hash[base_hash].body)
        blob = _weapon_blob(spec)
        name_prop = _prop(blob, 'm_name')
        if name_prop is not None:
            from . import reflect
            reflect.set_typed_value(name_prop, new_hash)
        resource = copy.copy(by_hash[base_hash])
        resource.name_hash = new_hash if resource.name_hash is not None else None
        resource.in_group_hash = new_hash
        resource.body = resources.encode_entity_spec(spec)
        specs.resources.append(resource)
        by_hash[new_hash] = resource
        aliases[new_hash] = base_hash
    # 3. Field changes.
    for weapon in defs:
        if not weapon.fields:
            continue
        resource = by_hash.get(_hash_of(weapon.name))
        if resource is None:
            raise WeaponError(f'weapon {weapon.name} is not in the level')
        spec = resources.decode_entity_spec(resource.body)
        blob = _weapon_blob(spec)
        for key, value in weapon.fields.items():
            set_value(blob, key, value)
        resource.body = resources.encode_entity_spec(spec)
    # 4. Your own models and animations.
    for weapon in defs:
        if not (weapon.model and weapon.model.get('asset')) and not weapon.clips and not weapon.arms:
            continue
        resource = by_hash.get(_hash_of(weapon.name))
        if resource is None:
            raise WeaponError(f'weapon {weapon.name} is not in the level')
        apply_model(groups, weapon, resource)
    # 5. Sounds of their own: each in its own sequence (the base weapon keeps its sounds).
    shared = None
    for weapon in defs:
        if not weapon.sound_data:
            continue
        from . import group as group_module, sound
        if shared is None:
            shared = group_module.read_parsed(game.read, sound.SHARED_GROUP)
        resource = by_hash.get(_hash_of(weapon.name))
        if resource is None:
            raise WeaponError(f'weapon {weapon.name} is not in the level')
        spec = resources.decode_entity_spec(resource.body)
        blob = _weapon_blob(spec)
        for key, body in sorted(weapon.sound_data.items()):
            sequence = sound.add_weapon_sound(groups['weapons'], shared, weapon.name, key,
                                              int(value_or_default(blob, key) or 0), body)
            set_value(blob, key, sequence)
        resource.body = resources.encode_entity_spec(spec)
    # Weapons with a model of their own show it on wall buys (not their base's).
    own_models = {_hash_of(w.name) for w in defs if w.model and w.model.get('asset')}
    for name_hash in own_models:
        aliases.pop(name_hash, None)
    return {'aliases': aliases, 'warnings': warnings, 'own_models': own_models}


def attach_models(defs: list[WeaponDef], source: Path) -> None:
    """Load the assets the weapons use as their model (WeaponDef.model_data) and their own
    animations (WeaponDef.clips, bozkit.weapon_anim)."""
    from . import assets, sound, weapon_anim
    for weapon in defs:
        try:
            weapon.clips = weapon_anim.load_clips(source, weapon.name)
        except weapon_anim.WeaponAnimError as exc:
            raise WeaponError(f'weapon {weapon.name}: {exc}') from None
        weapon.sound_data = {}
        for key, name in weapon.sounds.items():
            if FIELD_BY_KEY.get(key) is None or FIELD_BY_KEY[key].kind != 'sound':
                raise WeaponError(f'weapon {weapon.name}: {key} is not a sound field')
            try:
                weapon.sound_data[key] = sound.encoded(source, name)
            except sound.SoundError as exc:
                raise WeaponError(f'weapon {weapon.name}: {exc}') from None
        name = weapon.model.get('asset') if weapon.model else None
        if not name:
            continue
        try:
            asset = assets.load_def(source, name)
            model, textures = assets.load_game(source, name)
        except assets.AssetError as exc:
            raise WeaponError(f'weapon {weapon.name}: {exc}') from None
        if asset.kind != 'weapon':
            raise WeaponError(f'weapon {weapon.name}: asset {name} is a prop (make it a weapon '
                              'in the Assets tab)')
        weapon.model_data = (model, textures)


def _model_refs(blob):
    """(property, role) for every model/skin reference of a weapon: role 'view', 'ads' or
    ('lod', n)."""
    from . import reflect  # noqa: F401
    out = []
    for prop_name, role in (('renderableAsset', 'view'), ('renderableAssetADS', 'ads')):
        prop = _prop(blob, prop_name)
        if prop is not None and prop.nested is not None:
            out += [(p, role) for p in prop.nested.properties
                    if p.name_hash in (iw_hash('model'), iw_hash('skin'))]
    lods = _prop(blob, 'LODS')
    if lods is not None and lods.nested is not None:
        number = 0

        def walk(nested):
            nonlocal number
            for p in nested.properties:
                if p.name_hash == iw_hash('model'):
                    out.append((p, ('lod', number)))
                elif p.name_hash == iw_hash('skin'):
                    out.append((p, ('lod', number)))
                    number += 1
                if p.nested is not None:
                    walk(p.nested)
                for element in p.elements or []:
                    walk(element)
        walk(lods.nested)
    return out


def _templates(parsed, view_model: int):
    """(the material the stock view model uses, a raw texture to copy headers from)."""
    from . import native
    materials = {r.in_group_hash: r.body for t in parsed.types()
                 if t.class_hash == iw_hash('CIwMaterial') for r in t.resources}
    models = {r.in_group_hash: r.body for t in parsed.types()
              if t.class_hash == iw_hash('CIwModel') for r in t.resources}
    material = None
    body = models.get(view_model, b'')
    from .blender_scene import _model_materials
    for mh in _model_materials(body, set(materials)):
        decoded = native.decode_material(materials[mh])
        if material is None or decoded.same_as_default:
            material = decoded
    if material is None and materials:
        material = native.decode_material(next(iter(materials.values())))
    texture = None
    for t in parsed.types():
        if t.class_hash not in TEXTURE_CLASSES:
            continue
        for r in t.resources:
            try:
                native.texture_layout(r.body)
            except ValueError:
                continue
            texture = r.body
            break
        if texture is not None:
            break
    return material, texture


def _resources_of(parsed, class_name: str) -> dict:
    return {r.in_group_hash: r for t in parsed.types() if t.class_hash == iw_hash(class_name)
            for r in t.resources}


def _put(parsed, class_name: str, value: int, body: bytes) -> None:
    """Add a resource to a group, or replace the one already there."""
    from . import group as group_module
    existing = _resources_of(parsed, class_name).get(value)
    if existing is not None:
        existing.body = body
    else:
        _add(parsed, iw_hash(class_name), group_module.Resource(value, value, body))


def _set_reference(blob, name: str, value) -> None:
    """Point a weapon's existing reference at another resource: a hash (skel) or a name
    (m_weaponAsm, m_armsAsm)."""
    from . import reflect
    prop = _prop(blob, name)
    if prop is None:
        raise WeaponError(f'the weapon has no {name}')
    if isinstance(value, str):
        reflect.set_typed_value(prop, value)
    else:
        prop.raw = struct.pack('<I', value)
        prop.nested = prop.elements = None


def _patch_offsets(body: bytes, changes: dict) -> bytes:
    out = bytearray(body)
    for offset, value in changes.items():
        struct.pack_into('<I', out, offset, value)
    return bytes(out)


def apply_model(groups: dict, weapon: WeaponDef, resource) -> None:
    """Put *weapon*'s own model (WeaponDef.model, attached: on its own skeleton) and its own
    animations (WeaponDef.clips) on its spec. *groups*: 'weapons' and 'arms' parsed groups."""
    from . import anim, resources, weapon_anim, weapon_model
    weapons_group, arms_group = groups['weapons'], groups.get('arms')
    spec = resources.decode_entity_spec(resource.body)
    blob = _weapon_blob(spec)
    skels = _resources_of(weapons_group, 'CIwAnimSkel')
    anims = _resources_of(weapons_group, 'CIwAnim')
    asms = _resources_of(weapons_group, 'CIsAnimStateMachine')
    stock_skel = get_value(blob, 'skel')
    if not stock_skel or stock_skel not in skels:
        raise WeaponError(f'weapon {weapon.name}: its base has no skeleton')
    stock_bones = anim.decode_skel(skels[stock_skel].body)
    gun_asm_name = get_value(blob, 'm_weaponAsm') or ''
    gun_asm = asms.get(iw_hash(gun_asm_name))
    clips = weapon.clips or {}
    asset = bool(weapon.model.get('asset')) if weapon.model else False
    fit = (weapon.model.get('fit') or {}) if asset else {}

    try:
        if asset:
            if weapon.model_data is None:
                raise WeaponError(f'weapon {weapon.name}: its model asset was not attached')
            model, textures = weapon.model_data
            names = weapon_anim.bone_names(model)
            own = weapon_anim.own_skeleton(model, fit)
            own_hash = iw_hash(f'{weapon.name}_skel')
            _put(weapons_group, 'CIwAnimSkel', own_hash, anim.encode_skel(own))
            refs = _model_refs(blob)
            view = next((int.from_bytes(p.raw[:4], 'little') for p, role in refs if role == 'view'), 0)
            material, texture = _templates(weapons_group, view)
            if material is None or texture is None:
                raise WeaponError(f'weapon {weapon.name}: no material or raw texture to copy from')
            built = weapon_model.build(weapon.name, model, textures, fit, {n: n for n in names}, own,
                                       own_hash, material, texture)
            for class_name, value, body in built.resources:
                _put(weapons_group, class_name, value, body)
            for prop, role in refs:
                value = built.view if role == 'view' else built.ads if role == 'ads' else \
                    built.lods[min(role[1], len(built.lods) - 1)]
                prop.raw = struct.pack('<I', value)     # a resource reference: its hash
            _set_reference(blob, 'skel', own_hash)
            follow = weapon_anim.follow_list(model, stock_bones, weapon.model.get('bones') or {})
            gun_bones, gun_skel = own, own_hash

            def gun_keys(keys):
                return keys
        else:
            gun_bones, gun_skel = stock_bones, stock_skel

            def gun_keys(keys):
                return {int(k): v for k, v in keys.items() if str(k).isdigit()}

        # Your animations' lengths: the game ends a state (a reload: done) when its length is up.
        def length_ms(entry):
            frames = int(entry.get('length') or 0) or max(
                (c.frames[-1][0] for c in (entry.get('arms'), entry.get('gun')) if c and c.frames),
                default=0)
            return round(frames * 1000 / weapon_anim.FPS)
        lengths = {state: length_ms(entry) for state, entry in clips.items()
                   if entry.get('arms') or entry.get('gun')}

        # The gun's animations: all of them on its own skeleton; your clips on either.
        mine_gun = {state: entry['gun'] for state, entry in clips.items() if 'gun' in entry}
        if gun_asm is not None and (asset or mine_gun):
            changes, made = {}, {}
            for state, at, second in anim.asm_anim_offsets(gun_asm.body):
                for offset, is_primary in ((at, True), (second, False)):
                    source_hash = struct.unpack_from('<I', gun_asm.body, offset)[0]
                    stock = anims.get(source_hash)
                    clip = mine_gun.get(state) if is_primary else None
                    if stock is None and clip is None:
                        continue
                    if clip is None and not asset:
                        continue          # stock skeleton, no clip: the stock animation stays
                    stock_anim = anim.decode_anim(stock.body) if stock is not None else None
                    template = stock_anim.keyframes[0].header if stock_anim and stock_anim.keyframes else None
                    if clip is not None:
                        key = iw_hash(f'{weapon.name}_gun_{state:08x}')
                        game = weapon_anim.gun_clip_to_game(clip, model, fit) if asset else clip
                        body = weapon_anim.encode_clip(game, gun_skel, gun_bones,
                                                       gun_keys if not asset else (lambda k: k), template)
                    else:
                        key = iw_hash(f'{weapon.name}_gun_{source_hash:08x}')
                        if key not in made:
                            moved = weapon_anim.retarget(stock_bones, stock_anim, own, follow)
                            made[key] = weapon_anim.encode_clip(moved, gun_skel, gun_bones,
                                                                lambda k: k, template)
                        body = made[key]
                    _put(weapons_group, 'CIwAnim', key, body)
                    changes[offset] = key
            changes.update(anim.asm_lengths(gun_asm.body, lengths))
            name = f'{weapon.name}_gun'
            _put(weapons_group, 'CIsAnimStateMachine', iw_hash(name), _patch_offsets(gun_asm.body, changes))
            _set_reference(blob, 'm_weaponAsm', name)

        # The arms: your clips and where the arms sit, in a copy of the arms' state machine.
        mine_arms = {state: entry['arms'] for state, entry in clips.items() if 'arms' in entry}
        arms_asm_name = get_value(blob, 'm_armsAsm') or ''
        offset = weapon_anim.arms_offset(weapon.arms)
        if (mine_arms or offset is not None) and arms_group is not None:
            arm_asms = _resources_of(arms_group, 'CIsAnimStateMachine')
            arm_anims = _resources_of(arms_group, 'CIwAnim')
            arm_skels = _resources_of(arms_group, 'CIwAnimSkel')
            arms_asm = arm_asms.get(iw_hash(arms_asm_name))
            if arms_asm is None or not arm_skels:
                raise WeaponError(f'weapon {weapon.name}: no arms state machine {arms_asm_name}')
            arm_skel_hash, arm_skel = next(iter(arm_skels.items()))
            arm_bones = anim.decode_skel(arm_skel.body)
            changes = {}
            for state, at, _second in anim.asm_anim_offsets(arms_asm.body):
                clip = mine_arms.get(state)
                source_hash = struct.unpack_from('<I', arms_asm.body, at)[0]
                stock = arm_anims.get(source_hash)
                stock_anim = anim.decode_anim(stock.body) if stock is not None else None
                if clip is None:
                    if offset is None or stock_anim is None:
                        continue
                    stock_clip = weapon_anim.stock_clip(stock_anim, arm_bones)
                    clip = weapon_anim.Clip([(f, {str(i): v for i, v in k.items()})
                                             for f, k in stock_clip.frames])
                if offset is not None:
                    clip = weapon_anim.offset_arms(clip, arm_bones, offset)
                template = stock_anim.keyframes[0].header if stock_anim and stock_anim.keyframes else None
                key = iw_hash(f'{weapon.name}_arms_{state:08x}')
                body = weapon_anim.encode_clip(clip, arm_skel_hash, arm_bones,
                                               lambda k: {int(i): v for i, v in k.items()
                                                          if str(i).isdigit()}, template)
                _put(arms_group, 'CIwAnim', key, body)
                changes[at] = key
            changes.update(anim.asm_lengths(arms_asm.body, lengths))
            name = f'{weapon.name}_arms'
            _put(arms_group, 'CIsAnimStateMachine', iw_hash(name), _patch_offsets(arms_asm.body, changes))
            _set_reference(blob, 'm_armsAsm', name)
    except (weapon_model.WeaponModelError, weapon_anim.WeaponAnimError, anim.AnimError,
            ValueError) as exc:
        raise WeaponError(f'weapon {weapon.name}: {exc}') from None
    resource.body = resources.encode_entity_spec(spec)


def runtime(defs: list[WeaponDef], index: list[str]) -> list[dict]:
    """What boz.weapons needs at runtime: the project's weapons by name, with scripts and the
    names prompts show (a wall buy asks the game's text for "<weapon>_S_WEAPON")."""
    by_name = {d.name: d for d in defs}
    out = []
    for name in dict.fromkeys(list(index) + [d.name for d in defs]):
        weapon = by_name.get(name)
        entry = {'name': name, 'script': _module(weapon.script) if weapon else ''}
        if weapon and weapon.display:
            entry['display'] = weapon.display
        out.append(entry)
    return out


def _module(script: str) -> str:
    if not script:
        return ''
    text = script[:-4] if script.endswith('.lua') else script
    return text.replace('/', '.').replace('\\', '.')
