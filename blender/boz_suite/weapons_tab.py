"""The Weapons tab: the project's weapons, their properties, new and imported weapons, scripts.

The weapons come from the map's base level (bozkit.weapons reads its weapons group); the
project keeps its list in source/weapons/index.json and every changed, new or imported weapon in
source/weapons/<name>.json. Edits are saved as they are made; Build & Run applies them to the
map's weapons groups.

The tab's panels live in the Properties editor's scene tab of the Weapons workspace (as the Game
tab's forms do). The form rows are a collection rebuilt for the selected weapon; changing a row
writes the weapon's file.
"""
from __future__ import annotations

import math
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import link

try:
    from bozkit import blender_scene, library, viewmodel, weapons as wp
except ModuleNotFoundError:
    from ._vendor.bozkit import blender_scene, library, viewmodel, weapons as wp

WORKSPACE = "Weapons"
SCRIPT_TEMPLATE = '''-- {name}: a weapon script. self is the weapon: self.name, and the live weapon's
-- self:clip(), self:reserve(), self:set_ammo(clip, reserve), self:damage(),
-- self:set_damage(head, torso, limbs), self:fire_rate(), self:set_fire_rate(rpm).
-- Global variables (not local) are saved with the game.

-- The player got this weapon (wall buy, mystery box, boz.weapons.give).
function on_given()
end

-- The player took it in hand.
function on_equip()
end

-- Every shot (data.clip: rounds left before this one).
function on_fire(data)
end

-- A reload started.
function on_reload()
end
'''

_state: dict = {"levels": {}, "refreshing": False, "items": {}}


# --- Data --------------------------------------------------------------------------------

def _pack():
    from . import game
    models = game.game_models()
    return models.pack if models is not None else None


def level_weapons(level: str) -> list:
    """The game's weapons of a level (cached), [] without the asset library."""
    level = wp.GEAR.get(level, level)
    if level not in _state["levels"]:
        pack = _pack()
        try:
            _state["levels"][level] = wp.read_level(pack, level) if pack is not None else []
        except (KeyError, OSError, ValueError, library.LibraryError):
            _state["levels"][level] = []
    return _state["levels"][level]


def source_dir() -> Path | None:
    root = link.project_root()
    return root / "source" if root else None


def base_level(context) -> str:
    return wp.GEAR.get(link.map_scene().boz.base, link.map_scene().boz.base)


def defs() -> dict:
    source = source_dir()
    try:
        return {d.name: d for d in wp.load_defs(source)} if source else {}
    except wp.WeaponError:
        return {}


def project_index(context) -> list[str]:
    """The project's weapon list; written the first time (the Colt alone for a map that does
    not start from a whole shipped level)."""
    source = source_dir()
    if source is None:
        return []
    try:
        index = wp.load_index(source)
    except wp.WeaponError:
        index = None
    if index is None:
        template = "kino" if link.map_scene().boz.inherit else "empty"
        index = wp.default_index(level_weapons(base_level(context)), template)
        if level_weapons(base_level(context)):
            wp.save_index(source, index)
    return index


def game_weapon(level: str, name: str):
    target = wp._hash_of(name)
    return next((w for w in level_weapons(level) if w.name_hash == target), None)


def base_values(context, weapon_def) -> dict:
    """The values a weapon has before the project's changes (its game weapon's)."""
    level = weapon_def.level or base_level(context)
    found = game_weapon(level, weapon_def.source)
    return dict(found.values) if found else {f.key: f.default for f in wp.FIELDS}


def weapon_def(context, name: str):
    return defs().get(name) or wp.WeaponDef(name)


def current_values(context, name: str) -> tuple[dict, dict]:
    """(values with the project's changes, the base values)."""
    weapon = weapon_def(context, name)
    base = base_values(context, weapon)
    values = dict(base)
    values.update(weapon.fields)
    return values, base


def save(context, weapon) -> None:
    source = source_dir()
    if source is None:
        return
    is_new = weapon.base and weapon.base != weapon.name
    if not weapon.fields and not weapon.level and not is_new and not weapon.script:
        wp.delete_def(source, weapon.name)
    else:
        wp.save_def(source, weapon)


def start_weapon() -> tuple[str, int]:
    source = source_dir()
    try:
        return wp.load_start(source) if source else (wp.DEFAULT_START, wp.DEFAULT_START_RESERVE)
    except wp.WeaponError:
        return wp.DEFAULT_START, wp.DEFAULT_START_RESERVE


def _start_reserve_changed(self, context):
    if _state["refreshing"] or source_dir() is None:
        return
    name, _reserve = start_weapon()
    wp.save_start(source_dir(), name, self.boz_start_reserve)


def label_of(context, name: str) -> str:
    found = game_weapon(base_level(context), name)
    return found.label if found else name


def sound_items(context) -> list:
    """Sounds (and muzzle flashes) the level's weapons use, named after the first weapon using
    each: a new weapon can take any of them."""
    key = ("sounds", base_level(context))
    if key not in _state["items"]:
        seen = {}
        for weapon in level_weapons(base_level(context)):
            for spec in wp.FIELDS:
                if spec.kind == "sound":
                    value = weapon.values.get(spec.key) or 0
                    if value and value not in seen:
                        seen[value] = f"{weapon.label}: {spec.label}"
        _state["items"][key] = [("0", "None", "")] + [
            (str(value), text, "") for value, text in sorted(seen.items(), key=lambda kv: kv[1].lower())]
    return _state["items"][key]


