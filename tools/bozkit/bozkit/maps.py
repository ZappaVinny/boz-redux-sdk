"""The game's shipped Zombies maps, and what the tools need to know about them."""
from __future__ import annotations

LABELS = {'kino': 'Kino der Toten', 'callofthedead': 'Call of the Dead', 'ascension': 'Ascension',
          'tutorial': 'Tutorial'}
SHIPPED = tuple(LABELS)
# The tutorial uses Kino's weapons and arms groups.
GEAR = {'tutorial': 'kino'}
# Maps with weapon groups of their own.
WITH_WEAPONS = tuple(level for level in SHIPPED if level not in GEAR)
# Dead Ops Arcade is a separate mode the tools leave alone.
SKIPPED_PREFIXES = ('deadops', 'loading/deadops')


def gear(level: str) -> str:
    """The level whose weapons and arms groups *level* uses."""
    return GEAR.get(level, level)
