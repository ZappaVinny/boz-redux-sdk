"""The editor's link to its project: open the project's world, write it back on save, show the
game's log and the problems that would stop a build, and Build & Run.

The launcher starts Blender with BOZ_PROJECT (the project folder). The project's ``map.blend``
is the working file; every save also writes ``source/`` (bozkit.world), which is what builds
read. A project without ``map.blend`` gets one made from its world source on first open.
"""
from __future__ import annotations

import os
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

try:
    from bozkit import blender_scene, project as sdk_project, sdkhome, toolkit, world
except ModuleNotFoundError:
    from ._vendor.bozkit import blender_scene, project as sdk_project, sdkhome, toolkit, world

from . import convert, tabs

COLLISION_ITEMS = [
    ("floor", "Walkable", "Floors, ramps, stairs: players stand on it and zombies walk on it "
     "(the navmesh is built on its top)"),
    ("solid", "Blocking", "Walls, crates, machines: players and zombies cannot pass through it "
     "and nobody walks on it (it cuts a hole in the navmesh)"),
    ("none", "None", "Decoration: no collision, and the navmesh ignores it"),
]
ROLE_ITEMS = [("mesh", "Level mesh", "Geometry the level is built from, in place"),
              ("prop", "Prop", "A project prop: objects sharing its mesh (Alt+D) are copies of it"),
              ("model", "Game model", "A model from the game, copied into the level"),
              ("entity", "Game entity", "A copy of one of the game's entities (perks, spawns, ...)"),
              ("reference", "Base level", "Part of the inherited base level, shown read only"),
              # New items go last: saved files store the item's position.
              ("base", "Base level entity", "One of the base level's own entities: move, "
               "rotate, scale, duplicate or delete it and change its settings")]
SHAPE_ITEMS = [("box", "Box", "Collide with its bounds (fast)"),
               ("mesh", "Mesh", "Collide with its triangles (exact)")]
LOG_LINES = 3000


def project_root() -> Path | None:
    value = os.environ.get("BOZ_PROJECT")
    return Path(value) if value else None


def current_project():
    root = project_root()
    if root is None:
        return None
    try:
        return sdk_project.load_project(root)
    except sdk_project.ProjectError:
        return None


# Properties


class BOZ_ObjectSettings(PropertyGroup):
    role: EnumProperty(name="Role", items=ROLE_ITEMS, default="mesh")
    collision: EnumProperty(name="Collision", items=COLLISION_ITEMS, default="floor",
                            description="How players and zombies treat this mesh in the game")
    double_sided: BoolProperty(name="Double-sided", default=False,
                               description="Draw the back of every face too")
    source: StringProperty(name="Source", description="The game entity (a name or 0x hash) or "
                           "game model (group#0xhash) this places")
    group: StringProperty(name="Group", description="The game group holding the entity (empty: "
                          "the base level)")
    shape: EnumProperty(name="Shape", items=SHAPE_ITEMS, default="box")


class BOZ_SceneSettings(PropertyGroup):
    base: StringProperty(name="Base level", default="kino",
                         description="Shipped level giving rounds, zombie types, sounds and cameras")
    inherit: BoolProperty(name="Inherit the whole base level", default=False,
                          description="Start from the whole base level (its rooms, entities and "
                          "navmesh) and add this map's contents to it")
    start_level: BoolProperty(name="Start the level", default=True,
                              description="Start the game straight into this map")
    unlimited_health: BoolProperty(name="Unlimited health", default=False)
    unlimited_points: BoolProperty(name="Unlimited points", default=False)
    starting_points: IntProperty(name="Starting points", default=500, min=0, max=1000000)


# Log


def append_log(lines) -> None:
    text = tabs.log_text()
    if isinstance(lines, str):
        lines = [lines]
    for line in lines:
        text.write(line.rstrip("\n") + "\n")
    if len(text.lines) > LOG_LINES:
        keep = text.as_string().splitlines()[-LOG_LINES:]
        text.clear()
        text.write("\n".join(keep) + "\n")
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR" and area.spaces.active.text == text:
                area.spaces.active.top = max(0, len(text.lines) - 20)
                area.tag_redraw()


