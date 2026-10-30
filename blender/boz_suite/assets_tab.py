"""The Assets tab: your own models and textures, made game-ready.

Import a high-quality model (.blend, FBX, glTF, OBJ) as a Prop or a Weapon; Make game version
reduces it to the preset's triangle budget and texture size in a background Blender
(asset_build.py, bozkit.assets). The tab has a scene of its own (link.ASSET_SCENE) showing the
high-quality model, the game version, or both side by side, the game version drawn the way the
game draws it. Game checks list what blocks the build and what only warns, with fixes. A
finished asset is placed in the map from here, from Add → My assets, or from the palette's My
assets catalog; a placed asset is a model that references it (world.Model.asset), so making it
again updates every copy.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from . import link

from ._bozkit import assets, blender_scene

WORKSPACE = "Assets"
GAME_OBJECT = "BOZ asset game"
HIGH_ROOT = "BOZ asset high"
VIEW_KEY = "boz_asset_view"          # Assets workspace: its viewport is set up
_state: dict = {"process": None, "building": None, "refreshing": False, "frame": False,
                "shown": None}


def defs() -> list:
    source = link.source_dir()
    if source is None:
        return []
    out = []
    for path in sorted(assets.assets_dir(source).glob("*.json")) if assets.assets_dir(source).is_dir() else []:
        try:
            out.append(assets.load_def(source, path.stem))
        except assets.AssetError as exc:
            print(f"boz_suite: {exc}")
    return out


def asset_def(name: str):
    try:
        return assets.load_def(link.source_dir(), name)
    except (assets.AssetError, TypeError):
        return None


def stats_of(name: str) -> dict:
    source = link.source_dir()
    return assets.load_stats(source, name) if source else {}


class BOZ_AssetItem(PropertyGroup):
    label: StringProperty()
    kind: StringProperty()
    status: StringProperty()   # none, ok, warnings, errors, building


def _settings_changed(self, context):
    if _state["refreshing"]:
        return
    item = selected()
    asset = asset_def(item.name) if item else None
    if asset is None:
        return
    settings = link.map_scene().boz_asset_settings
    asset.kind = settings.kind
    asset.preset = settings.preset
    asset.triangles = settings.triangles if settings.custom_budget else 0
    asset.texture_size = int(settings.texture_size)
    asset.unit = "" if settings.unit == "auto" else settings.unit
    asset.bake_normals = settings.bake_normals
    assets.save_def(link.source_dir(), asset)
    refresh_list(context, keep=item.name)


TEXTURE_ITEMS = [("0", "Preset", "The preset's texture size")] + \
    [(str(side), f"{side}", f"Textures at most {side} x {side}") for side in (128, 256, 512, 1024)]
UNIT_ITEMS = [("auto", "Guess", "Guessed from its size (a weapon 30-200 cm long, a prop 10-600 cm)")] + \
    [(unit, {"cm": "Centimetres", "m": "Metres", "inch": "Inches", "mm": "Millimetres"}[unit], "")
     for unit in assets.UNITS]


class BOZ_AssetSettings(PropertyGroup):
    kind: EnumProperty(name="Kind", update=_settings_changed, items=[
        ("prop", "Prop", "A model to place in maps"),
        ("weapon", "Weapon", "A gun: its bones and parts (magazine, ...) are kept for the "
                             "Weapons tab")])
    preset: EnumProperty(name="Preset", update=_settings_changed, items=[
        (key, assets.PRESET_LABELS[key],
         ", ".join(f"{kind}: {tris} triangles, {side} textures"
                   for kind, (tris, side) in assets.PRESETS[key].items()))
        for key in assets.PRESETS])
    custom_budget: BoolProperty(name="Own budget", update=_settings_changed,
                                description="Set the triangle budget yourself")
    triangles: IntProperty(name="Triangles", min=50, max=20000, default=1500,
                           update=_settings_changed, description="The most triangles it may have")
    texture_size: EnumProperty(name="Textures", items=TEXTURE_ITEMS, update=_settings_changed)
    unit: EnumProperty(name="Source unit", items=UNIT_ITEMS, update=_settings_changed,
                       description="The unit the source file was made in")
    bake_normals: BoolProperty(name="Bake normal map", default=True, update=_settings_changed,
                               description="The game has no normal maps: shade their detail "
                                           "into the colour")


def selected():
    scene = link.map_scene()
    index = scene.boz_asset_index
    return scene.boz_assets[index] if 0 <= index < len(scene.boz_assets) else None


def refresh_list(context=None, keep: str | None = None) -> None:
    scene = link.map_scene()
    keep = keep or (selected().name if selected() else None)
    _state["refreshing"] = True
    try:
        scene.boz_assets.clear()
        for asset in defs():
            item = scene.boz_assets.add()
            item.name = asset.name
            item.kind = asset.kind
            stats = stats_of(asset.name)
            if _state["building"] == asset.name:
                item.status = "building"
            elif not stats:
                item.status = "none"
            else:
                item.status = "errors" if stats.get("errors") else \
                    "warnings" if stats.get("warnings") else "ok"
            item.label = f"{asset.name} ({asset.kind})"
        names = [i.name for i in scene.boz_assets]
        if keep in names:
            scene.boz_asset_index = names.index(keep)
        elif scene.boz_asset_index >= len(names):
            scene.boz_asset_index = max(0, len(names) - 1)
    finally:
        _state["refreshing"] = False
    refresh_settings()


def refresh_settings() -> None:
    item = selected()
    asset = asset_def(item.name) if item else None
    if asset is None:
        return
    settings = link.map_scene().boz_asset_settings
    _state["refreshing"] = True
    try:
        settings.kind = asset.kind
        settings.preset = asset.preset
        settings.custom_budget = bool(asset.triangles)
        settings.triangles = asset.budget()
        settings.texture_size = str(asset.texture_size) if str(asset.texture_size) in \
            {i[0] for i in TEXTURE_ITEMS} else "0"
        settings.unit = asset.unit or "auto"
        settings.bake_normals = asset.bake_normals
    finally:
        _state["refreshing"] = False


def _selected_changed(self, context):
    if _state["refreshing"]:
        return
    refresh_settings()
    show_asset(context)


def _bozkit_dir() -> Path:
    here = Path(__file__).resolve().parent
    vendor = here / "_vendor"
    return vendor if (vendor / "bozkit").is_dir() else here.parents[1] / "tools" / "bozkit"


def _command(name: str) -> list:
    here = Path(__file__).resolve().parent
    return [bpy.app.binary_path, "-b", "--factory-startup", "--python", str(here / "asset_build.py"),
            "--", str(_bozkit_dir()), str(link.project_root()), name]


def make(name: str, wait: bool = False) -> bool:
    """Make *name*'s game version in a background Blender; False when one is running. *wait*
    (tests, the background editor) runs it to the end here."""
    if _state["process"] is not None:
        return False
    link.append_log(f"asset {name}: making the game version")
    _state["building"] = name
    if wait or bpy.app.background:
        result = subprocess.run(_command(name), capture_output=True, text=True, timeout=1800,
                                encoding='utf-8', errors='replace')
        _finish(name, result.stdout + result.stderr)
        return True
    _state["process"] = subprocess.Popen(_command(name), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True,
                                         encoding='utf-8', errors='replace')
    refresh_list()
    bpy.app.timers.register(_poll, first_interval=0.5)
    return True


def _poll():
    process = _state["process"]
    if process is None:
        return None
    if process.poll() is None:
        return 0.5
    output = process.stdout.read() if process.stdout else ""
    _state["process"] = None
    _finish(_state["building"], output)
    return None


def _finish(name: str, output: str) -> None:
    _state["building"] = None
    for line in output.splitlines():
        if line.startswith("BOZ_ASSET_LOG "):
            link.append_log(f"asset {name}: {line[len('BOZ_ASSET_LOG '):]}")
    if "BOZ_ASSET_OK " in output:
        stats = json.loads(output.split("BOZ_ASSET_OK ", 1)[1].splitlines()[0])
        link.append_log(f"asset {name}: {stats['triangles']} triangles (from {stats['high_triangles']}), "
                        f"{len(stats['textures'])} textures, "
                        f"{len(stats['errors'])} problems, {len(stats['warnings'])} warnings")
        for problem in stats["errors"]:
            link.append_log(f"check {name}: {problem}")
    else:
        reason = output.split("BOZ_ASSET_FAILED ", 1)[1].strip() if "BOZ_ASSET_FAILED " in output \
            else (output.strip().splitlines() or ["Blender stopped"])[-1]
        link.append_log(f"asset {name}: could not be made: {reason}")
    try:
        refresh_list(keep=name)
        update_placed(name)
        if selected() is not None and selected().name == name:
            show_asset(bpy.context, force=True)
        rebuild_palette()
    except (ReferenceError, RuntimeError, AttributeError) as exc:
        print(f"boz_suite: after making {name}: {exc}")


def _images(name: str) -> list:
    folder = assets.game_dir(link.source_dir(), name) / "textures"
    out = []
    for index in range(len(list(folder.glob("*.png"))) if folder.is_dir() else 0):
        path = folder / f"{index}.png"
        image = bpy.data.images.load(str(path), check_existing=True)
        image.reload()
        image.name = f"BOZ asset {name} {index}"
        out.append(image)
    return out


def build_mesh(name: str, data_name: str, unit_scale: float = assets.ASSET_SCALE):
    """New mesh data for *name*'s game version, in centimetres (or its stored units times
    *unit_scale*), with game materials; None without a game version."""
    from . import convert
    try:
        model, _textures = assets.load_game(link.source_dir(), name)
    except (assets.AssetError, TypeError):
        return None
    data = bpy.data.meshes.new(data_name)
    data.from_pydata([tuple(c * unit_scale for c in blender_scene.to_blender(v))
                      for v in model.vertices], [], [tuple(t) for t in model.triangles])
    layer = data.uv_layers.new(name="UVMap")
    corners = [0] * len(data.loops)
    data.loops.foreach_get("vertex_index", corners)
    layer.data.foreach_set("uv", [c for v in corners for c in blender_scene.uv_to_blender(model.uvs[v])])
    for index, image in enumerate(_images(name)):
        material = bpy.data.materials.get(f"BOZ asset {name} {index}")
        if material is None:
            material = convert.material_for(f"BOZ asset {name} {index}", image)
        else:
            material.node_tree.nodes["BOZ Primary"].image = image
        data.materials.append(material)
    if model.materials:
        data.polygons.foreach_set("material_index", model.materials)
    data.update()
    data["boz_asset"] = name
    return data


def asset_mesh(name: str):
    """The shared mesh placed copies of *name* use (made when missing)."""
    data = bpy.data.meshes.get(f"BOZ asset {name}")
    return data if data is not None else build_mesh(name, f"BOZ asset {name}")


def update_placed(name: str) -> None:
    """After making an asset again: its placed copies get the new game version."""
    old = bpy.data.meshes.get(f"BOZ asset {name}")
    if old is None:
        return
    new = build_mesh(name, f"BOZ asset {name} new")
    if new is None:
        return
    for obj in bpy.data.objects:
        if obj.data == old:
            obj.data = new
    bpy.data.meshes.remove(old)
    new.name = f"BOZ asset {name}"


def placed(name: str) -> list:
    scene = link.map_scene()
    return [obj for obj in scene.objects if obj.get("boz_asset") == name]


def place_asset(scene, name: str, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0, 1.0)):
    """A model of *name* in the map at *position* (game axes, centimetres)."""
    from . import convert
    from ._bozkit import world
    data = asset_mesh(name)
    if data is None:
        return None
    taken = {o.name for o in scene.objects}
    label, number = name, 1
    while label in taken:
        number += 1
        label = f"{name}_{number}"
    model = world.Model(label, tuple(position), tuple(rotation), asset=name,
                        collision="solid", shape="box")
    return convert.model_object(model, scene, data=data)


def view_scene():
    scene = bpy.data.scenes.get(link.ASSET_SCENE)
    if scene is None:
        scene = bpy.data.scenes.new(link.ASSET_SCENE)
        scene.view_settings.view_transform = "Standard"
        world_data = bpy.data.worlds.get(link.ASSET_SCENE) or bpy.data.worlds.new(link.ASSET_SCENE)
        world_data.color = (0.18, 0.18, 0.2)
        scene.world = world_data
    return scene


def _clear_view(view) -> None:
    for obj in list(view.objects):
        data = obj.data
        bpy.data.objects.remove(obj)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Armature) and data.users == 0:
            bpy.data.armatures.remove(data)


def _load_high(view, asset) -> list:
    """The high-quality source's meshes (and armature) in the view, under one empty that scales
    them from the source's unit to centimetres."""
    path = link.project_root() / asset.source
    if not path.is_file():
        return []
    root = bpy.data.objects.new(HIGH_ROOT, None)
    view.collection.objects.link(root)
    unit = asset.unit or stats_of(asset.name).get("unit") or "cm"
    root.scale = (assets.UNITS[unit],) * 3
    objects = []
    if path.suffix.lower() == ".blend":
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            target.objects = list(source.objects)
        objects = [o for o in target.objects if o is not None]
        for obj in objects:
            view.collection.objects.link(obj)
    else:
        from . import shapes
        module, op = shapes.IMPORTERS[path.suffix.lower()]
        before = set(bpy.data.objects)
        window = bpy.context.window
        try:
            with bpy.context.temp_override(scene=view, collection=view.collection):
                getattr(getattr(bpy.ops, module), op)(filepath=str(path))
        except (RuntimeError, TypeError) as exc:
            print(f"boz_suite: could not show {path.name}: {exc}")
        objects = [o for o in bpy.data.objects if o not in before]
        del window
    wanted = [o for o in objects if o.type in ("MESH", "ARMATURE")
              and (o.type == "ARMATURE" or not asset.objects or o.name in asset.objects)]
    for obj in objects:
        if obj not in wanted:
            bpy.data.objects.remove(obj)
    for obj in wanted:
        obj["boz_preview"] = "asset_high"
        obj.hide_select = True
        if obj.parent is None:
            obj.parent = root
    return wanted


