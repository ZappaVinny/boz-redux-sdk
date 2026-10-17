"""The Game tab: the map's rules (bozkit.game, source/game.json).

- Level info: the name players see, the loading screen picture, the starting weapon, power on at
  the start.
- Rounds: each game's rounds (single player easy/normal/hard, co-op 2-4 players), the last one
  repeating and growing; a graph of zombies and health by round.
- Special rounds: dog rounds (and Ascension's monkeys), when they come and what spawns.
- Zombie types: which of the level's zombie looks spawn.
- Pickups and economy: points, power-up drops and times, the score table, the mystery box.
- Hooks: every event a script can follow, with its script stub.

Until a section is changed the base level's own data is shown (and used); the first change
copies it into game.json.
"""
from __future__ import annotations

import copy
import shutil
import tomllib
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import game as editor_game, link

from ._bozkit import game, group, weapons as wp, world as bworld
from ._bozkit import project as sdk_project
from ._bozkit import hashing
iw_hash = hashing.iw_hash

WORKSPACE = "Game"
GRAPH_IMAGE = "BOZ Rounds"
GRAPH_SIZE = (1600, 400)
GRAPH_ROUNDS = 40
_state: dict = {"base": {}, "names": None, "loading": False}

CHAIN_ITEMS = [(key, label, label) for key, label in game.CHAINS]
WAVE_TYPE_ITEMS = [(str(i), label, label) for i, (_key, label) in enumerate(game.CHAINS)]
ROUND_CLASS_ITEMS = [("CWave", "One round", "This round, once"),
                     ("CWaveRepeatable", "Repeats", "This round again and again, growing each time "
                                                   "(only as the last round)")]
SPECIAL_CLASS_ITEMS = [("CWaveSpeciality", "Special round", "Dogs or any zombie type"),
                       ("CWaveMonkey", "Monkey round", "Ascension's space monkeys (they need the "
                                                       "map's perk machines and lander)")]
HEALTH_ITEMS = [("game", "The game's", "Repeating rounds: 10 x round x round - 150 (the game's own)"),
                ("grow", "Grows by the multiplier", "Repeating rounds: the round's health times "
                                                    "its health multiplier each round")]


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
    source = link.source_dir()
    try:
        return game.load(source) if source else {}
    except game.GameError as exc:
        print(f"boz_suite: game: {exc}")
        return {}


def save(data: dict) -> None:
    source = link.source_dir()
    if source is not None:
        game.save(source, data)


def base_level() -> str:
    source = link.source_dir()
    try:
        return bworld.load(source).base if source else "kino"
    except Exception:
        return "kino"


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


def rounds_of(data: dict) -> dict | None:
    """The rounds the map uses: its own, else the base level's."""
    if data.get("rounds"):
        return data["rounds"]
    statics = base_statics()
    if statics is None:
        return None
    try:
        return game.read_rounds(statics)
    except game.GameError:
        return None


def dog_round() -> dict | None:
    """A dog round as the game has one: the base level's, else Kino's."""
    pack = editor_game.game_pack()
    for statics in (base_statics(), *([group.parse(pack.read("levels/kino/kino_statics.group.bin"))]
                                      if pack is not None else [])):
        if statics is None:
            continue
        try:
            specials = game.read_rounds(statics).get("specials") or []
        except game.GameError:
            continue
        found = next((w for w in specials if w.get("m_HellhoundWave")), None)
        if found is not None:
            return copy.deepcopy(found)
    return None


def own_rounds(data: dict) -> dict | None:
    """The map's own rounds, copied from the base level on the first change."""
    if not data.get("rounds"):
        base = rounds_of(data)
        if base is None:
            return None
        data["rounds"] = copy.deepcopy(base)
        data["rounds"].setdefault("repeat_health", "game")
    return data["rounds"]


def selected(collection, index):
    return collection[index] if 0 <= index < len(collection) else None


