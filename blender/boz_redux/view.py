"""What the BOZ overlays show: visibility switches, link lines and the selected-object panel."""

from __future__ import annotations

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:  # background mode without a GPU backend
    gpu = None

MARKER_TYPES = [
    ("perk", "Perks", ""), ("pack_a_punch", "Pack-a-Punch", ""), ("mystery_box", "Mystery box", ""),
    ("door", "Doors", ""), ("power", "Power", ""), ("trap", "Traps", ""),
    ("wall_buy", "Wall buys", ""), ("barricade", "Barricades", ""), ("teleporter", "Teleporters", ""),
    ("easter_egg", "Easter eggs", ""), ("ride", "Rides", ""), ("spawn", "Spawns", ""),
    ("effect", "Effects", ""), ("interact", "Interact", ""), ("trigger", "Triggers", ""),
    ("sound", "Sounds", ""), ("jump", "Jump points", ""), ("locator", "Locators", ""),
    ("camera", "Cameras", ""), ("ai", "AI", ""), ("collision", "Collision entities", ""),
    ("entity", "Other", ""),
]
LINK_COLOURS = {
    "power": (1.0, 0.95, 0.1, 1.0), "trap": (1.0, 0.15, 0.1, 1.0),
    "sibling": (1.0, 0.55, 0.1, 1.0), "unlocks": (0.1, 0.9, 1.0, 1.0),
    "member": (0.7, 0.45, 1.0, 1.0),
}
# Scene switch -> object kinds it shows.
SWITCHES = {
    "boz_show_markers": {"entity"},
    "boz_show_badges": {"badge"},
    "boz_show_areas": {"area"},
    "boz_show_shapes": {"shape"},
    "boz_show_collision": {"collision", "collision_piece"},
    "boz_show_portals": {"portal"},
    "boz_show_navigation": {"navigation_connection"},
}


def apply_visibility(context=None):
    context = context or bpy.context
    scene = context.scene
    types = set(scene.boz_marker_types)
    kinds = {kind for switch, members in SWITCHES.items() if getattr(scene, switch)
             for kind in members}
    for obj in scene.objects:
        kind = obj.get("boz_kind")
        if kind not in {k for members in SWITCHES.values() for k in members}:
            continue
        visible = kind in kinds
        if kind in {"entity", "badge"}:
            visible = visible and obj.get("boz_category", "entity") in types
        if obj.visible_get() != visible:
            try:
                obj.hide_set(not visible)
            except RuntimeError:  # not in the active view layer
                pass


def _update(self, context):
    apply_visibility(context)
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def _redraw(self, context):
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def links_of(obj) -> list[dict]:
    try:
        return json.loads(obj.get("boz_links", "[]"))
    except ValueError:
        return []


def link_index(scene) -> dict[str, bpy.types.Object]:
    index = {}
    for obj in scene.objects:
        identity = obj.get("boz_link_id")
        if identity and obj.get("boz_kind") in {"entity", "placed_model", "area"}:
            index.setdefault(identity, obj)
    return index


def _hex(value) -> str:
    return f"0x{int(value):08x}"


_handle = None


def _draw_links():
    try:
        _draw_link_lines()
    except Exception as exc:  # a draw callback must never break the viewport
        print(f"BOZ Redux: link drawing failed: {exc}")
        bpy.context.scene.boz_show_links = False


def _draw_link_lines():
    context = bpy.context
    scene = context.scene
    if gpu is None or not getattr(scene, "boz_show_links", False):
        return
    index = link_index(scene)
    selected = {obj for obj in context.selected_objects} if scene.boz_links_selected_only else None
    lines: dict[str, list] = {}
    for source in scene.objects:
        links = links_of(source) if "boz_links" in source else []
        for link in links:
            for target_id in link["targets"]:
                target = index.get(_hex(target_id))
                if target is None:
                    continue
                if selected is not None and source not in selected and target not in selected:
                    continue
                lines.setdefault(link["kind"], []).extend(
                    [source.matrix_world.translation[:], target.matrix_world.translation[:]])
    if not lines:
        return
    region = context.region
    try:
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        wide = True
    except (ValueError, SystemError):
        shader, wide = gpu.shader.from_builtin("UNIFORM_COLOR"), False
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("ALPHA")
    for kind, coordinates in lines.items():
        batch = batch_for_shader(shader, "LINES", {"pos": coordinates})
        shader.bind()
        if wide and region is not None:
            shader.uniform_float("viewportSize", (region.width, region.height))
            shader.uniform_float("lineWidth", 2.5)
        shader.uniform_float("color", LINK_COLOURS.get(kind, (1.0, 1.0, 1.0, 1.0)))
        batch.draw(shader)
    gpu.state.blend_set("NONE")


class BOZ_OT_link_select(Operator):
    bl_idname = "boz.link_select"
    bl_label = "Select"
    bl_description = "Select the linked object"
    bl_options = {"REGISTER", "UNDO"}

    target: StringProperty()
    name: StringProperty()

    def execute(self, context):
        target = (context.scene.objects.get(self.name) if self.name
                  else link_index(context.scene).get(self.target))
        if target is None:
            self.report({"WARNING"}, "The linked object is not in this scene")
            return {"CANCELLED"}
        if not target.visible_get():
            target.hide_set(False)
        for obj in context.selected_objects:
            obj.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        return {"FINISHED"}


def _edit_link(obj, component, field, change):
    links = links_of(obj)
    link = next((link for link in links if link["component"] == component
                 and link["field"] == field), None)
    if link is None:
        raise ValueError(f"{obj.name} has no {field} link")
    change(link)
    obj["boz_links"] = json.dumps(links)


