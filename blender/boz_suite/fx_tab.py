"""The Effects tab: the map's effects and projectiles, one list each.

An entry is either yours (bozkit.fx, source/fx.json: particles you made, or a game effect made
editable) or from the game, used as it is (bozkit.effects, source/effects.json). Add from the
game picks one from the game's library; Make editable turns a game effect into your own copy
under the same name (scripts do not change).

- Effects: an effect's emitters (bozkit.gfx values in their units, paired values labelled), its
  texture (PNG, flipbook, tint) and blend, a script (boz.Effect).
- Projectiles: yours fly and do what their pieces and script say (boz.Projectile); the game's
  keep their behaviour (a black hole, a monkey bomb), with Hide its model / Stays where spawned.
- Preview: the selected effect running in the tab's 3D view (camera-facing particles at their
  real size), its controls in that view's header.

Scripts spawn them by name (boz.effects); any weapon can fire a projectile (Weapons tab).
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import game, link
from ._bozkit import effects, fx, fx_preview, gfx

WORKSPACE = "Effects"
_state: dict = {"loading": False, "sim": None, "sprites": None, "key": None, "items": {},
                "handler": None, "last": None, "textures": {}, "shader": None, "cache": {}}
TOGGLES = [("fade_out", 0x08, "Fade out as they age"),
           ("trail", 0x04, "Trail: spawn along the path it moves (spawn every = distance)"),
           ("face_camera", 0x10, "Face the camera"),
           ("upright", 0x20, "Stand upright"),
           ("prewarm", 0x40, "Start a little along their path")]
# Paired values: (name, heading, unit, first label, second label, min, max, scale to stored)
PAIRS = [("spawn_every", "Time between particles", "ms", "Shortest", "Longest", 1.0, 60000.0, 1.0),
         ("life", "How long each one lives", "s", "Shortest", "Longest", 0.01, 600.0, 1000.0),
         ("size", "Size when made", "units", "Smallest", "Largest", 0.0, 10000.0, 1.0),
         ("spin", "Spin", "°/s", "From", "To", -100000.0, 100000.0, 1.0),
         ("angle", "Start angle", "°", "From", "To", -100000.0, 100000.0, 1.0)]


# Project data ------------------------------------------------------------------------------------

def data() -> dict:
    source = link.source_dir()
    try:
        return fx.load(source) if source else {"effects": [], "projectiles": []}
    except fx.FxError as exc:
        print(f"boz_suite: fx: {exc}")
        return {"effects": [], "projectiles": []}


def save(value: dict) -> None:
    source = link.source_dir()
    if source is not None:
        fx.save(source, value)
        _state["key"] = None


def used() -> list:
    source = link.source_dir()
    try:
        return effects.load(source) if source else []
    except effects.EffectError:
        return []


def save_used(current: list) -> None:
    source = link.source_dir()
    if source is not None:
        effects.save(source, current)
        _state["key"] = None


def selected(collection, index):
    return collection[index] if 0 <= index < len(collection) else None


def current_item(kind: str):
    scene = link.map_scene()
    if kind == "effect":
        return selected(scene.boz_fx_effects, scene.boz_fx_effect_index)
    return selected(scene.boz_fx_projectiles, scene.boz_fx_projectile_index)


def current_effect(value: dict) -> dict | None:
    item = current_item("effect")
    if item is None or item.source != "own":
        return None
    return next((e for e in value["effects"] if e["name"] == item.name), None)


def current_projectile(value: dict) -> dict | None:
    item = current_item("projectile")
    if item is None or item.source != "own":
        return None
    return next((p for p in value["projectiles"] if p["name"] == item.name), None)


def current_game(kind: str):
    item = current_item(kind)
    if item is None or item.source != "game":
        return None
    return next((u for u in used() if u.name == item.name), None)


def taken_names() -> set:
    value = data()
    return {e["name"] for e in value["effects"]} | {p["name"] for p in value["projectiles"]} | \
        {u.name for u in used()}


def unique(wanted: str) -> str:
    taken = taken_names()
    name, number = wanted, 1
    while name in taken:
        number += 1
        name = f"{wanted[:28]}_{number}"
    return name


def clean(text: str) -> str:
    import re
    name = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "effect"
    return name[:32] if name[0].isalpha() else ("fx_" + name)[:32]


# The emitter form ------------------------------------------------------------------------------

def _emitter_changed(self, context):
    if _state["loading"]:
        return
    value = data()
    effect = current_effect(value)
    scene = link.map_scene()
    if effect is None or not 0 <= scene.boz_fx_emitter_index < len(effect["emitters"]):
        return
    emitter = effect["emitters"][scene.boz_fx_emitter_index]
    form = scene.boz_fx_emitter
    emitter["space"], emitter["shape"] = int(form.space), int(form.shape)
    emitter["frame_mode"], emitter["frame_time"] = int(form.frame_mode), int(form.frame_time)
    emitter["duration"] = -1 if form.forever else round(form.duration * 1000)
    emitter["size_scale"] = round(form.size_scale, 4)
    for name in ("position", "position_spread", "velocity", "velocity_spread", "gravity"):
        emitter[name] = [round(v, 3) for v in getattr(form, name)]
    for name, *_rest, scale in PAIRS:
        emitter[name] = [round(getattr(form, name + "_a") * scale, 3), round(getattr(form, name + "_b") * scale, 3)]
    emitter["growth"] = round(form.growth, 3)
    flags = [f for f in emitter.get("flags", []) if f not in {t[0] for t in TOGGLES}]
    flags += [name for name, _bit, _label in TOGGLES if getattr(form, name)]
    emitter["flags"] = flags
    emitter["blend"], emitter["frames"], emitter["columns"] = form.blend, form.frames, min(form.columns, form.frames)
    emitter["tint"] = [round(c * 255) for c in form.tint]
    save(value)
    publish_problems(value)


def _to_form(emitter: dict) -> None:
    form = link.map_scene().boz_fx_emitter
    _state["loading"] = True
    try:
        form.space, form.shape = str(emitter.get("space", 0)), str(emitter.get("shape", 0))
        form.frame_mode, form.frame_time = str(emitter.get("frame_mode", 1)), int(emitter.get("frame_time", 33))
        duration = float(emitter.get("duration", -1))
        form.forever, form.duration = duration < 0, max(0.0, duration / 1000)
        form.size_scale = float(emitter.get("size_scale", 1.0))
        for name in ("position", "position_spread", "velocity", "velocity_spread", "gravity"):
            setattr(form, name, [float(v) for v in emitter.get(name, fx.DEFAULT_EMITTER[name])])
        for name, *_rest, scale in PAIRS:
            pair = emitter.get(name, fx.DEFAULT_EMITTER[name])
            setattr(form, name + "_a", float(pair[0]) / scale)
            setattr(form, name + "_b", float(pair[1]) / scale)
        form.growth = float(emitter.get("growth", 0))
        for name, _bit, _label in TOGGLES:
            setattr(form, name, name in emitter.get("flags", []))
        form.blend = emitter.get("blend", "add")
        form.frames, form.columns = int(emitter.get("frames", 1)), int(emitter.get("columns", 1))
        form.tint = [c / 255 for c in emitter.get("tint", [255, 255, 255])]
        form.texture = emitter.get("texture", "")
    finally:
        _state["loading"] = False


def _enum(items):
    return [(str(k), v, v) for k, v in items.items()]


def _emitter_props() -> dict:
    out = {
        "texture": StringProperty(name="Texture"),
        "blend": EnumProperty(name="Blend", update=_emitter_changed, items=[
            ("add", "Glow (add)", "Brightens what is behind it: fire, sparks, magic"),
            ("blend", "Solid (blend)", "Covers what is behind it: smoke, dust, debris")]),
        "tint": FloatVectorProperty(name="Tint", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
                                    default=(1.0, 1.0, 1.0), update=_emitter_changed,
                                    description="The texture's colours times this (white: as it is)"),
        "frames": IntProperty(name="Pictures", min=1, max=64, default=1, update=_emitter_changed,
                              description="A flipbook: how many pictures the texture holds, left to right "
                                          "then top to bottom (1: a single picture)"),
        "columns": IntProperty(name="Across", min=1, max=64, default=1, update=_emitter_changed,
                               description="How many pictures are in one row of the texture"),
        "frame_mode": EnumProperty(name="Pictures change", items=_enum(gfx.FRAME_MODES), update=_emitter_changed),
        "frame_time": IntProperty(name="Each picture (ms)", min=1, max=10000, default=33, update=_emitter_changed),
        "space": EnumProperty(name="Particles live in", items=_enum(gfx.SPACES), update=_emitter_changed,
                              description=gfx.FIELD["space"].help),
        "shape": EnumProperty(name="Each particle is a", items=_enum(gfx.SHAPES), update=_emitter_changed),
        "forever": BoolProperty(name="Keeps making particles", default=True, update=_emitter_changed,
                                description="For as long as the effect lives; off: only for the time below"),
        "duration": FloatProperty(name="For (s)", min=0.0, max=600.0, update=_emitter_changed,
                                  description="Then it stops making particles"),
        "size_scale": FloatProperty(name="Size x", min=0.0, max=100.0, default=1.0, update=_emitter_changed,
                                    description="Every particle's size times this"),
        "growth": FloatProperty(name="Grows (units/s)", min=-10000.0, max=10000.0, update=_emitter_changed,
                                description="How fast each particle gets bigger (negative: smaller)"),
        "position": FloatVectorProperty(name="Start at", size=3, subtype="XYZ", update=_emitter_changed,
                                        description="Where particles start, from the effect (units; y is up)"),
        "position_spread": FloatVectorProperty(name="Random extra (±)", size=3, subtype="XYZ", min=0.0,
                                               update=_emitter_changed,
                                               description="Up to this much further on each axis, at random"),
        "velocity": FloatVectorProperty(name="Speed (units/s)", size=3, subtype="XYZ", update=_emitter_changed,
                                        description="How fast and which way particles start moving (y is up)"),
        "velocity_spread": FloatVectorProperty(name="Random extra (±)", size=3, subtype="XYZ", min=0.0,
                                               update=_emitter_changed,
                                               description="Up to this much more on each axis, at random"),
        "gravity": FloatVectorProperty(name="Pulled (units/s²)", size=3, subtype="XYZ", update=_emitter_changed,
                                       description="Keeps changing their speed: negative y falls, positive y rises"),
    }
    for name, heading, unit, first, second, low, high, _scale in PAIRS:
        out[name + "_a"] = FloatProperty(name=first, min=low, max=high, update=_emitter_changed,
                                         description=f"{heading} ({unit}): {first.lower()}; each particle gets a "
                                                     "random value between the two")
        out[name + "_b"] = FloatProperty(name=second, min=low, max=high, update=_emitter_changed,
                                         description=f"{heading} ({unit}): {second.lower()}; each particle gets a "
                                                     "random value between the two")
    for name, _bit, label in TOGGLES:
        out[name] = BoolProperty(name=label, update=_emitter_changed)
    return out


BOZ_FxEmitter = type("BOZ_FxEmitter", (PropertyGroup,), {"__annotations__": _emitter_props()})


def _effect_changed(self, context):
    if _state["loading"]:
        return
    value = data()
    effect = current_effect(value)
    if effect is None:
        return
    scene = link.map_scene()
    effect["kind"], effect["scale"] = scene.boz_fx_kind, round(scene.boz_fx_scale, 3)
    save(value)


def _effect_pieces_changed(self, context):
    if _state["loading"]:
        return
    value = data()
    effect = current_effect(value)
    if effect is None:
        return
    form = link.map_scene().boz_fx_effect_pieces
    pieces = {}
    if form.use_blast:
        pieces["blast"] = {"damage": [int(form.damage_edge), int(form.damage_centre)],
                           "radius": [round(form.radius_full, 2), round(form.radius_edge, 2)]}
    if form.use_lure:
        pieces["lure"] = {"seconds": round(form.lure_seconds, 2)}
    if form.use_black_hole:
        pieces["black_hole"] = {"seconds": round(form.black_hole_seconds, 2)}
    if pieces:
        effect["pieces"] = pieces
    else:
        effect.pop("pieces", None)
    save(value)
    publish_problems(value)


class BOZ_FxEffectPieces(PropertyGroup):
    """What one of your effects does where it appears, besides being seen."""
    use_blast: BoolProperty(name="Blast", update=_effect_pieces_changed,
                            description="Damage around it when it appears (the player's kills)")
    damage_centre: FloatProperty(name="At the centre", min=0, max=fx.MAX_DAMAGE, default=1500, precision=0,
                                 update=_effect_pieces_changed)
    damage_edge: FloatProperty(name="At the edge", min=0, max=fx.MAX_DAMAGE, default=1000, precision=0,
                               update=_effect_pieces_changed)
    radius_full: FloatProperty(name="Full damage within", min=0.0, max=fx.MAX_RADIUS, default=32.0,
                               update=_effect_pieces_changed, description="Units")
    radius_edge: FloatProperty(name="Reaches", min=0.0, max=fx.MAX_RADIUS, default=64.0,
                               update=_effect_pieces_changed, description="Units: nothing beyond this")
    use_lure: BoolProperty(name="Lure zombies to it", update=_effect_pieces_changed,
                           description="Zombies go where it appeared, for the time given")
    lure_seconds: FloatProperty(name="For (s)", min=0.1, max=600.0, default=6.0, update=_effect_pieces_changed)
    use_black_hole: BoolProperty(name="Black hole", update=_effect_pieces_changed,
                                 description="The Gersch device's black hole opens where it appears")
    black_hole_seconds: FloatProperty(name="For (s)", min=0.1, max=600.0, default=6.0,
                                      update=_effect_pieces_changed)


def _load_effect_pieces(effect: dict) -> None:
    form = link.map_scene().boz_fx_effect_pieces
    pieces = effect.get("pieces") or {}
    was, _state["loading"] = _state["loading"], True
    try:
        form.use_blast = "blast" in pieces
        blast = pieces.get("blast") or fx.PIECES["blast"]
        form.damage_edge, form.damage_centre = (float(d) for d in blast["damage"])
        form.radius_full, form.radius_edge = (float(r) for r in blast["radius"])
        form.use_lure, form.lure_seconds = "lure" in pieces, float((pieces.get("lure") or {}).get("seconds", 6.0))
        form.use_black_hole = "black_hole" in pieces
        form.black_hole_seconds = float((pieces.get("black_hole") or {}).get("seconds", 6.0))
    finally:
        _state["loading"] = was


def _draw_pieces(layout, form, heading: str) -> None:
    """The blast, lure and black hole rows (effects and projectiles share them)."""
    box = layout.box()
    box.label(text=heading, icon="MODIFIER")
    box.prop(form, "use_blast")
    if form.use_blast:
        column = box.column(align=True)
        column.label(text="Damage:")
        row = column.row(align=True)
        row.prop(form, "damage_centre")
        row.prop(form, "damage_edge")
        column.label(text="Radius (units):")
        row = column.row(align=True)
        row.prop(form, "radius_full")
        row.prop(form, "radius_edge")
    row = box.row(align=True)
    row.prop(form, "use_lure")
    if form.use_lure:
        row.prop(form, "lure_seconds")
    row = box.row(align=True)
    row.prop(form, "use_black_hole")
    if form.use_black_hole:
        row.prop(form, "black_hole_seconds")
    return box


# Projectiles -----------------------------------------------------------------------------------

def _projectile_changed(self, context):
    if _state["loading"]:
        return
    value = data()
    projectile = current_projectile(value)
    if projectile is None:
        return
    form = link.map_scene().boz_fx_projectile
    projectile["gravity"], projectile["lifetime"] = bool(form.gravity), round(form.lifetime, 2)
    projectile["speed"], projectile["radius"] = round(form.speed, 1), round(form.radius, 1)
    pieces = projectile.setdefault("pieces", {})

    def toggle(key, on, make):
        if on:
            pieces[key] = make()
        else:
            pieces.pop(key, None)
    toggle("blast", form.use_blast, lambda: {"damage": [int(form.damage_edge), int(form.damage_centre)],
                                             "radius": [round(form.radius_full, 2), round(form.radius_edge, 2)]})
    toggle("lure", form.use_lure, lambda: {"seconds": round(form.lure_seconds, 2)})
    toggle("black_hole", form.use_black_hole, lambda: {"seconds": round(form.black_hole_seconds, 2)})
    toggle("impact", form.impact != "_none", lambda: form.impact)
    toggle("trail", form.trail != "_none", lambda: form.trail)
    old_ribbon = pieces.get("ribbon") or dict(fx.DEFAULT_RIBBON)
    toggle("ribbon", form.use_ribbon, lambda: dict(old_ribbon, width=round(form.ribbon_width, 2),
                                                   fade=round(form.ribbon_fade * 1000),
                                                   colour=[round(c, 3) for c in form.ribbon_colour]))
    save(value)
    publish_problems(value)


def _effect_items(self, context):
    names = [e["name"] for e in data()["effects"]] + [u.name for u in used() if u.kind == "effect"]
    items = [("_none", "None", "")] + [(n, n, "") for n in names]
    _state["items"]["effects"] = items
    return items


def _trail_items(self, context):
    items = [("_none", "None", "")] + [(e["name"], e["name"], "") for e in data()["effects"]]
    _state["items"]["trails"] = items
    return items


class BOZ_FxProjectile(PropertyGroup):
    speed: FloatProperty(name="Speed (units/s)", min=1.0, max=100000.0, default=3000.0, update=_projectile_changed,
                         description="How fast a weapon fires it (a weapon's own launch force wins when it has one)")
    gravity: BoolProperty(name="Falls (gravity)", update=_projectile_changed,
                          description="It arcs down like a grenade; off: it flies straight")
    lifetime: FloatProperty(name="Lasts (s)", min=0.1, max=600.0, default=5.0, update=_projectile_changed,
                            description="Then it is gone (on_end)")
    radius: FloatProperty(name="Enter/leave radius", min=0.0, max=fx.MAX_RADIUS, update=_projectile_changed,
                          description="What comes within it (zombies, players) calls on_enter / on_leave (0: off)")
    use_blast: BoolProperty(name="Blast where it hits", update=_projectile_changed,
                            description="Damage around the hit (the player's kills)")
    damage_centre: FloatProperty(name="At the centre", min=0, max=fx.MAX_DAMAGE, default=1500, precision=0,
                                 update=_projectile_changed)
    damage_edge: FloatProperty(name="At the edge", min=0, max=fx.MAX_DAMAGE, default=1000, precision=0,
                               update=_projectile_changed)
    radius_full: FloatProperty(name="Full damage within", min=0.0, max=fx.MAX_RADIUS, default=32.0,
                               update=_projectile_changed, description="Units")
    radius_edge: FloatProperty(name="Reaches", min=0.0, max=fx.MAX_RADIUS, default=64.0,
                               update=_projectile_changed, description="Units: nothing beyond this")
    use_lure: BoolProperty(name="Lure zombies where it lands", update=_projectile_changed)
    lure_seconds: FloatProperty(name="For (s)", min=0.1, max=600.0, default=6.0, update=_projectile_changed)
    use_black_hole: BoolProperty(name="Black hole where it lands", update=_projectile_changed,
                                 description="The Gersch device's black hole")
    black_hole_seconds: FloatProperty(name="For (s)", min=0.1, max=600.0, default=6.0, update=_projectile_changed)
    impact: EnumProperty(name="Effect where it hits", items=_effect_items, update=_projectile_changed)
    trail: EnumProperty(name="Effect riding along", items=_trail_items, update=_projectile_changed)
    use_ribbon: BoolProperty(name="Ribbon behind it", update=_projectile_changed, description="A streak behind it")
    ribbon_texture: StringProperty(name="Ribbon texture")
    ribbon_width: FloatProperty(name="Width", min=0.0, max=1000.0, default=100.0, update=_projectile_changed)
    ribbon_colour: FloatVectorProperty(name="Colour", subtype="COLOR_GAMMA", size=4, min=0.0, max=1.0,
                                       default=(1, 1, 1, 1), update=_projectile_changed)
    ribbon_fade: FloatProperty(name="Fades in (s)", min=0.0, max=30.0, default=1.2, update=_projectile_changed)


def load_projectile() -> None:
    projectile = current_projectile(data())
    if projectile is None:
        return
    form = link.map_scene().boz_fx_projectile
    pieces = projectile.get("pieces") or {}
    _state["loading"] = True
    try:
        form.speed = float(projectile.get("speed", 3000.0))
        form.gravity, form.lifetime = bool(projectile.get("gravity")), float(projectile.get("lifetime", 5.0))
        form.radius = float(projectile.get("radius", 0.0))
        form.use_blast = "blast" in pieces
        blast = pieces.get("blast") or fx.PIECES["blast"]
        form.damage_edge, form.damage_centre = (float(d) for d in blast["damage"])
        form.radius_full, form.radius_edge = (float(r) for r in blast["radius"])
        form.use_lure, form.lure_seconds = "lure" in pieces, float((pieces.get("lure") or {}).get("seconds", 6.0))
        form.use_black_hole = "black_hole" in pieces
        form.black_hole_seconds = float((pieces.get("black_hole") or {}).get("seconds", 6.0))
        impact, trail = pieces.get("impact") or "_none", pieces.get("trail") or "_none"
        if impact in {i[0] for i in _effect_items(form, None)}:
            form.impact = impact
        if trail in {i[0] for i in _trail_items(form, None)}:
            form.trail = trail
        form.use_ribbon = "ribbon" in pieces
        ribbon = {**fx.DEFAULT_RIBBON, **(pieces.get("ribbon") or {})}
        form.ribbon_texture = ribbon.get("texture", "")
        form.ribbon_width, form.ribbon_fade = float(ribbon["width"]), float(ribbon["fade"]) / 1000
        form.ribbon_colour = [float(c) for c in ribbon["colour"]]
    finally:
        _state["loading"] = False


class BOZ_FxItem(PropertyGroup):
    detail: StringProperty()
    source: StringProperty()        # "own" or "game"


# Game entries (used as they are) -----------------------------------------------------------------

def _game_changed(self, context):
    if _state["loading"]:
        return
    scene = link.map_scene()
    item = current_item("projectile")
    if item is None or item.source != "game":
        return
    current = used()
    for u in current:
        if u.name == item.name:
            u.hidden, u.anchored = scene.boz_fx_game_hidden, scene.boz_fx_game_anchored
    save_used(current)


# Refresh ---------------------------------------------------------------------------------------

def refresh(context=None) -> None:
    scene = link.map_scene()
    value = data()
    game_used = used()
    _state["loading"] = True
    effect = None
    try:
        for collection, index_name, own, kind in (
                (scene.boz_fx_effects, "boz_fx_effect_index", value["effects"], "effect"),
                (scene.boz_fx_projectiles, "boz_fx_projectile_index", value["projectiles"], "projectile")):
            keep = selected(collection, getattr(scene, index_name))
            keep = keep.name if keep else None
            collection.clear()
            for entry in own:
                item = collection.add()
                item.name, item.source = entry["name"], "own"
                if kind == "effect":
                    item.detail = f"yours · {entry.get('kind', 'lasting')}, {len(entry['emitters'])} emitters"
                else:
                    pieces = ", ".join(k.replace("_", " ") for k in (entry.get("pieces") or {})) or "blank"
                    item.detail = "yours · " + pieces + (" · script" if entry.get("script") else "")
            for u in game_used:
                if (u.kind == "effect") == (kind == "effect"):
                    item = collection.add()
                    item.name, item.source = u.name, "game"
                    item.detail = "from the game" + (f" · {effects.BEHAVIOURS.get(u.behaviour, '')}"
                                                     if kind == "projectile" else "")
            names = [i.name for i in collection]
            setattr(scene, index_name, names.index(keep) if keep in names else
                    max(0, min(getattr(scene, index_name), len(names) - 1)))
        item = current_item("effect")
        scene.boz_fx_rename = item.name if item else ""
        effect = current_effect(value)
        scene.boz_fx_emitters.clear()
        if effect is not None:
            scene.boz_fx_kind, scene.boz_fx_scale = effect.get("kind", "lasting"), float(effect.get("scale", 1.0))
            _load_effect_pieces(effect)
            for i, emitter in enumerate(effect["emitters"]):
                entry = scene.boz_fx_emitters.add()
                entry.name = f"Emitter {i + 1}"
                entry.detail = Path(emitter.get("texture") or "no texture").name
            scene.boz_fx_emitter_index = max(0, min(scene.boz_fx_emitter_index, len(effect["emitters"]) - 1))
        projectile = current_item("projectile")
        scene.boz_fx_projectile_rename = projectile.name if projectile else ""
        game_projectile = current_game("projectile")
        if game_projectile is not None:
            scene.boz_fx_game_hidden, scene.boz_fx_game_anchored = game_projectile.hidden, game_projectile.anchored
    finally:
        _state["loading"] = False
    if effect is not None and 0 <= scene.boz_fx_emitter_index < len(effect["emitters"]):
        _to_form(effect["emitters"][scene.boz_fx_emitter_index])
    load_projectile()
    publish_problems(value)


def publish_problems(value: dict | None = None) -> None:
    """fx.check's problems in the Problems panel, as you edit."""
    scene = link.map_scene()
    problems = fx.check(data() if value is None else value, link.project_root())
    others = [e for e in scene.get("boz_problems", []) if not str(e).endswith("\t" + link.EFFECTS_TAB)]
    scene["boz_problems"] = others + [f"{m}\t{link.EFFECTS_TAB}" for m in problems]