def _is_name_field(field) -> bool:
    return field.unit in ("entity name", "fog config name")


def _wave_props() -> dict:
    annotations = {}
    for field in game.FIELDS:
        description = f"{field.help} ({field.unit})" if field.unit else field.help
        if field.type == "float":
            annotations[field.name] = FloatProperty(name=field.label, description=description,
                                                    min=0.0, update=_wave_changed)
        elif field.type == "bool":
            annotations[field.name] = BoolProperty(name=field.label, description=description,
                                                   update=_wave_changed)
        elif field.type == "CParsableEnumManager::SpecialityWaveType":
            annotations[field.name] = EnumProperty(name=field.label, description=description,
                                                   items=WAVE_TYPE_ITEMS, update=_wave_changed)
        elif field.type == "unsigned int" and not _is_name_field(field):
            annotations[field.name] = IntProperty(name=field.label, description=description,
                                                  min=0, update=_wave_changed)
        else:
            annotations[field.name] = StringProperty(name=field.label, description=description,
                                                     update=_wave_changed)
    annotations["round_class"] = EnumProperty(name="Kind", items=ROUND_CLASS_ITEMS,
                                              update=_wave_changed)
    annotations["special_class"] = EnumProperty(name="Kind", items=SPECIAL_CLASS_ITEMS,
                                                update=_wave_changed)
    return annotations


def _to_form(form, wave: dict) -> None:
    _state["loading"] = True
    try:
        for field in game.FIELDS:
            value = wave.get(field.name, field.default)
            if field.type == "std::vector<unsigned int>":
                if field.unit == "entity names":
                    setattr(form, field.name, ", ".join(name_of(v) for v in value))
                else:
                    setattr(form, field.name, ", ".join(str(v) for v in value))
            elif field.type == "CParsableEnumManager::SpecialityWaveType":
                setattr(form, field.name, str(min(max(int(value), 0), 5)))
            elif _is_name_field(field):
                setattr(form, field.name, name_of(int(value)))
            elif field.type == "float":
                setattr(form, field.name, float(value))
            elif field.type == "bool":
                setattr(form, field.name, bool(value))
            else:
                setattr(form, field.name, int(value))
        cls = wave.get("class", "CWave")
        if cls in ("CWave", "CWaveRepeatable"):
            form.round_class = cls
        else:
            form.special_class = cls
    finally:
        _state["loading"] = False


def _from_form(form, wave: dict, special: bool) -> dict:
    out = {"class": form.special_class if special else form.round_class}
    for field in game.fields_of(out["class"]):
        value = getattr(form, field.name)
        if field.type == "std::vector<unsigned int>":
            parts = [p for p in value.replace(";", ",").split(",") if p.strip()]
            if field.unit == "entity names":
                out[field.name] = [hash_of(p) for p in parts]
            else:
                out[field.name] = [int(p) for p in parts if p.strip().isdigit()]
        elif field.type == "CParsableEnumManager::SpecialityWaveType":
            out[field.name] = int(value)
        elif _is_name_field(field):
            out[field.name] = hash_of(value)
        else:
            out[field.name] = value
    return out


def _wave_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    special = self.as_pointer() == scene.boz_game_special.as_pointer()
    data = load()
    rounds = own_rounds(data)
    if rounds is None:
        return
    if special:
        index = scene.boz_game_special_index
        specials = rounds.setdefault("specials", [])
        if not 0 <= index < len(specials):
            return
        specials[index] = _from_form(self, specials[index], True)
    else:
        chain = rounds["chains"][scene.boz_game_chain]
        index = scene.boz_game_round_index
        if not 0 <= index < len(chain):
            return
        chain[index] = _from_form(self, chain[index], False)
        if scene.boz_game_same_rounds:
            for key in game.CHAIN_KEYS:
                rounds["chains"][key] = copy.deepcopy(chain)
    save(data)
    refresh_lists(context, keep_forms=True)


