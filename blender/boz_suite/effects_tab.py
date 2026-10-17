"""The Effects tab: every effect and projectile of the game, and the names this map gives them.

Game effects lists what the game can spawn (bozkit.effects.catalog): the shared effects and each
map's own, and each map's projectiles (grenades, bolts, monkey bombs, the Gersch device) with
what they do. Every one works on any map: the build bundles what a map uses (bozkit.bundle).
Name it gives one a name scripts use (source/effects.json), and the changes a projectile can have
(Hide its model, Stays where spawned). Scripts spawn them with boz.effects (docs/effects.md).
"""
from __future__ import annotations

import re
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import link

try:
    from bozkit import effects
except ModuleNotFoundError:
    from ._vendor.bozkit import effects

WORKSPACE = "Effects"
_state: dict = {"catalog": None, "refreshing": False}
KIND_ITEMS = [("all", "All", "Effects and projectiles"),
              ("effect", "Effects", "Particles and visual effects"),
              ("projectile", "Projectiles", "Grenades, bolts, lures, black holes: they bring the "
                                            "game's behaviour")]


def source_dir() -> Path | None:
    root = link.project_root()
    return root / "source" if root else None


def _pack():
    from . import weapons_tab
    return weapons_tab._pack()


def catalog(refresh: bool = False) -> list:
    pack = _pack()
    if pack is None:
        return []
    if refresh or _state["catalog"] is None:
        try:
            _state["catalog"] = effects.catalog(pack.read, pack.names())
        except (effects.EffectError, OSError, KeyError, ValueError) as exc:
            print(f"boz_suite: effects: {exc}")
            _state["catalog"] = []
    return _state["catalog"]


def used() -> list:
    source = source_dir()
    try:
        return effects.load(source) if source else []
    except effects.EffectError:
        return []


def _where(level: str) -> str:
    return "every map" if not level else level


def setup(item) -> str:
    """Lua a script needs once before spawning *item*: a black hole's kills count as the player's
    only when the script asks (boz.zombies.credit_kills)."""
    if item.kind == "projectile" and item.behaviour == 6:
        return 'require("boz.zombies").credit_kills("SUBJECT_ZOMBIE_GERSCH_DEATH")\n'
    return ""


def snippet(item) -> str:
    """A line of Lua that spawns the map's effect *item*."""
    if item.kind == "projectile":
        triggers = effects.TRIGGERS.get(item.behaviour, ())
        # A black hole's swirl draws about a metre below the device: 2 m up puts it at chest height.
        raise_ = ", raise = 200" if item.behaviour == 6 else ""
        options = f', {{trigger = "{triggers[0]}", lifetime = 6{raise_}}}' if triggers else ""
        return f'effects.projectile("{item.name}", effects.aim(){options})'
    return f'effects.spawn("{item.name}", effects.aim(), {{lifetime = 2}})'


# --- Lists ------------------------------------------------------------------------------------

class BOZ_EffectEntry(PropertyGroup):
    key: StringProperty()
    label: StringProperty()
    kind: StringProperty()
    level: StringProperty()
    detail: StringProperty()


class BOZ_EffectUsed(PropertyGroup):
    kind: StringProperty()
    level: StringProperty()
    behaviour: IntProperty()
    hidden: BoolProperty()
    anchored: BoolProperty()


def selected(collection, index):
    return collection[index] if 0 <= index < len(collection) else None


def refresh_catalog(context, refresh: bool = False) -> None:
    scene = link.map_scene()
    kind = scene.boz_effect_kind
    _state["refreshing"] = True
    try:
        scene.boz_effect_entries.clear()
        for entry in catalog(refresh):
            if kind != "all" and entry.kind != kind:
                continue
            item = scene.boz_effect_entries.add()
            item.key, item.label, item.kind, item.level = entry.key, entry.label, entry.kind, entry.level
            what = effects.BEHAVIOURS.get(entry.behaviour, "") if entry.kind == "projectile" else "Effect"
            item.detail = what + (f" · fired by {', '.join(entry.users[:3])}" if entry.users else "")
        scene.boz_effect_index = min(scene.boz_effect_index, len(scene.boz_effect_entries) - 1)
    finally:
        _state["refreshing"] = False


def refresh_used(context, keep: str | None = None) -> None:
    scene = link.map_scene()
    keep = keep or (selected(scene.boz_effects_used, scene.boz_effect_used_index).name
                    if selected(scene.boz_effects_used, scene.boz_effect_used_index) else None)
    _state["refreshing"] = True
    try:
        scene.boz_effects_used.clear()
        for u in used():
            item = scene.boz_effects_used.add()
            item.name, item.kind, item.level, item.behaviour = u.name, u.kind, u.level, u.behaviour
            item.hidden, item.anchored = u.hidden, u.anchored
        names = [i.name for i in scene.boz_effects_used]
        scene.boz_effect_used_index = names.index(keep) if keep in names else 0
        current = selected(scene.boz_effects_used, scene.boz_effect_used_index)
        scene.boz_effect_rename = current.name if current else ""
        scene.boz_effect_hidden = current.hidden if current else False
        scene.boz_effect_anchored = current.anchored if current else False
    finally:
        _state["refreshing"] = False