def show_asset(context, force: bool = False) -> str:
    """Show the selected asset in the Assets tab's scene: its high-quality model and game
    version (an editable copy: Save edits writes it back)."""
    item = selected()
    view = view_scene()
    key = item.name if item else None
    if not force and _state["shown"] == key and view.objects:
        apply_view_mode(context)
        return ""
    _clear_view(view)
    _state["shown"] = key
    if item is None:
        return ""
    asset = asset_def(item.name)
    if asset is None:
        return ""
    _load_high(view, asset)
    data = build_mesh(item.name, f"{GAME_OBJECT} {item.name}")
    if data is not None:
        obj = bpy.data.objects.new(GAME_OBJECT, data)
        view.collection.objects.link(obj)
        obj["boz_preview"] = "asset_game"
        obj["boz_asset"] = item.name
        images = [m.node_tree.nodes["BOZ Primary"].image for m in data.materials
                  if m and m.use_nodes and "BOZ Primary" in m.node_tree.nodes]
        _show_texture(context, images[0] if images else None)
    _state["frame"] = True
    for window in context.window_manager.windows:
        if window.workspace.name == WORKSPACE:
            window.workspace[VIEW_KEY] = False
    apply_view_mode(context)
    return item.name


def _show_texture(context, image) -> None:
    for window in context.window_manager.windows:
        if window.workspace.name != WORKSPACE:
            continue
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image


