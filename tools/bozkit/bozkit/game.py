"""A map project's game rules (the Game tab): level info, rounds, special rounds, zombie types and
the economy, and the build step that puts them in the map.

How the game runs rounds (Ghidra: CLevelManager::StartFirstWave, CWaveManager::StartWave and
OnEvent, the CWave* classes):

- The level's ``CLevel`` lists its first round for single player by difficulty
  (``m_StartingWavesSP``: easy, normal, hard; the level manager's difficulty +0x20c picks one)
  and for co-op by player count (``m_StartingWavesMP``: 2, 3, 4 players). No entry: ``wave1``.
- Each round is a ``CWave`` resource (found by name, ``Wave_Find``); its ``m_NextWave`` names
  the next. A ``CWaveRepeatable`` with no next round repeats forever, growing each round:
  value x multiplier ^ (round - m_StartingWave) once the round is past m_StartingWave (zombie
  count, powered zombie count, max at once and spawn interval). Its health is not its data: the
  game hard-codes 10 x round^2 - 150 (CWaveRepeatable::GetZombieHealth); a map can ask boz.game
  to use the data instead (``repeat_health = "grow"``: health x health multiplier ^ (round -
  m_StartingWave)).
- Every zombie's health is then scaled by the difficulty (ZombieEasyHealthMultiplier 0.5,
  ZombieNormalHealthMultiplier and ZombieHardHealthMultiplier 1.0); powered zombies by the round's
  powered health multiplier.
- Special rounds (``CWaveSpeciality``: dog rounds; ``CWaveMonkey``: Ascension's space monkeys)
  are not in the chain. Every one whose ``m_waveType`` matches the game (0-2 the single player
  difficulty, 3-5 co-op with 2-4 players) is a candidate: the game runs them in order (each
  ``m_repeatTimes`` times), between ``m_minNormalWavesInterval`` and
  ``m_maxNormalWavesInterval`` normal rounds after the last one, with ``m_chance`` percent each
  round in between.

The economy is the game's console variables (read when a level starts: points at the start, drop
rates, power-up times; set by boz.game on this map only) and its score table (``CScoreConfig``
``score_table`` in the shared group, points per action; the ScoreConfigName cvar picks it, so a map
ships its own copy).

Project file: ``source/game.json``. Absent sections keep the base level's own data.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

from . import group, reflect, resources
from .hashing import iw_hash

WAVE = iw_hash('CWave')
LEVEL = iw_hash('CLevel')
SCORE_CONFIG = iw_hash('CScoreConfig')
STRING = iw_hash('CResolutionSpecificString')

CHAINS = [('easy', 'Single player, easy'), ('normal', 'Single player, normal'),
          ('hard', 'Single player, hard'), ('coop2', 'Co-op, 2 players'),
          ('coop3', 'Co-op, 3 players'), ('coop4', 'Co-op, 4 players')]
CHAIN_KEYS = [key for key, _ in CHAINS]
WAVE_CLASSES = ('CWave', 'CWaveRepeatable', 'CWaveSpeciality', 'CWaveMonkey')
SPECIAL_CLASSES = ('CWaveSpeciality', 'CWaveMonkey')


class GameError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    name: str
    declared: str      # the class that adds it (it applies to that class and its subclasses)
    type: str          # as the game stores it
    default: object    # the constructor's value (used when a resource leaves it out)
    label: str
    unit: str
    help: str


# Every reflected wave field, with the constructor defaults (CWave::CWave, ...).
FIELDS = [
    Field('m_ZombieCount', 'CWave', 'unsigned int', 0, 'Zombies', 'zombies',
          'How many zombies the round has (before power: see Powered zombies).'),
    Field('m_ZombieHealth', 'CWave', 'unsigned int', 100, 'Health', 'hit points',
          'Each zombie\'s health (an easy game halves it). On a repeating round only with '
          '"Health grows by the multiplier".'),
    Field('m_MaxActive', 'CWave', 'unsigned int', 0, 'At once', 'zombies',
          'The most zombies alive at the same time.'),
    Field('m_StartingZombies', 'CWave', 'unsigned int', 0, 'Spawn at start', 'zombies',
          'Zombies that spawn as soon as the round starts.'),
    Field('m_ZombieWalk', 'CWave', 'float', 0.25, 'Walkers', 'share (0-1)',
          'Share of the zombies that walk.'),
    Field('m_ZombieWalkFast', 'CWave', 'float', 0.25, 'Fast walkers', 'share (0-1)',
          'Share of the zombies that walk fast.'),
    Field('m_ZombieRun', 'CWave', 'float', 0.25, 'Runners', 'share (0-1)',
          'Share of the zombies that run.'),
    Field('m_ZombieSprint', 'CWave', 'float', 0.25, 'Sprinters', 'share (0-1)',
          'Share of the zombies that sprint.'),
    Field('m_TimeOut', 'CWave', 'unsigned int', 0, 'Spawn interval', 'ms',
          'Time between zombie spawns.'),
    Field('m_WaveTimeout', 'CWave', 'unsigned int', 0, 'Break after', 'ms',
          'Time from the round\'s end to the next round.'),
    Field('m_StartingTimer', 'CWave', 'unsigned int', 1000, 'Start delay', 'ms',
          'Time from the round\'s start to its first spawn.'),
    Field('m_ZombieType', 'CWave', 'unsigned int', 0, 'Zombie type', 'entity name',
          'The entity that spawns (empty: the map\'s ordinary zombie).'),
    Field('m_PoweredZombieType', 'CWave', 'unsigned int', 0, 'Powered zombie type', 'entity name',
          'Extra zombies once the power is on (Kino\'s crawlers after the power).'),
    Field('m_PoweredZombieCount', 'CWave', 'unsigned int', 0, 'Powered zombies', 'zombies',
          'How many extra zombies the round has once the power is on.'),
    Field('m_PoweredZombieHealthMult', 'CWave', 'float', 1.0, 'Powered health', 'x health',
          'Health of the powered zombies, as a multiple of the round\'s.'),
    Field('m_FogConfig', 'CWave', 'unsigned int', 0, 'Fog', 'fog config name',
          'The fog the round sets (dog rounds use a thick one; empty: unchanged).'),
    Field('m_ZombieCountMultiplier', 'CWaveRepeatable', 'float', 1.0, 'Zombies x', 'per round',
          'Each later round has this many times the zombies.'),
    Field('m_PoweredZombieCountMultiplier', 'CWaveRepeatable', 'float', 1.0, 'Powered zombies x',
          'per round', 'Each later round has this many times the powered zombies.'),
    Field('m_MaxActiveMultiplier', 'CWaveRepeatable', 'float', 1.0, 'At once x', 'per round',
          'Each later round allows this many times the zombies at once.'),
    Field('m_ZombieHealthMultiplier', 'CWaveRepeatable', 'float', 1.0, 'Health x', 'per round',
          'Each later round has this many times the health (only with "Health grows by the '
          'multiplier"; the game otherwise uses 10 x round^2 - 150 on repeating rounds).'),
    Field('m_TimeOutMultiplier', 'CWaveRepeatable', 'float', 1.0, 'Spawn interval x', 'per round',
          'Each later round has this many times the spawn interval (below 1: faster spawns).'),
    Field('m_StartingWave', 'CWaveRepeatable', 'unsigned int', 1, 'Grows after round', 'round',
          'The multipliers apply from the round after this one.'),
    Field('m_ZombieTypes', 'CWaveSpeciality', 'std::vector<unsigned int>', (), 'Zombie types',
          'entity names', 'What spawns (dogs: zombie_dog, zombie_dog_flaming).'),
    Field('m_healthBase', 'CWaveSpeciality', 'std::vector<unsigned int>', (), 'Health',
          'hit points', 'Health of what spawns.'),
    Field('m_players2ZombieNumber', 'CWaveSpeciality', 'std::vector<unsigned int>', (),
          'Count by players', 'zombies for 1, 2, 3, 4 players', 'How many spawn.'),
    Field('m_repeatTimes', 'CWaveSpeciality', 'unsigned int', 1, 'Times', 'rounds',
          'How many special rounds this one is before the next special one takes over.'),
    Field('m_minNormalWavesInterval', 'CWaveSpeciality', 'unsigned int', 3, 'At least', 'rounds',
          'Normal rounds at least before it (since the last special round).'),
    Field('m_maxNormalWavesInterval', 'CWaveSpeciality', 'unsigned int', 5, 'At most', 'rounds',
          'Normal rounds at most before it.'),
    Field('m_chance', 'CWaveSpeciality', 'unsigned int', 50, 'Chance', '% per round',
          'The chance each round between at least and at most.'),
    Field('m_waveType', 'CWaveSpeciality', 'CParsableEnumManager::SpecialityWaveType', 1, 'For',
          'game', 'Which game it is for (0-2 easy/normal/hard, 3-5 co-op 2-4 players).'),
    Field('m_HellhoundWave', 'CWaveSpeciality', 'bool', False, 'Dog round', '',
          'Plays the dog round music and effects.'),
    Field('m_monkeyLanderHash', 'CWaveMonkey', 'unsigned int', 0, 'Lander', 'entity name',
          'The lander the space monkeys arrive in.'),
]
FIELD = {f.name: f for f in FIELDS}
_PARENT = {'CWave': None, 'CWaveRepeatable': 'CWave', 'CWaveSpeciality': 'CWaveRepeatable',
           'CWaveMonkey': 'CWaveSpeciality'}


def fields_of(class_name: str) -> list[Field]:
    """The fields a wave class has (its own and inherited), in the order above."""
    chain, c = set(), class_name
    while c:
        chain.add(c)
        c = _PARENT[c]
    return [f for f in FIELDS if f.declared in chain]


# Economy: console variables the Game tab sets (name: label, unit, help, game default).
CVARS = {
    'StartingScore': ('Points at start', 'points', 'Points every player starts with.', 500),
    'PlayerDownScorePenalty': ('Points lost when down', 'share (0-1)',
                               'Share of a player\'s points lost when downed.', 0.05),
    'PickupPointsThreshold': ('Points between drops', 'points',
                              'Points the players earn before another power-up can drop.', 1000),
    'PickupKillThreshold': ('Kills between drops', 'kills',
                            'Kills before another power-up can drop (0: off).', 0),
    'PickupDropOnDeathProbability': ('Drop chance', '% per kill',
                                     'Chance a killed zombie drops a power-up once one can.', 2),
    'MaxPickupsPerWave': ('Drops per round', 'power-ups', 'The most power-ups a round drops.', 4),
    'DoublePointsTime': ('Double points', 'ms', 'How long double points lasts.', 30000),
    'InstaKillTime': ('Insta-kill', 'ms', 'How long insta-kill lasts.', 30000),
    'FireSaleTime': ('Fire sale', 'ms', 'How long a fire sale lasts.', 20000),
    'DeathMachineTime': ('Death machine', 'ms', 'How long the death machine lasts.', 30000),
    'MTXReviveCost': ('Self revive', 'points', 'Cost of the self revive.', 1000),
    'baseZombieHealth': ('Base zombie health', 'hit points',
                         'Health the zombie spawners start from.', 20),
    'maxSpawnedZombies': ('Zombies alive at most', 'zombies',
                          'Hard limit on zombies alive at once (all rounds).', 32),
    'EndWaveGrenades': ('Grenades per round', 'grenades',
                        'Grenades each player gets back at the end of a round.', 2),
}
# Power-up weights (ProbabilityOfSpawningEachPickup), in the game's order (CPickupManager).
PICKUPS = ['double_points', 'insta_kill', 'max_ammo', 'nuke', 'carpenter', 'firesale',
           'deathmachine', 'perkbottle', 'lightningbolt']
PICKUP_LABELS = ['Double points', 'Insta-kill', 'Max ammo', 'Nuke', 'Carpenter', 'Fire sale',
                 'Death machine', 'Perk bottle', 'Lightning bolt']
PICKUP_WEIGHTS = [10, 10, 10, 10, 10, 10, 10, 10, 0]
# Per-round limits (m_ScoreLimits): an action earns at most limit x round number in a round.
SCORE_LIMITS = [('SUBJECT_BARRICADE_FIX', 'Barricade points per round (x round)', 50)]
# The score table's actions (score_table), with labels.
SCORES = [
    ('SUBJECT_ZOMBIE_SCORE_HIT', 'Hit', 10),
    ('SUBJECT_ZOMBIE_SCORE_KILL_HEAD', 'Kill: headshot', 100),
    ('SUBJECT_ZOMBIE_SCORE_KILL_TORSO', 'Kill: body', 60),
    ('SUBJECT_ZOMBIE_SCORE_KILL_LIMB', 'Kill: limb', 50),
    ('SUBJECT_ZOMBIE_SCORE_KILL_KNIFE', 'Kill: knife', 130),
    ('SUBJECT_ZOMBIE_SCORE_KILL_GRENADE', 'Kill: grenade', 50),
    ('SUBJECT_BARRICADE_FIX', 'Barricade board', 10),
    ('SUBJECT_ADD_CARPENTER_SCORE', 'Carpenter', 200),
    ('SUBJECT_NUKE_EXPLODED_SCORE', 'Nuke', 400),
]


# Maps whose own level-name checks a map can answer as (boz.game; String_Equals in the level
# manager): what changes.
BEHAVES_LIKE = {'': 'Its own map', 'kino': 'Kino: the teleport sounds and start sequence',
                'ascension': 'Ascension: the round effects; no Kino start',
                'callofthedead': 'Call of the Dead: the snow camera and its start sound'}

# What the game then plays or spawns by name (LevelManager_UpdateAmbience, LevelManager_SetCamera,
# StartFirstWave): bundled with the map.
BEHAVES_LIKE_NEEDS = {'kino': ('tele_incomingend', 'start_kino'),
                      'callofthedead': ('snowCameraEffects', 'level_start_0'), 'ascension': ()}

# Events a map's hook scripts can follow (scripts/hooks/<event>.lua; boz.hooks), with their data.
HOOK_EVENTS = [
    ('round_started', 'A round started', '{round = n}'),
    ('power_on', 'The power was turned on', '{}'),
    ('perk_bought', 'A perk was bought', '{perk = "Juggernog", player = true}'),
    ('door_opened', 'A door or debris was opened', '{door = name, hash = n}'),
    ('zombie_killed', 'A zombie died', '{position = {x, y, z}, entity = e, by_player = true, headshot = true}'),
    ('player_downed', 'The player went down', '{}'),
    ('player_revived', 'The player was revived', '{}'),
    ('weapon_given', 'The player got a weapon', '{weapon = "mp40"}'),
    ('weapon_equipped', 'The player switched weapons', '{weapon = "mp40"}'),
    ('weapon_reloaded', 'The player reloaded', '{weapon = "mp40"}'),
    ('round_ended', 'A round ended (its last zombie died)', '{round = n}'),
    ('points_earned', 'Points were earned', '{points = n, player = true}'),
    ('points_spent', 'Points were spent (a buy)', '{points = n, player = true}'),
    ('player_hit', 'A zombie hit the player', '{damage = n}'),
    ('box_weapon', 'The mystery box picked a weapon', '{weapon = "mp40"}'),
    ('pack_a_punch', 'A weapon went into Pack-a-Punch', '{weapon = "mp40"}'),
    ('powerup_grabbed', 'A power-up was picked up', '{powerup = "nuke", player = true}'),
    ('nuke', 'A nuke went off', '{}'),
    ('carpenter', 'A carpenter rebuilt the barricades', '{}'),
    ('trap_activated', 'A trap was switched on', '{}'),
    ('teleporter_activated', 'A teleporter was used', '{}'),
]


def hook_stub(event: str) -> str:
    """The starting scripts/hooks/<event>.lua."""
    label, data = next(((l, d) for n, l, d in HOOK_EVENTS if n == event), (event, '{}'))
    return (f'-- {label}: runs every time it happens (the Game tab\'s Hooks list).\n'
            f'-- data: {data}\n\n'
            'return function(data)\n'
            f'    log("{event}")\n'
            'end\n')


def _value(field: Field, prop: reflect.Property):
    if field.type == 'std::vector<unsigned int>':
        (n,) = struct.unpack_from('<I', prop.raw, 0)
        return list(struct.unpack_from(f'<{n}I', prop.raw, 4))
    if field.type == 'CParsableEnumManager::SpecialityWaveType':
        return struct.unpack_from('<I', prop.raw, 0)[0]
    value = reflect.typed_value(prop)
    if isinstance(value, float):
        value = round(value, 6)
    return value


def _raw(field: Field, value) -> bytes:
    if field.type == 'std::vector<unsigned int>':
        values = [int(v) & 0xffffffff for v in value]
        return struct.pack(f'<I{len(values)}I', len(values), *values)
    if field.type in ('unsigned int', 'CParsableEnumManager::SpecialityWaveType'):
        return struct.pack('<I', int(value) & 0xffffffff)
    if field.type == 'float':
        return struct.pack('<f', float(value))
    if field.type == 'bool':
        return struct.pack('<?', bool(value))
    raise GameError(f'no codec for {field.type}')


def decode_wave(class_name: str, body: bytes) -> dict:
    """A wave resource as {"class", field: value} with every field of its class (defaults filled)."""
    blob = resources.decode_reflected(body)
    if blob is None:
        raise GameError('not a reflected wave')
    found = {p.name_hash: p for p in blob.properties}
    wave = {'class': class_name}
    for field in fields_of(class_name):
        prop = found.get(iw_hash(field.name))
        wave[field.name] = _value(field, prop) if prop is not None else (
            list(field.default) if isinstance(field.default, tuple) else field.default)
    next_wave = found.get(iw_hash('m_NextWave'))
    wave['next'] = struct.unpack_from('<I', next_wave.raw)[0] if next_wave else 0
    return wave


def encode_wave(wave: dict, next_hash: int = 0) -> bytes:
    """A wave resource body (every field written, the owner being its own class, as shipped)."""
    class_name = wave.get('class', 'CWave')
    if class_name not in WAVE_CLASSES:
        raise GameError(f'unknown wave class {class_name}')
    owner = iw_hash(class_name)
    blob = reflect.Blob(owner)
    for field in fields_of(class_name):
        value = wave.get(field.name, field.default)
        blob.properties.append(reflect.Property(owner, iw_hash(field.type), iw_hash(field.name),
                                                _raw(field, value)))
    blob.properties.append(reflect.Property(owner, iw_hash('unsigned int'), iw_hash('m_NextWave'),
                                            struct.pack('<I', next_hash)))
    return resources.encode_reflected(blob)


def _types(target: group.Group, class_hash: int):
    return [t for t in target.types() if t.class_hash == class_hash]


def _list_values(prop: reflect.Property) -> list[int]:
    (n,) = struct.unpack_from('<I', prop.raw, 0)
    return list(struct.unpack_from(f'<{n}I', prop.raw, 4))


def _level(statics: group.Group):
    for resource_type in _types(statics, LEVEL):
        for resource in resource_type.resources:
            blob = resources.decode_reflected(resource.body)
            if blob is not None:
                return resource, blob
    raise GameError('the level has no CLevel')


def read_rounds(statics: group.Group) -> dict:
    """The level's rounds: {"chains": {key: [wave, ...]}, "specials": [wave, ...]}. Each chain
    is its first round's chain of next rounds (the last one usually repeats)."""
    by_hash, specials = {}, []
    for resource_type in _types(statics, WAVE):
        for resource in resource_type.resources:
            class_name = next((c for c in WAVE_CLASSES if iw_hash(c) == resource.name_hash), 'CWave')
            wave = decode_wave(class_name, resource.body)
            by_hash[resource.in_group_hash] = wave
            if class_name in SPECIAL_CLASSES:
                specials.append(wave)
    _, blob = _level(statics)
    starts = {iw_hash(n): [] for n in ('m_StartingWavesSP', 'm_StartingWavesMP')}
    for prop in blob.properties:
        if prop.name_hash in starts:
            starts[prop.name_hash] = _list_values(prop)
    firsts = (starts[iw_hash('m_StartingWavesSP')] + [0, 0, 0])[:3] + \
        (starts[iw_hash('m_StartingWavesMP')] + [0, 0, 0])[:3]
    chains = {}
    for key, first in zip(CHAIN_KEYS, firsts):
        chain, seen, at = [], set(), first or iw_hash('wave1')
        while at in by_hash and at not in seen:
            seen.add(at)
            wave = dict(by_hash[at])
            chain.append(wave)
            at = wave['next']
        chains[key] = [{k: v for k, v in w.items() if k != 'next'} for w in chain]
    return {'chains': chains,
            'specials': [{k: v for k, v in w.items() if k != 'next'} for w in specials]}


