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


EMPTY_TEMPLATE = '''local {name} = boz.{parent}:extend("{name}")

return {name}
'''

OBJECT_TEMPLATE = '''-- {name}: {label}, changed by this script. self is that object.
local {name} = boz.{parent}:extend("{name}")

-- The level started.
function {name}:start()
{start}end
{hooks}
return {name}
'''

START_PARENT = '''    boz.{parent}.start(self)     -- keep what it does at the start
'''
OWN_START = ('Debris',)   # classes with a start() of their own, which a script must pass on

USE_HOOK = '''
-- A player used it. This hands the use back to the game, which pays and runs it. Leave the line
-- out and nothing happens. Note the dot, and self passed first.
function {name}:on_use(player)
    boz.{parent}.on_use(self, player)
end
'''


def _after(hook: str, arguments: str, comment: str) -> str:
    return f'''
-- {comment}
function {{name}}:{hook}({arguments})
end
'''


VOLUME_HOOKS = '''
-- A Use volume: a player pressed use (its cost already paid).
function {name}:on_use(player)
end

-- A Hit volume: it was shot.
function {name}:on_hit(player)
end

-- A Trigger volume: someone came in, or left. who.zombie is true for a zombie.
function {name}:on_enter(who)
end

function {name}:on_exit(who)
end
'''

# The classes a script can extend: class, what it is, the hooks its template starts with.
OBJECT_CLASSES = (
    ('Door', 'Door', USE_HOOK + _after('on_opened', 'player', 'It opened.')),
    ('Debris', 'Debris', USE_HOOK + _after('on_opened', 'player', 'It opened.')),
    ('Perk', 'Perk machine', USE_HOOK + _after('on_bought', 'player, perk', 'A player bought it.')),
    ('MysteryBox', 'Mystery box',
     USE_HOOK + _after('on_spun', 'player', 'A player spun it.')
     + _after('on_weapon', 'player, weapon', 'The box picked a weapon.')),
    ('PackAPunch', 'Pack-a-Punch',
     USE_HOOK + _after('on_upgraded', 'player, weapon', 'A weapon went in.')),
    ('PowerSwitch', 'Power switch', USE_HOOK + _after('on_on', 'player', 'The power came on.')),
    ('TrapSwitch', 'Trap switch',
     USE_HOOK + _after('on_activated', 'player', 'A player ran its traps.')
     + _after('on_cooled', '', 'Its trap is ready again.')),
    ('Trap', 'Trap', _after('on_cooled', '', 'It is ready again.')),
    ('WallBuy', 'Wall buy',
     USE_HOOK + _after('on_bought', 'player, weapon', 'A player bought the weapon or its ammo.')),
    ('Barricade', 'Barricade', USE_HOOK + _after('on_repaired', 'player', 'A player put a board back.')),
    ('ZombieSpawn', 'Zombie spawn', ''),
    ('Volume', 'Volume', VOLUME_HOOKS),
)


def stub(name: str, template: str = 'prefab', parent: str = 'Prefab') -> str:
    """A new script called *name*: template 'empty' (just the class), 'prefab' (a basic prefab
    with its hooks) or 'object' (extends *parent*, one of OBJECT_CLASSES, with that class's
    hooks). 'empty' extends *parent* too."""
    if not NAME_RE.fullmatch(name):
        raise ScriptError(f'script name {name!r}: use letters, digits and _')
    if template == 'empty':
        return EMPTY_TEMPLATE.format(name=name, parent=parent)
    if template == 'object':
        for class_name, label, hooks in OBJECT_CLASSES:
            if class_name == parent:
                start = START_PARENT.format(parent=parent) if parent in OWN_START else ''
                return OBJECT_TEMPLATE.format(name=name, parent=parent, label=label, start=start,
                                              hooks=hooks.format(name=name, parent=parent))
        raise ScriptError(f'no object class {parent!r}')
    return TEMPLATE.format(name=name)


def script_path(name: str) -> str:
    """The script called *name*, relative to scripts/."""
    return f'prefabs/{name}.lua'


def new_script(scripts: str | Path, name: str, template: str = 'prefab',
               parent: str = 'Prefab') -> str:
    """Create scripts/prefabs/<name>.lua (unless it exists; see stub); returns its path relative
    to scripts/ ('prefabs/<name>.lua')."""
    relative = script_path(name)
    path = Path(scripts) / relative
    if not path.exists():
        text = stub(name, template, parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    return relative


def list_scripts(scripts: str | Path) -> list[str]:
    """Scripts in scripts/prefabs, relative to scripts/."""
    folder = Path(scripts) / 'prefabs'
    return sorted(f'prefabs/{p.name}' for p in folder.glob('*.lua')) if folder.is_dir() else []