def _bounds(objects):
    from mathutils import Vector
    points = [o.matrix_world @ Vector(c) for o in objects if o.type == "MESH" for c in o.bound_box]
    if not points:
        return Vector(), Vector()
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low, high


def apply_view_mode(context) -> None:
    """High quality, Game or both side by side."""
    view = bpy.data.scenes.get(link.ASSET_SCENE)
    if view is None:
        return
    mode = context.window_manager.boz_asset_view
    game = view.objects.get(GAME_OBJECT)
    high = [o for o in view.objects if o.get("boz_preview") == "asset_high"]
    root = view.objects.get(HIGH_ROOT)
    if game is not None:
        game.hide_viewport = mode == "HIGH"
    for obj in high:
        obj.hide_viewport = mode == "GAME"
    if root is not None:
        root.location = (0.0, 0.0, 0.0)
        if mode == "BOTH" and game is not None:
            low, high_corner = _bounds([game])
            root.location.y = (high_corner.y - low.y) * 1.3 + 10.0
    view.update_tag()


def setup_view(window) -> bool:
    """The Assets tab's window shows its own scene, pinned."""
    view = bpy.data.scenes.get(link.ASSET_SCENE)
    if view is None:
        return False
    if window.scene != view:
        window.scene = view
    workspace = window.workspace
    if not workspace.use_pin_scene:
        workspace.use_pin_scene = True
    frame = _state.pop("frame", False)
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.use_local_collections = False
        space.clip_start, space.clip_end = 0.5, 100000.0
        space.shading.type = "MATERIAL"
        space.overlay.show_floor = True
        if frame:
            from mathutils import Euler
            import math
            objects = [o for o in view.objects if o.type == "MESH" and not o.hide_viewport]
            low, high = _bounds(objects)
            region = space.region_3d
            region.view_perspective = "PERSP"
            region.view_location = (low + high) / 2
            region.view_distance = max((high - low).length * 1.1, 10.0)
            region.view_rotation = Euler((math.radians(70), 0.0, math.radians(35))).to_quaternion()
        area.tag_redraw()
    workspace[VIEW_KEY] = True
    return True