def write_rounds(statics: group.Group, rounds: dict) -> None:
    """Replace the level's rounds: every chain and special round becomes the map's own waves
    (boz_<chain>_<n>, boz_special_<n>) and the CLevel starts each chain."""
    chains = rounds.get('chains') or {}
    missing = [k for k in CHAIN_KEYS if not chains.get(k)]
    if missing:
        raise GameError(f'rounds: no rounds for {", ".join(missing)}')
    wave_types = _types(statics, WAVE)
    if not wave_types:
        raise GameError('the level has no CWave resources to replace')
    wave_type = wave_types[0]
    for section in statics.sections:
        if section.types is not None:
            section.types[:] = [t for t in section.types if t is wave_type or t.class_hash != WAVE]
    wave_type.resources.clear()
    firsts = []
    for key in CHAIN_KEYS:
        chain = chains[key]
        names = [iw_hash(f'boz_{key}_{i + 1}') for i in range(len(chain))]
        for i, wave in enumerate(chain):
            if wave.get('class') in SPECIAL_CLASSES:
                raise GameError(f'rounds: {key} round {i + 1} is a special round')
            body = encode_wave(wave, names[i + 1] if i + 1 < len(names) else 0)
            wave_type.resources.append(group.Resource(iw_hash(wave.get('class', 'CWave')),
                                                      names[i], body))
        firsts.append(names[0])
    for i, wave in enumerate(rounds.get('specials') or []):
        if wave.get('class') not in SPECIAL_CLASSES:
            raise GameError(f'special round {i + 1} is not a special round class')
        wave_type.resources.append(group.Resource(iw_hash(wave['class']),
                                                  iw_hash(f'boz_special_{i + 1}'), encode_wave(wave)))
    resource, blob = _level(statics)
    values = {iw_hash('m_StartingWavesSP'): firsts[:3], iw_hash('m_StartingWavesMP'): firsts[3:]}
    present = set()
    for prop in blob.properties:
        if prop.name_hash in values:
            v = values[prop.name_hash]
            prop.raw = struct.pack(f'<I{len(v)}I', len(v), *v)
            prop.nested, prop.elements = None, None
            present.add(prop.name_hash)
    for name_hash, v in values.items():
        if name_hash not in present:
            blob.properties.append(reflect.Property(LEVEL, iw_hash('std::list<unsigned int>'),
                                                    name_hash, struct.pack(f'<I{len(v)}I', len(v), *v)))
    resource.body = resources.encode_reflected(blob)


