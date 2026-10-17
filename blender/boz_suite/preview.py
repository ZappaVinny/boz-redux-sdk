"""What the game will get for the map being edited: its walkable area (navmesh) and collision.

The map is compiled as Build & Run would (without installing anything), and the compiled level's
navmesh and collision mesh are shown as locked overlay objects through the shipped-map add-on's
builders (blue walkable floor, orange door-gated floor, red wire collision). The add-on's
visibility switches (scene.boz_show_navmesh, boz_show_collision, boz_show_markers,
boz_show_shapes) turn them and the base level's markers on and off.
"""
from __future__ import annotations

import struct

import bpy
from bpy.types import Operator, Panel
from bpy.props import EnumProperty

from ._bozkit import blender_scene, collision, group, levels, library, world

from . import convert, meshes, scene_view
from . import link

COLLECTIONS = {"navmesh": "Preview: walkable area", "collision": "Preview: collision"}
SWITCHES = {"navmesh": "boz_show_navmesh", "collision": "boz_show_collision"}
KINDS = {"navmesh": ("navmesh",), "collision": ("collision",)}


def _scene_meshes(statics: group.Group, name: str) -> list:
    """SceneMesh items for the compiled level's navmesh and collision entities."""
    path = f"{name}_statics.group.bin"
    out = []
    for resource_type in statics.types():
        for index, item in enumerate(resource_type.resources):
            if resource_type.class_hash == levels.NAVMESH:
                out.append(blender_scene.navmesh_meshes(path, item, index, name))
            elif resource_type.class_hash == levels.ENTITY_SPEC:
                try:
                    spec, component = blender_scene._collision_spec(item)
                except (ValueError, KeyError, AttributeError, struct.error):
                    continue
                position, rotation, scale = blender_scene._local_transform(spec)
                mesh = collision.decode(component.extra)
                out.append(blender_scene.SceneMesh(
                    "collision", levels.ENTITY_SPEC, item.in_group_hash, index, path,
                    f"{name}:collision {index}", f"{name} Collision",
                    [blender_scene.to_blender(v) for v in mesh.vertices],
                    blender_scene._triangles(mesh.indices),
                    face_materials=list(mesh.materials), material_names=mesh.material_names,
                    location=blender_scene.to_blender(position),
                    rotation=blender_scene.rotation_to_blender(rotation),
                    scale=blender_scene.scale_to_blender(scale),
                    key=f"preview|collision|{index}"))
    return out


def clear(kind: str) -> None:
    collection = bpy.data.collections.get(COLLECTIONS[kind])
    if collection is None:
        return
    for obj in list(collection.objects):
        data = obj.data
        bpy.data.objects.remove(obj)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)


def build(context) -> str:
    """Compile the scene's world and show its navmesh and collision. Returns a summary."""
    from . import link

    project = link.current_project()
    if project is None or project.kind != "map":
        raise ValueError("open this map from the SDK launcher to preview it")
    import os
    from ._bozkit import sdkhome
    client = os.environ.get("BOZ_CLIENT") or sdkhome.Settings.load().client
    pack = library.open_game(client or None)
    if pack is None:
        raise ValueError("the preview needs the game data: build the asset library in the launcher")
    problems = []
    source = convert.scene_to_world(link.map_scene(), problems)
    from ._bozkit import assets, weapons
    try:
        # The project's own weapons too, as Build & Run compiles it (wall buys may sell them).
        defs = weapons.load_defs(project.root / "source")
        weapons.attach_models(defs, project.root / "source")
        assets.attach(source, project.root / "source")
        files = world.compile_world(pack, project.map_name, source, None, weapons=defs)
    except (world.WorldError, levels.LevelError, weapons.WeaponError) as exc:
        raise ValueError(str(exc)) from None
    statics = files.groups[f"{project.map_name}_statics.group.bin"]
    items = _scene_meshes(statics, project.map_name)
    shown = {}
    for kind, name in COLLECTIONS.items():
        clear(kind)
        collection = bpy.data.collections.get(name) or bpy.data.collections.new(name)
        if collection.name not in link.map_scene().collection.children:
            link.map_scene().collection.children.link(collection)
        made_meshes, made_objects = {}, {}
        for item in items:
            if item.kind not in KINDS[kind]:
                continue
            obj = meshes.mesh_object(context, item, made_meshes, made_objects)
            for users in list(obj.users_collection):
                users.objects.unlink(obj)
            collection.objects.link(obj)
            obj.boz.role = "reference"
            obj.hide_select = True
            shown[kind] = shown.get(kind, 0) + len(obj.data.polygons)
    for name in list(bpy.data.collections.keys()):
        found = bpy.data.collections[name]
        if found.name.startswith(project.map_name) and not found.objects and not found.children:
            bpy.data.collections.remove(found)
    scene_view.apply_visibility(context)
    return (f"walkable area {shown.get('navmesh', 0)} polygons, collision "
            f"{shown.get('collision', 0)} triangles")


def has_preview(kind: str) -> bool:
    collection = bpy.data.collections.get(COLLECTIONS[kind])
    return bool(collection and collection.objects)


class BOZ_OT_preview(Operator):
    bl_idname = "boz.suite_preview"
    bl_label = "Show"
    bl_description = ("Show what the game gets for this map: the walkable area zombies and "
                      "players move on (blue, orange where a door blocks it) or the collision. "
                      "Compiles the map the first time")
    bl_options = {"REGISTER"}

    kind: EnumProperty(items=[("navmesh", "Walkable area", ""), ("collision", "Collision", "")])

    def execute(self, context):
        switch = SWITCHES[self.kind]
        if getattr(link.map_scene(), switch) and has_preview(self.kind):
            setattr(link.map_scene(), switch, False)
            return {"FINISHED"}
        if not has_preview(self.kind):
            if not _rebuild(self, context):
                return {"CANCELLED"}
        setattr(link.map_scene(), switch, True)
        return {"FINISHED"}