def refresh(context) -> None:
    refresh_catalog(context)
    refresh_used(context)


def _kind_changed(self, context):
    refresh_catalog(context)


def _entry_changed(self, context):
    if _state["refreshing"]:
        return
    scene = link.map_scene()
    item = selected(scene.boz_effect_entries, scene.boz_effect_index)
    if item is not None:
        scene.boz_effect_new_name = _clean(item.label)


def _used_changed(self, context):
    if _state["refreshing"]:
        return
    scene = link.map_scene()
    item = selected(scene.boz_effects_used, scene.boz_effect_used_index)
    _state["refreshing"] = True
    try:
        scene.boz_effect_rename = item.name if item else ""
        scene.boz_effect_hidden = item.hidden if item else False
        scene.boz_effect_anchored = item.anchored if item else False
    finally:
        _state["refreshing"] = False


def _changes_changed(self, context):
    """Hide its model / Stays where spawned: stored with the effect (the build makes the map's
    own copy of its spec without them)."""
    if _state["refreshing"]:
        return
    scene = link.map_scene()
    item = selected(scene.boz_effects_used, scene.boz_effect_used_index)
    source = source_dir()
    if item is None or source is None:
        return
    current = used()
    for u in current:
        if u.name == item.name:
            u.hidden, u.anchored = scene.boz_effect_hidden, scene.boz_effect_anchored
    effects.save(source, current)
    refresh_used(context, keep=item.name)


def _rename(self, context):
    if _state["refreshing"]:
        return
    scene = link.map_scene()
    item = selected(scene.boz_effects_used, scene.boz_effect_used_index)
    source = source_dir()
    new = _clean(scene.boz_effect_rename)
    if item is None or source is None or new == item.name:
        return
    current = used()
    if any(u.name == new for u in current):
        return
    for u in current:
        if u.name == item.name:
            u.name = new
    effects.save(source, current)
    refresh_used(context, keep=new)


def _clean(text: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "effect"
    if not name[0].isalpha():
        name = "e_" + name
    return name[:32]


# --- Operators --------------------------------------------------------------------------------

class BOZ_OT_effects_refresh(Operator):
    bl_idname = "boz.effects_refresh"
    bl_label = "Show the effects"
    bl_description = "Read every effect and projectile of the game"

    def execute(self, context):
        refresh_catalog(context, refresh=True)
        refresh_used(context)
        return {"FINISHED"}


class BOZ_OT_effect_use(Operator):
    bl_idname = "boz.effect_use"
    bl_label = "Name it"
    bl_description = ("Give this effect the name below: scripts spawn it with boz.effects (it works "
                      "on any map; the build brings what it needs)")

    def execute(self, context):
        scene = link.map_scene()
        item = selected(scene.boz_effect_entries, scene.boz_effect_index)
        source = source_dir()
        if item is None or source is None:
            return {"CANCELLED"}
        entry = next((e for e in catalog() if e.key == item.key), None)
        if entry is None:
            return {"CANCELLED"}
        current = used()
        name = _clean(scene.boz_effect_new_name or item.label)
        base, number = name, 1
        while any(u.name == name for u in current):
            number += 1
            name = f"{base[:29]}_{number}"
        current.append(effects.Used(name, entry.kind, entry.level, entry.hash, entry.behaviour))
        try:
            effects.save(source, current)
        except effects.EffectError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        refresh_used(context, keep=name)
        self.report({"INFO"}, f"{name}: scripts spawn it with boz.effects")
        return {"FINISHED"}


class BOZ_OT_effect_remove(Operator):
    bl_idname = "boz.effect_remove"
    bl_label = "Forget the name"
    bl_description = "Forget this name (scripts can still spawn the effect by its game name or 0x hash)"

    def execute(self, context):
        scene = link.map_scene()
        item = selected(scene.boz_effects_used, scene.boz_effect_used_index)
        source = source_dir()
        if item is None or source is None:
            return {"CANCELLED"}
        effects.save(source, [u for u in used() if u.name != item.name])
        refresh_used(context)
        return {"FINISHED"}


class BOZ_OT_effect_copy(Operator):
    bl_idname = "boz.effect_copy"
    bl_label = "Copy script line"
    bl_description = "Copy a line of Lua that spawns this effect where the player aims"

    def execute(self, context):
        scene = link.map_scene()
        item = selected(scene.boz_effects_used, scene.boz_effect_used_index)
        if item is None:
            return {"CANCELLED"}
        context.window_manager.clipboard = 'local effects = require("boz.effects")\n' + setup(item) + snippet(item)
        self.report({"INFO"}, "Copied")
        return {"FINISHED"}


# --- Panels -----------------------------------------------------------------------------------

class BOZ_UL_effect_entries(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.label, icon="PARTICLES" if item.kind == "effect" else "PHYSICS")
        row.label(text=_where(item.level))

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)
        if self.filter_name:
            text = self.filter_name.lower()
            flags = [self.bitflag_filter_item if text in f"{i.label} {i.level} {i.detail}".lower()
                     else 0 for i in items]
        return flags, []


