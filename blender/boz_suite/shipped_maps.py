"""The shipped-map tools: import the game's own group files (one, or a level folder) into the
scene, edit them, and write them back to files or into a mod, without a project
(docs/blender-existing-maps.md). The editor's sidebar shows them under Shipped files."""
from __future__ import annotations

import json
import os
import struct
import uuid
from pathlib import Path

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix

from ._bozkit import blender_scene, sdkhome
from . import scene_view as view
from .meshes import SUFFIX, build_mesh, import_result


class BOZ_ShippedSettings(PropertyGroup):
    client_root: StringProperty(
        name="Client folder", subtype="DIR_PATH",
        description="Your BOZ Redux client folder (the one with mods/ and assets/)",
        default=os.environ.get("BOZ_CLIENT", ""))
    mod_id: StringProperty(
        name="Mod", default="developer",
        description="Mod that Save to mod writes and Import level folder can include")
    run_mod: StringProperty(
        name="Test with", default="developer",
        description="Mod that Build & Run asks to start the level (the Developer mod by default; "
                    "it needs the standard library's boz.levels)")


def _settings(context):
    return getattr(context.window_manager, "boz_shipped", None)


def _mod_target(context):
    settings = _settings(context)
    if settings is None or not settings.client_root:
        raise ValueError("set the BOZ Redux client folder under Shipped files first")
    return settings.client_root, settings.mod_id


def _launch_check(context, root: Path) -> str | None:
    """Why the game cannot be started into a level with the test mod, or None."""
    if sdkhome.game_running():
        return "The game is already running; close it first"
    if sdkhome.game_command(root) is None:
        return f"No BOZ Redux client found in {root}"
    runner = _settings(context).run_mod or "developer"
    mod = next((m for m in sdkhome.client_mods(root) if m.id == runner), None)
    if mod is None:
        return f"The test mod '{runner}' is not in {root / 'mods'}"
    if not (mod.folder / "scripts" / "boz" / "levels.lua").is_file():
        return (f"The test mod '{runner}' has no boz.levels; copy the current standard library "
                "into its scripts/boz (the Developer mod has it)")
    if not mod.enabled:
        return f"The test mod '{runner}' is switched off; enable it in the launcher's Mods tab"
    return None


def _launch_level(context, root: Path, level: str) -> str:
    """Start the game straight into *level* with the test mod; returns the status message."""
    settings = _settings(context)
    runner = settings.run_mod or "developer"
    sdkhome.set_mod_setting(root, runner, "autostart_level", level)
    sdkhome.load_last(root, settings.mod_id)
    sdkhome.start_detached(sdkhome.game_command(root), root, root / "boz-log.txt")
    return f"{runner} starts {level}"


class BOZ_OT_import_group(Operator, ImportHelper):
    bl_idname = "boz.import_group"
    bl_label = "Import native group"
    bl_description = "Import editable resources from a BOZ .group.bin without changing the source"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = SUFFIX
    filter_glob: StringProperty(default="*.group.bin", options={"HIDDEN"})
    include_models: BoolProperty(
        name="Local asset models", default=False,
        description="Import reusable local-space CIwModel assets; these are not map placements")
    include_collision: BoolProperty(name="Collision", default=True)
    include_portals: BoolProperty(name="Portals", default=True)
    include_navigation: BoolProperty(name="Navigation connections", default=True)

    def execute(self, context):
        try:
            result = blender_scene.import_groups(
                [self.filepath],
                include_models=self.include_models,
                include_collision=self.include_collision,
                include_portals=self.include_portals,
                include_navigation=self.include_navigation,
            )
            return import_result(self, context, result)
        except (OSError, ValueError, struct.error) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class BOZ_OT_import_level(Operator):
    bl_idname = "boz.import_level"
    bl_label = "Import level folder"
    bl_description = ("Import every group of an extracted level folder (levels/kino), resolving "
                      "models, materials and textures from the shared ingame group")
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})
    include_shared: BoolProperty(
        name="Shared in-game groups", default=True,
        description="Resolve placements from the extracted pack's ingame and weapon groups")
    include_mod: BoolProperty(
        name="Include mod edits", default=True,
        description="Load groups previously saved to your mod instead of the game's copies")
    include_models: BoolProperty(name="Local asset models", default=False)
    include_collision: BoolProperty(name="Collision", default=True)
    include_portals: BoolProperty(name="Portals", default=True)
    include_navigation: BoolProperty(name="Navigation connections", default=True)

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            mod_assets = None
            if self.include_mod:
                settings = _settings(context)
                if settings is not None and settings.client_root and settings.mod_id:
                    mod_assets = blender_scene.mod_assets_folder(settings.client_root,
                                                                 settings.mod_id)
            editable, references = blender_scene.level_groups(self.directory, mod_assets)
            context.scene["boz_level_folder"] = str(Path(self.directory).resolve())
            result = blender_scene.import_groups(
                editable, references if self.include_shared else [],
                include_models=self.include_models,
                include_collision=self.include_collision,
                include_portals=self.include_portals,
                include_navigation=self.include_navigation,
            )
            return import_result(self, context, result)
        except (OSError, ValueError, struct.error) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


