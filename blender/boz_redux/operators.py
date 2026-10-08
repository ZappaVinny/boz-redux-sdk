"""Blender UI backed exclusively by bozkit's native format codecs."""

from __future__ import annotations

import struct
from array import array
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper, ImportHelper

try:
    from bozkit import blender_scene
except ModuleNotFoundError:
    from ._vendor.bozkit import blender_scene


def _mesh_object(context, item: blender_scene.SceneMesh):
    mesh = bpy.data.meshes.new(item.display_name)
    mesh.from_pydata(item.vertices, item.edges, item.faces)
    mesh.update(calc_edges=True)
    if item.uvs:
        native_uvs = mesh.attributes.new(name="boz_native_uv", type="FLOAT2", domain="POINT")
        for index, uv in enumerate(item.uvs):
            native_uvs.data[index].vector = uv
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_layer.active_render = True
        for loop in mesh.loops:
            uv_layer.data[loop.index].uv = item.uvs[loop.vertex_index]
    if item.vertex_colours:
        colours = mesh.color_attributes.new(name="boz_native_colour", type="FLOAT_COLOR",
                                            domain="CORNER")
        # Native colours address expanded render vertices.  Blender's shader
        # attribute interpolation is loop/corner based, so copy the render
        # vertex colour to each face corner instead of relying on a POINT
        # attribute conversion that differs between viewport/render backends.
        for loop in mesh.loops:
            colour = item.vertex_colours[loop.vertex_index]
            value = tuple(channel / 255.0 for channel in colour)
            colours.data[loop.index].color = value
    for name in item.material_names:
        material = bpy.data.materials.get(f"BOZ Collision: {name}")
        if material is None:
            material = bpy.data.materials.new(f"BOZ Collision: {name}")
        mesh.materials.append(material)
    for material_hash in item.material_hashes:
        name = f"BOZ Material {material_hash:08x}"
        material = bpy.data.materials.get(name)
        if material is None:
            material = bpy.data.materials.new(name)
        mesh.materials.append(material)
    if item.face_materials:
        for polygon, material_index in zip(mesh.polygons, item.face_materials, strict=True):
            polygon.material_index = material_index
    obj = bpy.data.objects.new(item.display_name, mesh)
    obj["boz_schema"] = blender_scene.SCHEMA
    obj["boz_kind"] = item.kind
    obj["boz_class_hash"] = f"0x{item.class_hash:08x}"
    obj["boz_resource_hash"] = f"0x{item.resource_hash:08x}"
    obj["boz_resource_index"] = item.resource_index
    obj["boz_source_group"] = item.source_group
    obj["boz_front_sector"] = item.front_sector
    obj["boz_back_sector"] = item.back_sector
    obj["boz_material_names"] = "\n".join(item.material_names)
    if item.instance_resource_hash is not None:
        obj["boz_instance_resource_hash"] = f"0x{item.instance_resource_hash:08x}"
        obj["boz_instance_resource_index"] = item.instance_resource_index
    obj.location = item.location
    x, y, z, w = item.rotation
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (w, x, y, z)
    if item.kind == "collision":
        obj.display_type = "WIRE"
        obj.hide_render = True
        obj.color = (1.0, 0.25, 0.05, 1.0)
    elif item.kind in {"portal", "navigation_connection"}:
        obj.display_type = "WIRE"
        obj.hide_render = True
    collection = bpy.data.collections.get(item.collection)
    if collection is None:
        collection = bpy.data.collections.new(item.collection)
        context.scene.collection.children.link(collection)
    collection.objects.link(obj)
    if item.kind in {"collision", "portal", "navigation_connection"}:
        obj.hide_set(True)
    return obj


