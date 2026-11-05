"""Links between a map's objects: which power switch a machine waits for, which traps a switch
runs, which doors open together, which window spawns climb in through a barricade, and links
scripts declare (``---@link``).

One table for the editor (the Links box, the overlay), the compiler (world_compile writes set
links into the entities' fields) and the runtime (world_data.lua ``links``, Object:links). A world
stores links by object name (``Prefab.links``: link name -> names). A link the user has not set
keeps its default (the entity's own link from its home map, or the map's power switch).

Links name what they point at by object kind, the palette's names (OBJECT_KINDS). A kind with no
game field is a link only scripts read.
"""
from __future__ import annotations

from dataclasses import dataclass

# Object kinds, by what an object is: game prefabs by their components, and your own objects
# by their editor role (model, volume, prefab). 'door' also covers debris (a door of yours).
OBJECT_KINDS = ('perk', 'door', 'barricade', 'trap', 'trap_switch', 'power_switch', 'mystery_box',
                'pack_a_punch', 'wall_buy', 'zombie_spawn', 'player_spawn', 'volume', 'model',
                'prefab', 'any')
PIECE_KINDS = {'debris': 'door'}   # prefabs of yours that are a kind of game object
_COMPONENT_KINDS = (('CTrapSwitch', 'trap_switch'), ('CTrap', 'trap'), ('CPerk', 'perk'),
                    ('CDoor', 'door'), ('CBarricade', 'barricade'),
                    ('CPowerSwitch', 'power_switch'), ('CMysteryBox', 'mystery_box'),
                    ('CPackAPunch', 'pack_a_punch'), ('CWeaponChalkOutline', 'wall_buy'))


def kinds_of(components=(), piece: str = '', role: str = '', extra: str = '') -> set[str]:
    """The object kinds an object is: by its components (game prefabs), its toolkit piece, its
    editor role ('model', 'volume', 'prefab' for your own) and an extra kind it declares
    ('door' for debris). Always includes 'any'."""
    present = set(components)
    out = {'any'}
    for component, kind in _COMPONENT_KINDS:
        if component in present:
            out.add(kind)
            if kind == 'trap_switch':
                break   # a switch is not also a trap
    if 'CSpawnPoint' in present:
        out.add('player_spawn' if piece == 'player_spawn' else 'zombie_spawn')
    if present & set(POWERED):
        out.add('powered')   # waits for a power switch (internal: the power link's)
    if role in ('model', 'volume', 'prefab'):
        out.add(role)
    if piece in PIECE_KINDS:
        out.add(PIECE_KINDS[piece])
    if extra:
        out.add(extra)
    return out


@dataclass(frozen=True)
class Kind:
    name: str                          # the key in Prefab.links and world_data.lua
    label: str
    on: frozenset                      # object kinds the link shows on ('any': every object)
    targets: frozenset                 # object kinds it may point at
    fields: tuple = ()                 # (component, field) it writes; () editor/script only
    many: bool = False                 # a list (else one target)
    piece: str = ''                    # targets must also be placed as this toolkit piece
    default: str = ''                  # what an unset link does, for the editor


POWERED = ('CPerk', 'CDoor', 'CPackAPunch', 'CTrapSwitch', 'CTeleporter', 'CTVScreen',
           'CProjectorScreen', 'CTurret', 'CTeleportMainframe')

KINDS = (
    Kind('power', 'Power switch', frozenset({'powered'}), frozenset({'power_switch'}),
         tuple((component, 'powerSwitch') for component in POWERED),
         default="the map's power switch"),
    Kind('traps', 'Traps', frozenset({'trap_switch'}), frozenset({'trap'}),
         (('CTrapSwitch', 'traps'),), many=True, default='its own traps, if placed'),
    Kind('siblings', 'Opens with', frozenset({'door'}), frozenset({'door'}),
         (('CDoor', 'm_Siblings'),), many=True, default='its own siblings, if placed'),
    Kind('spawns', 'Window spawns', frozenset({'barricade'}), frozenset({'zombie_spawn'}),
         many=True, piece='zombie_window', default='none'),
)
BY_NAME = {kind.name: kind for kind in KINDS}


def script_kind(name: str, target: str, many: bool, label: str) -> Kind:
    """A link a script declares (---@link name kind one|many "label"): on its own object only,
    read by scripts (no game field)."""
    return Kind(name, label or name.replace('_', ' ').capitalize(), frozenset({'any'}),
                frozenset({target}), many=many, default='none')


def kinds_for(object_kinds, declared=()) -> list[Kind]:
    """The link kinds an object of these object kinds has (built-in), then its script's."""
    present = set(object_kinds)
    built_in = [kind for kind in KINDS if kind.on & present]
    names = {kind.name for kind in built_in}
    return built_in + [kind for kind in declared if kind.name not in names]


def can_target(kind: Kind, object_kinds, piece: str = '') -> bool:
    """Whether an object (its object kinds, the toolkit piece it was placed as) may be a target."""
    present = set(object_kinds)
    return bool(kind.targets & present or 'any' in kind.targets) and \
        (not kind.piece or piece == kind.piece)


def clean(links: dict, declared=()) -> dict:
    """*links* as stored: known kinds only (built-in and *declared*), names as a list of strings,
    one name for single links. Empty lists stay (a list link set to nothing is "none")."""
    known = {**BY_NAME, **{kind.name: kind for kind in declared}}
    out = {}
    for name, targets in (links or {}).items():
        kind = known.get(name)
        if kind is None:
            if declared == ():   # a script's own link: kept as is (its script declares it)
                values = targets if isinstance(targets, (list, tuple)) else [targets]
                out[name] = [str(t) for t in values if str(t)]
            continue
        values = [str(t) for t in (targets if isinstance(targets, (list, tuple)) else [targets])
                  if str(t)]
        out[name] = values if kind.many else values[:1]
    return out


def renamed(links: dict, old: str, new: str) -> dict:
    """*links* with every target called *old* now called *new*."""
    return {name: [new if t == old else t for t in targets] for name, targets in links.items()}