def _basis(obj):
    """Native-parent-relative transform of an object, checking it still has its native parent."""
    expected = obj.get("boz_parent_key", "")
    actual = obj.parent.get("boz_key", "") if obj.parent is not None else ""
    if expected != actual:
        raise ValueError(f"{obj.name}: its parent must remain the imported native parent")
    if obj.parent is not None and obj.matrix_parent_inverse != Matrix.Identity(4):
        raise ValueError(f"{obj.name}: re-parenting changed its parent inverse; clear and restore it")
    location, rotation, scale = obj.matrix_basis.decompose()
    return tuple(location), (rotation.x, rotation.y, rotation.z, rotation.w), tuple(scale)


def _face_ints(obj, name):
    """Integer face attribute values, also while the object is in Edit Mode (Blender exposes no
    attribute data on the mesh then, only on the edit BMesh)."""
    if obj.mode == "EDIT":
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        layer = edit_mesh.faces.layers.int.get(name)
        if layer is None or len(edit_mesh.faces) != len(obj.data.polygons):
            return None
        return [face[layer] for face in edit_mesh.faces]
    attribute = obj.data.attributes.get(name)
    if attribute is None or len(attribute.data) != len(obj.data.polygons):
        return None
    values = [0] * len(obj.data.polygons)
    attribute.data.foreach_get("value", values)
    return values


def _object_uvs(obj, native_name, layer_name):
    mesh = obj.data
    native_uvs = mesh.attributes.get(native_name)
    layer = mesh.uv_layers.get(layer_name)
    values = None
    if native_uvs is not None and len(native_uvs.data) == len(mesh.vertices):
        values = [tuple(value.vector) for value in native_uvs.data]
    if layer is not None and len(layer.data) == len(mesh.loops) and len(mesh.loops):
        # Blender can keep a UV layer definition with no loop data after some Edit Mode
        # operations; the point-domain native copy then remains authoritative.
        loop_values = values or [(0.0, 0.0)] * len(mesh.vertices)
        seen = {}
        for loop in mesh.loops:
            uv = blender_scene.uv_from_blender(tuple(layer.data[loop.index].uv))
            if loop.vertex_index in seen and seen[loop.vertex_index] != uv:
                raise ValueError(f"{obj.name}: one native vertex has conflicting loop UVs "
                                 f"in {layer_name}")
            seen[loop.vertex_index] = uv
            loop_values[loop.vertex_index] = uv
        values = loop_values
    return values or []