NONE = "_none"   # Blender takes an empty identifier as a divider, not a choice


def weapon_items(context, include_none=True, listed_only=False) -> list:
    """Weapons to choose from: the project's list first, then (unless *listed_only*) every other
    weapon of the map (Pack-a-Punch results are rarely listed)."""
    key = ("weapons", base_level(context), include_none, listed_only, tuple(project_index(context)))
    if key not in _state["items"]:
        names = list(project_index(context))
        if not listed_only:
            names = list(dict.fromkeys(names + [w.name for w in level_weapons(base_level(context))]))
        items = [(NONE, "None", "")] if include_none else []
        items += [(name, label_of(context, name), "") for name in names]
        _state["items"][key] = items
    return _state["items"][key]


def clear_caches() -> None:
    _state["items"].clear()


# --- Rows of the form --------------------------------------------------------------------

def _enum_items(self, context):
    spec = wp.FIELD_BY_KEY.get(self.key)
    if spec is None:
        return [("0", "-", "")]
    if spec.kind == "enum":
        key = ("enum", self.key)
        if key not in _state["items"]:
            _state["items"][key] = [(str(v), label, "") for v, label in spec.options]
        return _state["items"][key]
    if spec.kind == "weapon":
        return weapon_items(context)
    if spec.kind == "sound":
        return sound_items(context)
    return [("0", "-", "")]


def _row_value(row):
    spec = wp.FIELD_BY_KEY[row.key]
    if spec.kind == "int":
        return int(row.value_int)
    if spec.kind == "float":
        return round(float(row.value_float), 4)
    if spec.kind == "bool":
        return bool(row.value_bool)
    if spec.kind == "enum":
        return int(row.value_enum)
    if spec.kind == "sound":
        return int(row.value_enum)
    if spec.kind == "weapon":
        return "" if row.value_enum == NONE else row.value_enum
    return None


def _row_changed(self, context):
    if _state["refreshing"]:
        return
    scene = link.map_scene()
    item = selected(scene)
    if item is None:
        return
    weapon = weapon_def(context, item.name)
    base = base_values(context, weapon)
    value = _row_value(self)
    original = base.get(self.key)
    if self.key == "Upgrade":
        same = (value or "") == (original or "")
    elif isinstance(value, float):
        same = abs(value - float(original or 0)) < 1e-4
    else:
        same = value == original
    if same:
        weapon.fields.pop(self.key, None)
    else:
        weapon.fields[self.key] = value
    save(context, weapon)
    self.changed = not same
    refresh_list(context, keep=item.name)


class BOZ_WeaponField(PropertyGroup):
    key: StringProperty()
    value_int: IntProperty(min=0, update=_row_changed)
    value_float: FloatProperty(precision=3, step=1, update=_row_changed)
    value_bool: BoolProperty(update=_row_changed)
    value_enum: EnumProperty(items=_enum_items, update=_row_changed)
    changed: BoolProperty()


def _selected_changed(self, context):
    refresh_fields(context)
    show_preview(context)


class BOZ_WeaponItem(PropertyGroup):
    label: StringProperty()
    status: StringProperty()   # game, edited, new, imported


def selected(scene):
    index = scene.boz_weapon_index
    return scene.boz_weapons[index] if 0 <= index < len(scene.boz_weapons) else None


def refresh_list(context, keep: str | None = None) -> None:
    scene = link.map_scene()
    keep = keep or (selected(scene).name if selected(scene) else None)
    all_defs = defs()
    _state["refreshing"] = True
    try:
        scene.boz_weapons.clear()
        start, reserve = start_weapon()
        scene.boz_start_reserve = reserve
        for name in project_index(context):
            item = scene.boz_weapons.add()
            item.name = name
            weapon = all_defs.get(name)
            item.label = label_of(context, name) if not (weapon and weapon.level) else \
                f"{name} ({weapon.level})"
            if name == start:
                item.label += "  (start)"
            if weapon is None:
                item.status = "game"
            elif weapon.level:
                item.status = "imported"
            elif weapon.base and weapon.base != weapon.name:
                item.status = "new"
            else:
                item.status = "edited"
        names = [item.name for item in scene.boz_weapons]
        if keep in names:
            scene.boz_weapon_index = names.index(keep)
        elif scene.boz_weapon_index >= len(names):
            scene.boz_weapon_index = max(0, len(names) - 1)
    finally:
        _state["refreshing"] = False


def refresh_fields(context) -> None:
    scene = link.map_scene()
    item = selected(scene)
    _state["refreshing"] = True
    try:
        scene.boz_weapon_fields.clear()
        if item is None:
            return
        values, base = current_values(context, item.name)
        changed = weapon_def(context, item.name).fields
        for spec in wp.FIELDS:
            row = scene.boz_weapon_fields.add()
            row.key = spec.key
            value = values.get(spec.key, spec.default)
            if spec.kind == "int":
                row.value_int = max(0, int(value or 0))
            elif spec.kind == "float":
                row.value_float = float(value or 0.0)
            elif spec.kind == "bool":
                row.value_bool = bool(value)
            elif spec.kind in ("enum", "sound"):
                wanted = str(int(value or 0))
                if wanted in {i[0] for i in _enum_items(row, context)}:
                    row.value_enum = wanted
            elif spec.kind == "weapon":
                wanted = str(value or NONE)
                if wanted in {i[0] for i in _enum_items(row, context)}:
                    row.value_enum = wanted
            row.changed = spec.key in changed
    finally:
        _state["refreshing"] = False


