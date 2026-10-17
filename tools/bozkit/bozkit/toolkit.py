"""The toolkit: one curated piece for each thing a map needs (each perk machine, Pack-a-Punch,
the mystery box, wall buys, doors, spawns, ...), with the settings a creator changes.

A piece is not tied to one shipped entity: it resolves to a working entity of the project's
base level (its own statics), and falls back to the shared ``ingame`` templates when the base
level has none. Settings are reflected fields of the entity's components; the compiler writes
the creator's values over the entity's own (bozkit.world Placement.fields).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import blender_scene as scene
from . import group, levels, reflect, resources
from . import maps
from .hashing import iw_hash

INGAME = 'ingame/ingame.group.bin'
POWER_SWITCH = 'powerSwitch'
# Perk machines told to work without power point their power switch here; the standard
# library's boz.world powers them when they start (as the game does Quick Revive in solo).
NO_POWER = 'boz_no_power'
WEAPON_FIELD = 'boz.weapon'
CHALK_FIELD = 'boz.chalk'   # editor-only: '' automatic, 'none', or an image in the project


@dataclass(frozen=True)
class Setting:
    key: str          # "Component.field"
    label: str
    kind: str         # int, float, bool, seconds (a ms field shown in seconds), power (needs
                      # the power switch), name (a hashed name), weapon, chalk, weapons (a list
                      # of weapon names: std::list<unsigned int>, u32 count + hashes)
    description: str = ''
    default: object = None   # when the entity leaves the field at the game's default


@dataclass(frozen=True)
class Piece:
    key: str
    label: str
    catalog: str
    category: str                      # blender_scene._category of the entity
    words: tuple[str, ...] = ()        # all must appear in the entity's label (lower case)
    spawn_type: str = ''               # zombie spawn points: the spawnType name
    exclude: tuple[str, ...] = ()      # component names the entity must not have
    require: tuple[str, ...] = ()      # component names the entity must have
    settings: tuple[Setting, ...] = ()
    description: str = ''
    model: bool | None = None          # True: must draw a model; False: must not; None: either


def _cost(component: str, field_name: str = 'm_Cost') -> Setting:
    return Setting(f'{component}.{field_name}', 'Cost', 'int', 'Points it costs')


def _reach(default: float = 200.0) -> Setting:
    return Setting('CPOI.m_MaxDistance', 'Use distance (cm)', 'float',
                   'How close players must be to use it', default)


def _power(component: str) -> Setting:
    return Setting(f'{component}.powerSwitch', 'Needs power', 'power',
                   'On: works once the power switch is turned on. Off: works from the start')


PERKS = (('juggernog', 'Juggernog', 'jugg'), ('quick_revive', 'Quick Revive', 'revive'),
         ('double_tap', 'Double Tap', 'double'), ('speed_cola', 'Speed Cola', 'speed'),
         ('stamin_up', 'Stamin-Up', 'stamin'), ('phd_flopper', 'PhD Flopper', 'phd'),
         ('deadshot', 'Deadshot', 'deadshot'))

PIECES = [
    *(Piece(key, label, 'Game prefabs/Machines', 'perk', (word,),
            settings=(_cost('CPerk', 'm_perkSinglePCost'),
                      Setting('CPerk.m_perkMultiPCost', 'Co-op cost', 'int',
                              'Points it costs in a co-op game', 1500),
                      _power('CPerk'), _reach(300.0)),
            description=f'{label} perk machine') for key, label, word in PERKS),
    Piece('pack_a_punch', 'Pack-a-Punch', 'Game prefabs/Machines', 'pack_a_punch',
          settings=(_cost('CPackAPunch'), _power('CPackAPunch'), _reach(300.0)),
          description='Upgrades the weapon a player puts in'),
    Piece('mystery_box', 'Mystery box', 'Game prefabs/Machines', 'mystery_box',
          settings=(_cost('CMysteryBox'),
                    Setting('CMysteryBox.m_FireSaleCost', 'Fire sale cost', 'int',
                            'Points it costs during a Fire Sale', 10),
                    Setting('CMysteryBox.m_MinWeapons', 'Uses before it moves: at least', 'int',
                            'The box moves after a random number of uses between these', 4),
                    Setting('CMysteryBox.m_MaxWeapons', 'Uses before it moves: at most', 'int',
                            '', 10),
                    Setting('CMysteryBox.m_Weapons', 'Weapon pool', 'weapons',
                            'The weapons the box rolls (shipped boxes have 17 or 18)')),
          description='A mystery box location (the game picks the active one)'),
    Piece('power_switch', 'Power switch', 'Game prefabs/Machines', 'power', ('power',),
          settings=(Setting('CPowerSwitch.StartEnabled', 'Usable from the start', 'bool',
                            'Off: players cannot pull it until a script or the game enables it '
                            '(Ascension\'s launch switch)', True),),
          description='Turns on everything that needs power'),
    Piece('wall_buy', 'Wall buy', 'Game prefabs/Buying', 'wall_buy',
          settings=(Setting(WEAPON_FIELD, 'Weapon', 'weapon', 'The weapon players buy here'),
                    _cost('CWeaponChalkOutline'),
                    Setting('CWeaponChalkOutline.m_ammoCost', 'Ammo cost', 'int',
                            'Points a refill costs when players already have the weapon', 0),
                    Setting('CWeaponChalkOutline.m_upgradedAmmoCost', 'Upgraded ammo cost', 'int',
                            'Points a refill costs for the Pack-a-Punched weapon', 0),
                    Setting(CHALK_FIELD, 'Chalk', 'chalk',
                            'The chalk drawing on the wall: the weapon\'s own, one drawn from its '
                            'model, your image, or none')),
          description='Where players buy a weapon (any weapon of the level)'),
    Piece('trap', 'Trap', 'Game prefabs/Defence', 'trap', exclude=('CTrapSwitch',),
          settings=(Setting('CTrap.m_ActivePeriodMS', 'Runs for (s)', 'seconds',
                            'How long it stays on once bought'),
                    Setting('CTrap.m_CoolDownPeriodMS', 'Cool-down (s)', 'seconds',
                            'How long before it can be bought again'),
                    Setting('CTrap.m_PlayerDamage', 'Player damage', 'int',
                            'Damage to players who walk into it')),
          description='A trap a trap switch turns on'),
    Piece('trap_switch', 'Trap switch', 'Game prefabs/Defence', 'trap', require=('CTrapSwitch',),
          settings=(_cost('CTrapSwitch'), _power('CTrapSwitch'), _reach(260.0)),
          description='The switch players pay to run a trap'),
    Piece('player_spawn', 'Player spawn', 'Level markers/Spawns', 'spawn', ('spawn_player',),
          description='Where a player starts (up to four)'),
    *(Piece(key, label, 'Level markers/Spawns', 'spawn', spawn_type=kind,
            settings=(Setting('CSpawnPoint.m_StartActive', 'Active from the start', 'bool',
                              'On: used from the first round wherever players are. Off: used '
                              'once players reach its area', False),),
            description=description)
      for key, label, kind, description in (
          ('zombie_window', 'Zombie spawn: window', 'WINDOWS',
           'Zombies climb in through a window here'),
          ('zombie_crawler', 'Zombie spawn: from above', 'hole',
           'Zombies drop in from a hole here'),
          ('dog_spawn', 'Dog spawn', 'LIGHTNING', 'Hellhounds appear here in dog rounds'))),
    Piece('jump_point', 'Jump point', 'Level markers/Jump points', 'jump',
          description='Where zombies jump across a gap'),
    Piece('sound_emitter', 'Sound emitter', 'Level markers/Sound', 'sound', model=False,
          settings=(Setting('CSoundEmitter.soundName', 'Sound', 'name',
                            'The name of the sound it plays'),
                    Setting('CSoundEmitter.StartEnabled', 'Plays from the start', 'bool',
                            'Off: silent until a script or the game starts it', True)),
          description='Plays a sound at this spot'),
]
BY_KEY = {piece.key: piece for piece in PIECES}
WALL_BUY_PREFIX = 'wall_'   # older maps: one piece per shipped wall buy
VARIANTS = {   # pieces with one design per distinct model in the game's levels
    'door': ('Door', 'Game prefabs/Doors',
             (_cost('CDoor'), _power('CDoor'),
              Setting('CDoor.m_HideAfterActivate', 'Disappears when opened', 'bool',
                      'On: the model vanishes once bought (debris). Off: it plays its opening '
                      'animation and stays', False)),
             'A door or debris players pay to open'),
    'barricade': ('Window barricade', 'Game prefabs/Barricades',
                  (Setting('CBarricade.m_StartBroken', 'Starts broken', 'bool',
                           'On: the boards start torn down', False),),
                  'Boards zombies tear down and players rebuild'),
}
# Wall buys: which weapon a chalk outline sells is not in its reflected fields (it is not the
# weapon class m_weaponType, nor the outline's model), so each shipped wall buy is its own piece.
WALL_BUYS = ('Olympia', 'M14', 'M16', 'MP40', 'MP5K', 'PM63', 'MPL', 'AK74u', 'AK47U', 'Stakeout',
             'Claymores', 'Claymore', 'FragGrenade', 'Semtex', 'BowieKnife', 'Sickle')


def wall_buy_piece(key: str) -> Piece:
    weapon = key[len(WALL_BUY_PREFIX):]
    label = next((name for name in WALL_BUYS if name.lower() == weapon), weapon)
    return Piece(key, f'Wall buy: {label}', 'Game prefabs/Buying', 'wall_buy',
                 (f'{weapon}_wallweapon',), settings=(_cost('CWeaponChalkOutline'),),
                 description=f'A chalk outline where players buy the {label}')


def variant_piece(key: str, label: str = '') -> Piece:
    category, _, _value = key.partition(':')
    title, catalog, settings, description = VARIANTS[category]
    return Piece(key, label or title, catalog, category, settings=settings,
                 description=description)


def piece(key: str) -> Piece:
    if key in BY_KEY:
        return BY_KEY[key]
    if key.partition(':')[0] in VARIANTS:
        return variant_piece(key)
    if key.startswith(WALL_BUY_PREFIX):
        return wall_buy_piece(key)
    raise KeyError(key)


def all_pieces(pack) -> list[Piece]:
    """Every piece: the fixed ones, and a door and barricade design for each distinct model."""
    variants, seen = [], set()
    for base in maps.SHIPPED:
        for item, spec, category, own in _entities(pack, f'levels/{base}/{base}_statics.group.bin'):
            if category not in VARIANTS:
                continue
            model = scene._model_reference(spec)
            if not model or (category, model) in seen:
                continue
            seen.add((category, model))
            label = f'{VARIANTS[category][0]}: {own}' if own else VARIANTS[category][0]
            variants.append(variant_piece(f'{category}:0x{item.in_group_hash:08x}', label))
    return PIECES + variants


def _entities(pack, path: str):
    """(resource, spec, category, own name) of a group's entity specs."""
    try:
        parsed = group.parse(pack.read(path))
    except KeyError:
        return
    for resource_type in parsed.types():
        if resource_type.class_hash != levels.ENTITY_SPEC:
            continue
        for item in resource_type.resources:
            try:
                spec = resources.decode_entity_spec(item.body)
            except (ValueError, struct.error):
                continue
            category = scene._category(scene._component_names(spec))
            own = scene._blob_value(scene._component(spec, 'CIsNamed'), 'name', '')
            yield item, spec, category, own if isinstance(own, str) else ''