def _scene_edits(context):
    """One SceneEdit per BOZ object; meshes shared by instances are read once."""
    edits, cache = [], {}
    for obj in context.scene.objects:
        if "boz_kind" not in obj:
            continue
        if obj.get("boz_schema") != blender_scene.SCHEMA:
            raise ValueError(f"{obj.name} was imported by an older add-on; re-import the group")
        kind = obj["boz_kind"]
        if kind in {"badge", "navmesh"}:
            continue
        if obj.mode == "EDIT":
            obj.update_from_editmode()
        location, rotation, scale = _basis(obj)
        geometry = {"vertices": [], "faces": [], "edges": [], "uvs": [], "uvs2": [],
                    "face_materials": []}
        if kind not in {"entity", "shape", "area"}:
            if obj.type != "MESH":
                raise ValueError(f"{obj.name}: native geometry must remain a mesh")
            mesh = obj.data
            if mesh.name not in cache:
                cache[mesh.name] = {
                    "vertices": [tuple(vertex.co) for vertex in mesh.vertices],
                    "faces": [tuple(polygon.vertices) for polygon in mesh.polygons],
                    "edges": [tuple(edge.vertices) for edge in mesh.edges],
                    "uvs": _object_uvs(obj, "boz_native_uv", "UVMap"),
                    "uvs2": (_object_uvs(obj, "boz_native_uv2", "UVMap2")
                             if "boz_native_uv2" in mesh.attributes else []),
                    "face_materials": [polygon.material_index for polygon in mesh.polygons],
                }
            geometry = cache[mesh.name]
        if kind in {"collision", "collision_piece"}:
            triangles = _face_ints(obj, "boz_triangle")
            if triangles is None:
                raise ValueError(f"{obj.name}: collision faces lost their native triangle ids; "
                                 "topology changes are not supported")
            geometry = dict(geometry, collision_triangles=triangles)
        if kind in {"portal", "navigation_connection", "collision_piece"}:
            # Portals and navigation are stored in world space; collision pieces are converted
            # from world space into their collision entity's space by bozkit.
            geometry = dict(geometry, vertices=[tuple(obj.matrix_world @ vertex.co)
                                                for vertex in obj.data.vertices])
        edits.append(blender_scene.SceneEdit(
            kind=kind,
            class_hash=int(obj["boz_class_hash"], 0),
            resource_hash=int(obj["boz_resource_hash"], 0),
            resource_index=int(obj["boz_resource_index"]),
            front_sector=obj.get("boz_front_sector", ""),
            back_sector=obj.get("boz_back_sector", ""),
            location=location, rotation=rotation, scale=scale,
            instance_resource_hash=(int(obj["boz_instance_resource_hash"], 0)
                                    if "boz_instance_resource_hash" in obj else None),
            instance_resource_index=obj.get("boz_instance_resource_index"),
            source_group=obj.get("boz_source_group", ""),
            instance_source_group=obj.get("boz_instance_source_group", ""),
            instance_path=tuple(int(value) for value in
                                obj.get("boz_instance_path", "").split("/") if value),
            shape=obj.get("boz_shape", ""),
            shape_component=obj.get("boz_shape_component", -1),
            links=view.links_of(obj),
            copy=json.loads(obj.get("boz_copy", "{}")),
            **geometry,
        ))
    return edits


def _scene_groups(edits):
    return sorted({path for edit in edits
                   for path in (edit.source_group, edit.instance_source_group) if path})


class BOZ_OT_export_group(Operator, ExportHelper):
    bl_idname = "boz.export_group"
    bl_label = "Export edited group"
    bl_description = "Write a new native group while preserving every untouched resource"
    bl_options = {"REGISTER"}

    filename_ext = SUFFIX
    # ExportHelper treats only ".bin" as the extension and would append ".group.bin" again on
    # every check (x.group.group.bin); the suffix is enforced in execute instead.
    check_extension = None
    filter_glob: StringProperty(default="*.group.bin", options={"HIDDEN"})

    def invoke(self, context, event):
        source = context.scene.get("boz_source_group", "")
        if source and not self.filepath:
            path = Path(source)
            base = path.name[:-len(SUFFIX)] if path.name.endswith(SUFFIX) else path.stem
            base += "-2" if base.endswith("-edited") else "-edited"
            self.filepath = str(path.with_name(base + SUFFIX))
        return super().invoke(context, event)

    def execute(self, context):
        try:
            edits = _scene_edits(context)
            groups = _scene_groups(edits)
            if len(groups) != 1:
                raise ValueError("this scene uses several groups; use Export edited level")
            output = self.filepath if self.filepath.endswith(SUFFIX) else self.filepath + SUFFIX
            report = blender_scene.export_groups(edits, {groups[0]: output}, write_unchanged=True,
                                                 deletions=_deletions(context.scene))
        except (OSError, ValueError, IndexError, struct.error) as exc:
            context.scene["boz_last_report"] = f"Export failed: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        message = f"Exported {report.edited} edits; preserved {report.preserved} resources"
        context.scene["boz_last_report"] = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BOZ_OT_export_level(Operator):
    bl_idname = "boz.export_level"
    bl_label = "Export edited level"
    bl_description = ("Write every changed group, under its original file name, into a new folder "
                      "(for example a project's assets folder)")
    bl_options = {"REGISTER"}

    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            edits = _scene_edits(context)
            folder = Path(self.directory)
            scene_groups = [line for line in context.scene.get("boz_source_groups", "").split("\n")
                            if line]
            outputs = {path: folder / Path(path).name
                       for path in sorted(set(_scene_groups(edits)) | set(scene_groups))}
            report = blender_scene.export_groups(edits, outputs,
                                                 level_folder=context.scene.get("boz_level_folder")
                                                 or None, deletions=_deletions(context.scene))
        except (OSError, ValueError, IndexError, struct.error) as exc:
            context.scene["boz_last_report"] = f"Export failed: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        names = ", ".join(Path(path).name for path in report.written) or "nothing (no changes)"
        message = f"Exported {report.edited} edits to {names}"
        context.scene["boz_last_report"] = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


