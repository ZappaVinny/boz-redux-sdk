"""The Game tab: the map's rules (bozkit.game, source/game.json), by what a player meets.

- Level: the name players see, the loading screen, the map picture for the launcher's PLAY
  screen, the starting weapon, power on at the start, another map's special behaviour.
- Rounds: the modes table (solo easy/normal/hard, co-op 2-4 players: which round set each plays,
  with zombies and health multipliers) and the round sets: a table of rounds ending in
  "After that", which repeats and grows. A mode on "the base map's own" plays the base level's
  rounds and nothing is copied into the project.
- Special rounds: dog rounds (and Ascension's monkeys) of the round set.
- Zombies, Points, Power-ups, Mystery box: the game's settings.

Every value shows the base map's (greyed) until it is changed; a changed one has its own reset.
game.check runs on each change and feeds the Problems panel. Hook scripts are in the Scripts
tab's sidebar.
"""
from __future__ import annotations

import copy
import shutil
import tomllib
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, IntVectorProperty, PointerProperty, StringProperty)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from . import game as editor_game, link

from ._bozkit import game, group, weapons as wp, world as bworld
from ._bozkit import project as sdk_project
from ._bozkit import hashing
iw_hash = hashing.iw_hash

WORKSPACE = "Game"
BASE = "__base__"          # a mode on the base level's own rounds (game.BASE_SET)
MODE_LABEL = dict(game.MODES)
_state: dict = {"base": {}, "base_rounds": {}, "names": None, "loading": False, "items": {}}

SPECIAL_CLASS_ITEMS = [("CWaveSpeciality", "Special round", "Dogs or any zombie type"),
                       ("CWaveMonkey", "Monkey round", "Ascension's space monkeys (they need the "
                                                       "map's perk machines and lander)")]
HEALTH_ITEMS = [("game", "The game's formula", "10 x round x round - 150, times the mode's health x"),
                ("grow", "Grows x per round", "The round's health times its health x each round")]
MODE_ITEMS = [(key, label, label) for key, label in game.MODES]
# Columns of the rounds table: (row property, wave field, header, ms shown as seconds).
COLUMNS = [("zombies", "m_ZombieCount", "Zombies", False),
           ("health", "m_ZombieHealth", "Health", False),
           ("at_once", "m_MaxActive", "At once", False),
           ("spawn", "m_TimeOut", "Spawn every s", True),
           ("pause", "m_WaveTimeout", "Break after s", True),
           ("delay", "m_StartingTimer", "Start delay s", True)]
TABLE_FIELDS = {field for _p, field, _h, _s in COLUMNS}
DETAIL_SKIP = TABLE_FIELDS | {"m_ZombieWalk", "m_ZombieWalkFast", "m_ZombieRun", "m_ZombieSprint"}
GROWTH = ("m_ZombieCountMultiplier", "m_PoweredZombieCountMultiplier", "m_MaxActiveMultiplier",
          "m_ZombieHealthMultiplier", "m_TimeOutMultiplier", "m_StartingWave")
SPECIAL_FIELDS = ("m_HellhoundWave", "m_ZombieTypes", "m_healthBase", "m_players2ZombieNumber",
                  "m_MaxActive", "m_minNormalWavesInterval", "m_maxNormalWavesInterval", "m_chance",
                  "m_repeatTimes", "m_TimeOut", "m_StartingTimer", "m_WaveTimeout", "m_FogConfig",
                  "m_monkeyLanderHash")


# The project and the base level -------------------------------------------------------------

def names() -> dict:
    if _state["names"] is None:
        try:
            _state["names"] = dict(wp.known_names())
        except Exception:
            _state["names"] = {}
    return _state["names"]


def name_of(value: int) -> str:
    if not value:
        return ""
    return names().get(value, f"0x{value:08x}")


def hash_of(text: str) -> int:
    text = text.strip()
    if not text:
        return 0
    if text.lower().startswith("0x"):
        try:
            return int(text, 16) & 0xffffffff
        except ValueError:
            return 0
    return iw_hash(text)


def load() -> dict:
    """game.json (a fresh copy; read again only when the file changed: panels draw often)."""
    source = link.source_dir()
    if not source:
        return {}
    file = game.path(source)
    try:
        stat = file.stat()
        key = (str(file), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(file), 0, 0)
    if _state.get("loaded_key") != key:
        try:
            # Older projects: modes still on a copy of the base's rounds play the base's own.
            _state["loaded"] = game.simplify(game.load(source), base_rounds())
        except game.GameError as exc:
            print(f"boz_suite: game: {exc}")
            _state["loaded"] = {}
        _state["loaded_key"] = key
    return copy.deepcopy(_state["loaded"])


def save(data: dict) -> None:
    source = link.source_dir()
    if source is None:
        return
    game.save(source, data)
    _state["loaded_key"] = None
    publish_problems(data)


def publish_problems(data: dict | None = None) -> None:
    """game.check's problems in the Problems panel (next to the world's own), as you edit."""
    scene = link.map_scene()
    problems = game.check(load() if data is None else data)
    others = [e for e in scene.get("boz_problems", []) if not str(e).endswith("\t" + link.GAME_TAB)]
    scene["boz_problems"] = others + [f"{message}\t{link.GAME_TAB}" for message in problems]


def base_level() -> str:
    source = link.source_dir()
    try:
        return bworld.load(source).base if source else "kino"
    except Exception:
        return "kino"


def base_label() -> str:
    return {"kino": "Kino", "ascension": "Ascension", "callofthedead": "Call of the Dead",
            "tutorial": "the tutorial"}.get(base_level(), base_level())


def base_statics():
    """The base level's statics group (rounds, zombie looks), or None without the game data."""
    level = base_level()
    if level not in _state["base"]:
        pack = editor_game.game_pack()
        statics = None
        if pack is not None:
            for name in (level, "kino"):
                try:
                    statics = group.parse(pack.read(f"levels/{name}/{name}_statics.group.bin"))
                    break
                except (KeyError, OSError, ValueError):
                    continue
        _state["base"][level] = statics
    return _state["base"][level]


def base_rounds() -> dict | None:
    """read_rounds of the base level (its six chains and special rounds), or None."""
    level = base_level()
    if level not in _state["base_rounds"]:
        statics = base_statics()
        try:
            _state["base_rounds"][level] = game.read_rounds(statics) if statics is not None else None
        except game.GameError:
            _state["base_rounds"][level] = None
    return _state["base_rounds"][level]


def rounds_data(data: dict) -> dict:
    rounds = data.setdefault("rounds", {})
    rounds.setdefault("sets", [])
    rounds.setdefault("modes", game.default_modes())
    for key in game.MODE_KEYS:
        rounds["modes"].setdefault(key, game.default_modes()[key])
    return rounds


def current_set(data: dict) -> dict | None:
    name = link.map_scene().boz_game_set
    return game.set_named(data.get("rounds") or {}, name) if name else None


def base_chain(mode: str) -> list:
    base = base_rounds()
    return (base or {}).get("chains", {}).get(mode) or []


def base_wave(entry: dict | None, index: int) -> dict | None:
    """The base round a set's round is compared with: the same round of the base mode it was
    copied from (its "After that" with the base's last)."""
    if entry is None or not entry.get("from"):
        return None
    chain = base_chain(entry["from"])
    count = len(entry.get("rounds") or [])
    if not chain:
        return None
    if index == count - 1:
        return chain[-1]
    return chain[index] if index < len(chain) - 1 else None


def base_special(entry: dict | None, index: int) -> dict | None:
    if entry is None or not entry.get("from"):
        return None
    mode = game.MODE_KEYS.index(entry["from"])
    specials = [w for w in (base_rounds() or {}).get("specials") or [] if int(w.get("m_waveType", 1)) == mode]
    return specials[index] if index < len(specials) else None


