"""The editor's shell: Blender's top bar, menus and Properties editor reshaped for the game.

Blender's UI is Python (bl_ui), so the shell swaps the draw functions of the stock classes and
restores them on unregister. What Python cannot change is listed in
docs/internal/blender-walls.md (the case for a fork).
"""
from __future__ import annotations

import bpy
from bpy.types import Menu, Operator

from . import tabs

_saved: list[tuple[object, str, object]] = []   # (class, attribute, original) to restore

# Properties panels kept per context; every other stock panel there is hidden.
KEEP_PANELS = {
    "object": {"OBJECT_PT_context_object", "OBJECT_PT_transform"},
    "material": {"EEVEE_MATERIAL_PT_context_material"},
    "scene": set(),
}
MODIFIERS = [("MIRROR", "Mirror", "MOD_MIRROR"), ("ARRAY", "Array", "MOD_ARRAY"),
             ("SOLIDIFY", "Solidify", "MOD_SOLIDIFY"), ("BEVEL", "Bevel", "MOD_BEVEL"),
             ("TRIANGULATE", "Triangulate", "MOD_TRIANGULATE"), ("WELD", "Weld", "AUTOMERGE_OFF")]
DISABLED_KEYS = {"render.render", "render.view_show", "render.play_rendered_anim"}


def _patch(cls, attribute: str, value) -> None:
    _saved.append((cls, attribute, cls.__dict__.get(attribute, None)))
    setattr(cls, attribute, value)


class BOZ_OT_switch_tab(Operator):
    bl_idname = "boz.switch_tab"
    bl_label = "Switch tab"
    bl_options = {"INTERNAL"}

    tab: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        return f"The {properties.tab} tab"

    def execute(self, context):
        workspace = bpy.data.workspaces.get(self.tab)
        if workspace is None:
            self.report({"ERROR"}, f"This file has no {self.tab} tab")
            return {"CANCELLED"}
        context.window.workspace = workspace
        return {"FINISHED"}


class BOZ_MT_project(Menu):
    bl_label = "Project"

    def draw(self, context):
        layout = self.layout
        layout.operator("wm.save_mainfile", text="Save", icon="FILE_TICK")
        layout.operator("boz.suite_build_and_run", icon="PLAY")
        layout.operator("boz.suite_build_settings", icon="PREFERENCES")
        row = layout.row()
        row.enabled = False
        row.operator("boz.coming", text="Export…", icon="EXPORT").feature = "Export"
        layout.separator()
        layout.operator("boz.check_world", text="Check for problems", icon="CHECKMARK")
        layout.operator("boz.open_project_folder", icon="FILE_FOLDER")
        layout.separator()
        layout.operator("boz.back_to_launcher", icon="QUIT")


class BOZ_MT_edit(Menu):
    bl_label = "Edit"

    def draw(self, context):
        layout = self.layout
        layout.operator("ed.undo", icon="LOOP_BACK")
        layout.operator("ed.redo", icon="LOOP_FORWARDS")
        layout.menu("TOPBAR_MT_undo_history")
        layout.separator()
        layout.operator("screen.userpref_show", text="Preferences…", icon="PREFERENCES")


class BOZ_MT_help(Menu):
    bl_label = "Help"

    def draw(self, context):
        layout = self.layout
        from pathlib import Path
        import os
        docs = Path(os.environ.get("BOZ_SDK_ROOT", "")) / "docs"
        for label, name in (("Making mods", "making-mods.md"), ("SDK projects", "sdk-projects.md"),
                            ("Standard library", "standard-library.md")):
            layout.operator("wm.path_open", text=label, icon="HELP").filepath = str(docs / name)


def _draw_left(self, context):
    layout = self.layout
    row = layout.row(align=True)
    row.menu("BOZ_MT_project")
    row.menu("BOZ_MT_edit")
    row.menu("BOZ_MT_help")
    layout.separator(type="LINE")
    active = context.window.workspace.name
    row = layout.row(align=True)
    for name in tabs.TAB_NAMES:
        if name in bpy.data.workspaces:
            row.operator(BOZ_OT_switch_tab.bl_idname, text=name, depress=name == active).tab = name