def _deletions(scene):
    try:
        return json.loads(scene.get("boz_deletions", "[]"))
    except ValueError:
        return []


def _reload_level(context) -> bool:
    folder = context.scene.get("boz_level_folder")
    if not folder:
        return False
    for obj in [obj for obj in context.scene.objects if "boz_kind" in obj]:
        bpy.data.objects.remove(obj)
    return bpy.ops.boz.import_level(directory=folder, include_mod=True) == {"FINISHED"}


def _boz_descendants(scene, root):
    """The object and every BOZ object below it (by native parent keys)."""
    keys, result = {root["boz_key"]}, [root]
    changed = True
    while changed:
        changed = False
        for obj in scene.objects:
            if obj not in result and obj.get("boz_parent_key") in keys:
                result.append(obj)
                keys.add(obj["boz_key"])
                changed = True
    return result


def _entity_roots(context):
    """Selected entity objects, without those whose BOZ ancestor is also selected."""
    picked = [obj for obj in context.selected_objects
              if obj.get("boz_kind") in {"placed_model", "entity"}]
    keys = {obj["boz_key"] for obj in picked}
    by_key = {obj.get("boz_key"): obj for obj in context.scene.objects if obj.get("boz_key")}
    roots = []
    for obj in picked:
        parent, nested = obj.get("boz_parent_key"), False
        while parent:
            if parent in keys:
                nested = True
                break
            parent = by_key[parent].get("boz_parent_key") if parent in by_key else ""
        if not nested:
            roots.append(obj)
    return roots


class BOZ_OT_duplicate_entity(Operator):
    bl_idname = "boz.duplicate_entity"
    bl_label = "Duplicate"
    bl_description = ("Copy the selected entities with everything attached (children, collision, "
                      "shapes, links); saving adds them to the level")
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        result = self.execute(context)
        if result == {"FINISHED"}:
            bpy.ops.transform.translate("INVOKE_DEFAULT")
        return result

    def execute(self, context):
        roots = _entity_roots(context)
        if not roots:
            self.report({"ERROR"}, "Select a model or marker to duplicate")
            return {"CANCELLED"}
        if any("boz_copy" in obj for obj in roots):
            self.report({"ERROR"}, "Save before duplicating a copy that has not been saved yet")
            return {"CANCELLED"}
        copies = []
        for root in roots:
            copy_id = uuid.uuid4().hex[:8]
            root_path = [int(v) for v in root.get("boz_instance_path", "").split("/") if v]
            originals = _boz_descendants(context.scene, root)
            mapping = {}
            for obj in originals:
                clone = obj.copy()  # shares mesh data, like the game's instances
                for collection in obj.users_collection:
                    collection.objects.link(clone)
                own_path = [int(v) for v in obj.get("boz_instance_path", "").split("/") if v]
                clone["boz_key"] = f'{obj["boz_key"]}#{copy_id}'
                clone["boz_copy"] = json.dumps({
                    "id": copy_id, "group": root.get("boz_instance_source_group", ""),
                    "index": root.get("boz_instance_resource_index"),
                    "hash": int(root["boz_instance_resource_hash"], 0),
                    "root_path": root_path, "path": own_path[len(root_path):]})
                if "boz_link_id" in clone:
                    del clone["boz_link_id"]  # its new name is only known after saving
                mapping[obj["boz_key"]] = clone
            for obj in originals:
                clone = mapping[obj["boz_key"]]
                parent_key = obj.get("boz_parent_key", "")
                if obj is not root and parent_key in mapping:
                    clone["boz_parent_key"] = mapping[parent_key]["boz_key"]
                    clone.parent = mapping[parent_key]
                    clone.matrix_parent_inverse = Matrix.Identity(4)
            copies.append(mapping[root["boz_key"]])
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in copies:
            obj.select_set(True)
        context.view_layer.objects.active = copies[-1]
        self.report({"INFO"}, f"Duplicated {len(copies)} entities; move them, then save")
        return {"FINISHED"}


