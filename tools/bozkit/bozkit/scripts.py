"""Prefab and model scripts: the properties they declare, and new scripts from a template.

A script is a Lua file in the project's ``scripts/`` folder, usually ``scripts/prefabs/<Name>.lua``.
It declares the properties the editor shows for each object using it, one per line::

    ---@property delay number 2 "Seconds before the wall opens"
    ---@property opens prefab "" "The prefab this one opens"

``<name> <type> <default> "<description>"``. Types: number, integer, bool, string, event,
prefab, part, weapon, sound. Defaults are Lua-style literals (``2``, ``true``, ``"text"``); the
description is optional. The editor reads these lines without running Lua; at runtime the values
are ``self.properties.<name>`` (boz.prefabs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TYPES = ('number', 'integer', 'bool', 'string', 'event', 'prefab', 'part', 'weapon', 'sound')
_LINE = re.compile(r'^\s*---@property\s+([A-Za-z_][A-Za-z0-9_]*)\s+([a-z]+)\s*(.*)$')
_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')
NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,47}$')


class ScriptError(ValueError):
    pass


@dataclass
class Property:
    name: str
    type: str
    default: object
    description: str = ''


def coerce(value, type_name: str):
    """A property value as Python stores it for *type_name*."""
    if type_name == 'number':
        return float(value)
    if type_name == 'integer':
        return int(float(value))
    if type_name == 'bool':
        if isinstance(value, str):
            return value.strip().lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    return '' if value is None else str(value)


def _default(text: str | None, type_name: str):
    if text is None:
        return coerce({'number': 0, 'integer': 0, 'bool': False}.get(type_name, ''), type_name)
    try:
        return coerce(text, type_name)
    except ValueError as exc:
        raise ScriptError(f'default {text!r} is not a {type_name}') from exc


def parse_properties(text: str) -> list[Property]:
    """The properties a script declares (``---@property`` lines), in order."""
    out, seen = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        match = _LINE.match(line)
        if not match:
            continue
        name, type_name, rest = match.groups()
        if type_name not in TYPES:
            raise ScriptError(f'line {number}: {type_name!r} is not a property type '
                              f'({", ".join(TYPES)})')
        if name in seen:
            raise ScriptError(f'line {number}: property {name!r} is declared twice')
        seen.add(name)
        tokens = [(quoted, plain) for quoted, plain in _TOKEN.findall(rest)]
        default_text = description = None
        if tokens:
            quoted, plain = tokens[0]
            default_text = plain if plain else bytes(quoted, 'utf-8').decode('unicode_escape')
        if len(tokens) > 1:
            description = ' '.join(q or p for q, p in tokens[1:])
        out.append(Property(name, type_name, _default(default_text, type_name), description or ''))
    return out


def read_properties(path: str | Path) -> list[Property]:
    try:
        return parse_properties(Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise ScriptError(f'cannot read {path}: {exc}') from exc


def values(properties: list[Property], given: dict) -> dict:
    """Each declared property's value: *given* where set (coerced), else its default."""
    out = {}
    for prop in properties:
        try:
            out[prop.name] = coerce(given[prop.name], prop.type) if prop.name in given \
                else prop.default
        except (TypeError, ValueError):
            out[prop.name] = prop.default
    return out


TEMPLATE = '''-- {name}: a script. It runs for every object it is attached to, and self is that object.
-- Properties declared below show in the editor for each object; their values are
-- self.properties.<name>.
--
---@property message string "{name} was used" "What to print when it is used"

-- The level started.
function start()
end

-- Only volumes send these (Trigger: on_enter / on_exit, Hit: on_hit, Use: on_use); volume is
-- the volume's name in the prefab. With one volume of a kind, there is no need to check it.
function on_enter(volume, who)       -- who.player, who.zombie
end

function on_exit(volume, who)
end

function on_hit(volume, info)
end

function on_use(volume, who)         -- the player pressed use (its cost already paid)
    print(self.properties.message)
end

-- boz.send(name, data) from any script, and game events: round_started, power_on,
-- perk_bought, door_opened, zombie_killed, player_downed, player_revived.
-- Global variables (not local) are saved with the game.
function on_event(name, data)
end
'''


def stub(name: str) -> str:
    """A new script for a prefab or model called *name*."""
    if not NAME_RE.fullmatch(name):
        raise ScriptError(f'script name {name!r}: use letters, digits and _')
    return TEMPLATE.format(name=name)


def new_script(scripts: str | Path, name: str) -> str:
    """Create scripts/prefabs/<name>.lua (unless it exists); returns its path relative to
    scripts/ ('prefabs/<name>.lua')."""
    relative = f'prefabs/{name}.lua'
    path = Path(scripts) / relative
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(stub(name), encoding='utf-8', newline='\n')
    return relative


def list_scripts(scripts: str | Path) -> list[str]:
    """Scripts in scripts/prefabs, relative to scripts/."""
    folder = Path(scripts) / 'prefabs'
    return sorted(f'prefabs/{p.name}' for p in folder.glob('*.lua')) if folder.is_dir() else []