BOZ_GameWave = type("BOZ_GameWave", (PropertyGroup,), {"__annotations__": _wave_props()})


class BOZ_GameRound(PropertyGroup):
    detail: StringProperty()


def _look_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    used = [item.hash & 0xffffffff for item in scene.boz_game_looks if item.used]
    data = load()
    if used:
        data.setdefault("zombies", {})["used"] = used
    else:
        data.pop("zombies", None)       # none ticked: the base level's own
    save(data)


class BOZ_GameLook(PropertyGroup):
    hash: IntProperty()
    detail: StringProperty()
    used: BoolProperty(name="Spawns", update=_look_changed)


class BOZ_GameHook(PropertyGroup):
    label: StringProperty()
    data: StringProperty()
    exists: BoolProperty()


def _round_label(chain: list, index: int) -> tuple[str, str]:
    wave = chain[index]
    last = index == len(chain) - 1
    if wave.get("class") == "CWaveRepeatable" and last:
        label = f"Round {index + 1} and on (repeats)"
    else:
        label = f"Round {index + 1}"
    detail = f"{wave.get('m_ZombieCount', 0)} zombies, {wave.get('m_ZombieHealth', 100)} health"
    return label, detail


def _special_label(wave: dict, index: int) -> tuple[str, str]:
    kind = "Monkey round" if wave.get("class") == "CWaveMonkey" else (
        "Dog round" if wave.get("m_HellhoundWave") else "Special round")
    game_label = dict(enumerate(label for _k, label in game.CHAINS)).get(int(wave.get("m_waveType", 1)), "?")
    return f"{index + 1}. {kind}", game_label


def refresh_lists(context, keep_forms: bool = False) -> None:
    scene = link.map_scene()
    data = load()
    rounds = rounds_of(data)
    _state["loading"] = True
    try:
        scene.boz_game_rounds.clear()
        scene.boz_game_specials.clear()
        if rounds is not None:
            chain = rounds["chains"].get(scene.boz_game_chain, [])
            for i in range(len(chain)):
                item = scene.boz_game_rounds.add()
                item.name, item.detail = _round_label(chain, i)
            for i, wave in enumerate(rounds.get("specials") or []):
                item = scene.boz_game_specials.add()
                item.name, item.detail = _special_label(wave, i)
            scene.boz_game_repeat_health = (rounds.get("repeat_health") or "game")
        scene.boz_game_round_index = min(scene.boz_game_round_index, max(len(scene.boz_game_rounds) - 1, 0))
        scene.boz_game_special_index = min(scene.boz_game_special_index,
                                           max(len(scene.boz_game_specials) - 1, 0))
    finally:
        _state["loading"] = False
    if not keep_forms:
        load_forms(context)
    draw_graph()


def load_forms(context) -> None:
    scene = link.map_scene()
    rounds = rounds_of(load())
    if rounds is None:
        return
    chain = rounds["chains"].get(scene.boz_game_chain, [])
    if 0 <= scene.boz_game_round_index < len(chain):
        _to_form(scene.boz_game_round, chain[scene.boz_game_round_index])
    specials = rounds.get("specials") or []
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


def graph_image():
    image = bpy.data.images.get(GRAPH_IMAGE)
    if image is None or tuple(image.size) != GRAPH_SIZE:
        if image is not None:
            bpy.data.images.remove(image)
        image = bpy.data.images.new(GRAPH_IMAGE, *GRAPH_SIZE, alpha=False)
    return image