def refresh(context) -> None:
    clear_caches()
    refresh_list(context)
    refresh_fields(context)


# --- Operators ----------------------------------------------------------------------------

def _import_items(self, context):
    key = ("import", base_level(context), tuple(project_index(context)))
    if key not in _state["items"]:
        listed = set(project_index(context))
        items = []
        for level in wp.WEAPON_LEVELS:
            for weapon in level_weapons(level):
                if weapon.name in listed or not wp.is_gun(weapon):
                    continue
                here = level == base_level(context)
                items.append((f"{level}:{weapon.name}",
                              f"{weapon.label} ({'this map' if here else level})",
                              "From this map's weapons" if here else
                              f"Copied from {level} with its models and animations"))
        _state["items"][key] = items or [("", "Every weapon is listed already", "")]
    return _state["items"][key]


class BOZ_OT_weapon_import(Operator):
    bl_idname = "boz.weapon_import"
    bl_label = "Import from game"
    bl_description = ("Add a game weapon to the project: one of this map's, or another map's "
                      "(copied with its models and animations)")
    bl_property = "choice"

    choice: EnumProperty(items=_import_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.choice:
            return {"CANCELLED"}
        level, _, name = self.choice.partition(":")
        source = source_dir()
        index = project_index(context)
        if level != base_level(context):
            if game_weapon(base_level(context), name) is not None:
                self.report({"WARNING"}, f"This map has its own {name}: added that one")
            else:
                wp.save_def(source, wp.WeaponDef(name, "", level))
        wp.save_index(source, index + [name])
        clear_caches()
        refresh_list(context, keep=name)
        refresh_fields(context)
        return {"FINISHED"}


class BOZ_OT_weapon_new(Operator):
    bl_idname = "boz.weapon_new"
    bl_label = "New weapon"
    bl_description = "A new weapon made from the selected one (its model and animations, your values)"

    name: StringProperty(name="Name")

    def invoke(self, context, event):
        item = selected(link.map_scene())
        if item is None:
            self.report({"WARNING"}, "Select the weapon to start from")
            return {"CANCELLED"}
        self.name = f"{item.name if not item.name.startswith('0x') else 'weapon'}_custom"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        item = selected(link.map_scene())
        name = self.name.strip()
        if not wp.NAME_RE.fullmatch(name):
            self.report({"ERROR"}, "Use letters, digits and _ (starting with a letter)")
            return {"CANCELLED"}
        if name in project_index(context) or game_weapon(base_level(context), name):
            self.report({"ERROR"}, f"There is already a weapon called {name}")
            return {"CANCELLED"}
        start = weapon_def(context, item.name)
        new = wp.WeaponDef(name, start.source, start.level, dict(start.fields))
        source = source_dir()
        wp.save_def(source, new)
        wp.save_index(source, project_index(context) + [name])
        clear_caches()
        refresh_list(context, keep=name)
        refresh_fields(context)
        return {"FINISHED"}


class BOZ_OT_weapon_remove(Operator):
    bl_idname = "boz.weapon_remove"
    bl_label = "Remove weapon"
    bl_description = ("Take the weapon off the project's list (a new or imported weapon is "
                      "deleted; the map's own weapons stay in the game files)")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item = selected(link.map_scene())
        if item is None:
            return {"CANCELLED"}
        source = source_dir()
        if item.status in ("new", "imported"):
            wp.delete_def(source, item.name)
        wp.save_index(source, [n for n in project_index(context) if n != item.name])
        clear_caches()
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_weapon_reset(Operator):
    bl_idname = "boz.weapon_reset"
    bl_label = "Reset"
    bl_description = "Undo every change to this weapon's values (or one value)"

    key: StringProperty()

    def execute(self, context):
        item = selected(link.map_scene())
        if item is None:
            return {"CANCELLED"}
        weapon = weapon_def(context, item.name)
        if self.key:
            weapon.fields.pop(self.key, None)
        else:
            weapon.fields.clear()
        save(context, weapon)
        refresh_list(context, keep=item.name)
        refresh_fields(context)
        return {"FINISHED"}


class BOZ_OT_weapon_field_help(Operator):
    bl_idname = "boz.weapon_field_help"
    bl_label = "About this value"
    bl_options = {"INTERNAL"}

    key: StringProperty()

    @classmethod
    def description(cls, context, properties):
        spec = wp.FIELD_BY_KEY.get(properties.key)
        if spec is None:
            return ""
        note = "" if spec.confirmed else "\n(Meaning from the shipped weapons, not yet proven in the game's code.)"
        return spec.description + note

    def execute(self, context):
        return {"FINISHED"}


def _script_path(name: str) -> str:
    return f"weapons/{name}.lua"


class BOZ_OT_weapon_script_new(Operator):
    bl_idname = "boz.weapon_script_new"
    bl_label = "Add script"
    bl_description = "A Lua script for this weapon (on_fire, on_equip, ...) opened in the Scripts tab"

    def execute(self, context):
        from . import objects
        item = selected(link.map_scene())
        folder = objects.scripts_dir()
        if item is None or folder is None:
            return {"CANCELLED"}
        name = "".join(c if c.isalnum() or c == "_" else "_" for c in item.name)
        relative = _script_path(name)
        path = folder / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SCRIPT_TEMPLATE.format(name=item.name), encoding="utf-8", newline="\n")
        weapon = weapon_def(context, item.name)
        weapon.script = relative
        save(context, weapon)
        refresh_list(context, keep=item.name)
        objects.show_script(context, path)
        return {"FINISHED"}