@dataclass
class Resolved:
    piece: Piece
    group: str                         # pack path of the entity's group
    hash: int
    name: str                          # what the world calls it (a name or 0x hash)
    model: int | None = None
    defaults: dict = field(default_factory=dict)   # setting key -> current value


def _spawn_type(spec) -> int | None:
    point = levels._component(spec, 'CSpawnPoint')
    prop = levels._blob_prop(point.blob, 'spawnType') if point and point.blob else None
    return struct.unpack_from('<I', prop.raw)[0] if prop is not None and len(prop.raw) >= 4 else None


def _matches(piece: Piece, spec, names: list[str], label: str, entity_name: str) -> bool:
    if scene._category(names) != piece.category:
        return False
    if any(name in names for name in piece.exclude):
        return False
    if any(name not in names for name in piece.require):
        return False
    text = f'{label} {entity_name}'.lower()
    if any(word not in text for word in piece.words):
        return False
    if piece.spawn_type and _spawn_type(spec) != iw_hash(piece.spawn_type):
        return False
    if piece.model is not None and (scene._model_reference(spec) is not None) != piece.model:
        return False
    if piece.category == 'spawn' and not piece.spawn_type and _spawn_type(spec) is not None \
            and 'spawn_player' not in text:
        return False
    return True


def _value(spec, key: str):
    component_name, _, field_name = key.partition('.')
    component = levels._component(spec, component_name)
    prop = levels._blob_prop(component.blob, field_name) if component and component.blob else None
    return reflect.typed_value(prop) if prop is not None else None