def shown_rounds(data: dict) -> tuple[list, list, bool]:
    """(rounds, special rounds, editable) the tables show: the chosen set's, else the base
    level's for the preview mode (read only)."""
    entry = current_set(data)
    if entry is not None:
        entry = game.normalize_set(entry)
        return entry["rounds"], entry["specials"], True
    mode = link.map_scene().boz_game_preview
    index = game.MODE_KEYS.index(mode)
    specials = [w for w in (base_rounds() or {}).get("specials") or [] if int(w.get("m_waveType", 1)) == index]
    return base_chain(mode), specials, False


def selected(collection, index):
    return collection[index] if 0 <= index < len(collection) else None


# Waves in forms ----------------------------------------------------------------------------

def _is_name_field(field) -> bool:
    return field.unit in ("entity name", "fog config name")


def _seconds(field) -> bool:
    return field.unit == "ms"


def _wave_props() -> dict:
    annotations = {}
    for field in game.FIELDS:
        description = f"{field.help} ({'seconds' if _seconds(field) else field.unit})" if field.unit else field.help
        top = game.MAXIMA.get(field.name)
        if field.name in game.SPEEDS:
            annotations[field.name] = FloatProperty(name=field.label, description=description, min=0.0,
                                                    max=1.0, subtype="FACTOR", update=_speed_changed)
        elif field.type == "float" or _seconds(field):
            limit = top / 1000.0 if _seconds(field) else top
            annotations[field.name] = FloatProperty(name=field.label, description=description, min=0.0,
                                                    soft_max=limit or 10.0, max=limit or 1e6,
                                                    precision=2, update=_wave_changed)
        elif field.type == "bool":
            annotations[field.name] = BoolProperty(name=field.label, description=description,
                                                   update=_wave_changed)
        elif field.name == "m_players2ZombieNumber":
            annotations[field.name] = IntVectorProperty(name=field.label, description=description, size=4,
                                                        min=0, max=top, update=_wave_changed)
        elif field.type in ("unsigned int", "CParsableEnumManager::SpecialityWaveType") and not _is_name_field(field):
            annotations[field.name] = IntProperty(name=field.label, description=description, min=0,
                                                  max=top or 2 ** 31 - 1, update=_wave_changed)
        else:
            annotations[field.name] = StringProperty(name=field.label, description=description,
                                                     update=_wave_changed)
    annotations["special_class"] = EnumProperty(name="Kind", description="The kind of special round",
                                                items=SPECIAL_CLASS_ITEMS, update=_wave_changed)
    return annotations


def form_value(field, value):
    """A wave value as the form shows it."""
    if field.type == "std::vector<unsigned int>":
        if field.name == "m_players2ZombieNumber":
            return tuple((list(value) + [0, 0, 0, 0])[:4])
        if field.unit == "entity names":
            return ", ".join(name_of(v) for v in value)
        return ", ".join(str(v) for v in value)
    if _is_name_field(field):
        return name_of(int(value))
    if _seconds(field):
        return int(value) / 1000.0
    if field.type == "float":
        return float(value)
    if field.type == "bool":
        return bool(value)
    return int(value)


def wave_value(field, value):
    """A form value as the wave stores it."""
    if field.type == "std::vector<unsigned int>":
        if field.name == "m_players2ZombieNumber":
            numbers = [int(v) for v in value]
            while len(numbers) > 1 and numbers[-1] == 0:
                numbers.pop()
            return numbers
        parts = [p for p in str(value).replace(";", ",").split(",") if p.strip()]
        if field.unit == "entity names":
            return [hash_of(p) for p in parts]
        return [int(p) for p in parts if p.strip().isdigit()]
    if _is_name_field(field):
        return hash_of(value)
    if _seconds(field):
        return int(round(float(value) * 1000))
    if field.type == "float":
        return round(float(value), 4)
    if field.type == "bool":
        return bool(value)
    return int(value)


def _to_form(form, wave: dict) -> None:
    _state["loading"] = True
    try:
        for field in game.FIELDS:
            value = wave.get(field.name, field.default)
            setattr(form, field.name, form_value(field, list(value) if isinstance(value, tuple) else value))
        if wave.get("class") in game.SPECIAL_CLASSES:
            form.special_class = wave["class"]
    finally:
        _state["loading"] = False


def _is_special_form(form) -> bool:
    return form.as_pointer() == link.map_scene().boz_game_special.as_pointer()


def _edit_wave(form, fn) -> None:
    """Apply fn(wave) to the round or special round the form shows, and save."""
    scene = link.map_scene()
    data = load()
    entry = current_set(data)
    if entry is None:
        return
    if _is_special_form(form):
        waves, index = entry.setdefault("specials", []), scene.boz_game_special_index
    else:
        waves, index = entry.setdefault("rounds", []), scene.boz_game_round_index
    if not 0 <= index < len(waves):
        return
    fn(waves[index])
    entry.update(game.normalize_set(entry))
    save(data)


def _wave_changed(self, context):
    if _state["loading"]:
        return
    special = _is_special_form(self)

    def write(wave):
        if special:
            wave["class"] = self.special_class
        for field in game.fields_of(wave.get("class", "CWave")):
            if field.name in TABLE_FIELDS and not special:
                continue                     # the table's columns write those
            wave[field.name] = wave_value(field, getattr(self, field.name))

    _edit_wave(self, write)
    refresh_lists(context, keep_forms=True)


def _speed_changed(self, context):
    """The four speed shares always add up to 100%: the others make room for a change."""
    if _state["loading"]:
        return
    values = {name: getattr(self, name) for name in game.SPEEDS}
    changed = next((n for n in game.SPEEDS if abs(values[n] - _state.get("speeds", {}).get(n, -1)) > 1e-6), None)
    if changed is not None:
        rest = [n for n in game.SPEEDS if n != changed]
        room, others = max(0.0, 1.0 - values[changed]), sum(values[n] for n in rest)
        _state["loading"] = True
        try:
            for name in rest:
                share = values[name] / others if others > 0 else 1.0 / len(rest)
                setattr(self, name, round(room * share, 4))
        finally:
            _state["loading"] = False
    _state["speeds"] = {name: getattr(self, name) for name in game.SPEEDS}
    _wave_changed(self, context)


BOZ_GameWave = type("BOZ_GameWave", (PropertyGroup,), {"__annotations__": _wave_props()})


# The rounds table ----------------------------------------------------------------------------

def _row_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    data = load()
    entry = current_set(data)
    if entry is None or not 0 <= self.index < len(entry.get("rounds") or []):
        return
    wave = entry["rounds"][self.index]
    for prop, field, _header, seconds in COLUMNS:
        value = getattr(self, prop)
        wave[field] = int(round(value * 1000)) if seconds else int(value)
    save(data)
    if scene.boz_game_round_index == self.index:
        load_forms(context)


def _row_props() -> dict:
    annotations = {"index": IntProperty(), "label": StringProperty()}
    for prop, field, header, seconds in COLUMNS:
        f = game.FIELD[field]
        top = game.MAXIMA[field]
        if seconds:
            annotations[prop] = FloatProperty(name=header, description=f.help, min=0.0, max=top / 1000.0,
                                              precision=1, step=50, update=_row_changed)
        else:
            annotations[prop] = IntProperty(name=header, description=f.help, min=0, max=top,
                                            update=_row_changed)
    return annotations


BOZ_GameRoundRow = type("BOZ_GameRoundRow", (PropertyGroup,), {"__annotations__": _row_props()})


class BOZ_GameRound(PropertyGroup):
    detail: StringProperty()


# Modes ---------------------------------------------------------------------------------------