def draw_graph() -> None:
    """Zombies (orange) and health (blue) for rounds 1-40 of the chosen game, each on its own
    scale; ticks every round, longer every 5."""
    try:
        import numpy
    except ImportError:
        return
    scene = link.map_scene()
    rounds = rounds_of(load())
    width, height = GRAPH_SIZE
    pixels = numpy.empty((height, width, 4), dtype=numpy.float32)
    pixels[:] = (0.09, 0.09, 0.1, 1.0)
    if rounds is not None:
        chain = rounds["chains"].get(scene.boz_game_chain, [])
        grow = (rounds.get("repeat_health") or "game") == "grow"
        values = [game.round_values(chain, r, grow_health=grow) for r in range(1, GRAPH_ROUNDS + 1)]
        margin = 20
        for key, colour in (("zombies", (0.95, 0.6, 0.2, 1.0)), ("health", (0.35, 0.65, 0.95, 1.0))):
            series = [v[key] for v in values]
            top = max(series) or 1
            xs = [margin + int((width - 2 * margin) * i / (GRAPH_ROUNDS - 1)) for i in range(GRAPH_ROUNDS)]
            ys = [margin + int((height - 2 * margin) * s / top) for s in series]
            for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
                steps = max(abs(x1 - x0), abs(y1 - y0), 1)
                for t in range(steps + 1):
                    x = x0 + (x1 - x0) * t // steps
                    y = y0 + (y1 - y0) * t // steps
                    pixels[max(0, y - 2):y + 3, max(0, x - 1):x + 2] = colour
        for i in range(GRAPH_ROUNDS):
            x = margin + int((width - 2 * margin) * i / (GRAPH_ROUNDS - 1))
            size = 14 if (i + 1) % 5 == 0 else 6
            pixels[0:size, x] = (0.45, 0.45, 0.5, 1.0)
    image = graph_image()
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    for window in bpy.context.window_manager.windows:
        if window.workspace.name != WORKSPACE:
            continue
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image
                area.tag_redraw()


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
        scene.boz_game_behaves_like = (data.get("level") or {}).get("behaves_like", "") or "none"
    finally:
        _state["loading"] = False


def _level_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    data = load()
    level = data.setdefault("level", {})
    level["power_on"] = scene.boz_game_power_on
    like = scene.boz_game_behaves_like
    if like == "none":
        level.pop("behaves_like", None)
    else:
        level["behaves_like"] = like
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


def _economy_props() -> dict:
    annotations = {}
    for name, (label, unit, help_text, default) in game.CVARS.items():
        description = f"{help_text} ({unit}; the game's: {default})"
        if isinstance(default, float):
            annotations[name] = FloatProperty(name=label, description=description, min=0.0,
                                              default=default, update=_economy_changed)
        else:
            annotations[name] = IntProperty(name=label, description=description, min=0,
                                            default=default, update=_economy_changed)
        annotations["set_" + name] = BoolProperty(name="", description="Change it on this map",
                                                  update=_economy_changed)
    for i, (key, label) in enumerate(zip(game.PICKUPS, game.PICKUP_LABELS)):
        annotations["pickup_" + key] = IntProperty(name=label, min=0, max=100,
                                                   default=game.PICKUP_WEIGHTS[i],
                                                   description="How likely this power-up is, against "
                                                               "the others (0: never)",
                                                   update=_economy_changed)
    annotations["set_pickups"] = BoolProperty(name="Change the power-ups", update=_economy_changed)
    for action, label, points in game.SCORES:
        annotations["score_" + action] = IntProperty(name=label, min=0, default=points,
                                                     description=f"Points for this (the game's: {points})",
                                                     update=_economy_changed)
    for action, label, limit in game.SCORE_LIMITS:
        annotations["limit_" + action] = IntProperty(name=label, min=0, default=limit,
                                                     description=f"At most this x the round number in a "
                                                                 f"round (the game's: {limit})",
                                                     update=_economy_changed)
    annotations["set_scores"] = BoolProperty(name="Change the points", update=_economy_changed)
    for name, (label, stock) in game.BOX_FIELDS.items():
        annotations["box_" + name] = IntProperty(name=label, min=0, default=stock,
                                                 description=f"(the game's: {stock}); a box given its "
                                                             "own value in the World tab keeps it",
                                                 update=_economy_changed)
    annotations["set_box"] = BoolProperty(name="Change the mystery box", update=_economy_changed)
    return annotations