def _native_materials(result):
    for texture_hash, item in result.textures.items():
        name = f"BOZ Texture {texture_hash:08x}"
        image = bpy.data.images.get(name)
        if image is None or image.size[:] != (item.width, item.height):
            if image is not None:
                bpy.data.images.remove(image)
            image = bpy.data.images.new(name, width=item.width, height=item.height, alpha=True)
        # Blender's first pixel row is the bottom of the image; native texture rows are top-down.
        pixels = array('f')
        stride = item.width * 4
        for row in range(item.height - 1, -1, -1):
            start = row * stride
            pixels.extend(channel / 255.0 for channel in item.rgba[start:start + stride])
        # Changing a generated image's colour space can recreate its pixel buffer.
        # Configure it before uploading texels, otherwise Blender packs a black image.
        image.colorspace_settings.name = "Non-Color"
        image.pixels.foreach_set(pixels)
        image.update()
        image.pack()
        image["boz_resource_hash"] = f"0x{texture_hash:08x}"
        image["boz_native_format"] = item.format
        image["boz_native_flags"] = f"0x{item.flags:08x}"
    for material_hash, item in result.materials.items():
        name = f"BOZ Material {material_hash:08x}"
        material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        # These are importer-owned materials; rebuild rather than retaining stale
        # alpha/texture links from an earlier import of the same resource.
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        for link in list(output.inputs["Surface"].links):
            links.remove(link)
        vertex = material.node_tree.nodes.get("BOZ Vertex Colour")
        if vertex is None:
            vertex = material.node_tree.nodes.new("ShaderNodeVertexColor")
            vertex.name = "BOZ Vertex Colour"
        vertex.layer_name = "boz_native_colour"
        emission = nodes.get("BOZ Native Unlit")
        if emission is None:
            emission = nodes.new("ShaderNodeEmission")
            emission.name = "BOZ Native Unlit"
        # This is a primary-texture editing preview, not an emulation of the game's
        # multi-stage shading. Preserve native colours on the mesh for future shading support.
        colour_output = vertex.outputs["Color"]
        alpha_output = None
        primary = None
        if item.texture_hashes:
            image = bpy.data.images.get(f"BOZ Texture {item.texture_hashes[0]:08x}")
            if image is not None:
                primary = result.textures.get(item.texture_hashes[0])
                texture = next((node for node in material.node_tree.nodes
                                if node.type == 'TEX_IMAGE'), None)
                if texture is None:
                    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
                texture.image = image
                uv = nodes.get("BOZ Primary UV") or nodes.new("ShaderNodeUVMap")
                uv.name = "BOZ Primary UV"
                uv.uv_map = "UVMap"
                links.new(uv.outputs["UV"], texture.inputs["Vector"])
                colour_output = texture.outputs["Color"]
                alpha_output = texture.outputs["Alpha"]
        for link in list(emission.inputs["Color"].links):
            links.remove(link)
        links.new(colour_output, emission.inputs["Color"])
        transparent = nodes.get("BOZ Transparent") or nodes.new("ShaderNodeBsdfTransparent")
        transparent.name = "BOZ Transparent"
        alpha_mix = nodes.get("BOZ Alpha Mix") or nodes.new("ShaderNodeMixShader")
        alpha_mix.name = "BOZ Alpha Mix"
        for socket in alpha_mix.inputs:
            for link in list(socket.links):
                links.remove(link)
        if alpha_output is None:
            alpha_mix.inputs[0].default_value = 1.0
        else:
            links.new(alpha_output, alpha_mix.inputs[0])
        links.new(transparent.outputs[0], alpha_mix.inputs[1])
        links.new(emission.outputs[0], alpha_mix.inputs[2])
        # Verified in the native GLES material-state function at 0x4a2b74fc:
        # flags[18:16]: 0/5 opaque, 1/4 SRC_ALPHA/ONE_MINUS_SRC_ALPHA,
        # 2 SRC_ALPHA/ONE, 3 ZERO/ONE_MINUS_SRC_COLOR.
        mode = (item.flags >> 16) & 7
        material["boz_native_flags"] = f"0x{item.flags:08x}"
        material["boz_blend_mode"] = mode
        surface = emission.outputs[0]
        if mode in {1, 4}:
            surface = alpha_mix.outputs[0]
        elif mode == 5 and primary is not None and primary.flags & 8:
            # GLES enables GL_ALPHA_TEST with GL_GREATER, 0.75 for this
            # material/texture combination (0x4a2b74fc). The imported
            # chandelier's cyan texels are ~87/255, so they must be cut out.
            cutoff = nodes.new("ShaderNodeMath")
            cutoff.name = "BOZ Native Alpha Test"
            cutoff.operation = 'GREATER_THAN'
            links.new(alpha_output, cutoff.inputs[0])
            cutoff.inputs[1].default_value = 0.75
            links.new(cutoff.outputs[0], alpha_mix.inputs[0])
            surface = alpha_mix.outputs[0]
        elif mode == 2:
            scale = nodes.new("ShaderNodeMixRGB")
            scale.blend_type = 'MULTIPLY'
            scale.inputs[0].default_value = 1.0
            links.new(colour_output, scale.inputs[1])
            if alpha_output is not None:
                links.new(alpha_output, scale.inputs[2])
            else:
                scale.inputs[2].default_value = (1, 1, 1, 1)
            links.new(scale.outputs[0], emission.inputs['Color'])
            add = nodes.new("ShaderNodeAddShader")
            links.new(transparent.outputs[0], add.inputs[0])
            links.new(emission.outputs[0], add.inputs[1])
            surface = add.outputs[0]
        elif mode == 3:
            inverse = nodes.new("ShaderNodeInvert")
            links.new(colour_output, inverse.inputs['Color'])
            links.new(inverse.outputs[0], transparent.inputs['Color'])
            surface = transparent.outputs[0]
        links.new(surface, output.inputs["Surface"])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"