_log_state = {"size": -1}


def _game_log() -> Path | None:
    client = os.environ.get("BOZ_CLIENT") or sdkhome.Settings.load().client
    return Path(client) / "boz-log.txt" if client else None


def poll_game_log():
    """Timer: copy new lines of the client's boz-log.txt into the log."""
    path = _game_log()
    try:
        size = path.stat().st_size if path else -1
    except OSError:
        size = -1
    previous = _log_state["size"]
    if size >= 0 and previous >= 0 and size != previous:
        start = previous if size > previous else 0
        with open(path, "rb") as stream:
            stream.seek(start)
            new = stream.read().decode("utf-8", "replace").splitlines()
        if new:
            append_log([f"game  {line}" for line in new])
    _log_state["size"] = size
    return 1.0


# Scene <-> world (convert.py)

mesh_name = convert.mesh_name
scene_to_world = convert.scene_to_world
world_to_scene = convert.world_to_scene


def write_source(scene) -> list:
    """Write the scene into the project's source folder; returns the problems found."""
    project = current_project()
    if project is None or project.kind != "map":
        return []
    problems = []
    result = scene_to_world(scene, problems)
    # map.blend is the working file and source/ is derived from it, so it is always rewritten.
    world.save(result, project.root / "source")
    if result.removed:
        convert.tidy_removed(scene, result.removed)
    scene["boz_problems"] = [f"{message}\t{name}" for message, name in problems]
    return problems


# Handlers


@persistent
def on_load(_dummy):
    for workspace in bpy.data.workspaces:
        for screen in workspace.screens:
            tabs.setup_screen(screen, workspace.name)
    project = current_project()
    if project is None or project.kind != "map":
        return
    scene = bpy.context.scene
    if hasattr(scene, "boz_links_selected_only") and "boz_links_shown" not in scene:
        scene.boz_links_selected_only = False   # Links shows every link until narrowed
        scene["boz_links_shown"] = True
    if bpy.data.filepath:
        scene = bpy.context.scene
        view = scene.view_settings
        view.view_transform, view.look = "Standard", "None"   # the game's colours
        convert.show_game_models(scene)
        if scene.boz.inherit and "boz_base_entities" not in scene:
            # Maps made before the base level's entities could be edited.
            count = convert.make_base_editable(scene, scene.boz.base)
            scene.boz_show_markers = True
            append_log(f"sdk   {count} of {scene.boz.base}'s entities can be edited now")
        from . import palette
        palette.show_palette()
        return
    blend = project.root / "map.blend"
    if blend.exists() or bpy.context.scene.objects:  # both startup handlers run; build once
        return
    # First open: build the scene from the world source, then save it as the project's map.blend.
    try:
        source_world = world.load(project.root / "source")
    except world.WorldError as exc:
        append_log(f"sdk   {exc}")
        return
    world_to_scene(source_world, project.root / "source", bpy.context.scene)
    bpy.app.timers.register(lambda: _first_save(blend), first_interval=0.2)


def _first_save(blend: Path):
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), relative_remap=True)
        append_log(f"sdk   made {blend.name} from the project's world")
    except RuntimeError as exc:
        append_log(f"sdk   could not save {blend}: {exc}")
    return None


@persistent
def on_save(_dummy):
    problems = write_source(bpy.context.scene)
    if problems:
        append_log([f"check {message}" for message, _ in problems])


# Operators


def problems_of(scene) -> list[tuple[str, str]]:
    return [tuple((entry.split("\t") + [""])[:2]) for entry in scene.get("boz_problems", [])]


