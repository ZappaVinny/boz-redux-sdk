"""
Hash-to-name lookup from the game definition (gamedef/reflection, gamedef/events).

The game identifies classes, fields and types by IwHashString; bozkit shows the names it knows
and falls back to ``0x<hash>`` otherwise.
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from .hashing import iw_hash


def sdk_root() -> Path:
    """The SDK folder: BOZ_SDK_ROOT (set for the editor), the folder of the bundled launcher in a
    release (boz-sdk.exe), else the repository checkout."""
    if os.environ.get('BOZ_SDK_ROOT'):
        return Path(os.environ['BOZ_SDK_ROOT'])
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


GAMEDEF = sdk_root() / 'gamedef'
GAME_VERSION = '1.0.11'


def gamedef_file(kind: str) -> Path:
    """A part of the game definition: 'symbols', 'reflection', 'events', 'runtime' or 'console'."""
    return GAMEDEF / kind / f'boz-{GAME_VERSION}.toml'

# Local name dictionary built from the user's own game files by `bozkit names` (never shipped).
NAMES_CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'bozkit' / 'names.txt'

# Type names as the game hashes them (not the shortened forms in the reflection file).
BASIC_TYPES = (
    'bool', 'char', 'unsigned char', 'short', 'unsigned short', 'int', 'unsigned int', 'long',
    'unsigned long', 'float', 'double', 'CIwFVec2', 'CIwFVec3', 'CIwFVec4', 'CIwFQuat', 'CIwFMat',
    'CIwColour', 'CIwSVec2', 'CIwVec2', 'CIsTimer',
)
EXTRA_CLASSES = ('CIsEntitySpec', 'CIsComponentSpec', 'CIsCollisionMeshSpec', 'CIsCollisionObjectSpec',
                 'CIsNavMeshVolumeMeshSpec')


class Names:
    def __init__(self, gamedef: Path = GAMEDEF, version: str = GAME_VERSION):
        self.names: dict[int, str] = {}
        self.classes: dict[str, dict] = {}
        for n in BASIC_TYPES + EXTRA_CLASSES:
            self.add(n)
        ref = gamedef / 'reflection' / f'boz-{version}.toml'
        if ref.exists():
            with ref.open('rb') as f:
                for c in tomllib.load(f).get('class', []):
                    self.classes[c['name']] = c
                    self.add(c['name'])
                    for fld in c.get('fields', []):
                        self.add(fld['name'])
                        self.add(fld['type'])
        events = gamedef / 'events' / f'boz-{version}.toml'
        if events.exists():
            with events.open('rb') as f:
                for e in tomllib.load(f).get('event', []):
                    self.add(e['name'])
        if NAMES_CACHE.exists():
            for line in NAMES_CACHE.read_text(encoding='latin-1').splitlines():
                if line:
                    self.add(line)

    def add(self, name: str) -> None:
        self.names.setdefault(iw_hash(name), name)

    def name(self, h: int | None) -> str:
        if h is None:
            return 'none'
        return self.names.get(h, f'0x{h:08x}')

    def hash(self, name: str) -> int:
        """Hash for a name or a 0x-prefixed hex string."""
        return int(name, 16) if name.startswith('0x') else iw_hash(name)