def _draw_right(self, context):
    layout = self.layout
    screen = context.screen
    if not screen.show_statusbar:
        layout.template_reports_banner()
        layout.template_running_jobs()
    row = layout.row(align=True)
    row.scale_x = 1.2
    row.operator("boz.suite_build_and_run", text="Build & Run", icon="PLAY")
    row.operator("boz.suite_build_settings", text="", icon="PREFERENCES")


_rehidden: list[list] = []   # panel families re-registered with poll -> False, parent first


def _never(cls, context):
    return False


def _hide_stock_panels() -> None:
    """Hide the stock panels of the kept Properties tabs that do not reach the game. Blender
    notes at registration whether a class has poll, so each hidden panel is re-registered (with
    its sub-panels, parent first)."""
    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    panels = [cls for cls in set(walk(bpy.types.Panel))
              if getattr(cls, "is_registered", False) and not cls.__name__.startswith("BOZ_")]
    children: dict[str, list] = {}
    for cls in panels:
        parent = getattr(cls, "bl_parent_id", "")
        if parent:
            children.setdefault(parent, []).append(cls)

    def family(cls):
        out = [cls]
        for child in children.get(getattr(cls, "bl_idname", cls.__name__), []):
            out += family(child)
        return out

    for cls in panels:
        context = getattr(cls, "bl_context", "")
        name = getattr(cls, "bl_idname", cls.__name__)
        if (getattr(cls, "bl_space_type", "") != "PROPERTIES" or context not in KEEP_PANELS
                or name in KEEP_PANELS[context] or getattr(cls, "bl_parent_id", "")):
            continue
        members = family(cls)
        for member in reversed(members):
            bpy.utils.unregister_class(member)
        _saved.append((cls, "poll", cls.__dict__.get("poll", None)))
        cls.poll = classmethod(_never)
        for member in members:
            bpy.utils.register_class(member)
        _rehidden.append(members)


def _show_stock_panels() -> None:
    while _rehidden:
        members = _rehidden.pop()
        for member in reversed(members):
            if getattr(member, "is_registered", False):
                bpy.utils.unregister_class(member)
        cls = members[0]
        index = next(i for i, entry in enumerate(_saved) if entry[0] is cls and entry[1] == "poll")
        _, _, original = _saved.pop(index)
        if original is None:
            del cls.poll
        else:
            cls.poll = original
        for member in members:
            bpy.utils.register_class(member)


def _text_header(original):
    def draw(self, context):
        space = context.space_data
        if space.text is not None and space.text.name == tabs.LOG_TEXT:
            layout = self.layout
            layout.label(text="Log", icon="CONSOLE")
            layout.separator_spacer()
            problems = len(context.scene.get("boz_problems", []))
            layout.label(text=f"{problems} problems" if problems else "No problems",
                         icon="ERROR" if problems else "CHECKMARK")
            layout.operator("boz.clear_log", text="Clear", icon="TRASH")
            return
        original(self, context)
    return draw


def _modifier_menu(self, context):
    layout = self.layout
    for kind, label, icon in MODIFIERS:
        layout.operator("object.modifier_add", text=label, icon=icon).type = kind
    layout.separator()
    layout.label(text="Modifiers are applied when the map is built")


def disable_render_keys() -> None:
    keyconfig = bpy.context.window_manager.keyconfigs.user
    if keyconfig is None:
        return
    for keymap in keyconfig.keymaps:
        for item in keymap.keymap_items:
            if item.idname in DISABLED_KEYS:
                item.active = False


CLASSES = [BOZ_OT_switch_tab, BOZ_MT_project, BOZ_MT_edit, BOZ_MT_help]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _patch(bpy.types.TOPBAR_HT_upper_bar, "draw_left", _draw_left)
    _patch(bpy.types.TOPBAR_HT_upper_bar, "draw_right", _draw_right)
    _patch(bpy.types.TEXT_HT_header, "draw", _text_header(bpy.types.TEXT_HT_header.draw))
    _patch(bpy.types.OBJECT_MT_modifier_add, "draw", _modifier_menu)
    _hide_stock_panels()
    if not bpy.app.background:
        bpy.app.timers.register(lambda: disable_render_keys() and None, first_interval=0.5)


def unregister():
    _show_stock_panels()
    while _saved:
        cls, attribute, original = _saved.pop()
        if original is None:
            try:
                delattr(cls, attribute)
            except AttributeError:
                pass
        else:
            setattr(cls, attribute, original)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
