"""Models, volumes and prefabs in the editor: the object's Game panel, grouping into prefabs, the
prefab library, and scripts with their properties.

- **Make prefab** (Ctrl+G) groups the selected models, volumes and prefabs under a new prefab
  (an Empty); **Ungroup** (Ctrl+Alt+G) takes one apart.
- **Save as new prefab** stores a prefab in the project's library (source/prefabs); it shows in
  the asset browser's **My prefabs** (prefab_library.py), and dropping it places an independent
  copy (no live link). Project → Prefab library deletes library prefabs.
- **Script**: New makes scripts/prefabs/<Name>.lua from a template; its ``---@property`` lines
  become fields in the panel (bozkit.scripts), saved with each object.
"""
from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel

try:
    from bozkit import scripts, toolkit, world
except ModuleNotFoundError:
    from ._vendor.bozkit import scripts, toolkit, world

from . import convert, link, tabs

KINDS = ("model", "volume", "prefab")


def kind_label(obj) -> tuple[str, str]:
    """(label, icon) of what an object is."""
    settings = obj.boz
    if settings.role == "reference":
        return "Base level (read only)", "LOCKED"
    if settings.role == "model":
        return ("Model: game model", "MESH_MONKEY") if settings.source else \
            ("Model: your mesh", "MESH_DATA")
    if settings.role == "volume":
        return f"Volume: {settings.volume.title()}", "CUBE"
    if settings.role == "prefab":
        if settings.original:
            return "Game prefab (from the original map)", "WORLD"
        if settings.source:
            piece = obj.get("boz_piece")
            try:
                label = toolkit.piece(piece).label if piece else settings.source
            except KeyError:
                label = settings.source
            return f"Game prefab: {label}", "TOOL_SETTINGS"
        return "Prefab", "OUTLINER_OB_EMPTY"
    return "Not part of the map", "QUESTION"


# Scripts


def scripts_dir() -> Path | None:
    project = link.current_project()
    return project.scripts if project is not None else None


def declared(obj) -> list:
    """The properties obj's script declares ([] without a script or when it cannot be read)."""
    folder = scripts_dir()
    if not obj.boz.script or folder is None:
        return []
    try:
        return scripts.read_properties(folder / obj.boz.script)
    except scripts.ScriptError:
        return []


def sync_properties(obj) -> None:
    """Give obj a value for every property its script declares (the default when new) and drop
    values for properties the script no longer has."""
    props = declared(obj)
    names = {prop.name for prop in props}
    for prop in props:
        key = convert.PROPERTY_PREFIX + prop.name
        if key not in obj:
            obj[key] = prop.default
        else:
            try:
                obj[key] = scripts.coerce(obj[key], prop.type)
            except (TypeError, ValueError):
                obj[key] = prop.default
    if obj.boz.script and scripts_dir() is not None:
        for key in [k for k in obj.keys() if k.startswith(convert.PROPERTY_PREFIX)]:
            if key[len(convert.PROPERTY_PREFIX):] not in names:
                del obj[key]


def script_text(path: Path):
    """The Blender text holding the script at *path* (loaded from the file, and reloaded when
    the file changed outside Blender while the text has no unsaved edits)."""
    path = Path(path).resolve()
    for text in bpy.data.texts:
        if text.filepath and Path(bpy.path.abspath(text.filepath)).resolve() == path:
            if not text.is_dirty and path.is_file():
                on_disk = path.read_text(encoding="utf-8")
                if on_disk != text.as_string():
                    text.clear()
                    text.write(on_disk)
            return text
    return bpy.data.texts.load(str(path))


def save_scripts() -> int:
    """Write the project's scripts edited in the Scripts tab back to their files."""
    folder = scripts_dir()
    if folder is None:
        return 0
    folder = folder.resolve()
    saved = 0
    for text in bpy.data.texts:
        if not text.filepath or not text.is_dirty:
            continue
        path = Path(bpy.path.abspath(text.filepath)).resolve()
        if folder not in path.parents:
            continue
        path.write_text(text.as_string(), encoding="utf-8", newline="\n")
        _mark_saved(text)
        saved += 1
    return saved