def round_values(chain: list[dict], round_number: int, power_on: bool = False,
                 grow_health: bool = False) -> dict:
    """What round *round_number* (1 = first) of a chain has, the way the game works it out:
    {"zombies", "health", "at_once", "interval"} (health before the difficulty scaling). Past the
    chain's end the last round repeats; a repeatable one grows by its multipliers once the round
    is past its m_StartingWave, and its health is the game's 10 x round^2 - 150 unless
    *grow_health* (boz.game's "grow")."""
    if not chain:
        return {'zombies': 0, 'health': 0, 'at_once': 0, 'interval': 0}
    wave = chain[min(round_number, len(chain)) - 1]
    repeats = wave.get('class', 'CWave') != 'CWave'
    start = int(wave.get('m_StartingWave', 1))

    def grown(name, mult_name):
        base = float(wave.get(name, FIELD[name].default))
        if repeats and round_number > start:
            base *= float(wave.get(mult_name, 1.0)) ** (round_number - start)
        return int(max(0.0, base))

    zombies = grown('m_ZombieCount', 'm_ZombieCountMultiplier')
    if power_on:
        zombies += grown('m_PoweredZombieCount', 'm_PoweredZombieCountMultiplier')
    if repeats and not grow_health:
        health = 10 * round_number * round_number - 150
    else:
        health = grown('m_ZombieHealth', 'm_ZombieHealthMultiplier')
    return {'zombies': zombies,
            'health': health,
            'at_once': grown('m_MaxActive', 'm_MaxActiveMultiplier'),
            'interval': grown('m_TimeOut', 'm_TimeOutMultiplier')}