class BOZ_OT_delete_entity(Operator):
    bl_idname = "boz.delete_entity"
    bl_label = "Delete"
    bl_description = ("Delete the selected entities with everything attached; refused while "
                      "power, trap or door links still point at them")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        roots = _entity_roots(context)
        if not roots:
            self.report({"ERROR"}, "Select a model or marker to delete")
            return {"CANCELLED"}
        doomed = [obj for root in roots for obj in _boz_descendants(context.scene, root)]
        names = {obj["boz_link_id"] for obj in doomed if obj.get("boz_link_id")}
        for other in context.scene.objects:
            if other in doomed or "boz_links" not in other:
                continue
            for link in view.links_of(other):
                if link["kind"] != "member" and any(f"0x{t:08x}" in names for t in link["targets"]):
                    self.report({"ERROR"}, f"{other.name.split(':', 1)[-1]} still has a "
                                f"{link['field']} link to it; remove that link first")
                    return {"CANCELLED"}
        deletions = _deletions(context.scene)
        for root in roots:
            if "boz_copy" in root:
                continue  # an unsaved copy simply disappears
            pieces = []
            for obj in _boz_descendants(context.scene, root):
                if obj.get("boz_kind") == "collision_piece":
                    pieces.append({"group": obj["boz_source_group"],
                                   "index": int(obj["boz_resource_index"]),
                                   "hash": int(obj["boz_resource_hash"], 0),
                                   "triangles": _face_ints(obj, "boz_triangle") or []})
            deletions.append({"group": root["boz_instance_source_group"],
                              "index": int(root["boz_instance_resource_index"]),
                              "hash": int(root["boz_instance_resource_hash"], 0),
                              "path": [int(v) for v in root.get("boz_instance_path", "").split("/") if v],
                              "collision": pieces})
        context.scene["boz_deletions"] = json.dumps(deletions)
        for obj in doomed:
            bpy.data.objects.remove(obj)
        self.report({"INFO"}, f"Deleted {len(roots)} entities; saving removes them from the level")
        return {"FINISHED"}


def _refresh_navmesh(context, written):
    """Show the navmesh just saved: replace the overlay's mesh from the written group."""
    for path in written:
        try:
            parsed = blender_scene.group.parse(Path(path).read_bytes())
        except (OSError, ValueError):
            continue
        for resource_type in parsed.types():
            if resource_type.class_hash != blender_scene.NAVMESH:
                continue
            for index, item in enumerate(resource_type.resources):
                for obj in context.scene.objects:
                    if obj.get("boz_kind") != "navmesh" or \
                            Path(obj.get("boz_source_group", "")).name != Path(path).name:
                        continue
                    fresh = blender_scene.navmesh_meshes(obj["boz_source_group"], item, index,
                                                         obj.name.split(":", 1)[0])
                    old = obj.data
                    obj.data = build_mesh(fresh)
                    bpy.data.meshes.remove(old)