def hash_list(raw: bytes) -> list[int]:
    """A std::list<unsigned int> value: u32 count, then the values."""
    if len(raw) < 4:
        return []
    count = struct.unpack_from('<I', raw)[0]
    if len(raw) != 4 + count * 4:
        return []
    return list(struct.unpack_from(f'<{count}I', raw, 4))


def encode_hash_list(values) -> bytes:
    return struct.pack('<I', len(values)) + b''.join(struct.pack('<I', v) for v in values)


def _list_value(spec, key: str) -> list[int] | None:
    component_name, _, field_name = key.partition('.')
    component = levels._component(spec, component_name)
    prop = levels._blob_prop(component.blob, field_name) if component and component.blob else None
    return hash_list(prop.raw) if prop is not None else None


def resolve(pack, base: str, key: str, names: dict[int, str] | None = None) -> Resolved | None:
    """The entity a piece places on *base*: the base level's own, else another level's (the
    compiler repacks what it uses), else ingame's template."""
    piece_ = piece(key)
    names = names or {}
    statics = f'levels/{base}/{base}_statics.group.bin'
    if key == 'player_spawn':
        # Players spawn at the entities named spawn_player_1 to 4 (the editor picks a free one).
        wanted = iw_hash('spawn_player_1')
        if any(item.in_group_hash == wanted for item, _s, _c, _o in _entities(pack, statics)):
            return Resolved(piece_, '', wanted, 'spawn_player_1')
        return None
    fixed = int(key.partition(':')[2], 16) if ':' in key else None
    paths = [statics] + [f'levels/{other}/{other}_statics.group.bin' for other in maps.SHIPPED
                         if other != base]
    if not key.startswith(WALL_BUY_PREFIX) and fixed is None:
        paths.append(INGAME)
    for path in paths:
        for item, spec, category, own in _entities(pack, path):
            if fixed is not None:
                if item.in_group_hash != fixed:
                    continue
            else:
                try:
                    label, _details = scene._describe(spec, category)
                except (ValueError, KeyError, TypeError, struct.error):
                    continue
                entity_name = own or names.get(item.in_group_hash, '')
                if not _matches(piece_, spec, scene._component_names(spec), label, entity_name):
                    continue
            known = names.get(item.in_group_hash, '')
            name = known if known and iw_hash(known) == item.in_group_hash \
                else f'0x{item.in_group_hash:08x}'
            defaults = _defaults(piece_, spec, names)
            defaults.update({setting.key: '' for setting in piece_.settings
                             if setting.key == CHALK_FIELD})
            return Resolved(piece_, '' if path == statics else path, item.in_group_hash, name,
                            scene._model_reference(spec), defaults)
    return None