class BOZ_OT_weapon_script_open(Operator):
    bl_idname = "boz.weapon_script_open"
    bl_label = "Open script"
    bl_description = "Open the weapon's script in the Scripts tab"

    def execute(self, context):
        from . import objects
        item = selected(link.map_scene())
        folder = objects.scripts_dir()
        weapon = weapon_def(context, item.name) if item else None
        if weapon is None or not weapon.script or folder is None:
            return {"CANCELLED"}
        objects.show_script(context, folder / weapon.script)
        return {"FINISHED"}


class BOZ_OT_weapon_script_clear(Operator):
    bl_idname = "boz.weapon_script_clear"
    bl_label = "Remove script"
    bl_description = "Detach the script from the weapon (the file stays)"

    def execute(self, context):
        item = selected(link.map_scene())
        if item is None:
            return {"CANCELLED"}
        weapon = weapon_def(context, item.name)
        weapon.script = ""
        save(context, weapon)
        refresh_list(context, keep=item.name)
        return {"FINISHED"}


class BOZ_PoolItem(PropertyGroup):
    label: StringProperty()
    enabled: BoolProperty(name="")


class BOZ_OT_box_pool(Operator):
    bl_idname = "boz.box_pool"
    bl_label = "Mystery box weapons"
    bl_description = "Choose the weapons this mystery box rolls (the project's weapons)"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        from . import convert
        obj = context.object
        if obj is None:
            return {"CANCELLED"}
        key = convert.FIELD_PREFIX + "CMysteryBox.m_Weapons"
        chosen = {n for n in str(obj.get(key, "")).split(",") if n}
        items = context.window_manager.boz_pool_items
        items.clear()
        for name, label, _desc in weapon_items(context, include_none=False, listed_only=True):
            item = items.add()
            item.name, item.label, item.enabled = name, label, name in chosen
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        column = self.layout.column(align=True)
        for item in context.window_manager.boz_pool_items:
            column.prop(item, "enabled", text=item.label)

    def execute(self, context):
        from . import convert
        obj = context.object
        chosen = [i.name for i in context.window_manager.boz_pool_items if i.enabled]
        obj[convert.FIELD_PREFIX + "CMysteryBox.m_Weapons"] = ",".join(chosen)
        return {"FINISHED"}


class BOZ_OT_weapon_start(Operator):
    bl_idname = "boz.weapon_start"
    bl_label = "Starting weapon"
    bl_description = ("Players start with this weapon instead of the Colt (they also get the knife "
                      "and two grenades); untick to go back to the Colt")

    def execute(self, context):
        item = selected(link.map_scene())
        if item is None or source_dir() is None:
            return {"CANCELLED"}
        current, reserve = start_weapon()
        wp.save_start(source_dir(), wp.DEFAULT_START if current == item.name else item.name, reserve)
        refresh_list(context, keep=item.name)
        return {"FINISHED"}


class BOZ_OT_weapons_refresh(Operator):
    bl_idname = "boz.weapons_refresh"
    bl_label = "Reload weapons"
    bl_description = "Read the project's weapon files again"

    def execute(self, context):
        refresh(context)
        show_preview(context)
        return {"FINISHED"}


# --- Panels -------------------------------------------------------------------------------

STATUS_ICONS = {"game": "BLANK1", "edited": "GREASEPENCIL", "new": "ADD", "imported": "IMPORT"}