def _mode_changed(self, context):
    if _state["loading"]:
        return
    data = load()
    rounds = rounds_data(data)
    mode = rounds["modes"][self.key]
    mode["zombies"], mode["health"] = round(self.zombies, 3), round(self.health, 3)
    save(data)


class BOZ_GameMode(PropertyGroup):
    key: StringProperty()
    label: StringProperty()
    round_set: StringProperty()
    zombies: FloatProperty(name="Zombies x", min=game.MULTIPLIER_RANGE[0], max=game.MULTIPLIER_RANGE[1],
                           default=1.0, precision=2, step=10, update=_mode_changed,
                           description="Every round's zombie count times this in this mode")
    health: FloatProperty(name="Health x", min=game.MULTIPLIER_RANGE[0], max=game.MULTIPLIER_RANGE[1],
                          default=1.0, precision=2, step=10, update=_mode_changed,
                          description="Every zombie's health times this in this mode")


# Zombie looks --------------------------------------------------------------------------------

def _look_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    used = [item.hash & 0xffffffff for item in scene.boz_game_looks if item.used]
    base = {item.hash & 0xffffffff for item in scene.boz_game_looks if item.base_used}
    data = load()
    if used and set(used) != base:
        data.setdefault("zombies", {})["used"] = used
    else:
        data.pop("zombies", None)       # none ticked, or the base level's own: nothing stored
    save(data)


class BOZ_GameLook(PropertyGroup):
    hash: IntProperty()
    detail: StringProperty()
    base_used: BoolProperty()
    used: BoolProperty(name="Spawns", description="This look can spawn in the map", update=_look_changed)


class BOZ_GameHook(PropertyGroup):
    label: StringProperty()
    data: StringProperty()
    exists: BoolProperty()


# Settings (console variables, score table, power-ups, box) -----------------------------------

def _cvar_seconds(name: str) -> bool:
    return game.CVARS[name][1] == "ms"


def cvar_default(name: str):
    default = game.CVARS[name][3]
    return default / 1000.0 if _cvar_seconds(name) else default


def _economy_props() -> dict:
    annotations = {}
    for name, (label, unit, help_text, default) in game.CVARS.items():
        top = game.CVAR_MAX[name]
        if _cvar_seconds(name):
            annotations[name] = FloatProperty(name=label, description=f"{help_text} (seconds)", min=0.0,
                                              max=top / 1000.0, default=default / 1000.0, precision=1,
                                              update=_economy_changed)
        elif isinstance(default, float):
            annotations[name] = FloatProperty(name=label, description=f"{help_text} ({unit})", min=0.0,
                                              max=float(top), default=default, update=_economy_changed)
        else:
            annotations[name] = IntProperty(name=label, description=f"{help_text} ({unit})", min=0,
                                            max=int(top), default=default, update=_economy_changed)
    for i, (key, label) in enumerate(zip(game.PICKUPS, game.PICKUP_LABELS)):
        annotations["pickup_" + key] = IntProperty(name=label, min=0, max=game.PICKUP_MAX,
                                                   default=game.PICKUP_WEIGHTS[i], subtype="FACTOR",
                                                   description="How likely this power-up is against the "
                                                               "others (0: never)",
                                                   update=_economy_changed)
    for action, label, points in game.SCORES:
        annotations["score_" + action] = IntProperty(name=label, min=0, max=game.SCORE_MAX, default=points,
                                                     description="Points for this", update=_economy_changed)
    for action, label, limit in game.SCORE_LIMITS:
        annotations["limit_" + action] = IntProperty(name=label, min=0, max=game.SCORE_MAX, default=limit,
                                                     description="At most this x the round number in a round",
                                                     update=_economy_changed)
    for name, (label, stock) in game.BOX_FIELDS.items():
        annotations["box_" + name] = IntProperty(name=label, min=0, max=game.BOX_MAX[name], default=stock,
                                                 description="A box given its own value in the World tab "
                                                             "keeps it",
                                                 update=_economy_changed)
    return annotations


def load_economy(context) -> None:
    form = link.map_scene().boz_game_economy
    economy = load().get("economy") or {}
    _state["loading"] = True
    try:
        cvars = economy.get("cvars") or {}
        for name, (_label, _unit, _help, default) in game.CVARS.items():
            value = cvars.get(name, default)
            setattr(form, name, value / 1000.0 if _cvar_seconds(name) else type(default)(value))
        weights = game.pickup_weights(economy) or game.PICKUP_WEIGHTS
        for i, key in enumerate(game.PICKUPS):
            setattr(form, "pickup_" + key, weights[i])
        scores = economy.get("scores") or {}
        for action, _label, points in game.SCORES:
            setattr(form, "score_" + action, int(scores.get(action, points)))
        limits = economy.get("score_limits") or {}
        for action, _label, limit in game.SCORE_LIMITS:
            setattr(form, "limit_" + action, int(limits.get(action, limit)))
        box = economy.get("box") or {}
        for name, (_label, stock) in game.BOX_FIELDS.items():
            setattr(form, "box_" + name, int(box.get(name, stock)))
    finally:
        _state["loading"] = False


def _economy_changed(self, context):
    """Only values that differ from the game's are stored (no ticks)."""
    if _state["loading"]:
        return
    form = self
    data = load()
    economy = {}
    cvars = {}
    for name, (_label, _unit, _help, default) in game.CVARS.items():
        value = getattr(form, name)
        if _cvar_seconds(name):
            value = int(round(value * 1000))
        elif isinstance(default, float):
            value = round(value, 4)
        if value != default:
            cvars[name] = value
    if cvars:
        economy["cvars"] = cvars
    weights = {key: getattr(form, "pickup_" + key) for key in game.PICKUPS}
    weights = {k: w for (k, w), d in zip(weights.items(), game.PICKUP_WEIGHTS) if w != d}
    if weights:
        economy["pickups"] = weights
    scores = {a: getattr(form, "score_" + a) for a, _l, p in game.SCORES if getattr(form, "score_" + a) != p}
    if scores:
        economy["scores"] = scores
    limits = {a: getattr(form, "limit_" + a) for a, _l, p in game.SCORE_LIMITS if getattr(form, "limit_" + a) != p}
    if limits:
        economy["score_limits"] = limits
    box = {n: getattr(form, "box_" + n) for n, (_l, stock) in game.BOX_FIELDS.items()
           if getattr(form, "box_" + n) != stock}
    if box:
        economy["box"] = box
    if economy:
        data["economy"] = economy
    else:
        data.pop("economy", None)
    save(data)


BOZ_GameEconomy = type("BOZ_GameEconomy", (PropertyGroup,), {"__annotations__": _economy_props()})


# Refresh -------------------------------------------------------------------------------------

def _round_label(count: int, index: int) -> str:
    return "After that" if index == count - 1 else f"Round {index + 1}"


def _special_label(wave: dict, index: int) -> tuple[str, str]:
    kind = "Monkey round" if wave.get("class") == "CWaveMonkey" else (
        "Dog round" if wave.get("m_HellhoundWave") else "Special round")
    low, high = wave.get("m_minNormalWavesInterval", 3), wave.get("m_maxNormalWavesInterval", 5)
    every = f"every {low}-{high} rounds" if high < 1000 else f"after {low}+ rounds"
    return f"{index + 1}. {kind}", f"{every}, {wave.get('m_chance', 50)}%, {wave.get('m_repeatTimes', 1)}x"