def _weapon_of(spec, names: dict[int, str]):
    """The weapon a wall buy sells: its "model" child's asset name."""
    for _cls, _reserved, child in spec.children:
        renderable = levels._component(child, 'CIsRenderableModel')
        if renderable is None or renderable.blob is None:
            continue
        for element in levels._blob_prop(renderable.blob, 'assets').elements or ():
            for prop in element.properties:
                if prop.name_hash in (iw_hash('name'), iw_hash('Name')):
                    return reflect.typed_value(prop)
    return None


def field_value(setting: Setting, value):
    """A setting's value as bozkit.world Placement.fields stores it (not for power settings:
    see fields_for)."""
    if setting.kind == 'int':
        return int(value)
    if setting.kind == 'seconds':
        return int(round(float(value) * 1000))
    if setting.kind == 'float':
        return float(value)
    if setting.kind == 'bool':
        return bool(value)
    if setting.kind == 'weapons':
        items = value if isinstance(value, (list, tuple)) else str(value).split(',')
        return [str(item).strip() for item in items if str(item).strip()]
    return str(value)


def fields_for(setting: Setting, value) -> dict:
    """The Placement.fields a setting's value writes (none for the chalk, which the compiler
    reads from the settings)."""
    if setting.kind == 'chalk':
        return {}
    if setting.kind == 'weapons' and not field_value(setting, value):
        return {}   # no pool chosen: the box keeps the game's
    return _fields_for(setting, value)