def _rebuild(operator, context) -> bool:
    from . import link
    context.window_manager.progress_begin(0, 1)
    try:
        message = build(context)
    except (ValueError, OSError) as exc:
        operator.report({"ERROR"}, f"Preview failed: {exc}")
        link.append_log(f"sdk   preview failed: {exc}")
        return False
    finally:
        context.window_manager.progress_end()
    link.append_log(f"sdk   preview: {message}")
    operator.report({"INFO"}, f"Preview: {message}")
    return True


class BOZ_OT_preview_refresh(Operator):
    bl_idname = "boz.suite_preview_refresh"
    bl_label = "Refresh"
    bl_description = "Compile the map again and update the walkable area and collision shown"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not _rebuild(self, context):
            return {"CANCELLED"}
        return {"FINISHED"}


def draw_switches(layout, context, compact=False) -> None:
    scene = link.map_scene()
    if not hasattr(scene, "boz_show_markers"):
        return
    row = layout.row(align=True)
    row.prop(scene, "boz_show_markers", text="" if compact else "Markers", icon="MESH_CUBE",
             toggle=True)
    row.prop(scene, "boz_show_shapes", text="" if compact else "Triggers", icon="CUBE",
             toggle=True)
    row.prop(scene, "boz_show_links", text="" if compact else "Links", icon="LINKED", toggle=True)
    if scene.boz_show_links:
        row.prop(scene, "boz_links_selected_only", text="" if compact else "Selected",
                 icon="RESTRICT_SELECT_OFF", toggle=True)
        error = scene_view.draw_error
        if error and not compact:
            layout.label(text=f"Links could not be drawn: {error}", icon="ERROR")
    row = layout.row(align=True)
    for kind, text, icon in (("navmesh", "Walkable", "MOD_TRIANGULATE"),
                             ("collision", "Collision", "MOD_PHYSICS")):
        on = getattr(scene, SWITCHES[kind]) and has_preview(kind)
        row.operator(BOZ_OT_preview.bl_idname, text="" if compact else text, icon=icon,
                     depress=on).kind = kind
    row.operator(BOZ_OT_preview_refresh.bl_idname, text="", icon="FILE_REFRESH")


def draw_header(self, context):
    workspace = context.workspace
    if workspace is None or workspace.name != "World":
        return
    self.layout.separator()
    self.layout.menu("BOZ_MT_shapes", text="Shapes", icon="MESH_CUBE")
    draw_switches(self.layout, context, compact=True)


class BOZ_PT_show(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BOZ"
    bl_label = "Show"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        draw_switches(layout, context)
        layout.label(text="Markers: entities without a model, coloured by type")
        layout.label(text="Triggers: trigger and collision volumes of entities")
        layout.label(text="Links: power, traps, doors and what they unlock")
        layout.label(text="Walkable: blue floor, orange behind doors (Refresh after edits)")


BOX_EDGES = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7),
             (0, 4), (1, 5), (2, 6), (3, 7)]
BOX_COLOUR = (1.0, 0.35, 0.2, 1.0)
_box_handle = None


def collision_box(obj):
    """World corners of a model's collision box (its mesh bounds grown by its padding, the way
    the compiler builds it), or None when it does not collide as a box."""
    from mathutils import Vector

    settings = obj.boz
    if obj.type != "MESH" or settings.role != "model" or settings.collision == "none" \
            or settings.shape != "box" or not obj.data.vertices:
        return None
    matrix = convert.world_matrix(obj)
    scale = matrix.to_scale()
    pad = [settings.padding / abs(c) if c else 0.0 for c in scale]
    points = [v.co for v in obj.data.vertices]
    low = [min(p[i] for p in points) - pad[i] for i in range(3)]
    high = [max(p[i] for p in points) + pad[i] for i in range(3)]
    return [matrix @ Vector(tuple(high[i] if corner >> i & 1 else low[i] for i in range(3)))
            for corner in range(8)]


def draw_collision_boxes():
    """Outline the collision box of each selected model (what players bump into). The area a
    blocking model shuts shows in the Walkable preview (Refresh), built by the compiler."""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return
    context = bpy.context
    lines = []
    for obj in context.selected_objects:
        corners = collision_box(obj)
        if corners:
            for a, b in BOX_EDGES:
                lines += [tuple(corners[a]), tuple(corners[b])]
    if not lines:
        return
    try:
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        wide = True
    except (ValueError, SystemError):
        shader, wide = gpu.shader.from_builtin("UNIFORM_COLOR"), False
    gpu.state.blend_set("ALPHA")
    batch = batch_for_shader(shader, "LINES", {"pos": lines})
    shader.bind()
    if wide and context.region is not None:
        shader.uniform_float("viewportSize", (context.region.width, context.region.height))
        shader.uniform_float("lineWidth", 2.0)
    shader.uniform_float("color", BOX_COLOUR)
    batch.draw(shader)
    gpu.state.blend_set("NONE")


CLASSES = (BOZ_OT_preview, BOZ_OT_preview_refresh, BOZ_PT_show)


def register():
    global _box_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_HT_header.append(draw_header)
    if not bpy.app.background:
        _box_handle = bpy.types.SpaceView3D.draw_handler_add(draw_collision_boxes, (), "WINDOW",
                                                             "POST_VIEW")


def unregister():
    global _box_handle
    if _box_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_box_handle, "WINDOW")
        _box_handle = None
    bpy.types.VIEW3D_HT_header.remove(draw_header)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