class BOZ_OT_import_group(Operator, ImportHelper):
    bl_idname = "boz.import_group"
    bl_label = "Import native group"
    bl_description = "Import editable resources from a BOZ .group.bin without changing the source"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".group.bin"
    filter_glob: StringProperty(default="*.group.bin", options={"HIDDEN"})
    include_models: BoolProperty(
        name="Local asset models", default=False,
        description="Import reusable local-space CIwModel assets; these are not map placements")
    include_collision: BoolProperty(name="Collision", default=True)
    include_portals: BoolProperty(name="Portals", default=True)
    include_navigation: BoolProperty(name="Navigation connections", default=True)

    def execute(self, context):
        try:
            result = blender_scene.import_group(
                self.filepath,
                include_models=self.include_models,
                include_collision=self.include_collision,
                include_portals=self.include_portals,
                include_navigation=self.include_navigation,
            )
            _native_materials(result)
            for item in result.meshes:
                _mesh_object(context, item)
        except (OSError, ValueError, struct.error) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        context.scene["boz_source_group"] = str(Path(self.filepath).resolve())
        self.report({"INFO"}, f"Imported {len(result.meshes)} editable resources")
        return {"FINISHED"}


class BOZ_OT_export_group(Operator, ExportHelper):
    bl_idname = "boz.export_group"
    bl_label = "Export edited group"
    bl_description = "Write a new native group while preserving every untouched resource"
    bl_options = {"REGISTER"}

    filename_ext = ".group.bin"
    filter_glob: StringProperty(default="*.group.bin", options={"HIDDEN"})

    def invoke(self, context, event):
        source = context.scene.get("boz_source_group", "")
        if source and not self.filepath:
            path = Path(source)
            suffix = ".group.bin"
            base = path.name[:-len(suffix)] if path.name.endswith(suffix) else path.stem
            base += "-2" if base.endswith("-edited") else "-edited"
            self.filepath = str(path.with_name(base + suffix))
        return super().invoke(context, event)

    def execute(self, context):
        source = context.scene.get("boz_source_group", "")
        if not source:
            self.report({"ERROR"}, "Import a native group before exporting")
            return {"CANCELLED"}
        edits = []
        for obj in context.scene.objects:
            if obj.type != "MESH" or "boz_kind" not in obj:
                continue
            if obj.get("boz_source_group") != source:
                continue
            if obj.mode == "EDIT":
                obj.update_from_editmode()
            if obj["boz_kind"] == "placed_model":
                vertices = [tuple(vertex.co) for vertex in obj.data.vertices]
            else:
                vertices = [tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices]
            faces = [tuple(polygon.vertices) for polygon in obj.data.polygons]
            edges = [tuple(edge.vertices) for edge in obj.data.edges]
            uvs = []
            native_uvs = obj.data.attributes.get("boz_native_uv")
            active_uvs = obj.data.uv_layers.active
            if native_uvs is not None and len(native_uvs.data) == len(obj.data.vertices):
                values = [tuple(value.vector) for value in native_uvs.data]
                # Blender can retain the UV layer definition while exposing no loop data after
                # some Edit Mode operations. In that case the point-domain native copy remains
                # authoritative instead of indexing an empty collection.
                if active_uvs is not None and len(active_uvs.data) == len(obj.data.loops):
                    seen_uvs = {}
                    for loop in obj.data.loops:
                        uv = tuple(active_uvs.data[loop.index].uv)
                        if loop.vertex_index in seen_uvs and seen_uvs[loop.vertex_index] != uv:
                            self.report({"ERROR"},
                                        f"{obj.name}: one native vertex has conflicting loop UVs")
                            return {"CANCELLED"}
                        seen_uvs[loop.vertex_index] = uv
                        values[loop.vertex_index] = uv
                uvs = values
            elif (active_uvs is not None and len(active_uvs.data) == len(obj.data.loops)
                  and len(obj.data.loops)):
                values = [None] * len(obj.data.vertices)
                seen_uvs = {}
                for loop in obj.data.loops:
                    uv = tuple(active_uvs.data[loop.index].uv)
                    if loop.vertex_index in seen_uvs and seen_uvs[loop.vertex_index] != uv:
                        self.report({"ERROR"},
                                    f"{obj.name}: one native vertex has conflicting loop UVs")
                        return {"CANCELLED"}
                    seen_uvs[loop.vertex_index] = uv
                    values[loop.vertex_index] = uv
                uvs = [value or (0.0, 0.0) for value in values]
            # If Blender discarded both editable UV representations, leave ``uvs`` empty. bozkit
            # then retains the source model's native UV block while applying geometry edits.
            edits.append(blender_scene.SceneEdit(
                kind=obj["boz_kind"],
                class_hash=int(obj["boz_class_hash"], 0),
                resource_hash=int(obj["boz_resource_hash"], 0),
                resource_index=int(obj["boz_resource_index"]),
                vertices=vertices,
                faces=faces,
                edges=edges,
                uvs=uvs,
                face_materials=[polygon.material_index for polygon in obj.data.polygons],
                front_sector=obj.get("boz_front_sector", ""),
                back_sector=obj.get("boz_back_sector", ""),
                location=tuple(obj.location),
                rotation=(obj.rotation_quaternion.x, obj.rotation_quaternion.y,
                          obj.rotation_quaternion.z, obj.rotation_quaternion.w),
                instance_resource_hash=(int(obj["boz_instance_resource_hash"], 0)
                                        if "boz_instance_resource_hash" in obj else None),
                instance_resource_index=obj.get("boz_instance_resource_index"),
            ))
        try:
            report = blender_scene.export_group(source, self.filepath, edits)
        except (OSError, ValueError, IndexError, struct.error) as exc:
            context.scene["boz_last_report"] = f"Export failed: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        message = f"Exported {report.edited} edits; preserved {report.preserved} resources"
        context.scene["boz_last_report"] = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BOZ_OT_validate_scene(Operator):
    bl_idname = "boz.validate_scene"
    bl_label = "Validate BOZ scene"
    bl_description = "Validate native resource identities, topology, and source relationships"

    def execute(self, context):
        problems = []
        seen = set()
        for obj in context.scene.objects:
            if "boz_kind" not in obj:
                continue
            identity = (obj.get("boz_source_group"), obj.get("boz_class_hash"),
                        obj.get("boz_resource_index"), obj.get("boz_resource_hash"),
                        obj.get("boz_instance_resource_index"))
            if identity in seen:
                problems.append(f"{obj.name}: duplicate native resource identity")
            seen.add(identity)
            if (obj.type != "MESH" or
                    (not obj.data.polygons and obj.get("boz_kind") != "navigation_connection")):
                problems.append(f"{obj.name}: editable native resource has no faces")
            if any(len(polygon.vertices) != 3 for polygon in obj.data.polygons):
                problems.append(f"{obj.name}: non-triangle face")
        if problems:
            for problem in problems[:8]:
                self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Validated {len(seen)} native resources")
        return {"FINISHED"}


class BOZ_PT_map_tools(Panel):
    bl_label = "BOZ Redux"
    bl_idname = "BOZ_PT_map_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BOZ Redux"

    def draw(self, context):
        layout = self.layout
        layout.operator(BOZ_OT_import_group.bl_idname, icon="IMPORT")
        layout.operator(BOZ_OT_validate_scene.bl_idname, icon="CHECKMARK")
        layout.operator(BOZ_OT_export_group.bl_idname, icon="EXPORT")
        source = context.scene.get("boz_source_group")
        if source:
            box = layout.box()
            box.label(text="Source group")
            box.label(text=Path(source).name)
        report = context.scene.get("boz_last_report")
        if report:
            box = layout.box()
            box.label(text="Last export")
            box.label(text=report)


CLASSES = (BOZ_OT_import_group, BOZ_OT_export_group, BOZ_OT_validate_scene, BOZ_PT_map_tools)