def load_economy(context) -> None:
    scene = link.map_scene()
    form = scene.boz_game_economy
    economy = load().get("economy") or {}
    _state["loading"] = True
    try:
        cvars = economy.get("cvars") or {}
        for name, (_label, _unit, _help, default) in game.CVARS.items():
            setattr(form, "set_" + name, name in cvars)
            setattr(form, name, type(default)(cvars.get(name, default)))
        weights = economy.get("pickups")
        form.set_pickups = weights is not None
        for i, key in enumerate(game.PICKUPS):
            setattr(form, "pickup_" + key, (weights or game.PICKUP_WEIGHTS)[i])
        scores = economy.get("scores")
        form.set_scores = bool(scores)
        for action, _label, points in game.SCORES:
            setattr(form, "score_" + action, int((scores or {}).get(action, points)))
        limits = economy.get("score_limits") or {}
        for action, _label, limit in game.SCORE_LIMITS:
            setattr(form, "limit_" + action, int(limits.get(action, limit)))
        box = economy.get("box")
        form.set_box = bool(box)
        for name, (_label, stock) in game.BOX_FIELDS.items():
            setattr(form, "box_" + name, int((box or {}).get(name, stock)))
    finally:
        _state["loading"] = False


def _economy_changed(self, context):
    if _state["loading"]:
        return
    form = self
    data = load()
    economy = {}
    cvars = {name: getattr(form, name) for name in game.CVARS if getattr(form, "set_" + name)}
    if cvars:
        economy["cvars"] = cvars
    if form.set_pickups:
        economy["pickups"] = [getattr(form, "pickup_" + key) for key in game.PICKUPS]
    if form.set_scores:
        economy["scores"] = {action: getattr(form, "score_" + action) for action, _l, _p in game.SCORES}
        economy["score_limits"] = {action: getattr(form, "limit_" + action)
                                   for action, _l, _p in game.SCORE_LIMITS}
    if form.set_box:
        economy["box"] = {name: getattr(form, "box_" + name) for name in game.BOX_FIELDS}
    if economy:
        data["economy"] = economy
    else:
        data.pop("economy", None)
    save(data)


BOZ_GameEconomy = type("BOZ_GameEconomy", (PropertyGroup,), {"__annotations__": _economy_props()})


def _chain_changed(self, context):
    if _state["loading"]:
        return
    link.map_scene().boz_game_round_index = 0
    refresh_lists(context)


def _round_selected(self, context):
    if not _state["loading"]:
        load_forms(context)


def _repeat_health_changed(self, context):
    if _state["loading"]:
        return
    data = load()
    rounds = own_rounds(data)
    if rounds is None:
        return
    rounds["repeat_health"] = link.map_scene().boz_game_repeat_health
    save(data)
    draw_graph()


class BOZ_OT_game_refresh(Operator):
    bl_idname = "boz.game_refresh"
    bl_label = "Show the game rules"
    bl_description = "Read the map's rules (and the base level's where the map has none)"

    def execute(self, context):
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_game_round_add(Operator):
    bl_idname = "boz.game_round_add"
    bl_label = "Add a round"
    bl_description = "Add a round after the selected one (a copy of it)"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        rounds = own_rounds(data)
        if rounds is None:
            return {"CANCELLED"}
        keys = game.CHAIN_KEYS if scene.boz_game_same_rounds else [scene.boz_game_chain]
        index = scene.boz_game_round_index
        new_index = index + 1
        for key in keys:
            chain = rounds["chains"][key]
            if not chain:
                chain.append({"class": "CWave"})
                new_index = 0
                continue
            i = min(index, len(chain) - 1)
            new = dict(chain[i], **{"class": "CWave"})
            if chain[i].get("class") != "CWave" and i == len(chain) - 1:
                chain.insert(i, new)            # a new round goes before the repeating one
                new_index = i
            else:
                chain.insert(i + 1, new)
                new_index = i + 1
        save(data)
        scene.boz_game_round_index = new_index
        refresh_lists(context)
        return {"FINISHED"}