def refresh_lists(context, keep_forms: bool = False) -> None:
    scene = link.map_scene()
    data = load()
    rounds = data.get("rounds") or {}
    _state["loading"] = True
    try:
        if scene.boz_game_set and game.set_named(rounds, scene.boz_game_set) is None:
            scene.boz_game_set = ""
        scene.boz_game_set_rename = scene.boz_game_set
        scene.boz_game_modes.clear()
        for key, label in game.MODES:
            mode = game.mode_of(rounds, key)
            item = scene.boz_game_modes.add()
            item.key, item.label, item.round_set = key, label, mode["set"]
            item.zombies, item.health = float(mode["zombies"]), float(mode["health"])
        chain, specials, _editable = shown_rounds(data)
        scene.boz_game_rounds.clear()
        for i, wave in enumerate(chain):
            item = scene.boz_game_rounds.add()
            item.index, item.label = i, _round_label(len(chain), i)
            for prop, field, _header, seconds in COLUMNS:
                value = wave.get(field, game.FIELD[field].default)
                setattr(item, prop, int(value) / 1000.0 if seconds else int(value))
        scene.boz_game_specials.clear()
        for i, wave in enumerate(specials):
            item = scene.boz_game_specials.add()
            item.name, item.detail = _special_label(wave, i)
        entry = current_set(data)
        scene.boz_game_after_health = (entry or {}).get("after_health", "game")
        scene.boz_game_round_index = min(scene.boz_game_round_index, max(len(scene.boz_game_rounds) - 1, 0))
        scene.boz_game_special_index = min(scene.boz_game_special_index, max(len(scene.boz_game_specials) - 1, 0))
    finally:
        _state["loading"] = False
    if not keep_forms:
        load_forms(context)


def load_forms(context) -> None:
    scene = link.map_scene()
    chain, specials, _editable = shown_rounds(load())
    if 0 <= scene.boz_game_round_index < len(chain):
        _to_form(scene.boz_game_round, chain[scene.boz_game_round_index])
        _state["speeds"] = {name: getattr(scene.boz_game_round, name) for name in game.SPEEDS}
    if 0 <= scene.boz_game_special_index < len(specials):
        _to_form(scene.boz_game_special, specials[scene.boz_game_special_index])


def refresh_looks(context) -> None:
    """Every map's zombie looks (any works on any map), the base level's first."""
    scene = link.map_scene()
    statics = base_statics()
    pack = editor_game.game_pack()
    _state["loading"] = True
    try:
        scene.boz_game_looks.clear()
        if statics is None:
            return
        base = game.read_zombie_types(statics, names())
        used = load().get("zombies", {}).get("used") or base["used"]
        own = {look["hash"] for look in base["all"]}
        looks = [dict(look, map=base_level()) for look in base["all"]]
        if pack is not None:
            looks += [look for look in game.all_zombie_types(pack, names()) if look["hash"] not in own]
        for look in looks:
            item = scene.boz_game_looks.add()
            item.name = look["label"]
            item.hash = look["hash"] - (1 << 32) if look["hash"] >= 1 << 31 else look["hash"]
            where = "this map's base" if look["hash"] in own else (look.get("map") or "shared")
            item.detail = f"{where} · {len(look['models'])} body parts"
            item.base_used = look["hash"] in base["used"]
            item.used = look["hash"] in used
    finally:
        _state["loading"] = False


def refresh_hooks(context) -> None:
    scene = link.map_scene()
    root = link.project_root()
    scene.boz_game_hooks.clear()
    for name, label, data in game.HOOK_EVENTS:
        item = scene.boz_game_hooks.add()
        item.name, item.label, item.data = name, label, data
        item.exists = bool(root and (root / "scripts" / "hooks" / f"{name}.lua").is_file())


def refresh(context) -> None:
    refresh_lists(context)
    refresh_looks(context)
    refresh_hooks(context)
    load_economy(context)
    load_level(context)
    publish_problems()


# Level ---------------------------------------------------------------------------------------