class BOZ_OT_link_remove(Operator):
    bl_idname = "boz.link_remove"
    bl_label = "Remove link"
    bl_description = "Remove this link (saved with Save to mod)"
    bl_options = {"REGISTER", "UNDO"}

    component: bpy.props.IntProperty()
    field: StringProperty()
    target: StringProperty()

    def execute(self, context):
        obj = context.active_object
        value = int(self.target, 16)
        _edit_link(obj, self.component, self.field,
                   lambda link: link.update(targets=[t for t in link["targets"] if t != value]))
        return {"FINISHED"}


class BOZ_OT_link_add_selected(Operator):
    bl_idname = "boz.link_add_selected"
    bl_label = "Link selected"
    bl_description = ("Link the other selected objects here (a single link such as power is "
                      "replaced)")
    bl_options = {"REGISTER", "UNDO"}

    component: bpy.props.IntProperty()
    field: StringProperty()

    def execute(self, context):
        obj = context.active_object
        targets = [other for other in context.selected_objects if other is not obj]
        if not targets:
            self.report({"ERROR"}, "Select the objects to link, then the one to link from last")
            return {"CANCELLED"}
        unnamed = [other.name for other in targets if not other.get("boz_link_id")]
        if unnamed:
            self.report({"ERROR"}, f"{unnamed[0]} has no game name, so it cannot be linked to")
            return {"CANCELLED"}
        values = [int(other["boz_link_id"], 16) for other in targets]

        def change(link):
            if link["list"]:
                link["targets"] = link["targets"] + [v for v in values if v not in link["targets"]]
            else:
                link["targets"] = values[-1:]
        try:
            _edit_link(obj, self.component, self.field, change)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class BOZ_PT_selected(Panel):
    bl_label = "Selected"
    bl_idname = "BOZ_PT_selected"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BOZ Redux"
    bl_parent_id = "BOZ_PT_map_tools"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and "boz_kind" in obj

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if obj.get("boz_kind") == "badge" and obj.parent is not None:
            obj = obj.parent
        layout.label(text=obj.name.split(":", 1)[-1])
        description = obj.get("boz_description")
        if description:
            for line in _wrap(description, 38):
                layout.label(text=line)
        index = link_index(context.scene)
        for link in links_of(obj):
            box = layout.box()
            row = box.row()
            row.label(text=f"{link['kind']}: {link['field']}")
            add = row.operator(BOZ_OT_link_add_selected.bl_idname, text="", icon="ADD")
            add.component, add.field = link["component"], link["field"]
            if not link["targets"]:
                box.label(text="(none)")
            for target in link["targets"]:
                key = _hex(target)
                other = index.get(key)
                row = box.row(align=True)
                select = row.operator(BOZ_OT_link_select.bl_idname,
                                      text=other.name.split(":", 1)[-1] if other else key,
                                      icon="RESTRICT_SELECT_OFF" if other else "QUESTION")
                select.target = key
                remove = row.operator(BOZ_OT_link_remove.bl_idname, text="", icon="X")
                remove.component, remove.field, remove.target = link["component"], link["field"], key
        incoming = [other for other in context.scene.objects if "boz_links" in other
                    and any(_hex(t) == obj.get("boz_link_id")
                            for link in links_of(other) for t in link["targets"])]
        if incoming:
            box = layout.box()
            box.label(text="Linked from")
            for other in incoming[:12]:
                select = box.operator(BOZ_OT_link_select.bl_idname,
                                      text=other.name.split(":", 1)[-1], icon="LINKED")
                select.name = other.name


def _wrap(text, width):
    words, line, lines = text.split(), "", []
    for word in words:
        if line and len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


def draw_switches(layout, scene):
    box = layout.box()
    box.label(text="Show")
    grid = box.grid_flow(columns=2, even_columns=True, align=True)
    for switch, text in (("boz_show_markers", "Markers"), ("boz_show_badges", "Badges"),
                         ("boz_show_areas", "Areas"), ("boz_show_links", "Links"),
                         ("boz_show_shapes", "Shapes"), ("boz_show_collision", "Collision"),
                         ("boz_show_portals", "Portals"), ("boz_show_navigation", "Nav")):
        grid.prop(scene, switch, text=text, toggle=True)
    if scene.boz_show_links:
        box.prop(scene, "boz_links_selected_only")
    if scene.boz_show_markers or scene.boz_show_badges:
        box.prop(scene, "boz_marker_types_expanded", text="Marker types",
                 icon="TRIA_DOWN" if scene.boz_marker_types_expanded else "TRIA_RIGHT",
                 emboss=False)
        if scene.boz_marker_types_expanded:
            box.prop(scene, "boz_marker_types")


CLASSES = (BOZ_OT_link_select, BOZ_OT_link_remove, BOZ_OT_link_add_selected, BOZ_PT_selected)

_PROPERTIES = {
    **{switch: BoolProperty(default=False, update=_update) for switch in SWITCHES},
    "boz_show_links": BoolProperty(default=False, update=_redraw),
    "boz_links_selected_only": BoolProperty(
        name="Only selected", default=True, update=_redraw,
        description="Draw only the links of the selected objects"),
    "boz_marker_types": EnumProperty(items=MARKER_TYPES, options={"ENUM_FLAG"},
                                     default={item[0] for item in MARKER_TYPES}, update=_update),
    "boz_marker_types_expanded": BoolProperty(default=False),
}


def register():
    global _handle
    for name, prop in _PROPERTIES.items():
        setattr(bpy.types.Scene, name, prop)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if gpu is not None and not bpy.app.background:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw_links, (), "WINDOW", "POST_VIEW")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in _PROPERTIES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