class BOZ_OT_build_and_run(Operator):
    bl_idname = "boz.suite_build_and_run"
    bl_label = "Build & Run"
    bl_description = ("Save, compile the map into a mod, install it with the Developer mod and "
                      "start the game in it")

    def execute(self, context):
        project = current_project()
        if project is None:
            self.report({"ERROR"}, "Open this map from the SDK launcher to build it")
            return {"CANCELLED"}
        if not bpy.data.filepath:
            bpy.ops.wm.save_as_mainfile(filepath=str(project.root / "map.blend"))
        else:
            bpy.ops.wm.save_mainfile()
        problems = problems_of(context.scene)
        if problems:
            append_log([f"check {message}" for message, _ in problems])
            self.report({"ERROR"}, f"{len(problems)} problems stop the build (see Problems)")
            return {"CANCELLED"}
        settings = context.scene.boz
        start_vars = {}
        if settings.unlimited_health:
            start_vars["UnlimitedHealth"] = "true"
        if settings.unlimited_points:
            start_vars["UnlimitedScore"] = "true"
        if settings.starting_points != 500:
            start_vars["StartingScore"] = str(settings.starting_points)
        client = os.environ.get("BOZ_CLIENT") or sdkhome.Settings.load().client
        try:
            message = sdkhome.run_in_game(project, client, start_vars)
        except (OSError, ValueError, sdk_project.ProjectError) as exc:
            append_log(f"build {exc}")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _log_state["size"] = 0  # the game rewrites boz-log.txt
        append_log(f"build {message}")
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BOZ_OT_build_settings(Operator):
    bl_idname = "boz.suite_build_settings"
    bl_label = "Build & Run settings"
    bl_description = "How Build & Run starts the game"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.boz
        layout.label(text="When the game starts:")
        layout.prop(settings, "unlimited_health")
        layout.prop(settings, "unlimited_points")
        layout.prop(settings, "starting_points")
        row = layout.row()
        row.enabled = False
        row.label(text="Starting round: coming later", icon="TIME")
        layout.separator()
        layout.prop(settings, "base")
        layout.label(text="The Developer mod (console: ` or F1) is always on.", icon="INFO")

    def execute(self, context):
        return {"FINISHED"}


class BOZ_OT_select_problem(Operator):
    bl_idname = "boz.select_problem"
    bl_label = "Select"
    bl_options = {"INTERNAL", "UNDO"}

    name: StringProperty()

    def execute(self, context):
        obj = context.scene.objects.get(self.name)
        if obj is None:
            return {"CANCELLED"}
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class BOZ_OT_check(Operator):
    bl_idname = "boz.check_world"
    bl_label = "Check"
    bl_description = "Look for problems that would stop the build"

    def execute(self, context):
        problems = []
        scene_to_world(context.scene, problems)
        context.scene["boz_problems"] = [f"{m}\t{n}" for m, n in problems]
        self.report({"INFO"} if not problems else {"WARNING"},
                    "No problems" if not problems else f"{len(problems)} problems")
        return {"FINISHED"}


class BOZ_OT_make_prop(Operator):
    bl_idname = "boz.make_prop"
    bl_label = "Make prop"
    bl_description = ("Give the selected object its own editable mesh and textures: a level mesh "
                      "or game model becomes a project prop; a game entity keeps working as "
                      "before and draws your mesh")
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Prop name")

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "MESH" and obj.boz.role not in ("prop", "reference") \
            and not convert.is_marker(obj)

    def invoke(self, context, event):
        self.name = convert.game_name(context.object.name)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.object
        entity = obj.boz.role in ("entity", "base")
        try:
            convert.make_prop(obj, self.name or obj.name)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{obj.name} draws your mesh now; edit it freely" if entity
                    else f"{obj.name} is a prop; Alt+D places more copies")
        return {"FINISHED"}