ZOMBIE_CONFIG = iw_hash('CZombieConfiguration')


def read_zombie_types(statics: group.Group, names: dict | None = None) -> dict:
    """The level's zombie looks: {"all": [{"hash", "skeleton", "models": [...]}], "used": [hash]}.
    A CZombieConfiguration is one look (a skeleton and the body part models per level of detail);
    the CLevel lists the ones zombies are picked from at random when they spawn."""
    names = names or {}
    looks = []
    for resource_type in _types(statics, ZOMBIE_CONFIG):
        for resource in resource_type.resources:
            blob = resources.decode_reflected(resource.body)
            if blob is None:
                continue
            look = {'hash': resource.in_group_hash, 'skeleton': 0, 'models': []}
            for prop in blob.properties:
                if prop.name_hash == iw_hash('m_skel'):
                    look['skeleton'] = struct.unpack_from('<I', prop.raw)[0]
                elif prop.name_hash == iw_hash('LOD0') and len(prop.raw) >= 4:
                    look['models'] = _list_values(prop)
            look['label'] = names.get(look['hash'], f'look {look["hash"]:08x}')
            looks.append(look)
    used = []
    _, blob = _level(statics)
    for prop in blob.properties:
        if prop.name_hash == iw_hash('m_zombiesConfigurations'):
            used = _list_values(prop)
    return {'all': looks, 'used': used}