def _manifest() -> dict | None:
    root = link.project_root()
    if root is None:
        return None
    try:
        return tomllib.loads((root / sdk_project.PROJECT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_level(context) -> None:
    scene = link.map_scene()
    data = load()
    manifest = _manifest() or {}
    _state["loading"] = True
    try:
        scene.boz_game_display_name = manifest.get("mod", {}).get("name", "")
        scene.boz_game_power_on = bool((data.get("level") or {}).get("power_on"))
        scene.boz_game_loading = (data.get("level") or {}).get("loading_image", "")
        scene.boz_game_map_picture = (data.get("level") or {}).get("map_picture", "")
        scene.boz_game_behaves_like = (data.get("level") or {}).get("behaves_like", "") or "none"
    finally:
        _state["loading"] = False


def _level_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    data = load()
    level = data.setdefault("level", {})
    if scene.boz_game_power_on:
        level["power_on"] = True
    else:
        level.pop("power_on", None)
    like = scene.boz_game_behaves_like
    if like == "none":
        level.pop("behaves_like", None)
    else:
        level["behaves_like"] = like
    if not level:
        data.pop("level", None)
    save(data)


def _display_name_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    manifest, root = _manifest(), link.project_root()
    name = scene.boz_game_display_name.strip()
    if manifest is None or root is None or not name:
        return
    manifest.setdefault("mod", {})["name"] = name
    try:
        sdk_project.save_manifest(root, manifest)
    except sdk_project.ProjectError as exc:
        print(f"boz_suite: game: {exc}")


def _set_chosen(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    scene.boz_game_round_index = 0
    scene.boz_game_special_index = 0
    refresh_lists(context)


def _preview_changed(self, context):
    if not _state["loading"]:
        refresh_lists(context)


def _round_selected(self, context):
    if not _state["loading"]:
        load_forms(context)


def _after_health_changed(self, context):
    if _state["loading"]:
        return
    data = load()
    entry = current_set(data)
    if entry is not None:
        entry["after_health"] = link.map_scene().boz_game_after_health
        save(data)


def _set_renamed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    old, new = scene.boz_game_set, scene.boz_game_set_rename.strip()[:game.SET_NAME_MAX]
    data = load()
    rounds = rounds_data(data)
    entry = game.set_named(rounds, old)
    if entry is None or not new or new == old or game.set_named(rounds, new) is not None:
        _state["loading"] = True
        scene.boz_game_set_rename = old
        _state["loading"] = False
        return
    entry["name"] = new
    for mode in rounds["modes"].values():
        if mode.get("set") == old:
            mode["set"] = new
    save(data)
    _state["loading"] = True
    scene.boz_game_set = new
    _state["loading"] = False
    refresh_lists(context)


# Operators -----------------------------------------------------------------------------------

class BOZ_OT_game_refresh(Operator):
    bl_idname = "boz.game_refresh"
    bl_label = "Show the game rules"
    bl_description = "Read the map's rules (and the base level's where the map has none)"

    def execute(self, context):
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_game_reset(Operator):
    bl_idname = "boz.game_reset"
    bl_label = "Back to the base map's"
    bl_description = "Set this value back to the base map's"
    bl_options = {"INTERNAL"}

    owner: StringProperty()      # a path from the map's scene ("boz_game_economy", ...)
    attr: StringProperty()
    value: StringProperty()      # Python literal

    def execute(self, context):
        import ast
        scene = link.map_scene()
        try:
            owner = scene.path_resolve(self.owner) if self.owner else scene
            value = ast.literal_eval(self.value)
            current = getattr(owner, self.attr)
            if isinstance(current, (int, float, bool, str)):
                value = type(current)(value)
            setattr(owner, self.attr, value)
        except (ValueError, TypeError, AttributeError, SyntaxError) as exc:
            self.report({"ERROR"}, f"Could not reset: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


def _set_items(self, context):
    rounds = load().get("rounds") or {}
    items = [(BASE, f"{base_label()}'s own", "The base map's rounds for this mode (nothing copied)")]
    items += [(s["name"], s["name"], "A round set of this map") for s in rounds.get("sets") or []]
    _state["items"]["sets"] = items          # Blender needs the strings kept alive
    return items


class BOZ_OT_game_mode_set(Operator):
    bl_idname = "boz.game_mode_set"
    bl_label = "Rounds"
    bl_description = "Which rounds this mode plays"
    bl_options = {"INTERNAL"}

    mode: StringProperty()
    choice: StringProperty()      # a set's name, or BASE

    def execute(self, context):
        data = load()
        rounds = rounds_data(data)
        rounds["modes"][self.mode]["set"] = "" if self.choice == BASE else self.choice
        save(data)
        refresh_lists(context)
        return {"FINISHED"}


class BOZ_OT_game_set_show(Operator):
    bl_idname = "boz.game_set_show"
    bl_label = "Show"
    bl_description = "The round set the tables below show and edit"
    bl_options = {"INTERNAL"}

    choice: StringProperty()

    def execute(self, context):
        link.map_scene().boz_game_set = "" if self.choice == BASE else self.choice
        return {"FINISHED"}


def _source_items(self, context):
    items = [(f"mode:{key}", f"{base_label()}'s {label.lower()}", f"A copy of the base map's {label.lower()} rounds")
             for key, label in game.MODES if base_chain(key)]
    rounds = load().get("rounds") or {}
    items += [(f"set:{s['name']}", f"Copy of {s['name']}", "A copy of this round set")
              for s in rounds.get("sets") or []]
    if not items:
        items = [("empty", "Three rounds", "A short set to start from")]
    _state["items"]["sources"] = items
    return items


def _new_name(rounds: dict, wanted: str) -> str:
    name, number = wanted, 1
    while game.set_named(rounds, name) is not None:
        number += 1
        name = f"{wanted} {number}"
    return name


class BOZ_OT_game_set_add(Operator):
    bl_idname = "boz.game_set_add"
    bl_label = "New round set"
    bl_description = ("Make a round set of your own, starting as a copy of the base map's rounds "
                      "for a mode (or of another set)")

    source: StringProperty(name="From", default="mode:normal")   # "mode:<key>", "set:<name>", "empty"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        rounds = rounds_data(data)
        kind, _, value = self.source.partition(":")
        if kind == "mode":
            entry = {"name": _new_name(rounds, "Standard" if not rounds["sets"] else MODE_LABEL[value]),
                     "from": value, "rounds": copy.deepcopy(base_chain(value)),
                     "specials": [{k: v for k, v in w.items() if k != "m_waveType"}
                                  for w in (base_rounds() or {}).get("specials") or []
                                  if int(w.get("m_waveType", 1)) == game.MODE_KEYS.index(value)]}
        elif kind == "set" and game.set_named(rounds, value) is not None:
            entry = copy.deepcopy(game.set_named(rounds, value))
            entry["name"] = _new_name(rounds, value)
        else:
            entry = {"name": _new_name(rounds, "Standard"), "from": "",
                     "rounds": [{"class": "CWave", "m_ZombieCount": n, "m_MaxActive": min(n, 24),
                                 "m_ZombieHealth": h} for n, h in ((6, 150), (10, 250), (14, 350))]}
        entry = game.normalize_set(entry)
        rounds["sets"].append(entry)
        assigned = ""
        if kind == "mode" and game.mode_of(rounds, value)["set"] == game.BASE_SET:
            rounds["modes"][value]["set"] = entry["name"]       # what you copy is what that mode plays
            assigned = f"; {MODE_LABEL[value]} plays it now (pick it for other modes in the table)"
        save(data)
        scene.boz_game_set = entry["name"]
        refresh_lists(context)
        self.report({"INFO"}, f"Round set {entry['name']} made{assigned}")
        return {"FINISHED"}


class BOZ_MT_game_mode_set(Menu):
    bl_idname = "BOZ_MT_game_mode_set"
    bl_label = "Rounds"

    def draw(self, context):
        mode = getattr(context, "boz_game_mode", None)
        for value, label, _description in _set_items(None, context):
            op = self.layout.operator(BOZ_OT_game_mode_set.bl_idname, text=label)
            op.mode, op.choice = (mode.key if mode else "normal"), value


class BOZ_MT_game_set_show(Menu):
    bl_idname = "BOZ_MT_game_set_show"
    bl_label = "Round set"

    def draw(self, context):
        for value, label, _description in _set_items(None, context):
            text = f"{label} (view only)" if value == BASE else label
            self.layout.operator(BOZ_OT_game_set_show.bl_idname, text=text).choice = value


class BOZ_MT_game_set_add(Menu):
    bl_idname = "BOZ_MT_game_set_add"
    bl_label = "New round set from"

    def draw(self, context):
        for value, label, _description in _source_items(None, context):
            self.layout.operator(BOZ_OT_game_set_add.bl_idname, text=label).source = value


class BOZ_OT_game_set_remove(Operator):
    bl_idname = "boz.game_set_remove"
    bl_label = "Remove round set"
    bl_description = "Delete this round set; modes that played it go back to the base map's own"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        rounds = rounds_data(data)
        name = scene.boz_game_set
        rounds["sets"] = [s for s in rounds["sets"] if s.get("name") != name]
        for mode in rounds["modes"].values():
            if mode.get("set") == name:
                mode["set"] = ""
        save(data)
        scene.boz_game_set = ""
        return {"FINISHED"}


class BOZ_OT_game_round_add(Operator):
    bl_idname = "boz.game_round_add"
    bl_label = "Add a round"
    bl_description = "Add a round after the selected one (a copy of it; always before After that)"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        entry = current_set(data)
        if entry is None:
            return {"CANCELLED"}
        waves = entry.setdefault("rounds", [])
        if not waves:
            waves.append({"class": "CWave", "m_ZombieCount": 6, "m_MaxActive": 6})
            new_index = 0
        else:
            i = min(scene.boz_game_round_index, len(waves) - 1)
            new_index = min(i + 1, len(waves) - 1)       # After that stays last
            waves.insert(new_index, dict(waves[i]))
        entry.update(game.normalize_set(entry))
        save(data)
        scene.boz_game_round_index = new_index
        refresh_lists(context)
        return {"FINISHED"}


class BOZ_OT_game_round_remove(Operator):
    bl_idname = "boz.game_round_remove"
    bl_label = "Remove the round"
    bl_description = "Remove the selected round (a set keeps at least one: its After that)"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        entry = current_set(data)
        if entry is None:
            return {"CANCELLED"}
        waves = entry.setdefault("rounds", [])
        index = scene.boz_game_round_index
        if len(waves) > 1 and 0 <= index < len(waves):
            if index == len(waves) - 1:
                # Removing After that: the round before takes its growth.
                growth = {k: waves[index][k] for k in GROWTH if k in waves[index]}
                waves[index - 1].update(growth)
            del waves[index]
        entry.update(game.normalize_set(entry))
        save(data)
        refresh_lists(context)
        return {"FINISHED"}


class BOZ_OT_game_special_add(Operator):
    bl_idname = "boz.game_special_add"
    bl_label = "Add a special round"
    bl_description = "Add a dog round (a copy of the selected special round, if there is one)"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        entry = current_set(data)
        if entry is None:
            return {"CANCELLED"}
        specials = entry.setdefault("specials", [])
        current = selected(specials, scene.boz_game_special_index)
        wave = dict(current) if current else dog_round()
        if wave is None:
            self.report({"ERROR"}, "No dog round to copy: the asset library is missing")
            return {"CANCELLED"}
        wave.pop("m_waveType", None)
        specials.append(wave)
        save(data)
        scene.boz_game_special_index = len(specials) - 1
        refresh_lists(context)
        return {"FINISHED"}


class BOZ_OT_game_special_remove(Operator):
    bl_idname = "boz.game_special_remove"
    bl_label = "Remove the special round"
    bl_description = "Remove the selected special round"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        entry = current_set(data)
        if entry is None:
            return {"CANCELLED"}
        specials = entry.setdefault("specials", [])
        if 0 <= scene.boz_game_special_index < len(specials):
            del specials[scene.boz_game_special_index]
        save(data)
        refresh_lists(context)
        return {"FINISHED"}


def dog_round() -> dict | None:
    """A dog round as the game has one: the base level's, else Kino's."""
    pack = editor_game.game_pack()
    candidates = [base_rounds()]
    if pack is not None:
        try:
            candidates.append(game.read_rounds(group.parse(pack.read("levels/kino/kino_statics.group.bin"))))
        except (KeyError, OSError, ValueError, game.GameError):
            pass
    for rounds in candidates:
        found = next((w for w in (rounds or {}).get("specials") or [] if w.get("m_HellhoundWave")), None)
        if found is not None:
            return copy.deepcopy(found)
    return None


class BOZ_OT_game_loading_pick(Operator):
    bl_idname = "boz.game_loading_pick"
    bl_label = "Choose a picture"
    bl_description = "The picture shown while the map loads (PNG or JPG; shown full screen)"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = link.project_root()
        source = Path(self.filepath)
        if root is None or not source.is_file():
            return {"CANCELLED"}
        target = root / "source" / f"loading{source.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        data = load()
        data.setdefault("level", {})["loading_image"] = target.relative_to(root).as_posix()
        save(data)
        load_level(context)
        return {"FINISHED"}


class BOZ_OT_game_picture_pick(Operator):
    bl_idname = "boz.game_picture_pick"
    bl_label = "Choose the map picture"
    bl_description = ("The map's picture on the client launcher's PLAY screen (PNG or JPG, "
                      "16:9 looks best)")

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = link.project_root()
        source = Path(self.filepath)
        if root is None or not source.is_file():
            return {"CANCELLED"}
        _set_map_picture(context, root, source)
        return {"FINISHED"}


def _set_map_picture(context, root: Path, source: Path) -> None:
    target = root / "source" / f"map_picture{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    for old in target.parent.glob("map_picture.*"):
        if old.resolve() != source.resolve():
            old.unlink()
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    data = load()
    data.setdefault("level", {})["map_picture"] = target.relative_to(root).as_posix()
    save(data)
    load_level(context)


class BOZ_OT_game_picture_capture(Operator):
    bl_idname = "boz.game_picture_capture"
    bl_label = "Capture the 3D view"
    bl_description = ("Makes the map picture from the 3D view as it looks now (1280 x 720): "
                      "frame the shot first")

    def execute(self, context):
        root = link.project_root()
        area = next((a for a in context.screen.areas if a.type == "VIEW_3D"), None)
        region = area and next((r for r in area.regions if r.type == "WINDOW"), None)
        if root is None or region is None:
            self.report({"ERROR"}, "Open a 3D view to capture")
            return {"CANCELLED"}
        scene = context.scene
        render = scene.render
        saved = (render.filepath, render.resolution_x, render.resolution_y,
                 render.resolution_percentage, render.image_settings.file_format)
        shot = root / "source" / "map_capture.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        try:
            render.filepath = str(shot)
            render.resolution_x, render.resolution_y, render.resolution_percentage = 1280, 720, 100
            render.image_settings.file_format = "PNG"
            with context.temp_override(area=area, region=region):
                bpy.ops.render.opengl(write_still=True, view_context=True)
        finally:
            (render.filepath, render.resolution_x, render.resolution_y,
             render.resolution_percentage, render.image_settings.file_format) = saved
        if not shot.is_file():
            self.report({"ERROR"}, "The 3D view could not be captured")
            return {"CANCELLED"}
        _set_map_picture(context, root, shot)
        shot.unlink(missing_ok=True)
        self.report({"INFO"}, "Map picture captured")
        return {"FINISHED"}


class BOZ_OT_game_picture_clear(Operator):
    bl_idname = "boz.game_picture_clear"
    bl_label = "No map picture"
    bl_description = "The PLAY screen shows the map's name instead of a picture"

    def execute(self, context):
        root = link.project_root()
        data = load()
        image = (data.get("level") or {}).pop("map_picture", None)
        save(data)
        if root is not None and image:
            (root / image).unlink(missing_ok=True)
        load_level(context)
        return {"FINISHED"}


class BOZ_OT_game_loading_clear(Operator):
    bl_idname = "boz.game_loading_clear"
    bl_label = "Use the base level's"
    bl_description = "Show the base level's loading screen"

    def execute(self, context):
        data = load()
        (data.get("level") or {}).pop("loading_image", None)
        save(data)
        load_level(context)
        return {"FINISHED"}


class BOZ_OT_game_hook(Operator):
    bl_idname = "boz.game_hook"
    bl_label = "Hook script"
    bl_description = "Create this event's script (scripts/hooks) or open it"

    event: StringProperty()

    def execute(self, context):
        from . import objects
        root = link.project_root()
        if root is None:
            return {"CANCELLED"}
        path = root / "scripts" / "hooks" / f"{self.event}.lua"
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(game.hook_stub(self.event), encoding="utf-8", newline="\n")
        objects.show_script(context, path)
        refresh_hooks(context)
        return {"FINISHED"}


# Drawing -------------------------------------------------------------------------------------

def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) < 1e-3
    try:
        return tuple(a) == tuple(b)
    except TypeError:
        return a == b


def value_row(layout, owner_path: str, owner, attr: str, base, text=None, editable=True, **kwargs):
    """One value: greyed while it is the base map's, highlighted with a reset once changed."""
    row = layout.row(align=True)
    changed = base is not None and not _same(getattr(owner, attr), base)
    row.enabled = editable
    row.active = changed or base is None
    row.alert = False
    if text is None:
        row.prop(owner, attr, **kwargs)
    else:
        row.prop(owner, attr, text=text, **kwargs)
    if changed and editable:
        op = row.operator(BOZ_OT_game_reset.bl_idname, text="", icon="LOOP_BACK")
        op.owner, op.attr, op.value = owner_path, attr, repr(tuple(base) if isinstance(base, list) else base)
    else:
        row.label(text="", icon="BLANK1")
    return row


class _GamePanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == WORKSPACE


def _no_project(layout) -> bool:
    if link.source_dir() is None:
        layout.label(text="Open a map project to set its rules", icon="INFO")
        return True
    return False


def _problems(layout, prefixes: tuple[str, ...]) -> None:
    """This section's problems, under it (they also show in the Problems panel)."""
    for message in game.check(load()):
        if message.startswith(prefixes):
            layout.label(text=message, icon="ERROR")


class BOZ_PT_game_level(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_level"
    bl_label = "Level"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        layout.use_property_split = True
        layout.prop(scene, "boz_game_display_name")
        row = layout.row(align=True)
        row.label(text="Loading screen: " + (scene.boz_game_loading or "the base map's"), icon="IMAGE_DATA")
        row.operator(BOZ_OT_game_loading_pick.bl_idname, text="", icon="FILEBROWSER")
        if scene.boz_game_loading:
            row.operator(BOZ_OT_game_loading_clear.bl_idname, text="", icon="X")
        row = layout.row(align=True)
        row.label(text="Map picture: " + (scene.boz_game_map_picture or "none (PLAY shows the name)"),
                  icon="IMAGE_REFERENCE")
        row.operator(BOZ_OT_game_picture_capture.bl_idname, text="", icon="RESTRICT_RENDER_OFF")
        row.operator(BOZ_OT_game_picture_pick.bl_idname, text="", icon="FILEBROWSER")
        if scene.boz_game_map_picture:
            row.operator(BOZ_OT_game_picture_clear.bl_idname, text="", icon="X")
        from . import weapons_tab
        name, reserve = weapons_tab.start_weapon()
        layout.label(text=f"Starting weapon: {name} ({reserve} spare; Weapons tab)", icon="MOD_PHYSICS")
        value_row(layout, "", scene, "boz_game_power_on", False)
        value_row(layout, "", scene, "boz_game_behaves_like", "none")
        _problems(layout, ("Level",))


class BOZ_UL_game_rounds(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        entry = current_set(load())
        base = base_wave(game.normalize_set(entry) if entry else None, item.index)
        editable = entry is not None
        row = layout.row(align=True)
        row.label(text=item.label, icon="FORWARD" if item.label == "After that" else "TIME")
        for prop, field, _header, seconds in COLUMNS:
            cell = row.row(align=True)
            cell.enabled = editable
            if base is not None:
                value = base.get(field, game.FIELD[field].default)
                value = int(value) / 1000.0 if seconds else int(value)
                cell.active = not _same(getattr(item, prop), value)
            cell.prop(item, prop, text="")


def _table_header(layout) -> None:
    row = layout.row(align=True)
    row.label(text="")
    for _prop, _field, header, _seconds in COLUMNS:
        row.label(text=header)


class BOZ_PT_game_rounds(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_rounds"
    bl_label = "Rounds"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        if base_rounds() is None and not (load().get("rounds") or {}).get("sets"):
            layout.label(text="Build the asset library in the launcher to see the rounds", icon="ERROR")
            return
        if not len(scene.boz_game_modes):
            layout.operator(BOZ_OT_game_refresh.bl_idname, icon="FILE_REFRESH")
            return
        data = load()
        # The modes table: which rounds each mode plays.
        box = layout.box()
        box.label(text="Modes: which rounds each one plays", icon="COMMUNITY")
        header = box.row(align=True)
        for text in ("Mode", "Rounds", "Zombies x", "Health x"):
            header.label(text=text)
        for i, mode in enumerate(scene.boz_game_modes):
            row = box.row(align=True)
            row.label(text=mode.label)
            shown = mode.round_set or f"{base_label()}'s own"
            sub = row.row(align=True)
            sub.active = bool(mode.round_set)
            sub.context_pointer_set("boz_game_mode", mode)
            sub.menu(BOZ_MT_game_mode_set.bl_idname, text=shown)
            value_row(row, f"boz_game_modes[{i}]", mode, "zombies", 1.0, text="")
            value_row(row, f"boz_game_modes[{i}]", mode, "health", 1.0, text="")
        # The round sets.
        row = layout.row(align=True)
        entry = current_set(data)
        row.label(text="Round set:")
        row.menu(BOZ_MT_game_set_show.bl_idname, text=scene.boz_game_set or f"{base_label()}'s own (view only)")
        row.menu(BOZ_MT_game_set_add.bl_idname, text="New", icon="ADD")
        if entry is not None:
            row.operator(BOZ_OT_game_set_remove.bl_idname, text="", icon="TRASH")
            layout.prop(scene, "boz_game_set_rename", text="Name")
            users = [m.label for m in scene.boz_game_modes if m.round_set == entry["name"]]
            layout.label(text=("Played in: " + ", ".join(users)) if users else
                         "No mode plays this set yet: pick it in the Modes table", icon="INFO")
        else:
            row = layout.row(align=True)
            row.prop(scene, "boz_game_preview", text="Showing")
            layout.label(text=f"{base_label()}'s own rounds can't be changed: make a New round set "
                              "from them", icon="INFO")
        _table_header(layout)
        row = layout.row()
        row.template_list("BOZ_UL_game_rounds", "", scene, "boz_game_rounds", scene,
                          "boz_game_round_index", rows=6)
        if entry is not None:
            column = row.column(align=True)
            column.operator(BOZ_OT_game_round_add.bl_idname, text="", icon="ADD")
            column.operator(BOZ_OT_game_round_remove.bl_idname, text="", icon="REMOVE")
        draw_round(layout, scene, entry)
        _problems(layout, ("Rounds",))


def draw_round(layout, scene, entry):
    """The selected round's details: speed mix, After that growth, advanced."""
    item = selected(scene.boz_game_rounds, scene.boz_game_round_index)
    if item is None:
        return
    form = scene.boz_game_round
    normalized = game.normalize_set(entry) if entry else None
    base = base_wave(normalized, item.index) or {}
    editable = entry is not None
    last = item.label == "After that"
    box = layout.box()
    box.label(text=f"{item.label}: " + ("this round again and again, growing each round" if last else
                                        "speeds and more"), icon="PREFERENCES")

    def field(column, name, **kwargs):
        f = game.FIELD[name]
        value = base.get(name, f.default) if base else None
        value_row(column, "boz_game_round", form, name,
                  None if value is None else form_value(f, value), editable=editable, **kwargs)

    column = box.column(align=True)
    column.label(text="Speed mix (always 100%)")
    for name in game.SPEEDS:
        field(column, name, slider=True)
    if last:
        column = box.column(align=True)
        column.label(text="Growth each round")
        for name in GROWTH:
            if name != "m_ZombieHealthMultiplier":
                field(column, name)
        row = column.row(align=True)
        row.enabled = editable
        row.prop(scene, "boz_game_after_health", text="Health")
        if scene.boz_game_after_health == "grow":
            field(column, "m_ZombieHealthMultiplier")
    box.prop(scene, "boz_game_advanced", text="Advanced: powered zombies, zombie type, fog",
             icon="TRIA_DOWN" if scene.boz_game_advanced else "TRIA_RIGHT", emboss=False)
    if scene.boz_game_advanced:
        column = box.column(align=True)
        for name in ("m_StartingZombies", "m_ZombieType", "m_PoweredZombieCount",
                     "m_PoweredZombieType", "m_PoweredZombieHealthMult", "m_FogConfig"):
            field(column, name)


class BOZ_PT_game_specials(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_specials"
    bl_label = "Special rounds"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout) or not len(scene.boz_game_modes):
            return
        data = load()
        entry = current_set(data)
        layout.label(text=(f'Of "{entry["name"]}": ' if entry else f"{base_label()}'s, view only: ") +
                     "they come between normal rounds, in this order", icon="INFO")
        row = layout.row()
        row.template_list("BOZ_UL_game_specials", "", scene, "boz_game_specials", scene,
                          "boz_game_special_index", rows=3)
        if entry is not None:
            column = row.column(align=True)
            column.operator(BOZ_OT_game_special_add.bl_idname, text="", icon="ADD")
            column.operator(BOZ_OT_game_special_remove.bl_idname, text="", icon="REMOVE")
        if not len(scene.boz_game_specials):
            return
        form = scene.boz_game_special
        base = base_special(game.normalize_set(entry) if entry else None, scene.boz_game_special_index) or {}
        box = layout.box()
        row = box.row()
        row.enabled = entry is not None
        row.prop(form, "special_class")
        column = box.column(align=True)
        for name in SPECIAL_FIELDS:
            f = game.FIELD[name]
            if f.declared == "CWaveMonkey" and form.special_class != "CWaveMonkey":
                continue
            value = base.get(name, f.default) if base else None
            value_row(column, "boz_game_special", form, name,
                      None if value is None else form_value(f, list(value) if isinstance(value, tuple) else value),
                      editable=entry is not None)
        _problems(layout, ("Special rounds",))


class BOZ_UL_game_specials(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.name, icon="OUTLINER_OB_FORCE_FIELD")
        row.label(text=item.detail)


class BOZ_UL_game_looks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.active = item.used != item.base_used or item.used
        row.prop(item, "used", text="")
        row.label(text=item.name, icon="GHOST_ENABLED")
        row.label(text=item.detail)


def _cvar_rows(layout, names: tuple[str, ...]) -> None:
    form = link.map_scene().boz_game_economy
    column = layout.column(align=True)
    for name in names:
        value_row(column, "boz_game_economy", form, name, cvar_default(name))


class BOZ_PT_game_zombies(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_zombies"
    bl_label = "Zombies"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        _cvar_rows(layout, game.CVAR_SECTIONS["zombies"])
        if not len(scene.boz_game_looks):
            layout.operator(BOZ_OT_game_refresh.bl_idname, icon="FILE_REFRESH")
            return
        layout.label(text="Looks: zombies spawn with one of the ticked ones, picked at random")
        layout.template_list("BOZ_UL_game_looks", "", scene, "boz_game_looks", scene,
                             "boz_game_look_index", rows=4)
        _problems(layout, ("Zombies",))


class BOZ_PT_game_points(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_points"
    bl_label = "Points"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        if _no_project(layout):
            return
        form = link.map_scene().boz_game_economy
        _cvar_rows(layout, game.CVAR_SECTIONS["points"])
        layout.label(text="Points per action")
        column = layout.column(align=True)
        for action, _label, points in game.SCORES:
            value_row(column, "boz_game_economy", form, "score_" + action, points)
        for action, _label, limit in game.SCORE_LIMITS:
            value_row(column, "boz_game_economy", form, "limit_" + action, limit)
        _problems(layout, ("Points",))


class BOZ_PT_game_powerups(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_powerups"
    bl_label = "Power-ups"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        if _no_project(layout):
            return
        form = link.map_scene().boz_game_economy
        total = sum(getattr(form, "pickup_" + key) for key in game.PICKUPS) or 1
        layout.label(text="Which one drops (share of all drops)")
        column = layout.column(align=True)
        for i, key in enumerate(game.PICKUPS):
            row = value_row(column, "boz_game_economy", form, "pickup_" + key, game.PICKUP_WEIGHTS[i], slider=True)
            row.label(text=f"{100 * getattr(form, 'pickup_' + key) / total:.0f}%")
        layout.label(text="When they drop, and for how long (seconds)")
        _cvar_rows(layout, game.CVAR_SECTIONS["powerups"])
        _problems(layout, ("Power-ups",))


class BOZ_PT_game_box(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_box"
    bl_label = "Mystery box"
    bl_order = 6

    def draw(self, context):
        layout = self.layout
        if _no_project(layout):
            return
        form = link.map_scene().boz_game_economy
        column = layout.column(align=True)
        for name, (_label, stock) in game.BOX_FIELDS.items():
            value_row(column, "boz_game_economy", form, "box_" + name, stock)
        layout.label(text="The weapons it gives: the Weapons tab's box pool", icon="MOD_PHYSICS")
        _problems(layout, ("Mystery box",))


class BOZ_UL_game_hooks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.label, icon="SCRIPT" if item.exists else "DOT")
        op = row.operator(BOZ_OT_game_hook.bl_idname, text="Open" if item.exists else "Create")
        op.event = item.name


class BOZ_PT_game_hooks(Panel):
    """Hook scripts: in the Scripts tab's sidebar, next to the script editor."""
    bl_idname = "BOZ_PT_game_hooks"
    bl_label = "Hooks"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "BOZ"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == "Scripts"

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        if not len(scene.boz_game_hooks):
            layout.operator(BOZ_OT_game_refresh.bl_idname, icon="FILE_REFRESH")
            return
        layout.label(text="A script that runs every time the event happens")
        layout.template_list("BOZ_UL_game_hooks", "", scene, "boz_game_hooks", scene,
                             "boz_game_hook_index", rows=6)
        item = selected(scene.boz_game_hooks, scene.boz_game_hook_index)
        if item is not None:
            layout.label(text=f"data: {item.data}")


CLASSES = (BOZ_GameWave, BOZ_GameRoundRow, BOZ_GameRound, BOZ_GameMode, BOZ_GameLook, BOZ_GameHook,
           BOZ_GameEconomy, BOZ_OT_game_refresh, BOZ_OT_game_reset, BOZ_OT_game_mode_set,
           BOZ_OT_game_set_show, BOZ_OT_game_set_add, BOZ_MT_game_mode_set, BOZ_MT_game_set_show,
           BOZ_MT_game_set_add, BOZ_OT_game_set_remove, BOZ_OT_game_round_add,
           BOZ_OT_game_round_remove, BOZ_OT_game_special_add, BOZ_OT_game_special_remove,
           BOZ_OT_game_loading_pick, BOZ_OT_game_loading_clear, BOZ_OT_game_picture_pick,
           BOZ_OT_game_picture_capture, BOZ_OT_game_picture_clear, BOZ_OT_game_hook,
           BOZ_UL_game_rounds, BOZ_UL_game_specials, BOZ_UL_game_looks, BOZ_UL_game_hooks,
           BOZ_PT_game_level, BOZ_PT_game_rounds, BOZ_PT_game_specials, BOZ_PT_game_zombies,
           BOZ_PT_game_points, BOZ_PT_game_powerups, BOZ_PT_game_box, BOZ_PT_game_hooks)

SCENE_PROPS = {
    "boz_game_modes": lambda: CollectionProperty(type=BOZ_GameMode),
    "boz_game_set": lambda: StringProperty(name="Round set", update=_set_chosen,
                                           description="The round set the tables show"),
    "boz_game_set_rename": lambda: StringProperty(name="Name", update=_set_renamed,
                                                  description="The round set's name"),
    "boz_game_preview": lambda: EnumProperty(name="Showing", items=MODE_ITEMS, default="normal",
                                             update=_preview_changed,
                                             description="Which mode's base rounds the tables show"),
    "boz_game_rounds": lambda: CollectionProperty(type=BOZ_GameRoundRow),
    "boz_game_round_index": lambda: IntProperty(update=_round_selected),
    "boz_game_round": lambda: PointerProperty(type=BOZ_GameWave),
    "boz_game_advanced": lambda: BoolProperty(name="Advanced", default=False),
    "boz_game_after_health": lambda: EnumProperty(name="Health", items=HEALTH_ITEMS,
                                                  update=_after_health_changed,
                                                  description="How zombie health grows once the rounds run out"),
    "boz_game_specials": lambda: CollectionProperty(type=BOZ_GameRound),
    "boz_game_special_index": lambda: IntProperty(update=_round_selected),
    "boz_game_special": lambda: PointerProperty(type=BOZ_GameWave),
    "boz_game_looks": lambda: CollectionProperty(type=BOZ_GameLook),
    "boz_game_look_index": lambda: IntProperty(),
    "boz_game_hooks": lambda: CollectionProperty(type=BOZ_GameHook),
    "boz_game_hook_index": lambda: IntProperty(),
    "boz_game_economy": lambda: PointerProperty(type=BOZ_GameEconomy),
    "boz_game_display_name": lambda: StringProperty(
        name="Name", description="The map's name in the launcher and mod list",
        update=_display_name_changed),
    "boz_game_loading": lambda: StringProperty(name="Loading screen",
                                               description="The picture shown while the map loads"),
    "boz_game_map_picture": lambda: StringProperty(
        name="Map picture", description="The map's picture on the client launcher's PLAY screen"),
    "boz_game_behaves_like": lambda: EnumProperty(
        name="Special behaviour", update=_level_changed,
        items=[("none" if k == "" else k, "None" if k == "" else f"Uses {v.split(':')[0]}'s", v)
               for k, v in game.BEHAVES_LIKE.items()],
        description="Some game code checks the map's name: answer those checks as this map"),
    "boz_game_power_on": lambda: BoolProperty(
        name="Power on at the start", update=_level_changed,
        description="The power is already on when the map starts"),
}


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, make in SCENE_PROPS.items():
        setattr(bpy.types.Scene, name, make())


def unregister():
    for name in reversed(list(SCENE_PROPS)):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