class BOZ_OT_save_to_mod(Operator):
    bl_idname = "boz.save_to_mod"
    bl_label = "Save to mod"
    bl_description = ("Write every changed group into your mod in the client's mods folder; the "
                      "game loads it the next time it starts")
    bl_options = {"REGISTER"}

    force_navmesh: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        try:
            client_root, mod_id = _mod_target(context)
            scene = context.scene
            sources = [line for line in scene.get("boz_source_groups", "").split("\n") if line]
            report = blender_scene.export_to_mod(
                _scene_edits(context), client_root, mod_id,
                level_folder=scene.get("boz_level_folder") or None, sources=sources,
                force_navmesh=self.force_navmesh, deletions=_deletions(scene))
        except (OSError, ValueError, IndexError, struct.error) as exc:
            context.scene["boz_last_report"] = f"Save failed: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if report.written:
            message = (f"Saved {report.edited} edits to mod {mod_id}: "
                       + ", ".join(Path(path).name for path in report.written))
            if report.navmesh:
                message += f"; {report.navmesh}"
                _refresh_navmesh(context, report.written)
            if report.added or report.removed:
                # New and removed entities only get their identities from the saved groups.
                message += f"; {report.added} added, {report.removed} deleted"
                context.scene["boz_deletions"] = "[]"
                if _reload_level(context):
                    message += "; level reloaded"
        else:
            message = "Nothing changed; mod left as it was"
            if report.navmesh:
                message += f" ({report.navmesh})"
        context.scene["boz_last_report"] = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


def _mod_items(self, context):
    settings = _settings(context)
    if settings is None or not settings.client_root:
        return [("", "Set the client folder first", "")]
    return [(mod.id, f"{mod.name} ({mod.id})", "") for mod in sdkhome.client_mods(Path(settings.client_root))] \
        or [("", "No mods in this client", "")]