def all_zombie_types(pack, names: dict | None = None) -> list[dict]:
    """Every map's zombie looks: [{"hash", "map", "label", "models"}] (any of them can be used on
    any map: the build brings it)."""
    from . import bundle, library
    names = names or {}
    out, seen = [], set()
    registry = bundle.Registry.of(pack)
    for value, entries in registry.by_hash.items():
        for entry in entries:
            if entry.cls != ZOMBIE_CONFIG or value in seen:
                continue
            seen.add(value)
            blob = resources.decode_reflected(entry.resource.body)
            models = []
            for prop in blob.properties if blob else []:
                if prop.name_hash == iw_hash('LOD0') and len(prop.raw) >= 4:
                    models = _list_values(prop)
            level = library.map_of(entry.path)
            out.append({'hash': value, 'map': level, 'models': models,
                        'label': names.get(value, f'{level or "shared"} look {value:08x}')})
    out.sort(key=lambda look: (look['map'], look['label']))
    return out


def write_zombie_types(statics: group.Group, used: list[int]) -> None:
    """The looks zombies spawn with (hashes of the level's CZombieConfiguration resources)."""
    known = {look['hash'] for look in read_zombie_types(statics)['all']}
    unknown = [h for h in used if h not in known]
    if unknown:
        raise GameError(f'zombie types: the level has no look {unknown[0]:08x}')
    if not used:
        raise GameError('zombie types: pick at least one look')
    resource, blob = _level(statics)
    raw = struct.pack(f'<I{len(used)}I', len(used), *used)
    for prop in blob.properties:
        if prop.name_hash == iw_hash('m_zombiesConfigurations'):
            prop.raw, prop.nested, prop.elements = raw, None, None
            break
    else:
        blob.properties.append(reflect.Property(LEVEL, iw_hash('std::vector<unsigned int>'),
                                                iw_hash('m_zombiesConfigurations'), raw))
    resource.body = resources.encode_reflected(blob)