def _mark_saved(text) -> None:
    """Clear a text's unsaved flag through the text editor's own save (when one is shown)."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR":
                try:
                    with bpy.context.temp_override(window=window, area=area, edit_text=text):
                        bpy.ops.text.save()
                except RuntimeError:
                    pass
                return


def show_script(context, path: Path) -> None:
    """Open a script in the Scripts tab's text editor and switch to that tab."""
    text = script_text(path)
    workspace = bpy.data.workspaces.get("Scripts")
    window = context.window
    if workspace is not None and window is not None:
        window.workspace = workspace
        _put_in_editor(workspace.screens[0], text)
    return text


def _put_in_editor(screen, text) -> None:
    area = tabs.script_area(screen)
    if area is not None:
        space = area.spaces.active
        space.text = text
        space.show_line_numbers = True
        space.show_syntax_highlight = True
        space.show_word_wrap = False
        area.tag_redraw()


TEXT_FILES = (".lua", ".txt", ".json", ".md", ".toml", ".ini", ".cfg")
_browsed = {}   # file browser area -> the file it last opened


def _path_text(value) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def watch_browser() -> float:
    """Timer: a file selected in the Scripts tab's file browser opens in its script editor (a
    file browser on its own only selects). The browser starts in the project's scripts folder."""
    folder = scripts_dir()
    for window in bpy.context.window_manager.windows:
        workspace = window.workspace
        if workspace.name != "Scripts":
            continue
        for area in window.screen.areas:
            if area.type != "FILE_BROWSER":
                continue
            params = getattr(tabs.space_of(area), "params", None)
            if params is None:
                continue
            key = area.as_pointer()
            if folder is not None and folder.is_dir() and \
                    workspace.get("boz_browser_root") != str(folder):
                workspace["boz_browser_root"] = str(folder)
                try:
                    params.directory = str(folder).encode()
                except TypeError:
                    params.directory = str(folder)
                _browsed[key] = ""
                continue
            path = Path(bpy.path.abspath(_path_text(params.directory))) / _path_text(params.filename)
            if not params.filename or path.suffix.lower() not in TEXT_FILES or \
                    not path.is_file() or _browsed.get(key) == str(path):
                continue
            _browsed[key] = str(path)
            try:
                _put_in_editor(window.screen, script_text(path))
            except (OSError, RuntimeError, UnicodeDecodeError) as exc:
                print(f"boz_suite: could not open {path}: {exc}")
    return 0.25


def sync_all(scene) -> None:
    for obj in scene.objects:
        if obj.boz.script:
            sync_properties(obj)


class BOZ_OT_script_new(Operator):
    bl_idname = "boz.script_new"
    bl_label = "New script"
    bl_description = "Make a script for this object from the template and open it"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Script name")

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.boz.role in KINDS

    def invoke(self, context, event):
        self.name = convert.clean_name(context.object.boz.part_name or context.object.name)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        folder = scripts_dir()
        if folder is None:
            self.report({"ERROR"}, "Open this map from the SDK launcher first")
            return {"CANCELLED"}
        try:
            relative = scripts.new_script(folder, self.name)
        except scripts.ScriptError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        context.object.boz.script = relative
        sync_properties(context.object)
        show_script(context, folder / relative)
        return {"FINISHED"}


def _script_items(self, context):
    folder = scripts_dir()
    found = scripts.list_scripts(folder) if folder is not None else []
    return [(path, path, "") for path in found] or [("", "(no scripts yet)", "")]


class BOZ_OT_script_pick(Operator):
    bl_idname = "boz.script_pick"
    bl_label = "Pick script"
    bl_description = "Use one of the project's scripts (scripts/prefabs)"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "path"

    path: EnumProperty(items=_script_items)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.boz.role in KINDS

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.path:
            return {"CANCELLED"}
        context.object.boz.script = self.path
        sync_properties(context.object)
        return {"FINISHED"}


class BOZ_OT_script_open(Operator):
    bl_idname = "boz.script_open"
    bl_label = "Open script"
    bl_description = "Edit its script in the Scripts tab (saving the map saves it)"

    external: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.object is not None and bool(context.object.boz.script)

    @classmethod
    def description(cls, context, properties):
        return ("Open its script in your own text editor (VS Code when installed)"
                if properties.external else cls.bl_description)

    def execute(self, context):
        folder = scripts_dir()
        if folder is None:
            return {"CANCELLED"}
        path = folder / context.object.boz.script
        if self.external:
            save_scripts()
            link.sdkhome.open_path(path, editor=True)
        else:
            show_script(context, path)
        return {"FINISHED"}