def _selection_changed(self, context):
    if not _state["loading"]:
        refresh(context)
        _state["key"] = None


def _rename(kind):
    def update(self, context):
        if _state["loading"]:
            return
        scene = link.map_scene()
        item = current_item(kind)
        new = clean(scene.boz_fx_rename if kind == "effect" else scene.boz_fx_projectile_rename)
        if item is None or new == item.name or new in taken_names():
            refresh(context)
            return
        old = item.name
        if item.source == "game":
            current = used()
            for u in current:
                if u.name == old:
                    u.name = new
            save_used(current)
        else:
            value = data()
            for entry in value["effects" if kind == "effect" else "projectiles"]:
                if entry["name"] == old:
                    entry["name"] = new
            for projectile in value["projectiles"]:
                pieces = projectile.get("pieces") or {}
                for key in ("impact", "trail"):
                    if pieces.get(key) == old:
                        pieces[key] = new
            save(value)
        item.name = new
        refresh(context)
    return update


# Operators -------------------------------------------------------------------------------------

class BOZ_OT_fx_new(Operator):
    bl_idname = "boz.fx_new"
    bl_label = "New effect"
    bl_description = "An effect of your own: one emitter to start (a soft glow); then pick its texture"

    name: StringProperty(name="Name", default="my_effect", description="What scripts call it (a-z, 0-9, _)")
    kind: EnumProperty(name="Kind", items=[("lasting", "Lasting", "Keeps going until removed: a glow, a trail"),
                                            ("burst", "Burst", "Plays once: an impact, a puff")])

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        value = data()
        effect = fx.new_effect(unique(clean(self.name)), self.kind)
        value["effects"].append(effect)
        save(value)
        refresh(context)
        scene = link.map_scene()
        scene.boz_fx_effect_index = [i.name for i in scene.boz_fx_effects].index(effect["name"])
        return {"FINISHED"}