BOX_FIELDS = {'m_Cost': ('Box cost', 950), 'm_FireSaleCost': ('Fire sale cost', 10),
              'm_MinWeapons': ('Weapons shown at least', 4),
              'm_MaxWeapons': ('Weapons shown at most', 10)}


def apply_box(groups: dict, box: dict) -> int:
    """Set the mystery boxes' cost and spin (CMysteryBox) where a box still has the game's value
    (a box given its own value in the World tab keeps it). Returns the boxes changed."""
    changed = 0
    for target in groups.values():
        for resource_type in _types(target, resources.ENTITY_SPEC):
            for resource in resource_type.resources:
                try:
                    spec = resources.decode_entity_spec(resource.body)
                except Exception:
                    continue
                touched = False
                for component in _all_components(spec):
                    if component.type_hash != iw_hash('CMysteryBox') or component.blob is None:
                        continue
                    for prop in component.blob.properties:
                        for name, (_, stock) in BOX_FIELDS.items():
                            if prop.name_hash == iw_hash(name) and name in box and \
                                    reflect.typed_value(prop) == stock:
                                reflect.set_typed_value(prop, int(box[name]))
                                touched = True
                if touched:
                    resource.body = resources.encode_entity_spec(spec)
                    changed += 1
    return changed


def _all_components(spec):
    yield from spec.components
    for _, _, child in spec.children:
        yield from _all_components(child)


def read_scores(shared: group.Group, prop_name: str = 'm_Scores') -> dict:
    """The shared score table's {action: points} (m_Scores), or its per-round limits
    (m_ScoreLimits: an action earns at most this x the round number per round)."""
    for resource_type in _types(shared, SCORE_CONFIG):
        for resource in resource_type.resources:
            if resource.in_group_hash != iw_hash('score_table'):
                continue
            blob = resources.decode_reflected(resource.body)
            out = {}
            for prop in blob.properties:
                if prop.name_hash != iw_hash(prop_name):
                    continue
                for element in prop.elements or []:
                    pair = {p.name_hash: reflect.typed_value(p) for p in element.properties}
                    action, points = pair.get(iw_hash('Type')), pair.get(iw_hash('Score'))
                    if isinstance(action, str):
                        out[action] = points
            return out
    if prop_name == 'm_ScoreLimits':
        return {action: limit for action, _, limit in SCORE_LIMITS}
    return {action: points for action, _, points in SCORES}