class BOZ_UL_effects_used(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.name, icon="PARTICLES" if item.kind == "effect" else "PHYSICS")
        row.label(text=_where(item.level))


class _EffectsPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == WORKSPACE


class BOZ_PT_effects_game(_EffectsPanel, Panel):
    bl_idname = "BOZ_PT_effects_game"
    bl_label = "Game effects"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if source_dir() is None:
            layout.label(text="Open a project to use effects", icon="INFO")
            return
        if _pack() is None:
            layout.label(text="Build the asset library in the launcher to see the effects", icon="ERROR")
            return
        layout.prop(scene, "boz_effect_kind", text="Show")
        if not len(scene.boz_effect_entries):
            layout.operator(BOZ_OT_effects_refresh.bl_idname, icon="FILE_REFRESH")
            return
        layout.template_list("BOZ_UL_effect_entries", "", scene, "boz_effect_entries", scene,
                             "boz_effect_index", rows=10)
        item = selected(scene.boz_effect_entries, scene.boz_effect_index)
        if item is None:
            return
        box = layout.box()
        box.label(text=item.label, icon="PARTICLES" if item.kind == "effect" else "PHYSICS")
        box.label(text=item.detail)
        box.label(text="From the shared effects" if not item.level else
                  f"From {item.level}: works on any map")
        row = box.row(align=True)
        row.prop(scene, "boz_effect_new_name", text="Name")
        row.operator(BOZ_OT_effect_use.bl_idname, icon="ADD")


class BOZ_PT_effects_used(_EffectsPanel, Panel):
    bl_idname = "BOZ_PT_effects_used"
    bl_label = "Named effects"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if source_dir() is None:
            return
        if not len(scene.boz_effects_used) and used():
            refresh_used(context)
        if not len(scene.boz_effects_used):
            layout.label(text="Pick one in Game effects, then Name it", icon="INFO")
            return
        row = layout.row()
        row.template_list("BOZ_UL_effects_used", "", scene, "boz_effects_used", scene,
                          "boz_effect_used_index", rows=4)
        row.column(align=True).operator(BOZ_OT_effect_remove.bl_idname, text="", icon="REMOVE")
        item = selected(scene.boz_effects_used, scene.boz_effect_used_index)
        if item is None:
            return
        box = layout.box()
        box.prop(scene, "boz_effect_rename", text="Name")
        if item.kind == "projectile":
            box.label(text=effects.BEHAVIOURS.get(item.behaviour, "Projectile"))
            column = box.column(align=True)
            column.prop(scene, "boz_effect_hidden")
            column.prop(scene, "boz_effect_anchored")
            triggers = effects.TRIGGERS.get(item.behaviour, ())
            if triggers:
                box.label(text="Triggers: " + ", ".join(triggers))
        box.label(text=snippet(item))
        box.operator(BOZ_OT_effect_copy.bl_idname, icon="COPYDOWN")


CLASSES = (BOZ_EffectEntry, BOZ_EffectUsed, BOZ_OT_effects_refresh, BOZ_OT_effect_use,
           BOZ_OT_effect_remove, BOZ_OT_effect_copy, BOZ_UL_effect_entries, BOZ_UL_effects_used,
           BOZ_PT_effects_game, BOZ_PT_effects_used)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.boz_effect_entries = CollectionProperty(type=BOZ_EffectEntry)
    bpy.types.Scene.boz_effect_index = IntProperty(update=_entry_changed)
    bpy.types.Scene.boz_effect_kind = EnumProperty(name="Effects", items=KIND_ITEMS,
                                                   update=_kind_changed)
    bpy.types.Scene.boz_effect_new_name = StringProperty(
        name="Name", description="What scripts call it (a-z, 0-9, _)")
    bpy.types.Scene.boz_effects_used = CollectionProperty(type=BOZ_EffectUsed)
    bpy.types.Scene.boz_effect_used_index = IntProperty(update=_used_changed)
    bpy.types.Scene.boz_effect_rename = StringProperty(
        name="Name", description="What scripts call it", update=_rename)
    bpy.types.Scene.boz_effect_hidden = BoolProperty(
        name="Hide its model", update=_changes_changed,
        description="Leave its own model out (a black hole without the device lying on the floor)")
    bpy.types.Scene.boz_effect_anchored = BoolProperty(
        name="Stays where spawned", update=_changes_changed,
        description="Leave its physics out: no gravity, it stays exactly where a script spawns it")


def unregister():
    for name in ("boz_effect_anchored", "boz_effect_hidden", "boz_effect_rename", "boz_effect_used_index", "boz_effects_used",
                 "boz_effect_new_name", "boz_effect_kind", "boz_effect_index", "boz_effect_entries"):
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