def _fields_for(setting: Setting, value) -> dict:
    """The Placement.fields a setting's value writes. "Needs power" off means the machine works
    from the start: perks are powered by the standard library (boz.world), Pack-a-Punch has a
    flag for it, and doors and trap switches without a power switch need none. On leaves the
    game's own link to the power switch."""
    if setting.kind != 'power':
        return {setting.key: field_value(setting, value)}
    if value:
        return {}
    component = setting.key.partition('.')[0]
    if component == 'CPerk':
        return {setting.key: NO_POWER}
    if component == 'CPackAPunch':
        return {setting.key: 0, 'CPackAPunch.m_HasPower': True}
    return {setting.key: 0}


CATEGORY_PIECES = {'perk': 'juggernog', 'pack_a_punch': 'pack_a_punch', 'mystery_box': 'mystery_box',
                   'wall_buy': 'wall_buy', 'trap': 'trap', 'sound': 'sound_emitter',
                   'power': 'power_switch'}


def settings_for(spec, names: dict[int, str] | None = None) -> tuple[str, dict]:
    """(piece key, settings as the panel shows them) for an existing entity of a level, by what
    it is: a shipped perk shows the perk settings, a door the door settings, and so on."""
    names = names or {}
    category = scene._category(scene._component_names(spec))
    if category == 'door':
        key = 'door:0x00000000'
    elif category == 'trap' and levels._component(spec, 'CTrapSwitch') is not None:
        key = 'trap_switch'
    else:
        key = CATEGORY_PIECES.get(category, '')
    if not key:
        return '', {}
    return key, _defaults(piece(key), spec, names)


def _defaults(piece_: Piece, spec, names: dict[int, str]) -> dict:
    """A piece's settings as the panel shows them, read from the entity's own fields (the chalk
    is the editor's own setting: shipped wall buys have theirs painted in the rooms)."""
    values = {}
    for setting in piece_.settings:
        if setting.key == CHALK_FIELD:
            continue
        if setting.kind == 'weapons':
            found = _list_value(spec, setting.key)
            if found is not None:
                values[setting.key] = ','.join(names.get(h, f'0x{h:08x}') for h in found)
            continue
        value = _weapon_of(spec, names) if setting.key == WEAPON_FIELD else _value(spec, setting.key)
        if value is None:
            value = setting.default
        if value is None:
            continue
        if setting.kind == 'seconds':
            value = round(value / 1000.0, 3)
        elif setting.kind == 'power':
            value = bool(value)
        elif setting.kind in ('name', 'weapon') and isinstance(value, int):
            value = names.get(value, f'0x{value:08x}')
        values[setting.key] = value
    return values