class BOZ_UL_weapons(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        layout.label(text=item.label or item.name, icon=STATUS_ICONS.get(item.status, "BLANK1"))


class _WeaponsPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == WORKSPACE


class BOZ_PT_weapons(_WeaponsPanel, Panel):
    bl_idname = "BOZ_PT_weapons"
    bl_label = "Weapons"

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if link.project_root() is None:
            layout.label(text="Open a map project to edit its weapons", icon="INFO")
            return
        if not level_weapons(base_level(context)):
            layout.label(text="Build the asset library to see the game's weapons", icon="ERROR")
            return
        if not len(scene.boz_weapons) and project_index(context):
            layout.operator(BOZ_OT_weapons_refresh.bl_idname, text="Show the project's weapons",
                            icon="FILE_REFRESH")
            return
        row = layout.row()
        row.template_list("BOZ_UL_weapons", "", scene, "boz_weapons", scene, "boz_weapon_index",
                          rows=8)
        column = row.column(align=True)
        column.operator(BOZ_OT_weapon_import.bl_idname, text="", icon="IMPORT")
        column.operator(BOZ_OT_weapon_new.bl_idname, text="", icon="DUPLICATE")
        column.operator(BOZ_OT_weapon_remove.bl_idname, text="", icon="REMOVE")
        column.separator()
        column.operator(BOZ_OT_weapons_refresh.bl_idname, text="", icon="FILE_REFRESH")
        row = layout.row(align=True)
        row.operator(BOZ_OT_weapon_import.bl_idname, icon="IMPORT")
        row.operator(BOZ_OT_weapon_new.bl_idname, icon="DUPLICATE")
        layout.label(text="Pencil: changed. Plus: new. Arrow: from another map.", icon="INFO")


def _draw_group(layout, context, group: str) -> None:
    scene = link.map_scene()
    rows = [r for r in scene.boz_weapon_fields if wp.FIELD_BY_KEY[r.key].group == group]
    for row in rows:
        spec = wp.FIELD_BY_KEY[row.key]
        line = layout.row(align=True)
        text = spec.label + (f" ({spec.unit})" if spec.unit and spec.unit != "x" else "")
        if not spec.confirmed:
            text += " *"
        if spec.kind == "readonly":
            values, _base = current_values(context, selected(scene).name)
            value = values.get(spec.key) or 0
            shown = wp._names().get(value, f"0x{value:08x}") if value else "none"
            line.label(text=f"{text}: {shown}")
        elif spec.kind == "int":
            line.prop(row, "value_int", text=text)
        elif spec.kind == "float":
            line.prop(row, "value_float", text=text)
        elif spec.kind == "bool":
            line.prop(row, "value_bool", text=text)
        else:
            line.prop(row, "value_enum", text=text)
        if row.changed:
            line.operator(BOZ_OT_weapon_reset.bl_idname, text="", icon="LOOP_BACK").key = row.key
        line.operator(BOZ_OT_weapon_field_help.bl_idname, text="", icon="QUESTION").key = row.key


def _make_group_panel(group: str, index: int):
    class _Group(_WeaponsPanel, Panel):
        bl_idname = f"BOZ_PT_weapon_group_{index}"
        bl_label = group
        bl_parent_id = "BOZ_PT_weapon_properties"
        bl_options = {"DEFAULT_CLOSED"} if group in ("Sounds", "HUD", "Projectile") else set()

        def draw(self, context):
            _draw_group(self.layout, context, group)

    _Group.__name__ = f"BOZ_PT_weapon_group_{index}"
    return _Group


class BOZ_PT_weapon_properties(_WeaponsPanel, Panel):
    bl_idname = "BOZ_PT_weapon_properties"
    bl_label = "Properties"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and selected(link.map_scene()) is not None

    def draw_header(self, context):
        item = selected(link.map_scene())
        self.layout.label(text=item.label if item else "")

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        item = selected(scene)
        if not len(scene.boz_weapon_fields):
            layout.operator(BOZ_OT_weapons_refresh.bl_idname, text="Show its values",
                            icon="FILE_REFRESH")
            return
        weapon = weapon_def(context, item.name)
        if weapon.base and weapon.base != weapon.name:
            layout.label(text=f"Made from {label_of(context, weapon.base)}: its model and animations",
                         icon="DUPLICATE")
        if weapon.level:
            layout.label(text=f"From {weapon.level}: its sounds and effects may be missing here",
                         icon="IMPORT")
        if _state.get("preview"):
            layout.label(text=_state["preview"], icon="VIEW_CAMERA")
        start, _reserve = start_weapon()
        is_start = start == item.name
        row = layout.row(align=True)
        row.operator(BOZ_OT_weapon_start.bl_idname, depress=is_start,
                     icon="CHECKBOX_HLT" if is_start else "CHECKBOX_DEHLT")
        if is_start:
            row.prop(scene, "boz_start_reserve", text="Spare rounds")
        row = layout.row(align=True)
        row.label(text="* meaning from the shipped weapons")
        if weapon.fields:
            row.operator(BOZ_OT_weapon_reset.bl_idname, text="Reset all", icon="LOOP_BACK").key = ""


class BOZ_PT_weapon_script(_WeaponsPanel, Panel):
    bl_idname = "BOZ_PT_weapon_script"
    bl_label = "Script"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and selected(link.map_scene()) is not None

    def draw(self, context):
        layout = self.layout
        item = selected(link.map_scene())
        weapon = weapon_def(context, item.name)
        if not weapon.script:
            layout.label(text="Only for special behaviour; boz.weapons covers the rest")
            layout.operator(BOZ_OT_weapon_script_new.bl_idname, icon="ADD")
            return
        row = layout.row(align=True)
        row.operator(BOZ_OT_weapon_script_open.bl_idname, text=weapon.script, icon="TEXT")
        row.operator(BOZ_OT_weapon_script_clear.bl_idname, text="", icon="X")


GROUP_PANELS = [_make_group_panel(group, index) for index, group in enumerate(wp.GROUPS)]

CLASSES = (BOZ_WeaponField, BOZ_WeaponItem, BOZ_PoolItem, BOZ_OT_box_pool, BOZ_UL_weapons,
           BOZ_OT_weapon_import, BOZ_OT_weapon_new, BOZ_OT_weapon_remove, BOZ_OT_weapon_reset,
           BOZ_OT_weapon_field_help, BOZ_OT_weapon_script_new, BOZ_OT_weapon_script_open,
           BOZ_OT_weapon_script_clear, BOZ_OT_weapon_start, BOZ_OT_weapons_refresh,
           BOZ_PT_weapons, BOZ_PT_weapon_properties, *GROUP_PANELS, BOZ_PT_weapon_script)


# --- First-person preview -------------------------------------------------------------------
# The Weapons tab has a scene of its own (link.VIEW_SCENE): the selected weapon as the player sees
# it, the arms in their idle pose holding the gun (bozkit.viewmodel), through a camera at the
# game's eye. The tab is pinned to that scene; every other tab shows the map, and everything
# that works on the map asks link.map_scene() for it.

VIEW_CAMERA = "BOZ view camera"
VIEW_KEY = "boz_weapon_view"     # Weapons workspace: its viewport is set up


def view_scene():
    scene = bpy.data.scenes.get(link.VIEW_SCENE)
    if scene is None:
        scene = bpy.data.scenes.new(link.VIEW_SCENE)
        scene.render.resolution_x, scene.render.resolution_y = 1280, 720   # the game's frame
        scene.view_settings.view_transform = "Standard"
        world = bpy.data.worlds.get(link.VIEW_SCENE) or bpy.data.worlds.new(link.VIEW_SCENE)
        world.color = (0.05, 0.05, 0.06)
        scene.world = world
    return scene


def _view_object(scene, name, data):
    obj = bpy.data.objects.get(name)
    wanted = "CAMERA" if isinstance(data, bpy.types.Camera) else "MESH"
    if obj is not None and obj.type != wanted:
        bpy.data.objects.remove(obj)
        obj = None
    if obj is None:
        obj = bpy.data.objects.new(name, data)
    elif obj.data is not data:
        old = obj.data
        obj.data = data
        if isinstance(old, bpy.types.Mesh) and old.users == 0:
            bpy.data.meshes.remove(old)
    for collection in list(obj.users_collection):
        if collection is not scene.collection:
            collection.objects.unlink(obj)
    if obj.name not in scene.collection.objects:
        scene.collection.objects.link(obj)
    obj.boz.role = "reference"
    obj["boz_preview"] = "weapon"
    obj.hide_select = True
    return obj


def _rig(context, item):
    """The selected weapon's posable arms and gun (cached), or raises KeyError/ValueError."""
    weapon = weapon_def(context, item.name)
    level = weapon.level or base_level(context)
    key = (level, weapon.source)
    if _state.get("rig_key") != key:
        pack = _pack()
        if pack is None:
            raise KeyError("no asset library")
        _state["rig"] = viewmodel.Rig(pack.read, level, weapon.source)
        _state["rig_key"] = key
        _state["poses"] = {}
        _state["anim_items"] = None
    return _state["rig"]


def _posed(rig, state: int | None, frame: int) -> dict:
    """{part label: flat Blender vertex coordinates} of the rig in *state* at *frame* (cached)."""
    key = (state, frame)
    poses = _state.setdefault("poses", {})
    if key not in poses:
        out = {}
        for part in rig.pose(state, frame):
            coords = []
            for position in part.positions:
                coords += blender_scene.to_blender(position)
            out[part.label] = (part, coords)
        poses[key] = out
    return poses[key]


def show_preview(context) -> str:
    """Build the selected weapon's first-person view in the Weapons tab's scene (idle)."""
    scene = link.map_scene()
    item = selected(scene)
    if item is None or _pack() is None:
        return "No weapon selected"
    from . import game
    try:
        rig = _rig(context, item)
        posed = _posed(rig, None, 0)
    except (KeyError, ValueError, OSError) as exc:
        _state["rig_key"] = None
        _state["preview"] = f"No first-person view: {exc}"
        return _state["preview"]
    _stop_playing()
    view = view_scene()
    wanted = set()
    for label, (part, coords) in posed.items():
        base = game.model_mesh(part.path, part.model)
        if base is None or len(base.vertices) != len(part.positions):
            continue
        mesh = base.copy()
        mesh.name = f"BOZ view {label}"
        mesh.vertices.foreach_set("co", coords)
        mesh.update()
        obj = _view_object(view, f"BOZ view {label}", mesh)
        obj.matrix_world.identity()
        wanted.add(obj.name)
    camera_data = bpy.data.cameras.get(VIEW_CAMERA) or bpy.data.cameras.new(VIEW_CAMERA)
    camera_data.sensor_fit = "VERTICAL"   # the game's field of view is vertical
    camera_data.angle = math.radians(viewmodel.DEFAULT_FOV)
    camera_data.clip_start = 5.0
    camera_data.clip_end = 100000.0
    camera = _view_object(view, VIEW_CAMERA, camera_data)
    camera.location = (0.0, 0.0, 0.0)
    # The game's eye looks down +Z with Y up: Blender's -Y with Z up.
    camera.rotation_euler = (math.pi / 2, 0.0, math.pi)
    view.camera = camera
    wanted.add(camera.name)
    for obj in list(view.objects):
        if obj.name not in wanted:
            bpy.data.objects.remove(obj)
    wm = context.window_manager
    _state["anim_guard"] = True
    try:
        wm.boz_anim_state = str(rig.idle())
        wm.boz_anim_frame = 0
    except TypeError:
        pass
    finally:
        _state["anim_guard"] = False
    _apply_visibility(context)
    _state["frame_gun"] = True
    for window in wm.windows:
        if window.workspace.name == WORKSPACE:
            window.workspace[VIEW_KEY] = False   # set the viewport up again
    _state["preview"] = f"{item.label}: first-person view"
    return _state["preview"]


def _apply_visibility(context) -> None:
    """Arms shown or hidden; the camera hidden in the free view."""
    wm = context.window_manager
    arms = bpy.data.objects.get("BOZ view arms")
    if arms is not None:
        arms.hide_viewport = not wm.boz_view_arms
    camera = bpy.data.objects.get(VIEW_CAMERA)
    if camera is not None:
        camera.hide_viewport = wm.boz_view_free


def show_pose(context, state: int | None, frame: int) -> None:
    """Pose the view's arms and gun in *state* at *frame*."""
    item = selected(link.map_scene())
    if item is None:
        return
    try:
        posed = _posed(_rig(context, item), state, frame)
    except (KeyError, ValueError, OSError):
        return
    for label, (_part, coords) in posed.items():
        obj = bpy.data.objects.get(f"BOZ view {label}")
        if obj is None or obj.type != "MESH" or len(obj.data.vertices) * 3 != len(coords):
            continue
        obj.data.vertices.foreach_set("co", coords)
        obj.data.update()


def _frame_gun(window) -> None:
    """Free view: look at the gun from its side, orbiting around it."""
    from mathutils import Euler, Vector
    gun = bpy.data.objects.get("BOZ view gun") or bpy.data.objects.get("BOZ view arms")
    if gun is None or gun.type != "MESH" or not gun.data.vertices:
        return
    points = [v.co for v in gun.data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = area.spaces.active.region_3d
        region.view_perspective = "PERSP"
        region.view_location = (low + high) / 2
        region.view_distance = max((high - low).length * 1.4, 1.0)
        region.view_rotation = Euler((math.radians(75), 0.0, math.radians(125))).to_quaternion()
        area.tag_redraw()


def setup_view(window) -> bool:
    """Show the Weapons tab's scene in its window, pinned: through the camera (first person) or
    free to move around (free view)."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    if view is None or view.camera is None:
        return False
    if window.scene != view:
        window.scene = view
    workspace = window.workspace
    if not workspace.use_pin_scene:
        workspace.use_pin_scene = True     # pins the window's scene: the view
    free = bpy.context.window_manager.boz_view_free
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.use_local_collections = False
        space.use_local_camera = False
        space.overlay.show_floor = False
        space.overlay.show_axis_x = space.overlay.show_axis_y = False
        space.clip_start, space.clip_end = 1.0, 100000.0
        if not free:
            space.region_3d.view_perspective = "CAMERA"
        area.tag_redraw()
    if free and _state.pop("frame_gun", False):
        _frame_gun(window)
    workspace[VIEW_KEY] = True
    return True


def _view_changed(self, context):
    _apply_visibility(context)
    _state["frame_gun"] = True
    for window in context.window_manager.windows:
        if window.workspace.name == WORKSPACE:
            setup_view(window)


def _arms_changed(self, context):
    _apply_visibility(context)


# --- Animations (view only) -----------------------------------------------------------------

def _anim_items(self, context):
    item = selected(link.map_scene())
    rig = _state.get("rig") if item is not None and _state.get("rig_key") else None
    if rig is None:
        return [("0", "No animations", "")]
    if _state.get("anim_items") is None:
        items = []
        for state in rig.states():
            seconds = state.frames / viewmodel.FPS
            items.append((str(state.name), state.label,
                          f"{state.frames} frames, {seconds:.1f} s"
                          + (", loops" if state.looping else "")
                          + f" (state 0x{state.name:08x})"))
        _state["anim_items"] = items or [("0", "No animations", "")]
        _state["anim_states"] = {s.name: s for s in rig.states()}
    return _state["anim_items"]


def current_anim():
    """(state, its ViewState or None, frame) chosen in the Animations panel."""
    wm = bpy.context.window_manager
    try:
        name = int(wm.boz_anim_state)
    except (TypeError, ValueError):
        return None, None, 0
    return name, _state.get("anim_states", {}).get(name), wm.boz_anim_frame


def _anim_state_changed(self, context):
    if _state.get("anim_guard"):
        return
    _state["anim_guard"] = True
    try:
        context.window_manager.boz_anim_frame = 0
    finally:
        _state["anim_guard"] = False
    name, _view_state, _frame = current_anim()
    show_pose(context, name, 0)


def _anim_frame_changed(self, context):
    if _state.get("anim_guard"):
        return
    name, view_state, frame = current_anim()
    if view_state is not None and frame >= view_state.frames:
        _state["anim_guard"] = True
        try:
            context.window_manager.boz_anim_frame = frame = view_state.frames - 1
        finally:
            _state["anim_guard"] = False
    show_pose(context, name, frame)


def _play_tick():
    wm = bpy.context.window_manager
    if not wm.boz_anim_playing or bpy.data.objects.get("BOZ view arms") is None:
        wm.boz_anim_playing = False
        return None
    _name, view_state, frame = current_anim()
    if view_state is None:
        wm.boz_anim_playing = False
        return None
    frame += 1
    if frame >= view_state.frames:
        if not wm.boz_anim_loop:
            wm.boz_anim_playing = False
            return None
        frame = 0
    wm.boz_anim_frame = frame
    return 1.0 / viewmodel.FPS


def _stop_playing() -> None:
    wm = bpy.context.window_manager
    if wm.boz_anim_playing:
        wm.boz_anim_playing = False
    if bpy.app.timers.is_registered(_play_tick):
        bpy.app.timers.unregister(_play_tick)


class BOZ_OT_weapon_anim_play(Operator):
    bl_idname = "boz.weapon_anim_play"
    bl_label = "Play"
    bl_description = "Play the chosen animation in the view (again to pause)"

    def execute(self, context):
        wm = context.window_manager
        if wm.boz_anim_playing:
            _stop_playing()
            return {"FINISHED"}
        _name, view_state, frame = current_anim()
        if view_state is None:
            return {"CANCELLED"}
        if frame >= view_state.frames - 1:
            wm.boz_anim_frame = 0          # from the start again
        wm.boz_anim_playing = True
        if not bpy.app.timers.is_registered(_play_tick):
            bpy.app.timers.register(_play_tick, first_interval=1.0 / viewmodel.FPS)
        return {"FINISHED"}


class BOZ_PT_weapon_animations(_WeaponsPanel, Panel):
    bl_idname = "BOZ_PT_weapon_animations"
    bl_label = "Animations"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and selected(link.map_scene()) is not None

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        if not _state.get("rig_key"):
            layout.label(text="Select a weapon to see its animations", icon="INFO")
            return
        layout.prop(wm, "boz_anim_state", text="Animation")
        _name, view_state, _frame = current_anim()
        row = layout.row(align=True)
        row.operator(BOZ_OT_weapon_anim_play.bl_idname, text="Pause" if wm.boz_anim_playing else "Play",
                     icon="PAUSE" if wm.boz_anim_playing else "PLAY")
        row.prop(wm, "boz_anim_loop", text="", icon="FILE_REFRESH", toggle=True)
        row.prop(wm, "boz_anim_frame", text="Frame")
        if view_state is not None:
            layout.label(text=f"{view_state.frames} frames, {view_state.frames / viewmodel.FPS:.1f} s"
                         + (", loops in the game" if view_state.looping else ""))
        layout.label(text="Viewing only for now: replacing animations comes later", icon="INFO")


def draw_view_header(self, context):
    """The Weapons tab's viewport header: first person or free view, arms, play."""
    workspace = context.workspace
    if workspace is None or workspace.name != WORKSPACE:
        return
    wm = context.window_manager
    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    row.prop(wm, "boz_view_free", text="Free view" if wm.boz_view_free else "First person",
             icon="ORIENTATION_GIMBAL" if wm.boz_view_free else "VIEW_CAMERA", toggle=True)
    row.prop(wm, "boz_view_arms", text="Arms", icon="HIDE_OFF" if wm.boz_view_arms else "HIDE_ON",
             toggle=True)
    if _state.get("rig_key"):
        layout.operator(BOZ_OT_weapon_anim_play.bl_idname, text="",
                        icon="PAUSE" if wm.boz_anim_playing else "PLAY")


VIEW_CLASSES = (BOZ_OT_weapon_anim_play, BOZ_PT_weapon_animations)


def leave_view(window) -> None:
    """Any other tab: the map, never the weapon view."""
    if window.scene is not None and window.scene.name == link.VIEW_SCENE:
        window.scene = link.map_scene()


def refresh_view(window) -> None:
    """Called by the tabs' timer while the Weapons tab is on screen."""
    if not window.workspace.get(VIEW_KEY) or window.scene.name != link.VIEW_SCENE:
        if bpy.data.objects.get(VIEW_CAMERA) is None and selected(link.map_scene()) is not None:
            show_preview(bpy.context)
        setup_view(window)


def on_load() -> None:
    """After a map opens: fill the tab (from a timer, where scene data may change)."""
    def later():
        try:
            if link.project_root() is not None and level_weapons(base_level(bpy.context)):
                refresh(bpy.context)
        except (AttributeError, RuntimeError):
            pass
        return None
    _state["levels"].clear()
    bpy.app.timers.register(later, first_interval=0.5)


def register():
    for cls in CLASSES + VIEW_CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.boz_view_free = BoolProperty(
        name="Free view", update=_view_changed,
        description="Move around the weapon freely instead of looking through the game's eye")
    wm.boz_view_arms = BoolProperty(name="Arms", default=True, update=_arms_changed,
                                    description="Show the player's arms")
    wm.boz_anim_state = EnumProperty(name="Animation", items=_anim_items,
                                     update=_anim_state_changed,
                                     description="The animation shown in the view")
    wm.boz_anim_frame = IntProperty(name="Frame", min=0, update=_anim_frame_changed,
                                    description="The animation's keyframe shown (24 a second)")
    wm.boz_anim_playing = BoolProperty()
    wm.boz_anim_loop = BoolProperty(name="Loop", default=True,
                                    description="Play the animation over and over")
    bpy.types.VIEW3D_HT_header.append(draw_view_header)
    bpy.types.Scene.boz_weapons = CollectionProperty(type=BOZ_WeaponItem)
    bpy.types.Scene.boz_weapon_index = IntProperty(update=_selected_changed)
    bpy.types.Scene.boz_weapon_fields = CollectionProperty(type=BOZ_WeaponField)
    bpy.types.Scene.boz_start_reserve = IntProperty(
        name="Starting spare rounds", min=0, default=wp.DEFAULT_START_RESERVE,
        description="Spare rounds of the starting weapon (the game's default: 40)",
        update=_start_reserve_changed)
    bpy.types.WindowManager.boz_pool_items = CollectionProperty(type=BOZ_PoolItem)


def unregister():
    if bpy.app.timers.is_registered(_play_tick):
        bpy.app.timers.unregister(_play_tick)
    bpy.types.VIEW3D_HT_header.remove(draw_view_header)
    for name in ("boz_view_free", "boz_view_arms", "boz_anim_state", "boz_anim_frame",
                 "boz_anim_playing", "boz_anim_loop"):
        delattr(bpy.types.WindowManager, name)
    del bpy.types.WindowManager.boz_pool_items
    del bpy.types.Scene.boz_start_reserve
    del bpy.types.Scene.boz_weapon_fields
    del bpy.types.Scene.boz_weapon_index
    del bpy.types.Scene.boz_weapons
    for cls in reversed(CLASSES + VIEW_CLASSES):
        bpy.utils.unregister_class(cls)