class BOZ_OT_game_model(Operator):
    bl_idname = "boz.use_game_model"
    bl_label = "Use the game's model"
    bl_description = "Draw this entity with the game's own model again (drops your edited mesh)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("boz_custom_model")

    def execute(self, context):
        from . import game
        obj = context.object
        placement = world.Placement(obj.boz.source, (0.0, 0.0, 0.0), group=obj.boz.group)
        data = game.entity_mesh(context.scene.boz.base, placement.hash, obj.boz.group)
        if "boz_custom_model" in obj:
            del obj["boz_custom_model"]
        if data is not None:
            convert.show_mesh(obj, data)
        else:   # it draws nothing of its own: back to its marker
            convert.colour_marker(obj, convert.entity_category(
                context.scene.boz.base, placement.hash, obj.boz.group))
        return {"FINISHED"}


def _game_textures(self, context):
    """Every game texture with a preview, for the From game search (built once)."""
    from . import game
    cache = _game_textures.__dict__.setdefault("items", [])
    if not cache:
        try:
            built = game.library.Library()
        except game.library.LibraryError:
            return [("", "Build the asset library first", "")]
        for asset in built.search(kind="texture", limit=100000):
            cache.append((f"{asset.groups[0]}#0x{asset.hash:08x}",
                          f"{asset.title} ({asset.width}x{asset.height})", asset.label or ""))
        built.close()
    return cache


def _weapons(self, context):
    from . import game
    cache = _weapons.__dict__.setdefault("by_base", {})
    base = context.scene.boz.base
    if base not in cache:
        cache[base] = [(name, name, "") for name in game.weapon_names(base)] or \
            [("", "No weapons found (build the asset library)", "")]
    return cache[base]


def _set_texture(material, image) -> None:
    """Put *image* in a material's main texture slot (game material or project material)."""
    nodes = material.node_tree.nodes if material.use_nodes else None
    if nodes is None:
        return
    node = nodes.get("BOZ Primary")
    if node is None or node.type != "TEX_IMAGE":
        node = next((n for n in nodes if n.type == "TEX_IMAGE" and n.name != "BOZ Lightmap"), None)
    if node is None:
        node = nodes.new("ShaderNodeTexImage")
        node.name = "BOZ Primary"
        shader = nodes.get("Principled BSDF") or nodes.get("Emission")
        if shader is not None:
            material.node_tree.links.new(node.outputs["Color"], shader.inputs[0])
    node.image = image


class BOZ_OT_texture_file(Operator):
    bl_idname = "boz.texture_file"
    bl_label = "Replace texture"
    bl_description = "Use an image file (PNG or JPG; power-of-two sides up to 1024) as this texture"
    bl_options = {"REGISTER", "UNDO"}

    slot: IntProperty()
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.object
        material = obj.material_slots[self.slot].material if self.slot < len(obj.material_slots) else None
        if material is None:
            self.report({"ERROR"}, "This slot has no material")
            return {"CANCELLED"}
        _set_texture(material, bpy.data.images.load(self.filepath, check_existing=True))
        return {"FINISHED"}


class BOZ_OT_texture_game(Operator):
    bl_idname = "boz.texture_game"
    bl_label = "Texture from the game"
    bl_description = "Use one of the game's textures here"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "texture"

    slot: IntProperty()
    texture: EnumProperty(items=_game_textures)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from . import game
        obj = context.object
        path, _, value = self.texture.partition("#")
        built = game.texture_material(path, int(value, 16)) if value else None
        if built is None:
            self.report({"ERROR"}, "That texture could not be loaded")
            return {"CANCELLED"}
        if self.slot < len(obj.material_slots):
            obj.material_slots[self.slot].material = built
        else:
            obj.data.materials.append(built)
        game.ensure_colour(obj.data)
        return {"FINISHED"}