class BOZ_OT_script_clear(Operator):
    bl_idname = "boz.script_clear"
    bl_label = "Remove script"
    bl_description = "Take the script off this object (the file stays)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        obj.boz.script = ""
        for key in [k for k in obj.keys() if k.startswith(convert.PROPERTY_PREFIX)]:
            del obj[key]
        return {"FINISHED"}


class BOZ_OT_script_reload(Operator):
    bl_idname = "boz.script_reload"
    bl_label = "Reload properties"
    bl_description = "Read the script's properties again (after editing it)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sync_all(link.map_scene())
        return {"FINISHED"}


# Prefabs


def _selected_parts(context):
    return [obj for obj in context.selected_objects
            if obj.boz.role in KINDS and not obj.boz.original]


class BOZ_OT_make_prefab(Operator):
    bl_idname = "boz.make_prefab"
    bl_label = "Make prefab"
    bl_description = ("Group the selected models, volumes and prefabs into one prefab: it moves "
                      "as one, can have a script, and Save as new prefab puts it in the library")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_selected_parts(context))

    def execute(self, context):
        from mathutils import Matrix, Vector

        parts = _selected_parts(context)
        if len(parts) == 1 and convert.is_prefab_group(parts[0]):
            self.report({"WARNING"}, f"{parts[0].name} is a prefab already: select more objects "
                                     "to group with it")
            return {"CANCELLED"}
        skipped = len([o for o in context.selected_objects if o.boz.original])
        matrices = {obj: convert.world_matrix(obj) for obj in parts}
        points = [matrices[obj].translation for obj in parts]
        centre = Vector((sum(p.x for p in points) / len(points), sum(p.y for p in points) / len(points),
                         min(p.z for p in points)))
        parents = {obj.parent for obj in parts}
        outer = parents.pop() if len(parents) == 1 else None
        prefab = bpy.data.objects.new("Prefab", None)
        prefab.empty_display_type = "CUBE"
        prefab.empty_display_size = 20.0
        prefab.show_name = True
        prefab.boz.role = "prefab"
        collection = convert.map_collection(link.map_scene())
        collection.objects.link(prefab)
        if convert.is_prefab_group(outer):
            prefab.parent = outer
            prefab.matrix_parent_inverse = Matrix.Identity(4)
            prefab.matrix_basis = convert.world_matrix(outer).inverted() @ Matrix.Translation(centre)
            prefab.boz.part_name = "Prefab"
        else:
            prefab.location = centre
        inverse = convert.world_matrix(prefab).inverted()
        for obj in parts:
            obj.parent = prefab
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = inverse @ matrices[obj]
            convert.move_to(obj, collection)   # parts sit with their prefab in the outliner
            if not obj.boz.part_name:
                obj.boz.part_name = convert.clean_name(convert._without_suffix(obj.name))
        convert.sync_part_names(link.map_scene())
        for other in context.selected_objects:
            other.select_set(False)
        prefab.select_set(True)
        context.view_layer.objects.active = prefab
        message = f"Grouped {len(parts)} objects into {prefab.name}; rename it in its panel"
        if skipped:
            message += f" ({skipped} from the original map stay where they are)"
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BOZ_OT_ungroup_prefab(Operator):
    bl_idname = "boz.ungroup_prefab"
    bl_label = "Ungroup"
    bl_description = "Take the prefab apart: its parts stay where they are"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return convert.is_prefab_group(context.object)

    def execute(self, context):
        from mathutils import Matrix

        prefab = context.object
        outer = prefab.parent
        for child in list(prefab.children):
            matrix = convert.world_matrix(child)
            child.parent = outer
            child.matrix_parent_inverse = Matrix.Identity(4)
            child.matrix_basis = (convert.world_matrix(outer).inverted() @ matrix) if outer \
                else matrix
            if not convert.is_prefab_group(outer):
                convert.strip_part_name(child)
                child.boz.part_name = ""
        bpy.data.objects.remove(prefab)
        return {"FINISHED"}