class BOZ_OT_choose_mod(Operator):
    bl_idname = "boz.choose_mod"
    bl_label = "Choose mod"
    bl_description = "Pick one of the mods in the client's mods folder"
    bl_property = "mod"

    mod: EnumProperty(items=_mod_items)
    target: StringProperty(default="mod_id", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = _settings(context)
        if settings is None or not self.mod:
            return {"CANCELLED"}
        setattr(settings, self.target, self.mod)
        return {"FINISHED"}


class BOZ_OT_build_and_run(Operator):
    bl_idname = "boz.build_and_run"
    bl_label = "Build & Run"
    bl_description = ("Save to your mod, then start the game straight into this level with the "
                      "test mod (Developer by default); the game's output goes to boz-log.txt")
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            client_root, _ = _mod_target(context)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        root = Path(client_root).expanduser().resolve()
        folder = context.scene.get("boz_level_folder")
        if not folder:
            self.report({"ERROR"}, "Build & Run needs a level imported with Import level folder")
            return {"CANCELLED"}
        problem = _launch_check(context, root)
        if problem:
            self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        if bpy.ops.boz.save_to_mod() != {"FINISHED"}:
            return {"CANCELLED"}
        message = f"{context.scene.get('boz_last_report', '')}; " \
            + _launch_level(context, root, Path(folder).name)
        context.scene["boz_last_report"] = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BOZ_OT_rebuild_navmesh(Operator):
    bl_idname = "boz.rebuild_navmesh"
    bl_label = "Rebuild navmesh"
    bl_description = ("Save to mod and rebuild the navmesh from the game's original wherever the "
                      "level differs from it (repairs mods saved by older add-on versions)")
    bl_options = {"REGISTER"}

    def execute(self, context):
        return bpy.ops.boz.save_to_mod(force_navmesh=True)


class BOZ_OT_validate_scene(Operator):
    bl_idname = "boz.validate_scene"
    bl_label = "Validate BOZ scene"
    bl_description = "Validate native resource identities, topology, transforms and parents"

    def execute(self, context):
        problems = []
        seen = set()
        for obj in context.scene.objects:
            if "boz_kind" not in obj:
                continue
            kind = obj.get("boz_kind")
            # Every imported object has a unique key; collision pieces share their resource.
            identity = obj.get("boz_key") or (
                obj.get("boz_source_group"), obj.get("boz_class_hash"),
                obj.get("boz_resource_index"), obj.get("boz_resource_hash"),
                obj.get("boz_instance_source_group"),
                obj.get("boz_instance_resource_index"), obj.get("boz_instance_path"))
            if identity in seen:
                problems.append(f"{obj.name}: copied with Blender's own duplicate; delete it and "
                                "use BOZ Redux > Duplicate")
            seen.add(identity)
            if obj.get("boz_schema") != blender_scene.SCHEMA:
                problems.append(f"{obj.name}: imported by an older add-on; re-import")
            try:
                _basis(obj)
            except ValueError as exc:
                problems.append(str(exc))
            if kind in {"entity", "shape", "badge", "area", "navmesh"}:
                continue
            if obj.type != "MESH" or (not obj.data.polygons
                                      and kind not in {"navigation_connection", "collision"}):
                problems.append(f"{obj.name}: editable native resource has no faces")
                continue
            if any(len(polygon.vertices) != 3 for polygon in obj.data.polygons):
                problems.append(f"{obj.name}: non-triangle face")
        if problems:
            for problem in problems[:8]:
                self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Validated {len(seen)} native objects")
        return {"FINISHED"}


class BOZ_PT_shipped_files(Panel):
    bl_label = "Shipped files"
    bl_idname = "BOZ_PT_shipped_files"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Shipped files"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = _settings(context)
        if settings is not None:
            box = layout.box()
            box.prop(settings, "client_root", text="Client")
            for field, label in (("mod_id", "Mod"), ("run_mod", "Test with")):
                row = box.row(align=True)
                row.prop(settings, field, text=label)
                pick = row.operator(BOZ_OT_choose_mod.bl_idname, text="", icon="DOWNARROW_HLT")
                pick.target = field
        layout.operator(BOZ_OT_import_level.bl_idname, icon="FILE_FOLDER")
        layout.operator(BOZ_OT_validate_scene.bl_idname, icon="CHECKMARK")
        row = layout.row(align=True)
        row.operator(BOZ_OT_duplicate_entity.bl_idname, icon="DUPLICATE")
        row.operator(BOZ_OT_delete_entity.bl_idname, icon="TRASH")
        pending = len(_deletions(context.scene))
        if pending:
            layout.label(text=f"{pending} deletions waiting for save", icon="INFO")
        column = layout.column(align=True)
        column.operator(BOZ_OT_build_and_run.bl_idname, icon="PLAY")
        column.operator(BOZ_OT_save_to_mod.bl_idname, icon="FILE_TICK")
        column.operator(BOZ_OT_rebuild_navmesh.bl_idname, icon="MOD_SMOOTH")
        column.enabled = bool(settings is not None and settings.client_root)
        view.draw_switches(layout, context.scene)
        more = layout.column(align=True)
        more.label(text="Files")
        more.operator(BOZ_OT_import_group.bl_idname, icon="IMPORT")
        more.operator(BOZ_OT_export_level.bl_idname, icon="EXPORT")
        more.operator(BOZ_OT_export_group.bl_idname, icon="EXPORT")
        sources = [line for line in context.scene.get("boz_source_groups", "").split("\n") if line]
        if sources:
            box = layout.box()
            box.label(text="Source groups" if len(sources) > 1 else "Source group")
            box.label(text=Path(sources[0]).name if len(sources) == 1
                      else f"{len(sources)} groups in {Path(sources[0]).parent.name}")
        report = context.scene.get("boz_last_report")
        if report:
            box = layout.box()
            box.label(text="Last export")
            box.label(text=report)


CLASSES = (BOZ_ShippedSettings, BOZ_OT_import_group, BOZ_OT_import_level, BOZ_OT_export_group,
           BOZ_OT_export_level, BOZ_OT_save_to_mod, BOZ_OT_build_and_run, BOZ_OT_rebuild_navmesh,
           BOZ_OT_choose_mod, BOZ_OT_duplicate_entity, BOZ_OT_delete_entity, BOZ_OT_validate_scene,
           BOZ_PT_shipped_files)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.boz_shipped = PointerProperty(type=BOZ_ShippedSettings)


def unregister():
    del bpy.types.WindowManager.boz_shipped
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