def _score_list(name: str, scores: dict) -> reflect.Property:
    owner = iw_hash('ScorePair')
    elements = []
    for action, points in scores.items():
        elements.append(reflect.Blob(owner, [
            reflect.Property(owner, iw_hash('std::string'), iw_hash('Type'), action.encode('ascii') + b'\0'),
            reflect.Property(owner, iw_hash('unsigned int'), iw_hash('Score'),
                             struct.pack('<I', int(points)))]))
    raw = struct.pack('<I', len(elements)) + b''.join(reflect.encode(e) for e in elements)
    return reflect.Property(SCORE_CONFIG, iw_hash('std::list<ScorePair>'), iw_hash(name), raw,
                            elements=elements)


def score_config(scores: dict, limits: dict | None = None) -> bytes:
    """A CScoreConfig body: points per action (m_Scores) and per-round limits (m_ScoreLimits,
    the game's barricade limit when *limits* is None)."""
    if limits is None:
        limits = {action: limit for action, _, limit in SCORE_LIMITS}
    props = [_score_list('m_ScoreLimits', limits), _score_list('m_Scores', scores)]
    return resources.encode_reflected(reflect.Blob(SCORE_CONFIG, props))


def score_table_name(map_name: str) -> str:
    return f'boz_score_{map_name}'


def loading_group_name(map_name: str) -> str:
    return f'loading_{map_name}'


def loading_screen(template: group.Group, png: Path | bytes, map_name: str) -> group.Group:
    """The loading screen group with the picture replaced. The game's picture is a 1024 x 1024
    ETC1 texture whose top 1024 x 768 the screen shows (the UI addresses it in pixels, so the size
    must stay; raw textures that big do not load): the picture is fitted there and encoded the
    same way."""
    from PIL import Image
    import io
    from . import levels, native
    image = Image.open(io.BytesIO(png) if isinstance(png, (bytes, bytearray)) else png).convert('RGB')
    canvas = Image.new('RGB', (1024, 1024), (0, 0, 0))
    canvas.paste(image.resize((1024, 768), Image.LANCZOS), (0, 0))
    copy = group.parse(group.encode(template))
    replaced = False
    for resource_type in copy.types():
        for resource in resource_type.resources:
            if resource_type.class_hash == iw_hash('CIwTexture') and \
                    resource.in_group_hash == iw_hash('loading_ipad'):
                resource.body = native.replace_cooked_etc1(resource.body, canvas)
                replaced = True
    if not replaced:
        raise GameError('the loading screen group has no loading picture')
    return levels.renamed(copy, loading_group_name(map_name))


def point_loading_screen(fixed: group.Group, map_name: str) -> None:
    """Point every resolution of ``loading-<map>`` at the map's own loading group."""
    path = f'loading/{map_name}/{loading_group_name(map_name)}.group'.encode('ascii')
    for resource_type in _types(fixed, STRING):
        for resource in resource_type.resources:
            if resource.in_group_hash != iw_hash(f'loading-{map_name}'):
                continue
            body = resource.body
            (count,) = struct.unpack_from('<I', body, 0)
            out, p = bytearray(struct.pack('<I', count)), 4
            for _ in range(count):
                key = body[p:p + 4]
                end = body.index(b'\0', p + 4)
                out += key + path + b'\0'
                p = end + 1
            out += body[p:]
            resource.body = bytes(out)
            return
    raise GameError(f'fixed has no loading-{map_name}')


def path(source: Path) -> Path:
    return Path(source) / 'game.json'


def load(source: Path) -> dict:
    """source/game.json ({} when there is none)."""
    file = path(source)
    if not file.is_file():
        return {}
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise GameError(f'game.json: {exc}') from None
    if not isinstance(data, dict):
        raise GameError('game.json: not an object')
    return data