class BOZ_OT_save_prefab(Operator):
    bl_idname = "boz.save_prefab"
    bl_label = "Save as new prefab"
    bl_description = ("Put this prefab in the project's prefab library (My prefabs): placing it "
                      "makes independent copies")
    bl_options = {"REGISTER"}

    name: StringProperty(name="Prefab name")
    replace: BoolProperty(name="Replace the prefab of that name", default=False)

    @classmethod
    def poll(cls, context):
        return convert.is_prefab_group(context.object)

    def invoke(self, context, event):
        self.name = convert.object_name(context.object)
        self.replace = False
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        root = link.project_root()
        if root is None:
            self.report({"ERROR"}, "Open this map from the SDK launcher first")
            return {"CANCELLED"}
        name = convert.clean_name(self.name)
        if name in world.library_names(root / "source") and not self.replace:
            self.report({"ERROR"}, f"There is a prefab called {name} already: tick Replace, or "
                                   "pick another name")
            return {"CANCELLED"}
        try:
            prefab, meshes = convert.prefab_of(context.object)
            prefab.name = name
            world.save_prefab(root / "source", prefab, meshes)
        except (ValueError, world.WorldError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        rebuild_library()
        self.report({"INFO"}, f"Saved {name}: drag it from My prefabs in the asset browser")
        return {"FINISHED"}


def place_library_prefab(scene, name: str, position, rotation=(0.0, 0.0, 0.0, 1.0)):
    """A copy of the library prefab *name* at *position* (game axes); None when it is missing."""
    root = link.project_root()
    if root is None or not name:
        return None
    try:
        prefab, meshes = world.load_prefab(root / "source", name)
    except world.WorldError as exc:
        link.append_log(f"check {exc}")
        return None
    folder = root / "source" / "prefabs" / name
    data = {mesh.name: convert._mesh_data(mesh, folder, mesh.name) for mesh in meshes}
    prefab.position, prefab.rotation = tuple(position), tuple(rotation)
    obj = convert.prefab_object(prefab, scene.boz.base, scene, data)
    sync_all(scene)
    return obj


def rebuild_library() -> None:
    from . import prefab_library
    prefab_library.rebuild(link.project_root())


class BOZ_OT_place_prefab(Operator):
    bl_idname = "boz.place_prefab"
    bl_label = "Place"
    bl_description = "Place a copy of this prefab at the 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    def execute(self, context):
        position = convert.blender_scene.from_blender(tuple(link.map_scene().cursor.location))
        obj = place_library_prefab(link.map_scene(), self.name, position)
        if obj is None:
            self.report({"ERROR"}, f"There is no prefab {self.name} in the library")
            return {"CANCELLED"}
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class BOZ_OT_delete_library_prefab(Operator):
    bl_idname = "boz.delete_library_prefab"
    bl_label = "Delete from the library"
    bl_description = "Remove this prefab from My prefabs (copies already placed stay)"
    bl_options = {"REGISTER"}

    name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        import shutil
        root = link.project_root()
        if root is None:
            return {"CANCELLED"}
        folder = root / "source" / "prefabs"
        (folder / f"{self.name}.json").unlink(missing_ok=True)
        if (folder / self.name).is_dir():
            shutil.rmtree(folder / self.name)
        rebuild_library()
        return {"FINISHED"}


class BOZ_MT_prefab_library(bpy.types.Menu):
    bl_idname = "BOZ_MT_prefab_library"
    bl_label = "Prefab library"

    def draw(self, context):
        layout = self.layout
        root = link.project_root()
        names = world.library_names(root / "source") if root else []
        if not names:
            layout.label(text="Empty: select a prefab, then Save as new prefab")
            return
        layout.label(text="Drag prefabs from My prefabs in the asset browser")
        layout.separator()
        for name in names:
            layout.operator(BOZ_OT_delete_library_prefab.bl_idname, text=f"Delete {name}",
                            icon="TRASH").name = name


# The object's Game panel


def _draw_game_settings(layout, obj) -> None:
    """A game prefab's settings (cost, needs power, weapon, chalk, ...)."""
    key = obj.get("boz_piece")
    try:
        piece = toolkit.piece(key) if key else None
    except KeyError:
        piece = None
    if piece is None:
        return
    box = layout.box()
    box.label(text="Settings", icon="TOOL_SETTINGS")
    for setting in piece.settings:
        name = convert.FIELD_PREFIX + setting.key
        if setting.kind == "weapon":
            row = box.row()
            row.label(text=f"{setting.label}: {obj.get(name, '?')}")
            row.operator(link.BOZ_OT_choose_weapon.bl_idname, text="Choose…")
        elif setting.kind == "weapons":
            from . import weapons_tab
            chosen = [n for n in str(obj.get(name, "")).split(",") if n]
            row = box.row()
            row.label(text=f"{setting.label}: {len(chosen)} weapons" if chosen else
                      f"{setting.label}: the game's")
            row.operator(weapons_tab.BOZ_OT_box_pool.bl_idname, text="Edit…")
        elif setting.kind == "chalk":
            if obj.boz.original:
                continue   # shipped chalk is painted on the room's wall
            mode = str(obj.get(name, ""))
            box.label(text=f"Chalk: {({'': 'Automatic', 'none': 'None'}).get(mode, mode)}")
            row = box.row(align=True)
            row.operator(link.BOZ_OT_chalk.bl_idname, text="Automatic", depress=mode == "").mode = ""
            row.operator(link.BOZ_OT_chalk.bl_idname, text="None", depress=mode == "none").mode = "none"
            row.operator(link.BOZ_OT_chalk_image.bl_idname, text="Image…",
                         depress=mode not in ("", "none"))
        elif name in obj:
            box.prop(obj, f'["{name}"]', text=setting.label)
    if obj.boz.original and obj.get(convert.FIELD_PREFIX + toolkit.WEAPON_FIELD):
        box.label(text="Its chalk drawing is painted on the wall and stays", icon="INFO")


def _draw_script(layout, obj) -> None:
    box = layout.box()
    box.label(text="Script", icon="SCRIPT")
    if not obj.boz.script:
        row = box.row(align=True)
        row.operator(BOZ_OT_script_new.bl_idname, text="New", icon="ADD")
        row.operator(BOZ_OT_script_pick.bl_idname, text="Pick…", icon="FILEBROWSER")
        return
    row = box.row(align=True)
    row.operator(BOZ_OT_script_open.bl_idname, text=obj.boz.script, icon="TEXT")
    row.operator(BOZ_OT_script_open.bl_idname, text="", icon="URL").external = True
    row.operator(BOZ_OT_script_reload.bl_idname, text="", icon="FILE_REFRESH")
    row.operator(BOZ_OT_script_clear.bl_idname, text="", icon="X")
    props = declared(obj)
    if not props:
        box.label(text="It declares no properties (---@property lines)")
    for prop in props:
        key = convert.PROPERTY_PREFIX + prop.name
        if key in obj:
            box.prop(obj, f'["{key}"]', text=prop.name.replace("_", " ").capitalize())
        else:
            box.label(text=f"{prop.name}: press Reload properties", icon="ERROR")


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
        label, icon = kind_label(obj)
        layout.label(text=label, icon=icon)
        if settings.role == "reference" or settings.role not in KINDS:
            if obj.get("boz_chalk"):
                layout.label(text="The wall buy's chalk (set on the wall buy)")
            return
        if settings.original:
            layout.label(text=f"Name: {convert.object_name(obj)}")
        else:
            layout.prop(obj, "name", text="Name")
        if convert.is_part(obj):
            layout.prop(settings, "part_name")
            layout.label(text=f"In the game: {convert.object_name(obj.parent)}."
                              f"{convert.object_name(obj)}")

        if settings.role == "model":
            if obj.get("boz_asset"):
                users = obj.data.users if obj.data else 1
                layout.label(text=f"Asset {obj['boz_asset']}" +
                             (f": {users} copies" if users > 1 else "") +
                             " (change it in the Assets tab)", icon="ASSET_MANAGER")
            elif settings.source:
                layout.operator(link.BOZ_OT_make_editable.bl_idname, icon="MESH_DATA")
            else:
                users = obj.data.users if obj.data else 1
                layout.label(text=f"Mesh {convert.mesh_name(obj)}" +
                             (f": {users} copies share it" if users > 1 else " (Alt+D copies share it)"))
                layout.prop(settings, "double_sided")
            layout.prop(settings, "collision", expand=True)
            if settings.collision != "none":
                layout.prop(settings, "shape", expand=True)
                if settings.shape == "box":
                    layout.prop(settings, "padding")
        elif settings.role == "volume":
            layout.prop(settings, "volume", expand=True)
            layout.prop(settings, "who", expand=True)
            layout.prop(settings, "once")
            if settings.volume == "use":
                layout.prop(settings, "prompt")
                layout.prop(settings, "cost")
            size = tuple(round(c * world.TRIGGER_SIZE) for c in obj.scale)
            layout.label(text=f"Size {size[0]} x {size[1]} x {size[2]} cm (scale it)")
        elif settings.role == "prefab" and not settings.source:
            parts = [child for child in obj.children if child.boz.role in KINDS]
            layout.label(text=f"{len(parts)} parts: " + ", ".join(
                child.boz.part_name or child.name for child in parts[:6]) +
                ("…" if len(parts) > 6 else ""))
            row = layout.row(align=True)
            row.operator(BOZ_OT_save_prefab.bl_idname, icon="FILE_TICK")
            row.operator(BOZ_OT_ungroup_prefab.bl_idname, icon="X")
            if obj.get("boz_library"):
                layout.label(text=f"Placed from the library: {obj['boz_library']}")
        else:
            if settings.original:
                box = layout.box()
                box.label(text=obj.get("boz_description") or "One of the base level's entities",
                          icon="WORLD")
                changed, moved = convert._base_changes(obj)
                box.label(text="Changed in this map" if changed or moved or obj.get("boz_custom_model")
                          else "As the level has it")
                box.label(text="Delete (X) takes it out of the map; Shift+D adds a copy")
                box.operator(link.BOZ_OT_reset_base.bl_idname, icon="LOOP_BACK")
            _draw_game_settings(layout, obj)
            if obj.get("boz_custom_model") or obj.get("boz_game_model"):
                box = layout.box()
                box.label(text="Draws your mesh; works as before" if obj.get("boz_custom_model")
                          else "Draws a game model you picked; works as before", icon="MESH_DATA")
                box.operator(link.BOZ_OT_game_model.bl_idname, icon="LOOP_BACK")
            elif obj.type == "MESH" and not convert.is_marker(obj):
                layout.operator(link.BOZ_OT_make_editable.bl_idname, text="Edit its model",
                                icon="MESH_DATA")

        if settings.role in ("model", "prefab"):
            box = layout.box()
            box.label(text="When the level starts", icon="PLAY")
            row = box.row()
            row.prop(settings, "start_visible")
            row.prop(settings, "start_collision")
            if not settings.original:
                box.prop(settings, "blocks")
                if settings.blocks and settings.role == "model":
                    box.prop(settings, "block_margin")
        _draw_script(layout, obj)


addon_keymaps: list = []


def register_keys() -> None:
    config = bpy.context.window_manager.keyconfigs.addon
    if config is None:
        return
    keymap = config.keymaps.new(name="Object Mode", space_type="EMPTY")
    addon_keymaps.append((keymap, keymap.keymap_items.new(BOZ_OT_make_prefab.bl_idname, "G",
                                                          "PRESS", ctrl=True)))
    addon_keymaps.append((keymap, keymap.keymap_items.new(BOZ_OT_ungroup_prefab.bl_idname, "G",
                                                          "PRESS", ctrl=True, alt=True)))


def draw_object_menu(self, context):
    self.layout.separator()
    self.layout.operator(BOZ_OT_make_prefab.bl_idname, icon="OUTLINER_OB_EMPTY")
    self.layout.operator(BOZ_OT_ungroup_prefab.bl_idname)


CLASSES = (BOZ_OT_script_new, BOZ_OT_script_pick, BOZ_OT_script_open, BOZ_OT_script_clear,
           BOZ_OT_script_reload, BOZ_OT_make_prefab, BOZ_OT_ungroup_prefab, BOZ_OT_save_prefab,
           BOZ_OT_place_prefab, BOZ_OT_delete_library_prefab, BOZ_MT_prefab_library,
           BOZ_PT_object)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object.append(draw_object_menu)
    register_keys()
    if not bpy.app.background:
        bpy.app.timers.register(watch_browser, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(watch_browser):
        bpy.app.timers.unregister(watch_browser)
    for keymap, item in addon_keymaps:
        keymap.keymap_items.remove(item)
    addon_keymaps.clear()
    bpy.types.VIEW3D_MT_object.remove(draw_object_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