class BOZ_OT_choose_weapon(Operator):
    bl_idname = "boz.choose_weapon"
    bl_label = "Choose weapon"
    bl_description = "The weapon this wall buy sells (any weapon of the level)"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "weapon"

    weapon: EnumProperty(items=_weapons)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from . import game
        obj = context.object
        obj[convert.FIELD_PREFIX + toolkit.WEAPON_FIELD] = self.weapon
        if not obj.get("boz_custom_model"):
            placement = world.Placement(obj.boz.source, (0.0, 0.0, 0.0), group=obj.boz.group)
            data = game.entity_mesh(context.scene.boz.base, placement.hash, obj.boz.group,
                                    game.weapon_model(context.scene.boz.base, self.weapon))
            if data is not None and obj.type == "MESH":
                convert.show_mesh(obj, data)
                for child in obj.children:
                    if child.boz.role == "reference" and child.get("boz_kind") == "placed_model":
                        child.hide_set(True)   # the base level's own weapon model
        convert.refresh_chalk(obj, context.scene.boz.base)
        return {"FINISHED"}


class BOZ_OT_chalk(Operator):
    bl_idname = "boz.chalk"
    bl_label = "Chalk"
    bl_description = "Automatic: the weapon's own chalk, or one drawn from its model. None: no chalk"
    bl_options = {"REGISTER", "UNDO"}

    mode: StringProperty()

    def execute(self, context):
        obj = context.object
        obj[convert.FIELD_PREFIX + world.CHALK_FIELD] = self.mode
        convert.refresh_chalk(obj, context.scene.boz.base)
        return {"FINISHED"}


class BOZ_OT_chalk_image(Operator):
    bl_idname = "boz.chalk_image"
    bl_label = "Chalk image"
    bl_description = ("Use your own chalk drawing (white on black, 128 x 64 like the game's, or any "
                      "power-of-two size); it is copied into the project")
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import shutil
        root = project_root()
        if root is None:
            self.report({"ERROR"}, "Open this map from the SDK launcher first")
            return {"CANCELLED"}
        obj = context.object
        name = f"chalk/{convert.game_name(obj.name)}.png"
        target = root / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.filepath, target)
        bpy.data.meshes.get(f"BOZ game chalk {name}") and bpy.data.meshes.remove(
            bpy.data.meshes[f"BOZ game chalk {name}"])
        obj[convert.FIELD_PREFIX + world.CHALK_FIELD] = name
        convert.refresh_chalk(obj, context.scene.boz.base)
        return {"FINISHED"}


class BOZ_PT_textures(Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_label = "Textures"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj.boz.role in ("entity", "base", "model", "reference") and not obj.get("boz_custom_model"):
            layout.label(text="The game's own textures; Edit its model or Make prop to change",
                         icon="INFO")
        if not obj.material_slots:
            layout.operator(BOZ_OT_texture_game.bl_idname, text="Texture from the game",
                            icon="TEXTURE").slot = 0
            return
        for index, slot in enumerate(obj.material_slots):
            box = layout.box()
            image = convert.image_of(slot.material)
            row = box.row()
            if image is not None:
                row.template_icon(icon_value=image.preview_ensure().icon_id, scale=4.0)
            column = row.column()
            column.label(text=image.name if image else "(no texture)")
            if image is not None:
                column.label(text=f"{image.size[0]} x {image.size[1]}")
            editable = obj.boz.role in ("mesh", "prop") or obj.get("boz_custom_model")
            buttons = column.row(align=True)
            buttons.enabled = bool(editable)
            buttons.operator(BOZ_OT_texture_file.bl_idname, text="Replace…",
                             icon="FILEBROWSER").slot = index
            buttons.operator(BOZ_OT_texture_game.bl_idname, text="From game…",
                             icon="TEXTURE").slot = index


class BOZ_OT_show_game_models(Operator):
    bl_idname = "boz.show_game_models"
    bl_label = "Show game models"
    bl_description = "Show the game's models for placed entities and game models (from the asset library)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        changed = convert.show_game_models(context.scene)
        self.report({"INFO"}, f"{changed} objects now show their game model")
        return {"FINISHED"}


class BOZ_OT_clear_log(Operator):
    bl_idname = "boz.clear_log"
    bl_label = "Clear log"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        tabs.log_text().clear()
        return {"FINISHED"}


class BOZ_OT_open_project_folder(Operator):
    bl_idname = "boz.open_project_folder"
    bl_label = "Open project folder"

    def execute(self, context):
        root = project_root()
        if root is None:
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(root))
        return {"FINISHED"}


