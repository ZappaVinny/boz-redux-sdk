"""Links between a map's objects: which power switch a machine waits for, which traps a switch
runs, which doors open together, which window zombie spawns climb in through a barricade.

One table for the editor (the Links box, the overlay), the compiler (world_compile writes set
links into the entities' fields) and the runtime (world_data.lua ``links``, boz.objects.links).
A world stores links by object name (``Prefab.links``: link name -> names); a link the user has
not set keeps its default (the entity's own link from its home map, or the map's power switch).

A kind with no game field is an editor/script link: the compiler and scripts use it, the game
never sees it. Lua prefabs will declare kinds of their own the same way (block 3).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    name: str                          # the key in Prefab.links and world_data.lua
    label: str
    on: frozenset                      # component names: the kind shows on entities with any
    targets: frozenset                 # component names: what it may point at (any of them)
    fields: tuple = ()                 # (component, field) it writes; () editor/script only
    many: bool = False                 # a list (else one target)
    piece: str = ''                    # targets must also be placed as this toolkit piece
    default: str = ''                  # what an unset link does, for the editor


POWERED = ('CPerk', 'CDoor', 'CPackAPunch', 'CTrapSwitch', 'CTeleporter', 'CTVScreen',
           'CProjectorScreen', 'CTurret', 'CTeleportMainframe')

KINDS = (
    Kind('power', 'Power switch', frozenset(POWERED), frozenset({'CPowerSwitch'}),
         tuple((component, 'powerSwitch') for component in POWERED),
         default="the map's power switch"),
    Kind('traps', 'Traps', frozenset({'CTrapSwitch'}), frozenset({'CTrap'}),
         (('CTrapSwitch', 'traps'),), many=True, default='its own traps, if placed'),
    Kind('siblings', 'Opens with', frozenset({'CDoor'}), frozenset({'CDoor'}),
         (('CDoor', 'm_Siblings'),), many=True, default='its own siblings, if placed'),
    Kind('spawns', 'Window spawns', frozenset({'CBarricade'}), frozenset({'CSpawnPoint'}),
         many=True, piece='zombie_window', default='none'),
)
BY_NAME = {kind.name: kind for kind in KINDS}


def kinds_for(components) -> list[Kind]:
    """The link kinds an entity with these component names has."""
    present = set(components)
    return [kind for kind in KINDS if kind.on & present]


def can_target(kind: Kind, components, piece: str = '') -> bool:
    """Whether an entity (component names, the toolkit piece it was placed as) may be a target."""
    return bool(kind.targets & set(components)) and (not kind.piece or piece == kind.piece)


def clean(links: dict) -> dict:
    """*links* as stored: known kinds only, names as a list of strings, one name for single
    links. Empty lists stay (a list link set to nothing is "none", not "default")."""
    out = {}
    for name, targets in (links or {}).items():
        kind = BY_NAME.get(name)
        if kind is None:
            continue
        values = [str(t) for t in (targets if isinstance(targets, (list, tuple)) else [targets])
                  if str(t)]
        out[name] = values if kind.many else values[:1]
    return out


def renamed(links: dict, old: str, new: str) -> dict:
    """*links* with every target called *old* now called *new*."""
    return {name: [new if t == old else t for t in targets] for name, targets in links.items()}