def _library_items(self, context):
    from . import effects_tab
    kind = "projectile" if getattr(self, "kind", "effect") == "projectile" else "effect"
    key = ("library", kind)
    if key not in _state["items"]:
        items = []
        for entry in effects_tab.catalog():
            if entry.kind != kind:
                continue
            where = "every map" if not entry.level else entry.level
            what = effects.BEHAVIOURS.get(entry.behaviour, "") if kind == "projectile" else ""
            items.append((entry.key, f"{entry.label}  ·  {where}" + (f"  ·  {what}" if what else ""),
                          ", ".join(entry.users[:3])))
        _state["items"][key] = items or [("_none", "Build the asset library in the launcher first", "")]
    return _state["items"][key]


class BOZ_OT_fx_add_game(Operator):
    bl_idname = "boz.fx_add_game"
    bl_label = "Add from the game…"
    bl_description = ("Pick one of the game's effects (or projectiles: a black hole, a monkey bomb) to use "
                      "on this map as it is; Make editable turns an effect into your own copy")
    bl_property = "entry"

    kind: StringProperty(default="effect", options={"HIDDEN"})
    entry: EnumProperty(name="From the game", items=_library_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from . import effects_tab
        found = next((e for e in effects_tab.catalog() if e.key == self.entry), None)
        if found is None:
            return {"CANCELLED"}
        name = unique(clean(found.label))
        current = used()
        current.append(effects.Used(name, found.kind, found.level, found.hash, found.behaviour))
        try:
            save_used(current)
        except effects.EffectError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        refresh(context)
        scene = link.map_scene()
        collection, index = (scene.boz_fx_effects, "boz_fx_effect_index") if found.kind == "effect" else \
            (scene.boz_fx_projectiles, "boz_fx_projectile_index")
        setattr(scene, index, [i.name for i in collection].index(name))
        self.report({"INFO"}, f"{name}: scripts spawn it with boz.effects")
        return {"FINISHED"}


class BOZ_OT_fx_make_editable(Operator):
    bl_idname = "boz.fx_make_editable"
    bl_label = "Make editable"
    bl_description = ("Turn this game effect into your own copy under the same name: its particles and "
                      "textures, which you can then change (anything else it had, a model or a sound, is "
                      "left out)")

    def execute(self, context):
        game_entry = current_game("effect")
        pack = game.game_pack()
        if game_entry is None or pack is None:
            return {"CANCELLED"}
        try:
            effect = fx.copy_game_effect(pack, game_entry.hash, game_entry.name, link.source_dir())
        except (fx.FxError, OSError, ValueError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        save_used([u for u in used() if u.name != game_entry.name])
        value = data()
        value["effects"].append(effect)
        save(value)
        refresh(context)
        self.report({"INFO"}, f"{game_entry.name} is yours now: {len(effect['emitters'])} emitters")
        return {"FINISHED"}


class BOZ_OT_fx_remove(Operator):
    bl_idname = "boz.fx_remove"
    bl_label = "Remove"
    bl_description = "Take it off this map (your textures stay in source/fx)"

    kind: StringProperty(default="effect", options={"HIDDEN"})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item = current_item(self.kind)
        if item is None:
            return {"CANCELLED"}
        if item.source == "game":
            save_used([u for u in used() if u.name != item.name])
        else:
            value = data()
            key = "effects" if self.kind == "effect" else "projectiles"
            value[key] = [e for e in value[key] if e["name"] != item.name]
            save(value)
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_fx_emitter_add(Operator):
    bl_idname = "boz.fx_emitter_add"
    bl_label = "Add emitter"
    bl_description = "Another emitter in this effect (a copy of the selected one)"

    def execute(self, context):
        scene = link.map_scene()
        value = data()
        effect = current_effect(value)
        if effect is None:
            return {"CANCELLED"}
        if len(effect["emitters"]) >= fx.MAX_EMITTERS:
            self.report({"ERROR"}, f"An effect has at most {fx.MAX_EMITTERS} emitters")
            return {"CANCELLED"}
        current = selected(effect["emitters"], scene.boz_fx_emitter_index)
        effect["emitters"].append(copy.deepcopy(current) if current else fx.new_emitter())
        save(value)
        refresh(context)
        scene.boz_fx_emitter_index = len(effect["emitters"]) - 1
        return {"FINISHED"}


class BOZ_OT_fx_emitter_remove(Operator):
    bl_idname = "boz.fx_emitter_remove"
    bl_label = "Remove emitter"
    bl_description = "Remove the selected emitter (an effect keeps at least one)"

    def execute(self, context):
        scene = link.map_scene()
        value = data()
        effect = current_effect(value)
        if effect is None or len(effect["emitters"]) <= 1:
            return {"CANCELLED"}
        del effect["emitters"][scene.boz_fx_emitter_index]
        save(value)
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_fx_texture(Operator):
    bl_idname = "boz.fx_texture"
    bl_label = "Choose a texture"
    bl_description = ("The picture each particle shows (PNG or JPG with transparency; a flipbook holds its "
                      "pictures in a grid); copied into source/fx")

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg", options={"HIDDEN"})
    target: StringProperty(default="emitter", options={"HIDDEN"})   # emitter or ribbon

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = link.map_scene()
        source = link.source_dir()
        path = Path(self.filepath)
        if source is None or not path.is_file():
            return {"CANCELLED"}
        value = data()
        if self.target == "ribbon":
            projectile = current_projectile(value)
            if projectile is None:
                return {"CANCELLED"}
            stored = fx.import_texture(source, path, f"{projectile['name']}_ribbon")
            projectile.setdefault("pieces", {}).setdefault("ribbon", dict(fx.DEFAULT_RIBBON))["texture"] = stored
        else:
            effect = current_effect(value)
            if effect is None or not 0 <= scene.boz_fx_emitter_index < len(effect["emitters"]):
                return {"CANCELLED"}
            stored = fx.import_texture(source, path, f"{effect['name']}_{scene.boz_fx_emitter_index}")
            effect["emitters"][scene.boz_fx_emitter_index]["texture"] = stored
        save(value)
        _state["sprites"] = None
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_fx_projectile_new(Operator):
    bl_idname = "boz.fx_projectile_new"
    bl_label = "New projectile"
    bl_description = ("A projectile of your own: it flies; what it does is its pieces (blast, lure, black "
                      "hole, effects, ribbon) and its script. Any weapon can fire it (Weapons tab)")

    name: StringProperty(name="Name", default="my_bolt", description="What scripts and weapons call it")
    preset: EnumProperty(name="Start from", items=[(k, label, help) for k, (label, help, _p) in fx.PRESETS.items()],
                         description="Pieces to start with (Blank: none; a script does the rest)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        value = data()
        projectile = fx.new_projectile(unique(clean(self.name)), self.preset)
        value["projectiles"].append(projectile)
        save(value)
        refresh(context)
        scene = link.map_scene()
        scene.boz_fx_projectile_index = [i.name for i in scene.boz_fx_projectiles].index(projectile["name"])
        load_projectile()
        return {"FINISHED"}


class BOZ_OT_fx_script(Operator):
    bl_idname = "boz.fx_script"
    bl_label = "Script"
    bl_description = ("Make its script (a projectile: launch, update, hit, enter, leave, end; an effect: "
                      "spawn, update, end) or open it in the Scripts tab")

    kind: StringProperty(default="projectile", options={"HIDDEN"})    # projectile or effect

    def execute(self, context):
        from . import objects
        root = link.project_root()
        value = data()
        item = current_projectile(value) if self.kind == "projectile" else current_effect(value)
        if root is None or item is None:
            self.report({"ERROR"}, "Only your own effects and projectiles have scripts (Make editable first)")
            return {"CANCELLED"}
        if not item.get("script"):
            item["script"] = fx.script_path(self.kind, item["name"])
            save(value)
        path = root / item["script"]
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fx.script_stub(self.kind, item["name"]), encoding="utf-8", newline="\n")
        objects.show_script(context, path)
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_fx_copy_line(Operator):
    bl_idname = "boz.fx_copy_line"
    bl_label = "Copy script line"
    bl_description = "Copy a line of Lua that spawns it where the player aims"

    kind: StringProperty(default="effect", options={"HIDDEN"})

    def execute(self, context):
        item = current_item(self.kind)
        if item is None:
            return {"CANCELLED"}
        context.window_manager.clipboard = 'local effects = require("boz.game.effects")\n' + snippet(self.kind, item)
        self.report({"INFO"}, "Copied")
        return {"FINISHED"}


def snippet(kind: str, item) -> str:
    if kind == "projectile":
        game_entry = current_game("projectile")
        triggers = effects.TRIGGERS.get(game_entry.behaviour, ()) if game_entry else ()
        options = f', {{trigger = "{triggers[0]}", lifetime = 6}}' if triggers else ""
        return f'effects.projectile("{item.name}", effects.aim(){options})'
    return f'effects.spawn("{item.name}", effects.aim(), {{lifetime = 2}})'


# The preview (the tab's 3D view) ----------------------------------------------------------------

def preview_effect() -> dict | None:
    """The effect the preview plays: yours as it is now, or a game one's particles (copied into a
    cache once)."""
    value = data()
    effect = current_effect(value)
    if effect is not None:
        return effect
    game_entry = current_game("effect")
    pack = game.game_pack()
    if game_entry is None or pack is None:
        return None
    cache = _state["cache"]
    if game_entry.hash not in cache:
        import tempfile
        folder = Path(tempfile.gettempdir()) / "boz_fx_preview" / f"{game_entry.hash:08x}"
        try:
            copied = fx.copy_game_effect(pack, game_entry.hash, "preview", folder / "source")
            cache[game_entry.hash] = (copied, folder)
        except (fx.FxError, OSError, ValueError, KeyError):
            cache[game_entry.hash] = None
    found = cache[game_entry.hash]
    return found[0] if found else None


def _preview_root(effect: dict) -> Path:
    for entry in _state["cache"].values():
        if entry and entry[0] is effect:
            return entry[1]
    return link.project_root()


def _shader():
    if _state["shader"] is None:
        import gpu
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        iface = gpu.types.GPUStageInterfaceInfo("boz_fx_iface")
        iface.smooth("VEC2", "v_uv")
        iface.smooth("VEC4", "v_color")
        info.vertex_out(iface)
        info.push_constant("MAT4", "mvp")
        info.sampler(0, "FLOAT_2D", "image")
        info.fragment_out(0, "VEC4", "frag")
        info.vertex_source("void main() { v_uv = uv; v_color = color; gl_Position = mvp * vec4(pos, 1.0); }")
        info.fragment_source("void main() { frag = texture(image, v_uv) * v_color; }")
        _state["shader"] = gpu.shader.create_from_info(info)
    return _state["shader"]


def _texture(path: Path):
    import gpu
    key = str(path)
    if key not in _state["textures"]:
        try:
            image = bpy.data.images.load(key, check_existing=True)
            _state["textures"][key] = gpu.texture.from_image(image)
        except RuntimeError:
            _state["textures"][key] = None
    return _state["textures"][key]


ROOM_SIZE, ROOM_HEIGHT, ROOM_GRID = 300.0, 250.0, 50.0   # units: a corner of a room, for scale


def _draw_room():
    """A floor and two walls round the effect (it plays at the floor's centre), with a line every
    50 units, so its size reads as it would in a map."""
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    s, h = ROOM_SIZE, ROOM_HEIGHT
    surfaces = [
        ([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], (0.22, 0.22, 0.23, 1.0)),   # floor
        ([(-s, s, 0), (s, s, 0), (s, s, h), (-s, s, h)], (0.30, 0.29, 0.28, 1.0)),      # back wall
        ([(-s, -s, 0), (-s, s, 0), (-s, s, h), (-s, -s, h)], (0.26, 0.26, 0.27, 1.0)),  # side wall
    ]
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set("NONE")
    shader.bind()
    for corners, colour in surfaces:
        batch = batch_for_shader(shader, "TRIS", {"pos": [corners[i] for i in (0, 1, 2, 0, 2, 3)]})
        shader.uniform_float("color", colour)
        batch.draw(shader)
    lines = []
    steps = int(2 * s / ROOM_GRID)
    for i in range(steps + 1):
        t = -s + i * ROOM_GRID
        lines += [(t, -s, 0.05), (t, s, 0.05), (-s, t, 0.05), (s, t, 0.05)]         # floor
        lines += [(t, s - 0.05, 0), (t, s - 0.05, h)]                                # back wall
        lines += [(-s + 0.05, t, 0), (-s + 0.05, t, h)]                              # side wall
    for i in range(int(h / ROOM_GRID) + 1):
        z = i * ROOM_GRID
        lines += [(-s, s - 0.05, z), (s, s - 0.05, z), (-s + 0.05, -s, z), (-s + 0.05, s, z)]
    batch = batch_for_shader(shader, "LINES", {"pos": lines})
    shader.uniform_float("color", (0.38, 0.38, 0.40, 1.0))
    batch.draw(shader)


def _draw_preview():
    """Draws the running effect as camera-facing particles (game units = Blender units; the
    game's y up is Blender's z up)."""
    context = bpy.context
    if context.workspace is None or context.workspace.name != WORKSPACE:
        return
    scene = link.map_scene()
    effect = preview_effect()
    if effect is None:
        return
    import json
    import gpu
    from gpu_extras.batch import batch_for_shader
    from mathutils import Vector
    key = json.dumps(effect, sort_keys=True)
    if _state["key"] != key:
        _state["key"], _state["sim"], _state["last"] = key, fx_preview.Simulation(effect), None
        _state["textures"].clear()
    sim = _state["sim"]
    now = time.monotonic()
    if scene.boz_fx_playing and _state["last"] is not None:
        step = min(0.1, now - _state["last"]) * 1000 * scene.boz_fx_speed
        if scene.boz_fx_moving:
            sim.step_moving(step)
        else:
            sim.step(step)
        if effect.get("kind") == "burst" and sim.time > 3000 and scene.boz_fx_loop:
            _state["key"] = None
    _state["last"] = now
    origin = Vector(scene.cursor.location) if scene.boz_fx_in_map else Vector((0, 0, 0))
    if not scene.boz_fx_in_map:
        _draw_room()
    view = context.region_data.view_matrix
    right, up = Vector(view[0][:3]), Vector(view[1][:3])
    mvp = context.region_data.perspective_matrix
    shader = _shader()
    root = _preview_root(effect)
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)
    for index, emitter in enumerate(effect.get("emitters", [])):
        texture = _texture(Path(root) / emitter["texture"]) if emitter.get("texture") else None
        if texture is None:
            continue
        frames, columns = max(1, int(emitter.get("frames", 1))), max(1, int(emitter.get("columns", 1)))
        rows = -(-frames // columns)
        tint = [c / 255 for c in emitter.get("tint", [255, 255, 255])]
        positions, uvs, colours = [], [], []
        for particle in sim.particles:
            if particle.emitter != index:
                continue
            centre = origin + Vector((particle.x, -particle.z, particle.y))
            half = particle.size
            import math
            a = math.radians(particle.angle)
            r = (right * math.cos(a) + up * math.sin(a)) * half
            u = (up * math.cos(a) - right * math.sin(a)) * half
            frame = fx_preview.frame_of(particle, emitter, sim.time) % frames
            u0, v0 = (frame % columns) / columns, 1 - (frame // columns + 1) / rows
            u1, v1 = u0 + 1 / columns, v0 + 1 / rows
            corners = [centre - r - u, centre + r - u, centre + r + u, centre - r + u]
            tex = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            alpha = fx_preview.alpha_of(particle, emitter)
            for i in (0, 1, 2, 0, 2, 3):
                positions.append(corners[i][:])
                uvs.append(tex[i])
                colours.append((*tint, alpha))
        if not positions:
            continue
        gpu.state.blend_set("ADDITIVE" if emitter.get("blend", "add") == "add" else "ALPHA")
        batch = batch_for_shader(shader, "TRIS", {"pos": positions, "uv": uvs, "color": colours})
        shader.bind()
        shader.uniform_float("mvp", mvp)
        shader.uniform_sampler("image", texture)
        batch.draw(shader)
    gpu.state.blend_set("NONE")
    gpu.state.depth_mask_set(True)


def _redraw_tick():
    try:
        scene = link.map_scene()
    except Exception:  # noqa: BLE001 - the editor is closing
        return None
    for window in bpy.context.window_manager.windows:
        if window.workspace.name != WORKSPACE:
            continue
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return 1 / 30 if scene.boz_fx_playing else 0.5


def setup_view(space) -> None:
    """The Effects tab's 3D view: only the preview (the map's objects hidden) unless In the map."""
    scene = link.map_scene()
    for name in ("show_object_viewport_mesh", "show_object_viewport_curve", "show_object_viewport_empty",
                 "show_object_viewport_light", "show_object_viewport_camera", "show_object_viewport_armature",
                 "show_object_viewport_surf", "show_object_viewport_meta", "show_object_viewport_font",
                 "show_object_viewport_lattice", "show_object_viewport_grease_pencil"):
        if hasattr(space, name):
            setattr(space, name, scene.boz_fx_in_map)


def _in_map_changed(self, context):
    for window in context.window_manager.windows:
        if window.workspace.name != WORKSPACE:
            continue
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                setup_view(area.spaces.active)


def draw_view_header(self, context):
    """The preview's controls, in the Effects tab's 3D view header."""
    if context.workspace is None or context.workspace.name != WORKSPACE:
        return
    scene = link.map_scene()
    layout = self.layout
    row = layout.row(align=True)
    row.prop(scene, "boz_fx_playing", text="", icon="PAUSE" if scene.boz_fx_playing else "PLAY")
    row.operator(BOZ_OT_fx_restart.bl_idname, text="", icon="FILE_REFRESH")
    row.prop(scene, "boz_fx_speed", text="Speed")
    row.prop(scene, "boz_fx_loop", text="", icon="LOOP_FORWARDS")
    row.prop(scene, "boz_fx_moving", text="", icon="CURVE_PATH")
    row.prop(scene, "boz_fx_in_map", text="", icon="WORLD")
    item = current_item("effect")
    layout.label(text=f"Preview: {item.name}" if item else "Preview: select an effect")


class BOZ_OT_fx_restart(Operator):
    bl_idname = "boz.fx_restart"
    bl_label = "Restart"
    bl_description = "Play the effect from the start"

    def execute(self, context):
        _state["key"] = None
        return {"FINISHED"}


# Panels ----------------------------------------------------------------------------------------

class _FxPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == WORKSPACE and \
            link.source_dir() is not None


class BOZ_UL_fx(UIList):
    def draw_item(self, context, layout, data_, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        mine = getattr(item, "source", "own") != "game"
        row.label(text=item.name, icon="PARTICLES" if mine else "LINKED")
        row.label(text=item.detail)


def _problems(layout, prefix: str) -> None:
    for message in fx.check(data(), link.project_root()):
        if message.startswith(prefix):
            layout.label(text=message, icon="ERROR")


def _pair(layout, form, name):
    heading, unit, first, second = next((h, u, a, b) for n, h, u, a, b, *_r in PAIRS if n == name)
    column = layout.column(align=True)
    column.label(text=f"{heading} ({unit}), random between:")
    row = column.row(align=True)
    row.prop(form, name + "_a")
    row.prop(form, name + "_b")


class BOZ_PT_fx_effects(_FxPanel, Panel):
    bl_idname = "BOZ_PT_fx_effects"
    bl_label = "Effects"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if not len(scene.boz_fx_effects) and (data()["effects"] or any(u.kind == "effect" for u in used())):
            refresh(context)
        layout.label(text="What the map can spawn: yours, or the game's as they are", icon="INFO")
        row = layout.row()
        row.template_list("BOZ_UL_fx", "effects", scene, "boz_fx_effects", scene, "boz_fx_effect_index", rows=4)
        column = row.column(align=True)
        column.operator(BOZ_OT_fx_new.bl_idname, text="", icon="ADD")
        column.operator(BOZ_OT_fx_remove.bl_idname, text="", icon="REMOVE").kind = "effect"
        layout.operator(BOZ_OT_fx_add_game.bl_idname, icon="VIEWZOOM").kind = "effect"
        item = current_item("effect")
        if item is None:
            return
        layout.prop(scene, "boz_fx_rename", text="Name")
        if item.source == "game":
            box = layout.box()
            box.label(text="From the game, used as it is", icon="LINKED")
            box.operator(BOZ_OT_fx_make_editable.bl_idname, icon="GREASEPENCIL")
        else:
            row = layout.row(align=True)
            row.prop(scene, "boz_fx_kind", expand=True)
            layout.prop(scene, "boz_fx_scale")
            effect = current_effect(data()) or {}
            layout.operator(BOZ_OT_fx_script.bl_idname, text="Open script" if effect.get("script") else "Make a script",
                            icon="SCRIPT").kind = "effect"
            _draw_pieces(layout, scene.boz_fx_effect_pieces,
                         "Where it appears: these run unless its script's on_spawn returns false")
        row = layout.row(align=True)
        row.label(text=snippet("effect", item), icon="SCRIPT")
        row.operator(BOZ_OT_fx_copy_line.bl_idname, text="", icon="COPYDOWN").kind = "effect"
        _problems(layout, "Effects")


class BOZ_PT_fx_emitter(_FxPanel, Panel):
    bl_idname = "BOZ_PT_fx_emitter"
    bl_label = "Particles"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        item = current_item("effect") if super().poll(context) else None
        return item is not None and item.source == "own"

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        layout.label(text="An effect is one or more emitters; each makes particles", icon="INFO")
        row = layout.row()
        row.template_list("BOZ_UL_fx", "emitters", scene, "boz_fx_emitters", scene, "boz_fx_emitter_index", rows=2)
        column = row.column(align=True)
        column.operator(BOZ_OT_fx_emitter_add.bl_idname, text="", icon="ADD")
        column.operator(BOZ_OT_fx_emitter_remove.bl_idname, text="", icon="REMOVE")
        form = scene.boz_fx_emitter
        box = layout.box()
        box.label(text="Look", icon="TEXTURE")
        row = box.row(align=True)
        row.label(text="Picture: " + (Path(form.texture).name if form.texture else "none"))
        row.operator(BOZ_OT_fx_texture.bl_idname, text="", icon="FILEBROWSER").target = "emitter"
        row = box.row(align=True)
        row.prop(form, "blend", expand=True)
        box.prop(form, "tint")
        row = box.row(align=True)
        row.prop(form, "frames")
        row.prop(form, "columns")
        if form.frames > 1:
            box.prop(form, "frame_mode")
            box.prop(form, "frame_time")
        box.prop(form, "shape")
        box = layout.box()
        box.label(text="Making particles", icon="PARTICLES")
        _pair(box, form, "spawn_every")
        box.prop(form, "forever")
        if not form.forever:
            box.prop(form, "duration")
        _pair(box, form, "life")
        box = layout.box()
        box.label(text="Size and turning", icon="FULLSCREEN_ENTER")
        _pair(box, form, "size")
        row = box.row(align=True)
        row.prop(form, "size_scale")
        row.prop(form, "growth")
        _pair(box, form, "spin")
        _pair(box, form, "angle")
        box = layout.box()
        box.label(text="Where they start and how they move", icon="ORIENTATION_GLOBAL")
        box.prop(form, "position")
        box.prop(form, "position_spread")
        box.prop(form, "velocity")
        box.prop(form, "velocity_spread")
        box.prop(form, "gravity")
        box.prop(form, "space")
        box = layout.box()
        box.label(text="More", icon="PREFERENCES")
        for name, _bit, _label in TOGGLES:
            box.prop(form, name)


class BOZ_PT_fx_projectiles(_FxPanel, Panel):
    bl_idname = "BOZ_PT_fx_projectiles"
    bl_label = "Projectiles"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if not len(scene.boz_fx_projectiles) and (data()["projectiles"] or any(u.kind == "projectile" for u in used())):
            refresh(context)
        layout.label(text="What weapons and scripts fire; any weapon can (Weapons tab)", icon="INFO")
        row = layout.row()
        row.template_list("BOZ_UL_fx", "projectiles", scene, "boz_fx_projectiles", scene,
                          "boz_fx_projectile_index", rows=3)
        column = row.column(align=True)
        column.operator(BOZ_OT_fx_projectile_new.bl_idname, text="", icon="ADD")
        column.operator(BOZ_OT_fx_remove.bl_idname, text="", icon="REMOVE").kind = "projectile"
        layout.operator(BOZ_OT_fx_add_game.bl_idname, icon="VIEWZOOM").kind = "projectile"
        item = current_item("projectile")
        if item is None:
            return
        layout.prop(scene, "boz_fx_projectile_rename", text="Name")
        if item.source == "game":
            game_entry = current_game("projectile")
            box = layout.box()
            box.label(text="From the game: " + (effects.BEHAVIOURS.get(game_entry.behaviour, "a projectile")
                                                if game_entry else "a projectile"), icon="LINKED")
            box.prop(scene, "boz_fx_game_hidden")
            box.prop(scene, "boz_fx_game_anchored")
            row = layout.row(align=True)
            row.label(text=snippet("projectile", item), icon="SCRIPT")
            row.operator(BOZ_OT_fx_copy_line.bl_idname, text="", icon="COPYDOWN").kind = "projectile"
            return
        form = scene.boz_fx_projectile
        projectile = current_projectile(data()) or {}
        layout.operator(BOZ_OT_fx_script.bl_idname, text="Open script" if projectile.get("script") else "Make a script",
                        icon="SCRIPT").kind = "projectile"
        box = layout.box()
        box.label(text="How it flies", icon="CURVE_PATH")
        box.prop(form, "speed")
        box.prop(form, "gravity")
        box.prop(form, "lifetime")
        box.prop(form, "radius")
        box = _draw_pieces(layout, form, "Pieces: they run unless its script returns false")
        box.prop(form, "impact")
        box.prop(form, "trail")
        box.prop(form, "use_ribbon")
        if form.use_ribbon:
            row = box.row(align=True)
            row.label(text="Ribbon picture: " + (Path(form.ribbon_texture).name if form.ribbon_texture else "the Ray Gun's"))
            row.operator(BOZ_OT_fx_texture.bl_idname, text="", icon="FILEBROWSER").target = "ribbon"
            box.prop(form, "ribbon_width")
            box.prop(form, "ribbon_colour")
            box.prop(form, "ribbon_fade")
        _problems(layout, "Projectiles")


CLASSES = (BOZ_FxEmitter, BOZ_FxEffectPieces, BOZ_FxProjectile, BOZ_FxItem, BOZ_OT_fx_new, BOZ_OT_fx_add_game,
           BOZ_OT_fx_make_editable, BOZ_OT_fx_remove, BOZ_OT_fx_emitter_add, BOZ_OT_fx_emitter_remove,
           BOZ_OT_fx_texture, BOZ_OT_fx_projectile_new, BOZ_OT_fx_script, BOZ_OT_fx_copy_line,
           BOZ_OT_fx_restart, BOZ_UL_fx, BOZ_PT_fx_effects, BOZ_PT_fx_emitter, BOZ_PT_fx_projectiles)

SCENE_PROPS = {
    "boz_fx_effects": lambda: CollectionProperty(type=BOZ_FxItem),
    "boz_fx_effect_index": lambda: IntProperty(update=_selection_changed),
    "boz_fx_emitters": lambda: CollectionProperty(type=BOZ_FxItem),
    "boz_fx_emitter_index": lambda: IntProperty(update=_selection_changed),
    "boz_fx_emitter": lambda: PointerProperty(type=BOZ_FxEmitter),
    "boz_fx_projectiles": lambda: CollectionProperty(type=BOZ_FxItem),
    "boz_fx_projectile_index": lambda: IntProperty(update=_selection_changed),
    "boz_fx_projectile": lambda: PointerProperty(type=BOZ_FxProjectile),
    "boz_fx_effect_pieces": lambda: PointerProperty(type=BOZ_FxEffectPieces),
    "boz_fx_rename": lambda: StringProperty(name="Name", update=_rename("effect"),
                                            description="What scripts call it (a-z, 0-9, _)"),
    "boz_fx_projectile_rename": lambda: StringProperty(name="Name", update=_rename("projectile"),
                                                       description="What scripts and weapons call it"),
    "boz_fx_kind": lambda: EnumProperty(name="Kind", update=_effect_changed, items=[
        ("lasting", "Lasting", "Keeps going until removed (a script's lifetime)"),
        ("burst", "Burst", "Plays once (an impact)")]),
    "boz_fx_scale": lambda: FloatProperty(name="Scale", min=0.01, max=100.0, default=1.0, update=_effect_changed,
                                          description="Speed, size and growth of every emitter times this"),
    "boz_fx_game_hidden": lambda: BoolProperty(name="Hide its model", update=_game_changed,
                                               description="Leave its own model out (a black hole without the device)"),
    "boz_fx_game_anchored": lambda: BoolProperty(name="Stays where spawned", update=_game_changed,
                                                 description="Leave its physics out: no gravity, it stays where a "
                                                             "script spawns it"),
    "boz_fx_playing": lambda: BoolProperty(name="Play", default=True, description="Play the preview"),
    "boz_fx_speed": lambda: FloatProperty(name="Speed", min=0.05, max=4.0, default=1.0,
                                          description="How fast the preview plays"),
    "boz_fx_loop": lambda: BoolProperty(name="Loop", default=True, description="A burst plays again"),
    "boz_fx_moving": lambda: BoolProperty(name="Moving", default=False,
                                          description="The effect moves in a circle (see trails as they look on a "
                                                      "projectile)"),
    "boz_fx_in_map": lambda: BoolProperty(name="In the map", default=False, update=_in_map_changed,
                                          description="Show the map and play the effect at the 3D cursor"),
}


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, make in SCENE_PROPS.items():
        setattr(bpy.types.Scene, name, make())
    if not bpy.app.background:
        _state["handler"] = bpy.types.SpaceView3D.draw_handler_add(_draw_preview, (), "WINDOW", "POST_VIEW")
        bpy.app.timers.register(_redraw_tick, first_interval=1.0, persistent=True)
    bpy.types.VIEW3D_HT_header.append(draw_view_header)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_view_header)
    if _state["handler"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_state["handler"], "WINDOW")
        _state["handler"] = None
    if bpy.app.timers.is_registered(_redraw_tick):
        bpy.app.timers.unregister(_redraw_tick)
    for name in reversed(list(SCENE_PROPS)):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