class BOZ_OT_game_round_remove(Operator):
    bl_idname = "boz.game_round_remove"
    bl_label = "Remove the round"
    bl_description = "Remove the selected round (a game keeps at least one)"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        rounds = own_rounds(data)
        if rounds is None:
            return {"CANCELLED"}
        keys = game.CHAIN_KEYS if scene.boz_game_same_rounds else [scene.boz_game_chain]
        for key in keys:
            chain = rounds["chains"][key]
            if len(chain) > 1 and 0 <= scene.boz_game_round_index < len(chain):
                del chain[scene.boz_game_round_index]
        save(data)
        refresh_lists(context)
        return {"FINISHED"}


class BOZ_OT_game_rounds_copy(Operator):
    bl_idname = "boz.game_rounds_copy"
    bl_label = "Use these rounds in every game"
    bl_description = "Copy this game's rounds to every difficulty and player count"

    def execute(self, context):
        scene = link.map_scene()
        data = load()
        rounds = own_rounds(data)
        if rounds is None:
            return {"CANCELLED"}
        for key in game.CHAIN_KEYS:
            rounds["chains"][key] = copy.deepcopy(rounds["chains"][scene.boz_game_chain])
        save(data)
        refresh_lists(context)
        self.report({"INFO"}, "Every game has these rounds")
        return {"FINISHED"}


class BOZ_OT_game_rounds_reset(Operator):
    bl_idname = "boz.game_rounds_reset"
    bl_label = "Back to the base level's rounds"
    bl_description = "Forget the map's own rounds and special rounds: the base level's are used"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        data = load()
        data.pop("rounds", None)
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
        rounds = own_rounds(data)
        if rounds is None:
            return {"CANCELLED"}
        specials = rounds.setdefault("specials", [])
        current = selected(specials, scene.boz_game_special_index)
        wave = dict(current) if current else dog_round()
        if wave is None:
            self.report({"ERROR"}, "No dog round to copy: the asset library is missing")
            return {"CANCELLED"}
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
        rounds = own_rounds(data)
        if rounds is None:
            return {"CANCELLED"}
        specials = rounds.setdefault("specials", [])
        if 0 <= scene.boz_game_special_index < len(specials):
            del specials[scene.boz_game_special_index]
        save(data)
        refresh_lists(context)
        return {"FINISHED"}


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


class BOZ_UL_game_rounds(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.name, icon="TIME")
        row.label(text=item.detail)


class BOZ_UL_game_looks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.prop(item, "used", text="")
        row.label(text=item.name, icon="GHOST_ENABLED")
        row.label(text=item.detail)


class BOZ_UL_game_hooks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.label, icon="SCRIPT" if item.exists else "DOT")
        op = row.operator(BOZ_OT_game_hook.bl_idname, text="Open" if item.exists else "Create")
        op.event = item.name


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


def _draw_fields(layout, form, class_name, skip=()):
    column = layout.column(align=True)
    for field in game.fields_of(class_name):
        if field.name in skip:
            continue
        column.prop(form, field.name)