def save(source: Path, data: dict) -> None:
    file = path(source)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def check(data: dict) -> list[str]:
    """Problems with the Game tab's data (the build stops on them)."""
    problems = []
    rounds = data.get('rounds')
    if rounds:
        for key in CHAIN_KEYS:
            chain = (rounds.get('chains') or {}).get(key) or []
            if not chain:
                problems.append(f'Rounds: {dict(CHAINS)[key]} has no rounds')
            for i, wave in enumerate(chain):
                shares = sum(float(wave.get(n, FIELD[n].default)) for n in
                             ('m_ZombieWalk', 'm_ZombieWalkFast', 'm_ZombieRun', 'm_ZombieSprint'))
                if shares <= 0:
                    problems.append(f'Rounds: {dict(CHAINS)[key]} round {i + 1}: no zombie speeds')
                if int(wave.get('m_MaxActive', 0)) <= 0 and int(wave.get('m_ZombieCount', 0)) > 0:
                    problems.append(f'Rounds: {dict(CHAINS)[key]} round {i + 1}: '
                                    'at once must be at least 1')
    for name, value in (data.get('economy', {}).get('cvars') or {}).items():
        if name not in CVARS:
            problems.append(f'Economy: unknown setting {name}')
        elif not isinstance(value, (int, float)) or value < 0:
            problems.append(f'Economy: {CVARS[name][0]} must be a number of 0 or more')
    if rounds and rounds.get('repeat_health', 'game') not in ('game', 'grow'):
        problems.append('Rounds: repeat health must be "game" or "grow"')
    for name, value in ((data.get('economy') or {}).get('box') or {}).items():
        if name not in BOX_FIELDS or not isinstance(value, int) or value < 0:
            problems.append(f'Economy: box setting {name} must be a whole number of 0 or more')
    if (data.get('level') or {}).get('behaves_like', '') not in BEHAVES_LIKE:
        problems.append('Level info: behaves like must be one of ' + ', '.join(repr(k) for k in BEHAVES_LIKE))
    for name, value in ((data.get('economy') or {}).get('score_limits') or {}).items():
        if not isinstance(value, int) or value < 0:
            problems.append(f'Economy: the limit for {name} must be a whole number of 0 or more')
    weights = data.get('economy', {}).get('pickups')
    if weights is not None and (len(weights) != len(PICKUPS) or
                                any(not isinstance(w, int) or w < 0 for w in weights)):
        problems.append('Economy: power-up weights must be 9 whole numbers of 0 or more')
    return problems


def runtime(data: dict, map_name: str) -> dict:
    """What boz.game applies when the map starts: {"cvars": {name: value}, "power_on": bool}."""
    economy = data.get('economy') or {}
    cvars = dict(economy.get('cvars') or {})
    if economy.get('pickups') is not None:
        cvars['ProbabilityOfSpawningEachPickup'] = '{' + ','.join(str(int(w)) for w in economy['pickups']) + '}'
    if economy.get('scores'):
        cvars['ScoreConfigName'] = score_table_name(map_name)
    level = data.get('level') or {}
    rounds = data.get('rounds') or {}
    return {'cvars': cvars, 'power_on': bool(level.get('power_on')), 'level': map_name,
            'grow_health': rounds.get('repeat_health') == 'grow',
            'behaves_like': level.get('behaves_like', '')}


def apply(data: dict, project_root: Path, groups: dict, map_name: str, read=None, pack=None) -> dict:
    """Put the Game tab's data into the map's groups; returns the runtime part (see runtime)."""
    problems = check(data)
    if problems:
        raise GameError('; '.join(problems))
    statics = groups.get(f'{map_name}_statics.group.bin')
    if data.get('rounds'):
        if statics is None:
            raise GameError('the map has no statics group for its rounds')
        write_rounds(statics, data['rounds'])
    scores = (data.get('economy') or {}).get('scores')
    if scores:
        if statics is None:
            raise GameError('the map has no statics group for its score table')
        types = _types(statics, SCORE_CONFIG)
        if types:
            score_type = types[0]
        else:
            score_type = group.ResourceType(SCORE_CONFIG, 1, 1, [])
            _add_type(statics, score_type)
        key = iw_hash(score_table_name(map_name))
        score_type.resources[:] = [r for r in score_type.resources if r.in_group_hash != key]
        score_type.resources.append(group.Resource(None if score_type.names_omitted else key, key,
                                                   score_config(scores, (data.get('economy') or {}).get('score_limits'))))
    zombies = data.get('zombies') or {}
    if zombies.get('used'):
        if statics is None:
            raise GameError('the map has no statics group for its zombie types')
        used = [int(h) for h in zombies['used']]
        have = {look['hash'] for look in read_zombie_types(statics)['all']}
        missing = [h for h in used if h not in have]
        if missing and pack is not None:
            # Looks of other maps come with their skeleton and models.
            from . import bundle
            bundle.Bundle(bundle.Registry.of(pack), groups, map_name).add(
                missing, target=f'{map_name}_statics.group.bin')
        write_zombie_types(statics, used)
    like = (data.get('level') or {}).get('behaves_like', '')
    if like and pack is not None:
        from . import bundle
        bundle.Bundle(bundle.Registry.of(pack), groups, map_name).add(
            [iw_hash(n) for n in BEHAVES_LIKE_NEEDS.get(like, ())],
            prefer=f'levels/{like}/{like}_statics.group.bin')
    box = (data.get('economy') or {}).get('box')
    if box:
        apply_box(groups, box)
    image = (data.get('level') or {}).get('loading_image')
    if image:
        file = Path(project_root) / image
        if not file.is_file():
            raise GameError(f'loading screen image {image} not found')
        if read is None:
            raise GameError('a loading screen needs the game data')
        template = group.parse(read('loading/kino/loading_droid.group.bin'))
        groups[f'{loading_group_name(map_name)}.group.bin'] = loading_screen(template, file, map_name)
        fixed = groups.get('fixed.group.bin')
        if fixed is not None:
            point_loading_screen(fixed, map_name)
    return runtime(data, map_name)


def _add_type(target: group.Group, resource_type: group.ResourceType) -> None:
    for section in target.sections:
        if section.hash == group.RESOURCES:
            section.types.append(resource_type)
            return
    raise GameError('the group has no resources section')