def leave_view(window) -> None:
    if window.scene is not None and window.scene.name == link.ASSET_SCENE:
        window.scene = link.map_scene()


def refresh_view(window) -> None:
    """The tabs' timer, while the Assets tab is on screen."""
    if not window.workspace.get(VIEW_KEY) or window.scene.name != link.ASSET_SCENE:
        if _state["shown"] is None and selected() is not None:
            show_asset(bpy.context)
        else:
            view_scene()
        setup_view(window)


def _clean_name(text: str) -> str:
    name = "".join(c if c.isalnum() and c.isascii() else "_" for c in text).strip("_") or "asset"
    if not name[0].isalpha():
        name = "a_" + name
    return name[:40]


class BOZ_OT_asset_import(Operator):
    bl_idname = "boz.asset_import"
    bl_label = "Import…"
    bl_description = ("Bring in a high-quality model (.blend, FBX, glTF, OBJ) and make its game "
                      "version")

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.blend;*.fbx;*.glb;*.gltf;*.obj", options={"HIDDEN"})
    kind: EnumProperty(name="Kind", items=[("prop", "Prop", "A model to place in maps"),
                                           ("weapon", "Weapon", "A gun (its bones are kept)")])
    preset: EnumProperty(name="Preset", items=[(k, assets.PRESET_LABELS[k], "") for k in assets.PRESETS])
    name: StringProperty(name="Name", description="The asset's name (empty: from the file)")

    def invoke(self, context, event):
        if link.project_root() is None:
            self.report({"ERROR"}, "Open a project first")
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = link.project_root()
        path = Path(self.filepath)
        if path.suffix.lower() not in assets.SOURCE_TYPES or not path.is_file():
            self.report({"ERROR"}, "Pick a .blend, .fbx, .glb, .gltf or .obj file")
            return {"CANCELLED"}
        name = _clean_name(self.name or path.stem)
        taken = {a.name.lower() for a in defs()}
        base, number = name, 1
        while name.lower() in taken:
            number += 1
            name = f"{base}_{number}"
        try:
            copy = assets.copy_source(root, name, path)
            assets.save_def(root / "source", assets.AssetDef(name, self.kind, copy, str(path),
                                                             preset=self.preset))
        except (assets.AssetError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        refresh_list(context, keep=name)
        make(name)
        self.report({"INFO"}, f"Imported {name}: making its game version")
        return {"FINISHED"}


class BOZ_OT_asset_make(Operator):
    bl_idname = "boz.asset_make"
    bl_label = "Make game version"
    bl_description = "Reduce the high-quality model and its textures to the budget"

    def invoke(self, context, event):
        item = selected()
        asset = asset_def(item.name) if item else None
        if asset is not None and asset.edited:
            return context.window_manager.invoke_confirm(
                self, event, title="Make it again?",
                message="Your edits to the game version are replaced", confirm_text="Make")
        return self.execute(context)

    def execute(self, context):
        item = selected()
        if item is None:
            return {"CANCELLED"}
        if not make(item.name):
            self.report({"WARNING"}, "An asset is being made: wait for it to finish")
            return {"CANCELLED"}
        return {"FINISHED"}


class BOZ_OT_asset_refresh_source(Operator):
    bl_idname = "boz.asset_refresh_source"
    bl_label = "Refresh from source"
    bl_description = ("Copy the file it was imported from again (to pick up changes, such as a "
                      "magazine added to it) and make the game version again")

    def execute(self, context):
        item = selected()
        asset = asset_def(item.name) if item else None
        if asset is None:
            return {"CANCELLED"}
        original = Path(asset.original)
        if not original.is_file():
            self.report({"ERROR"}, f"{original} is gone: import the file again")
            return {"CANCELLED"}
        try:
            asset.source = assets.copy_source(link.project_root(), asset.name, original)
            asset.edited = False
            assets.save_def(link.source_dir(), asset)
        except (assets.AssetError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _state["shown"] = None
        make(asset.name)
        return {"FINISHED"}


class BOZ_OT_asset_remove(Operator):
    bl_idname = "boz.asset_remove"
    bl_label = "Remove asset"
    bl_description = "Delete the asset from the project (its source copy and game version)"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item = selected()
        if item is None:
            return {"CANCELLED"}
        copies = placed(item.name)
        if copies:
            self.report({"ERROR"}, f"{len(copies)} copies of {item.name} are in the map: delete "
                                   "them first")
            return {"CANCELLED"}
        assets.delete(link.project_root(), item.name)
        _state["shown"] = None
        refresh_list(context)
        show_asset(context, force=True)
        rebuild_palette()
        return {"FINISHED"}


class BOZ_OT_asset_fix(Operator):
    bl_idname = "boz.asset_fix"
    bl_label = "Fix"
    bl_options = {"INTERNAL"}

    fix: StringProperty()

    @classmethod
    def description(cls, context, properties):
        return {"reduce": "Lower the triangle budget by a fifth and make it again",
                "texture": "Halve the texture size and make it again",
                "unit": "Use centimetres as the source unit and make it again"}.get(properties.fix, "")

    def execute(self, context):
        item = selected()
        asset = asset_def(item.name) if item else None
        if asset is None:
            return {"CANCELLED"}
        stats = stats_of(asset.name)
        if self.fix == "reduce":
            asset.triangles = max(50, int(min(asset.budget(), stats.get("triangles", asset.budget())) * 0.8))
        elif self.fix == "texture":
            asset.texture_size = max(64, asset.max_texture() // 2)
        elif self.fix == "unit":
            asset.unit = "cm"
        assets.save_def(link.source_dir(), asset)
        refresh_settings()
        make(asset.name)
        return {"FINISHED"}


class BOZ_OT_asset_save_edits(Operator):
    bl_idname = "boz.asset_save_edits"
    bl_label = "Save edits"
    bl_description = ("Keep your changes to the game version shown here (bone weights follow the "
                      "nearest original vertex)")

    def execute(self, context):
        item = selected()
        view = bpy.data.scenes.get(link.ASSET_SCENE)
        obj = view.objects.get(GAME_OBJECT) if view else None
        if item is None or obj is None:
            return {"CANCELLED"}
        try:
            save_edits(item.name, obj)
        except (assets.AssetError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        refresh_list(context, keep=item.name)
        update_placed(item.name)
        self.report({"INFO"}, f"Saved your edits to {item.name}")
        return {"FINISHED"}


def save_edits(name: str, obj) -> None:
    """Write the view's game-version object back as *name*'s game version."""
    from mathutils import kdtree
    source = link.source_dir()
    old, textures = assets.load_game(source, name)
    data = obj.data
    data.calc_loop_triangles()
    uv_layer = data.uv_layers.active
    tree = None
    if old.weights:
        tree = kdtree.KDTree(len(old.vertices))
        for index, v in enumerate(old.vertices):
            tree.insert(blender_scene.to_blender(v), index)
        tree.balance()
    vertices, uvs, triangles, faces, weights, index = [], [], [], [], [], {}
    for triangle in data.loop_triangles:
        corners = []
        for loop_index in triangle.loops:
            loop = data.loops[loop_index]
            uv = tuple(uv_layer.data[loop_index].uv) if uv_layer else (0.0, 0.0)
            key = (loop.vertex_index, round(uv[0], 5), round(uv[1], 5), triangle.material_index)
            if key not in index:
                index[key] = len(vertices)
                co = obj.matrix_world @ data.vertices[loop.vertex_index].co
                native = blender_scene.from_blender(tuple(c * assets.ASSET_UNIT for c in co))
                vertices.append(tuple(int(round(c)) for c in native))
                uvs.append(blender_scene.uv_from_blender(uv))
                if tree is not None:
                    _co, nearest, _distance = tree.find(blender_scene.to_blender(vertices[-1]))
                    weights.append(old.weights[nearest])
            corners.append(index[key])
        triangles.append(tuple(corners))
        faces.append(min(triangle.material_index, len(textures) - 1))
    model = assets.GameModel(vertices, uvs, triangles, faces, old.texture_names, old.bones,
                             weights, {})
    asset = assets.load_def(source, name)
    errors, warnings = assets.check(asset, model, textures)
    stats = assets.describe(model, textures)
    previous = assets.load_stats(source, name)
    stats.update({k: previous[k] for k in ("high_triangles", "unit", "length_cm", "materials")
                  if k in previous})
    stats.update({"errors": errors, "warnings": warnings})
    assets.write_game(source, name, model, textures, stats)
    asset.edited = True
    assets.save_def(source, asset)


class BOZ_OT_asset_place(Operator):
    bl_idname = "boz.asset_place"
    bl_label = "Place in map"
    bl_description = "Add a copy of the asset to the map at the 3D cursor (World tab)"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        name = self.name or (selected().name if selected() else "")
        if not name or not assets.has_game(link.source_dir(), name):
            self.report({"ERROR"}, "Make the asset's game version first")
            return {"CANCELLED"}
        scene = link.map_scene()
        position = blender_scene.from_blender(tuple(scene.cursor.location))
        obj = place_asset(scene, name, position)
        if obj is None:
            return {"CANCELLED"}
        for other in scene.objects:
            other.select_set(False)
        self.report({"INFO"}, f"Placed {obj.name} in the map at the 3D cursor (World tab)")
        return {"FINISHED"}


class BOZ_OT_assets_refresh(Operator):
    bl_idname = "boz.assets_refresh"
    bl_label = "Reload assets"
    bl_description = "Read the project's assets again"

    def execute(self, context):
        refresh_list(context)
        show_asset(context, force=True)
        return {"FINISHED"}


class BOZ_MT_my_assets(Menu):
    bl_idname = "BOZ_MT_my_assets"
    bl_label = "My assets"

    def draw(self, context):
        made = [a for a in defs() if assets.has_game(link.source_dir(), a.name)]
        if not made:
            self.layout.label(text="No assets yet: import one in the Assets tab")
        for asset in made:
            self.layout.operator(BOZ_OT_asset_place.bl_idname, text=asset.name,
                                 icon="MESH_MONKEY" if asset.kind == "prop" else "MOD_ARMATURE").name = asset.name


STATUS_ICONS = {"none": "QUESTION", "ok": "CHECKMARK", "warnings": "INFO", "errors": "ERROR",
                "building": "SORTTIME"}


class BOZ_UL_assets(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        layout.label(text=item.label or item.name, icon=STATUS_ICONS.get(item.status, "BLANK1"))


class _AssetsPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == WORKSPACE


class BOZ_PT_assets(_AssetsPanel, Panel):
    bl_idname = "BOZ_PT_assets"
    bl_label = "Assets"

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if link.project_root() is None:
            layout.label(text="Open a project to bring in assets", icon="INFO")
            return
        if not len(scene.boz_assets) and defs():
            layout.operator(BOZ_OT_assets_refresh.bl_idname, text="Show the project's assets",
                            icon="FILE_REFRESH")
            return
        row = layout.row()
        row.template_list("BOZ_UL_assets", "", scene, "boz_assets", scene, "boz_asset_index", rows=5)
        column = row.column(align=True)
        column.operator(BOZ_OT_asset_import.bl_idname, text="", icon="IMPORT")
        column.operator(BOZ_OT_asset_remove.bl_idname, text="", icon="REMOVE")
        column.separator()
        column.operator(BOZ_OT_assets_refresh.bl_idname, text="", icon="FILE_REFRESH")
        layout.operator(BOZ_OT_asset_import.bl_idname, icon="IMPORT")
        if _state["building"]:
            layout.label(text=f"Making {_state['building']}…", icon="SORTTIME")


class BOZ_PT_asset_settings(_AssetsPanel, Panel):
    bl_idname = "BOZ_PT_asset_settings"
    bl_label = "Game version"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and selected() is not None

    def draw_header(self, context):
        self.layout.label(text=selected().name)

    def draw(self, context):
        layout = self.layout
        settings = link.map_scene().boz_asset_settings
        item = selected()
        asset = asset_def(item.name)
        if asset is None:
            layout.label(text="This asset's settings cannot be read", icon="ERROR")
            return
        layout.prop(settings, "kind", expand=True)
        layout.prop(settings, "preset")
        row = layout.row(align=True)
        row.prop(settings, "custom_budget")
        sub = row.row(align=True)
        sub.enabled = settings.custom_budget
        sub.prop(settings, "triangles")
        layout.prop(settings, "texture_size")
        layout.prop(settings, "unit")
        layout.prop(settings, "bake_normals")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.enabled = _state["building"] is None
        row.operator(BOZ_OT_asset_make.bl_idname, icon="MOD_DECIM")
        row = layout.row(align=True)
        row.operator(BOZ_OT_asset_refresh_source.bl_idname, icon="FILE_REFRESH")
        row.operator(BOZ_OT_asset_save_edits.bl_idname, icon="FILE_TICK")
        layout.operator(BOZ_OT_asset_place.bl_idname, icon="OBJECT_ORIGIN").name = item.name
        if asset.edited:
            layout.label(text="The game version has your edits", icon="GREASEPENCIL")
        layout.label(text=f"From {Path(asset.original).name or asset.source}", icon="FILE")


class BOZ_PT_asset_checks(_AssetsPanel, Panel):
    bl_idname = "BOZ_PT_asset_checks"
    bl_label = "Game checks"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and selected() is not None

    def draw(self, context):
        layout = self.layout
        item = selected()
        asset = asset_def(item.name)
        stats = stats_of(item.name)
        if not stats or asset is None:
            layout.label(text="Not made yet: Make game version", icon="INFO")
            return
        column = layout.column(align=True)
        column.label(text=f"Triangles: {stats['triangles']} of {asset.budget()} "
                          f"(from {stats.get('high_triangles', '?')}; stock guns about 1,100)")
        column.label(text=f"Vertices: {stats['vertices']} (the game takes up to {assets.MAX_VERTICES})")
        sizes = ", ".join(f"{w}x{h}" for w, h in stats["textures"])
        column.label(text=f"Textures: {sizes} ({stats['texture_bytes'] / 1048576:.1f} MB)")
        if "length_cm" in stats:
            column.label(text=f"Size: {stats['length_cm']:.0f} cm long (source unit: {stats.get('unit')})")
        if stats.get("bones"):
            column.label(text=f"Bones: {stats['bones']}")
        if not stats["errors"] and not stats["warnings"]:
            layout.label(text="Ready for the game", icon="CHECKMARK")
        for problem in stats["errors"]:
            row = layout.row()
            row.alert = True
            row.label(text=problem, icon="ERROR")
            fix = "reduce" if "vertices" in problem else "unit" if "from its centre" in problem else \
                "texture" if "texture" in problem else ""
            if fix:
                row.operator(BOZ_OT_asset_fix.bl_idname, text="Fix").fix = fix
        for warning in stats["warnings"]:
            row = layout.row()
            row.label(text=warning, icon="INFO")
            fix = "reduce" if "budget" in warning else "texture" if "preset" in warning else ""
            if fix:
                row.operator(BOZ_OT_asset_fix.bl_idname, text="Fix").fix = fix
        if asset.kind == "weapon":
            box = layout.box()
            box.label(text="Parts")
            found = set(stats.get("parts", []))
            for tag, label in assets.WEAPON_PARTS:
                box.label(text=f"{label} ({tag})", icon="CHECKMARK" if label in found else "X")


def draw_view_header(self, context):
    workspace = context.workspace
    if workspace is None or workspace.name != WORKSPACE:
        return
    self.layout.separator()
    self.layout.prop(context.window_manager, "boz_asset_view", expand=True)


def draw_add_menu(self, context):
    if link.project_root() is not None:
        self.layout.menu(BOZ_MT_my_assets.bl_idname, icon="ASSET_MANAGER")


def _view_mode_changed(self, context):
    apply_view_mode(context)
    _state["frame"] = True
    for window in context.window_manager.windows:
        if window.workspace.name == WORKSPACE:
            setup_view(window)


def rebuild_palette() -> None:
    from . import prefab_library
    try:
        prefab_library.rebuild(link.project_root())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"boz_suite: could not update My assets: {exc}")


def on_load() -> None:
    def later():
        try:
            if link.project_root() is not None:
                refresh_list()
        except (AttributeError, RuntimeError):
            pass
        return None
    _state["shown"] = None
    bpy.app.timers.register(later, first_interval=0.6)


CLASSES = (BOZ_AssetItem, BOZ_AssetSettings, BOZ_UL_assets, BOZ_OT_asset_import, BOZ_OT_asset_make,
           BOZ_OT_asset_refresh_source, BOZ_OT_asset_remove, BOZ_OT_asset_fix,
           BOZ_OT_asset_save_edits, BOZ_OT_asset_place, BOZ_OT_assets_refresh, BOZ_MT_my_assets,
           BOZ_PT_assets, BOZ_PT_asset_settings, BOZ_PT_asset_checks)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.boz_assets = CollectionProperty(type=BOZ_AssetItem)
    bpy.types.Scene.boz_asset_index = IntProperty(update=_selected_changed)
    bpy.types.Scene.boz_asset_settings = PointerProperty(type=BOZ_AssetSettings)
    bpy.types.WindowManager.boz_asset_view = EnumProperty(
        name="Show", update=_view_mode_changed, default="BOTH", items=[
            ("HIGH", "High quality", "The model you imported"),
            ("GAME", "Game", "The game version, drawn the way the game draws it"),
            ("BOTH", "Side by side", "Both, next to each other")])
    bpy.types.VIEW3D_HT_header.append(draw_view_header)
    bpy.types.VIEW3D_MT_add.append(draw_add_menu)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_add_menu)
    bpy.types.VIEW3D_HT_header.remove(draw_view_header)
    del bpy.types.WindowManager.boz_asset_view
    del bpy.types.Scene.boz_asset_settings
    del bpy.types.Scene.boz_asset_index
    del bpy.types.Scene.boz_assets
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