class BOZ_OT_back_to_launcher(Operator):
    bl_idname = "boz.back_to_launcher"
    bl_label = "Save and close"
    bl_description = "Save the map and close the editor (the launcher stays open)"

    def execute(self, context):
        if bpy.data.filepath:
            bpy.ops.wm.save_mainfile()
        bpy.ops.wm.quit_blender()
        return {"FINISHED"}


class BOZ_OT_reset_base(Operator):
    bl_idname = "boz.reset_base"
    bl_label = "Put back as the level has it"
    bl_description = "Move this entity back to where the base level has it, with its own settings"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.boz.role == "base"

    def execute(self, context):
        convert.reset_base(context.object)
        return {"FINISHED"}


# Panels


class BOZ_PT_object(Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_label = "Game"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            return
        settings = obj.boz
        layout.prop(settings, "role")
        if settings.role in ("mesh", "prop", "model"):
            layout.prop(settings, "collision", expand=True)
        if settings.role in ("prop", "model") and settings.collision != "none":
            layout.prop(settings, "shape", expand=True)
        if settings.role in ("mesh", "prop"):
            layout.prop(settings, "double_sided")
        if settings.role == "mesh" and obj.type == "MESH":
            layout.label(text=f"In the game: {mesh_name(obj)}")
        elif settings.role == "prop" and obj.type == "MESH":
            users = obj.data.users
            layout.label(text=f"Prop {mesh_name(obj)}: {users} placed" if users > 1
                         else f"Prop {mesh_name(obj)} (Alt+D places copies)")
        elif settings.role == "reference":
            layout.label(text="Part of the base level (read only)", icon="LOCKED")
        if settings.role == "base":
            box = layout.box()
            box.label(text=obj.get("boz_description") or "One of the base level's entities",
                      icon="WORLD")
            changed, moved = convert._base_changes(obj)
            box.label(text="Changed in this map" if changed or moved or obj.get("boz_custom_model")
                      else "As the level has it")
            box.label(text="Delete (X) takes it out of the map; Shift+D adds a copy")
            box.operator(BOZ_OT_reset_base.bl_idname, icon="LOOP_BACK")
        if settings.role in ("entity", "base") and obj.get("boz_piece"):
            try:
                piece = toolkit.piece(obj["boz_piece"])
            except KeyError:
                piece = None
            if piece is not None:
                layout.label(text=piece.label, icon="TOOL_SETTINGS")
                for setting in piece.settings:
                    name = convert.FIELD_PREFIX + setting.key
                    if setting.kind == "weapon":
                        row = layout.row()
                        row.label(text=f"{setting.label}: {obj.get(name, '?')}")
                        row.operator(BOZ_OT_choose_weapon.bl_idname, text="Choose…")
                    elif setting.kind == "chalk" and settings.role == "base":
                        continue   # shipped chalk is painted on the room's wall
                    elif setting.kind == "chalk":
                        mode = str(obj.get(name, ""))
                        shown = {"": "Automatic", "none": "None"}.get(mode, mode)
                        layout.label(text=f"Chalk: {shown}")
                        row = layout.row(align=True)
                        row.operator(BOZ_OT_chalk.bl_idname, text="Automatic",
                                     depress=mode == "").mode = ""
                        row.operator(BOZ_OT_chalk.bl_idname, text="None",
                                     depress=mode == "none").mode = "none"
                        row.operator(BOZ_OT_chalk_image.bl_idname, text="Image…",
                                     depress=mode not in ("", "none"))
                    elif name in obj:
                        layout.prop(obj, f'["{name}"]', text=setting.label)
        if settings.role == "base" and obj.get(convert.FIELD_PREFIX + toolkit.WEAPON_FIELD):
            layout.label(text="Its chalk drawing is painted on the wall and stays", icon="INFO")
        if settings.role in ("model", "entity"):
            layout.prop(settings, "source")
            if settings.role == "entity":
                layout.prop(settings, "group")
        if settings.role in ("entity", "base") and obj.get("boz_custom_model"):
            box = layout.box()
            box.label(text="Draws your edited mesh; works as before", icon="MESH_DATA")
            box.label(text=f"Its mesh: {mesh_name(obj)}")
            box.operator(BOZ_OT_game_model.bl_idname, icon="LOOP_BACK")
        elif convert.is_marker(obj):
            pass
        elif obj.type == "MESH" and settings.role in ("entity", "base"):
            layout.operator(BOZ_OT_make_prop.bl_idname, text="Edit its model", icon="MESH_CUBE")
        elif obj.type == "MESH" and settings.role not in ("prop", "reference"):
            layout.operator(BOZ_OT_make_prop.bl_idname, icon="MESH_CUBE")


class BOZ_PT_problems(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Problems"
    bl_label = "Problems"

    def draw(self, context):
        layout = self.layout
        layout.operator(BOZ_OT_check.bl_idname, icon="CHECKMARK")
        problems = problems_of(context.scene)
        if not problems:
            layout.label(text="Nothing stops the build", icon="CHECKMARK")
        for message, name in problems:
            row = layout.row()
            row.label(text=message, icon="ERROR")
            if name:
                row.operator(BOZ_OT_select_problem.bl_idname, text="", icon="RESTRICT_SELECT_OFF").name = name


class BOZ_PT_project(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BOZ"
    bl_label = "Project"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        project = current_project()
        if project is None:
            layout.label(text="Not opened from the SDK launcher", icon="ERROR")
            return
        layout.label(text=project.mod.name, icon="FILE_FOLDER")
        layout.label(text=f"Level: {project.map_name or '-'}")
        layout.prop(context.scene.boz, "base")


CLASSES = [BOZ_ObjectSettings, BOZ_SceneSettings, BOZ_OT_build_and_run, BOZ_OT_build_settings,
           BOZ_OT_select_problem, BOZ_OT_check, BOZ_OT_make_prop, BOZ_OT_game_model,
           BOZ_OT_texture_file, BOZ_OT_texture_game, BOZ_OT_choose_weapon, BOZ_OT_chalk,
           BOZ_OT_chalk_image, BOZ_PT_textures,
           BOZ_OT_show_game_models,
           BOZ_OT_clear_log, BOZ_OT_open_project_folder,
           BOZ_OT_back_to_launcher, BOZ_OT_reset_base, BOZ_PT_object, BOZ_PT_problems, BOZ_PT_project]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.boz = PointerProperty(type=BOZ_ObjectSettings)
    bpy.types.Scene.boz = PointerProperty(type=BOZ_SceneSettings)
    bpy.app.handlers.load_post.append(on_load)
    bpy.app.handlers.load_factory_startup_post.append(on_load)
    bpy.app.handlers.save_post.append(on_save)
    if not bpy.app.background:
        bpy.app.timers.register(poll_game_log, first_interval=1.0, persistent=True)
        bpy.app.timers.register(tabs.refresh_windows, first_interval=0.5, persistent=True)


def unregister():
    for timer in (poll_game_log, tabs.refresh_windows):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    for handlers, function in ((bpy.app.handlers.load_post, on_load),
                               (bpy.app.handlers.load_factory_startup_post, on_load),
                               (bpy.app.handlers.save_post, on_save)):
        if function in handlers:
            handlers.remove(function)
    del bpy.types.Scene.boz
    del bpy.types.Object.boz
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
