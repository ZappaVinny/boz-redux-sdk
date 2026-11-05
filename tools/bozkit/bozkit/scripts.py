"""Object scripts: the settings they declare, and new scripts from a template.

A script is a Lua file in the project's ``scripts/`` folder, usually ``scripts/prefabs/<Name>.lua``,
that returns a class (``local Skull = boz.Prefab:extend("Skull") ... return Skull``). It declares
settings the editor shows next to the object's own, one per line::

    ---@setting points int 100 "Points for shooting it"
    ---@setting opens object "" "The prefab this one opens"

``<name> <kind> <default> "<label>"``. Kinds: int, float, bool, seconds, text, weapon, sound,
object, event. At runtime the values are ``self.settings.<name>``.

Links to other objects show in the object's Links box (bozkit.links.OBJECT_KINDS)::

    ---@link targets trap many "Traps it runs"

``<name> <object kind> one|many "<label>"``; at runtime ``self:links("targets")``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TYPES = ('int', 'float', 'bool', 'seconds', 'text', 'weapon', 'sound', 'object', 'event')
_LINE = re.compile(r'^\s*---@setting\s+([A-Za-z_][A-Za-z0-9_]*)\s+([a-z]+)\s*(.*)$')
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
    if type_name in ('float', 'seconds'):
        return float(value)
    if type_name == 'int':
        return int(float(value))
    if type_name == 'bool':
        if isinstance(value, str):
            return value.strip().lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    return '' if value is None else str(value)


def _default(text: str | None, type_name: str):
    if text is None:
        return coerce({'float': 0, 'seconds': 0, 'int': 0, 'bool': False}.get(type_name, ''),
                      type_name)
    try:
        return coerce(text, type_name)
    except ValueError as exc:
        raise ScriptError(f'default {text!r} is not a {type_name}') from exc


def parse_properties(text: str) -> list[Property]:
    """The settings a script declares (``---@setting`` lines), in order."""
    out, seen = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith('---@property'):
            raise ScriptError(f'line {number}: ---@property is now ---@setting (kinds: '
                              f'{", ".join(TYPES)})')
        match = _LINE.match(line)
        if not match:
            continue
        name, type_name, rest = match.groups()
        if type_name not in TYPES:
            raise ScriptError(f'line {number}: {type_name!r} is not a setting kind '
                              f'({", ".join(TYPES)})')
        if name in seen:
            raise ScriptError(f'line {number}: setting {name!r} is declared twice')
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


_LINK_LINE = re.compile(r'^\s*---@link\s+([A-Za-z_][A-Za-z0-9_]*)\s+([a-z_]+)\s+(one|many)\s*(.*)$')


def parse_links(text: str) -> list:
    """The links a script declares (``---@link`` lines), as bozkit.links kinds."""
    from . import links

    out, seen = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith('---@link'):
            continue
        match = _LINK_LINE.match(line)
        if not match:
            raise ScriptError(f'line {number}: write ---@link <name> <kind> one|many "<label>"')
        name, kind, count, rest = match.groups()
        if kind not in links.OBJECT_KINDS:
            raise ScriptError(f'line {number}: {kind!r} is not an object kind '
                              f'({", ".join(links.OBJECT_KINDS)})')
        if name in seen or name in links.BY_NAME:
            raise ScriptError(f'line {number}: link {name!r} is declared twice or is built in')
        seen.add(name)
        label = ' '.join(q or p for q, p in _TOKEN.findall(rest))
        out.append(links.script_kind(name, kind, count == 'many', label))
    return out


def read_links(path: str | Path) -> list:
    try:
        return parse_links(Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise ScriptError(f'cannot read {path}: {exc}') from exc


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


TEMPLATE = '''-- {name}: attached to an object; returns its class. self is that object.
local {name} = boz.Prefab:extend("{name}")

---@setting message text "{name} was used" "What to print when it is used"

-- The level started.
function {name}:start()
end

-- Its volumes: on_enter / on_exit (Trigger), on_hit (Hit), on_use (Use, its cost already paid).
-- volume is the volume's name in the prefab.
function {name}:on_use(player, volume)
    print(self.settings.message)
end

-- boz.send(name, data) from any script, and game events (round_started, power_on, ...).
-- Fields you set on self (self.count = 3) are kept in saves.
function {name}:on_event(name, data)
end

return {name}
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