class BOZ_PT_game_level(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_level"
    bl_label = "Level info"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        layout.prop(scene, "boz_game_display_name")
        row = layout.row(align=True)
        row.label(text="Loading screen: " + (scene.boz_game_loading or "the base level's"), icon="IMAGE_DATA")
        row.operator(BOZ_OT_game_loading_pick.bl_idname, text="", icon="FILEBROWSER")
        if scene.boz_game_loading:
            row.operator(BOZ_OT_game_loading_clear.bl_idname, text="", icon="X")
        from . import weapons_tab
        name, reserve = weapons_tab.start_weapon()
        layout.label(text=f"Starting weapon: {name} ({reserve} spare; Weapons tab)", icon="MOD_PHYSICS")
        layout.prop(scene, "boz_game_power_on")
        layout.prop(scene, "boz_game_behaves_like")


class BOZ_PT_game_rounds(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_rounds"
    bl_label = "Rounds"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        if base_statics() is None and not load().get("rounds"):
            layout.label(text="Build the asset library in the launcher to see the rounds", icon="ERROR")
            return
        if not len(scene.boz_game_rounds):
            layout.operator(BOZ_OT_game_refresh.bl_idname, icon="FILE_REFRESH")
            return
        row = layout.row(align=True)
        row.prop(scene, "boz_game_chain", text="Game")
        row.prop(scene, "boz_game_same_rounds", text="Same for all", toggle=True)
        layout.label(text="Base level's rounds" if not load().get("rounds") else "This map's rounds",
                     icon="INFO")
        row = layout.row()
        row.template_list("BOZ_UL_game_rounds", "", scene, "boz_game_rounds", scene,
                          "boz_game_round_index", rows=6)
        column = row.column(align=True)
        column.operator(BOZ_OT_game_round_add.bl_idname, text="", icon="ADD")
        column.operator(BOZ_OT_game_round_remove.bl_idname, text="", icon="REMOVE")
        form = scene.boz_game_round
        box = layout.box()
        box.prop(form, "round_class")
        _draw_fields(box, form, form.round_class)
        layout.prop(scene, "boz_game_repeat_health", text="Repeating health")
        row = layout.row(align=True)
        row.operator(BOZ_OT_game_rounds_copy.bl_idname, icon="DUPLICATE")
        row.operator(BOZ_OT_game_rounds_reset.bl_idname, icon="LOOP_BACK")
        layout.label(text="Graph: zombies (orange) and health (blue), rounds 1-40", icon="GRAPH")


class BOZ_PT_game_specials(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_specials"
    bl_label = "Special rounds"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout) or not len(scene.boz_game_rounds):
            return
        layout.label(text="They come between normal rounds, in this order (each for its game)")
        row = layout.row()
        row.template_list("BOZ_UL_game_rounds", "specials", scene, "boz_game_specials", scene,
                          "boz_game_special_index", rows=4)
        column = row.column(align=True)
        column.operator(BOZ_OT_game_special_add.bl_idname, text="", icon="ADD")
        column.operator(BOZ_OT_game_special_remove.bl_idname, text="", icon="REMOVE")
        if not len(scene.boz_game_specials):
            return
        form = scene.boz_game_special
        box = layout.box()
        box.prop(form, "special_class")
        _draw_fields(box, form, form.special_class,
                     skip=("m_ZombieCountMultiplier", "m_PoweredZombieCountMultiplier",
                           "m_PoweredZombieType", "m_PoweredZombieCount", "m_PoweredZombieHealthMult",
                           "m_ZombieWalk", "m_ZombieWalkFast", "m_ZombieRun", "m_ZombieSprint",
                           "m_ZombieType", "m_ZombieCount"))


class BOZ_PT_game_zombies(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_zombies"
    bl_label = "Zombie types"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        if not len(scene.boz_game_looks):
            layout.operator(BOZ_OT_game_refresh.bl_idname, icon="FILE_REFRESH")
            return
        layout.label(text="Zombies spawn with one of the ticked looks, picked at random")
        layout.template_list("BOZ_UL_game_looks", "", scene, "boz_game_looks", scene,
                             "boz_game_look_index", rows=4)


class BOZ_PT_game_economy(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_economy"
    bl_label = "Pickups and economy"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        form = scene.boz_game_economy
        column = layout.column(align=True)
        for name in game.CVARS:
            row = column.row(align=True)
            row.prop(form, "set_" + name)
            sub = row.row(align=True)
            sub.enabled = getattr(form, "set_" + name)
            sub.prop(form, name)
        box = layout.box()
        box.prop(form, "set_pickups")
        if form.set_pickups:
            grid = box.grid_flow(columns=3, align=True)
            for key in game.PICKUPS:
                grid.prop(form, "pickup_" + key)
        box = layout.box()
        box.prop(form, "set_scores")
        if form.set_scores:
            for action, _label, _points in game.SCORES:
                box.prop(form, "score_" + action)
            for action, _label, _limit in game.SCORE_LIMITS:
                box.prop(form, "limit_" + action)
        box = layout.box()
        box.prop(form, "set_box")
        if form.set_box:
            for name in game.BOX_FIELDS:
                box.prop(form, "box_" + name)


class BOZ_PT_game_hooks(_GamePanel, Panel):
    bl_idname = "BOZ_PT_game_hooks"
    bl_label = "Hooks"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if _no_project(layout):
            return
        if not len(scene.boz_game_hooks):
            refresh_hooks(context)
        layout.label(text="A script that runs every time the event happens (scripts/hooks)")
        layout.template_list("BOZ_UL_game_hooks", "", scene, "boz_game_hooks", scene,
                             "boz_game_hook_index", rows=6)
        item = selected(scene.boz_game_hooks, scene.boz_game_hook_index)
        if item is not None:
            layout.label(text=f"data: {item.data}")


CLASSES = (BOZ_GameWave, BOZ_GameRound, BOZ_GameLook, BOZ_GameHook, BOZ_GameEconomy,
           BOZ_OT_game_refresh, BOZ_OT_game_round_add, BOZ_OT_game_round_remove,
           BOZ_OT_game_rounds_copy, BOZ_OT_game_rounds_reset, BOZ_OT_game_special_add,
           BOZ_OT_game_special_remove, BOZ_OT_game_loading_pick, BOZ_OT_game_loading_clear,
           BOZ_OT_game_hook, BOZ_UL_game_rounds, BOZ_UL_game_looks, BOZ_UL_game_hooks,
           BOZ_PT_game_level, BOZ_PT_game_rounds, BOZ_PT_game_specials, BOZ_PT_game_zombies,
           BOZ_PT_game_economy, BOZ_PT_game_hooks)

SCENE_PROPS = {
    "boz_game_chain": lambda: EnumProperty(name="Game", items=CHAIN_ITEMS, default="normal",
                                           update=_chain_changed),
    "boz_game_same_rounds": lambda: BoolProperty(
        name="Same rounds for every game", default=False,
        description="Changes go to every difficulty and player count"),
    "boz_game_rounds": lambda: CollectionProperty(type=BOZ_GameRound),
    "boz_game_round_index": lambda: IntProperty(update=_round_selected),
    "boz_game_round": lambda: PointerProperty(type=BOZ_GameWave),
    "boz_game_specials": lambda: CollectionProperty(type=BOZ_GameRound),
    "boz_game_special_index": lambda: IntProperty(update=_round_selected),
    "boz_game_special": lambda: PointerProperty(type=BOZ_GameWave),
    "boz_game_repeat_health": lambda: EnumProperty(name="Repeating health", items=HEALTH_ITEMS,
                                                   update=_repeat_health_changed),
    "boz_game_looks": lambda: CollectionProperty(type=BOZ_GameLook),
    "boz_game_look_index": lambda: IntProperty(),
    "boz_game_hooks": lambda: CollectionProperty(type=BOZ_GameHook),
    "boz_game_hook_index": lambda: IntProperty(),
    "boz_game_economy": lambda: PointerProperty(type=BOZ_GameEconomy),
    "boz_game_display_name": lambda: StringProperty(
        name="Name", description="The map's name in the launcher and mod list",
        update=_display_name_changed),
    "boz_game_loading": lambda: StringProperty(name="Loading screen"),
    "boz_game_behaves_like": lambda: EnumProperty(
        name="Behaves like", update=_level_changed,
        items=[("none" if k == "" else k, v.split(":")[0], v) for k, v in game.BEHAVES_LIKE.items()],
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
