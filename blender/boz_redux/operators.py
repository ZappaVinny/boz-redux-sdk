"""Blender UI backed exclusively by bozkit's native format codecs."""

from __future__ import annotations

import struct
from pathlib import Path

import json
import uuid

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix

try:
    import numpy
except ModuleNotFoundError:  # Blender bundles numpy; the fallback keeps tests portable.
    numpy = None

try:
    from bozkit import blender_scene
except ModuleNotFoundError:
    from ._vendor.bozkit import blender_scene

from . import view

try:
    from ._build import BUILD
except ImportError:  # running from the SDK checkout rather than an installed ZIP
    BUILD = "source"

SUFFIX = ".group.bin"
HELPER_KINDS = {"collision", "collision_piece", "portal", "navigation_connection", "shape",
                "navmesh"}
# Marker colour by what the entity does (sRGB-ish display colours).
MARKER_COLOURS = {
    "perk": (0.65, 0.2, 1.0), "pack_a_punch": (1.0, 0.1, 0.8), "mystery_box": (0.1, 0.9, 1.0),
    "door": (1.0, 0.55, 0.1), "power": (1.0, 0.95, 0.1), "trap": (1.0, 0.1, 0.1),
    "wall_buy": (0.2, 1.0, 0.3), "barricade": (0.75, 0.5, 0.3), "teleporter": (0.2, 0.4, 1.0),
    "easter_egg": (1.0, 0.5, 0.7), "ride": (0.6, 0.8, 1.0), "spawn": (0.6, 0.0, 0.0),
    "effect": (0.6, 0.85, 1.0), "interact": (0.8, 1.0, 0.3), "trigger": (0.3, 0.8, 0.5),
    "sound": (0.2, 0.7, 0.7), "jump": (1.0, 1.0, 1.0), "locator": (0.55, 0.55, 0.55),
    "camera": (0.4, 0.5, 0.7), "ai": (1.0, 0.4, 0.0), "collision": (0.9, 0.2, 0.2),
    "entity": (0.4, 0.4, 0.4), "area": (0.7, 0.45, 1.0),
}
# Shape colour by role: solid collision, ghost (pass-through trigger) volume, interaction reach.
SHAPE_COLOURS = {"solid": (1.0, 0.15, 0.1), "ghost": (0.1, 1.0, 0.3), "reach": (1.0, 0.85, 0.1)}
NAV_COLOURS = {"walkable": (0.15, 0.45, 1.0), "door": (1.0, 0.5, 0.1), "jump": (1.0, 1.0, 1.0),
               "tagged": (0.7, 0.45, 1.0)}
GLYPH_SIZE = 12.0
PACKAGE = __name__.rpartition(".")[0]


class BOZ_AP_preferences(AddonPreferences):
    bl_idname = PACKAGE

    client_root: StringProperty(
        name="Client folder", subtype="DIR_PATH",
        description="Your BOZ Redux client folder (the one with mods/ and assets/)")
    mod_id: StringProperty(
        name="Mod", default="blender_edits",
        description="Mod that Save to mod writes and Import level folder can include")

    def draw(self, context):
        self.layout.prop(self, "client_root")
        self.layout.prop(self, "mod_id")


def _settings(context):
    """The add-on preferences, or None when the add-on was registered without being enabled."""
    addon = context.preferences.addons.get(PACKAGE)
    return addon.preferences if addon is not None else None


def _mod_target(context):
    settings = _settings(context)
    if settings is None or not settings.client_root:
        raise ValueError("set the BOZ Redux client folder in the BOZ Redux sidebar first")
    return settings.client_root, settings.mod_id


def _set_corner_uvs(mesh, name, uvs):
    """Create a face-corner UV layer from per-render-vertex native UVs."""
    layer = mesh.uv_layers.new(name=name)
    corner_vertices = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", corner_vertices)
    converted = [blender_scene.uv_to_blender(value) for value in uvs]
    layer.data.foreach_set("uv", [component for vertex in corner_vertices
                                  for component in converted[vertex]])
    return layer


def _build_mesh(item: blender_scene.SceneMesh):
    mesh = bpy.data.meshes.new(item.display_name)
    mesh.from_pydata(item.vertices, item.edges, item.faces)
    mesh.update(calc_edges=True)
    if item.uvs:
        native_uvs = mesh.attributes.new(name="boz_native_uv", type="FLOAT2", domain="POINT")
        native_uvs.data.foreach_set("vector", [c for uv in item.uvs for c in uv])
        _set_corner_uvs(mesh, "UVMap", item.uvs).active_render = True
        # Texture stage 1 reads the second UV set. A few lightmapped models have none;
        # sampling the first set keeps them visible instead of reading one lightmap texel.
        _set_corner_uvs(mesh, "UVMap2", item.uvs2 or item.uvs)
        if item.uvs2:
            native_uvs2 = mesh.attributes.new(name="boz_native_uv2", type="FLOAT2",
                                              domain="POINT")
            native_uvs2.data.foreach_set("vector", [c for uv in item.uvs2 for c in uv])
        mesh.uv_layers.active = mesh.uv_layers["UVMap"]
    if item.kind in {"placed_model", "model"}:
        # Native colours address expanded render vertices; copy them to face corners. Values stay
        # in the game's display encoding because the preview shader works in that space. Models
        # without colours get white, the GL primary colour without a colour array.
        colours = mesh.color_attributes.new(name="boz_native_colour", type="FLOAT_COLOR",
                                            domain="CORNER")
        corner_vertices = [0] * len(mesh.loops)
        mesh.loops.foreach_get("vertex_index", corner_vertices)
        if item.vertex_colours:
            source = [tuple(channel / 255.0 for channel in colour) for colour in item.vertex_colours]
            colours.data.foreach_set("color", [c for vertex in corner_vertices
                                               for c in source[vertex]])
        else:
            colours.data.foreach_set("color", [1.0] * (4 * len(mesh.loops)))
    if item.kind == "navmesh":
        for name in item.material_names:
            mesh.materials.append(_colour_material(f"BOZ Nav: {name}", NAV_COLOURS[name], 0.35))
    else:
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
        mesh.polygons.foreach_set("material_index", item.face_materials)
    if item.kind in {"collision", "collision_piece"}:
        # Each face remembers its native triangle so pieces can be stitched back in order.
        triangles = mesh.attributes.new(name="boz_triangle", type="INT", domain="FACE")
        triangles.data.foreach_set("value", item.collision_triangles
                                   or list(range(len(item.faces))))
    mesh["boz_resource_hash"] = f"0x{item.resource_hash:08x}"
    return mesh


def _collection(context, item: blender_scene.SceneMesh):
    collection = bpy.data.collections.get(item.collection)
    if collection is None:
        collection = bpy.data.collections.new(item.collection)
        parent_name = f"BOZ {item.group_name}" if item.group_name else ""
        parent = context.scene.collection
        if parent_name:
            parent = bpy.data.collections.get(parent_name)
            if parent is None:
                parent = bpy.data.collections.new(parent_name)
                context.scene.collection.children.link(parent)
        parent.children.link(collection)
    return collection


def _colour_material(name, colour, alpha):
    """An importer-owned unlit material in one colour, for markers and shapes."""
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = (*colour, alpha)  # Solid mode
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*colour, 1.0)
    surface = emission.outputs[0]
    if alpha < 1.0:
        mix = nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = alpha
        links.new(nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[1])
        links.new(emission.outputs[0], mix.inputs[2])
        surface = mix.outputs[0]
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "BLENDED"
    links.new(surface, output.inputs["Surface"])
    return material


def _glyph_mesh():
    """A small octahedron shared by every marker."""
    mesh = bpy.data.meshes.get("BOZ Marker Glyph")
    if mesh is None:
        size = GLYPH_SIZE
        vertices = [(size, 0, 0), (-size, 0, 0), (0, size, 0), (0, -size, 0),
                    (0, 0, size * 1.6), (0, 0, -size)]
        faces = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
                 (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]
        mesh = bpy.data.meshes.new("BOZ Marker Glyph")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        mesh.materials.append(None)  # one slot; each marker links its own colour to it
    return mesh


def _mesh_object(context, item: blender_scene.SceneMesh, meshes=None, objects=None):
    """Create one object. Instances of one model share a mesh datablock (``meshes``)."""
    meshes = {} if meshes is None else meshes
    objects = {} if objects is None else objects
    if item.kind in {"entity", "badge", "area"}:
        # Markers are coloured meshes: Blender cannot colour empties.
        colour = MARKER_COLOURS.get(item.category, MARKER_COLOURS["entity"])
        obj = bpy.data.objects.new(item.display_name, _glyph_mesh())
        material = _colour_material(f"BOZ Marker: {item.category or 'entity'}", colour, 1.0)
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material
        obj.color = (*colour, 1.0)
        obj.hide_render = True
    else:
        mesh = meshes.get(item.mesh_key) if item.mesh_key else None
        if mesh is None:
            mesh = _build_mesh(item)
            if item.mesh_key:
                meshes[item.mesh_key] = mesh
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
    obj["boz_key"] = item.key
    obj["boz_parent_key"] = item.parent_key
    if item.category:
        obj["boz_category"] = item.category
    if item.components:
        obj["boz_components"] = ", ".join(item.components)
    if item.description:
        obj["boz_description"] = item.description
    if item.link_id:
        obj["boz_link_id"] = f"0x{item.link_id:08x}"  # hex: IDProperty ints are signed 32-bit
    if item.links:
        obj["boz_links"] = json.dumps(item.links)
    if item.instance_resource_hash is not None:
        obj["boz_instance_resource_hash"] = f"0x{item.instance_resource_hash:08x}"
        obj["boz_instance_resource_index"] = item.instance_resource_index
        obj["boz_instance_source_group"] = item.instance_source_group or item.source_group
        obj["boz_instance_path"] = "/".join(map(str, item.instance_path))
    parent = objects.get(item.parent_key) if item.parent_key else None
    if parent is not None:
        obj.parent = parent
        obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = item.location
    x, y, z, w = item.rotation
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (w, x, y, z)
    obj.scale = item.scale
    if item.kind in {"collision", "collision_piece"}:
        obj.display_type = "WIRE"
        obj.hide_render = True
        obj.color = (1.0, 0.25, 0.05, 1.0)
    elif item.kind == "shape":
        colour = SHAPE_COLOURS.get(item.category, SHAPE_COLOURS["solid"])
        if not obj.material_slots:
            obj.data.materials.append(None)
        obj.material_slots[0].link = "OBJECT"
        alpha = 0.15 if item.category == "reach" else 0.3
        obj.material_slots[0].material = _colour_material(f"BOZ Shape: {item.category}", colour,
                                                          alpha)
        obj.color = (*colour, alpha)
        obj.show_wire = True
        obj.show_transparent = True
        obj.hide_render = True
        obj["boz_shape"] = item.shape
        obj["boz_shape_component"] = item.shape_component
    elif item.kind == "navmesh":
        # Display only: saving rebuilds the navmesh from collision.
        obj.show_wire = True
        obj.show_transparent = True
        obj.hide_render = True
        obj.hide_select = True
    elif item.kind == "badge":
        # A badge only shows what its model does; it follows the model and is not edited.
        obj.lock_location = obj.lock_rotation = obj.lock_scale = (True, True, True)
        obj.hide_select = True
    elif item.kind in {"portal", "navigation_connection"}:
        obj.display_type = "WIRE"
        obj.hide_render = True
    _collection(context, item).objects.link(obj)
    if item.kind in HELPER_KINDS:
        obj.hide_set(True)
    if item.key:
        objects[item.key] = obj
    return obj


def _upload_image(name, item):
    image = bpy.data.images.get(name)
    if image is None or image.size[:] != (item.width, item.height):
        if image is not None:
            bpy.data.images.remove(image)
        image = bpy.data.images.new(name, width=item.width, height=item.height, alpha=True)
    # Changing a generated image's colour space can recreate its pixel buffer, so it is set
    # before upload. Texels stay in the game's display encoding (decoded in the shader).
    image.colorspace_settings.name = "Non-Color"
    # Upload upright: Blender's first pixel row is the bottom row. UVs are mirrored to match
    # (blender_scene.uv_to_blender).
    if numpy is not None:
        pixels = numpy.frombuffer(item.rgba, dtype=numpy.uint8).reshape(item.height, item.width, 4)
        image.pixels.foreach_set((pixels[::-1].astype(numpy.float32) / 255.0).ravel())
    else:
        stride = item.width * 4
        values = []
        for row in range(item.height - 1, -1, -1):
            values.extend(channel / 255.0 for channel in item.rgba[row * stride:(row + 1) * stride])
        image.pixels.foreach_set(values)
    image.update()
    image.pack()
    image["boz_native_format"] = item.format
    image["boz_native_flags"] = f"0x{item.flags:08x}"
    return image


def _srgb_decode_group():
    """Node group converting the game's display-encoded colour to linear for Blender."""
    name = "BOZ sRGB Decode"
    tree = bpy.data.node_groups.get(name)
    if tree is not None:
        return tree
    tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
    tree.interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
    tree.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = tree.nodes, tree.links
    inputs, outputs = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    split, join = nodes.new("ShaderNodeSeparateColor"), nodes.new("ShaderNodeCombineColor")
    links.new(inputs.outputs[0], split.inputs[0])

    def math(operation, a, b=None):
        node = nodes.new("ShaderNodeMath")
        node.operation = operation
        for socket, value in zip(node.inputs, (a, b)):
            if isinstance(value, float):
                socket.default_value = value
            elif value is not None:
                links.new(value, socket)
        return node.outputs[0]

    for channel in range(3):
        value = split.outputs[channel]
        linear = math("DIVIDE", value, 12.92)
        curve = math("POWER", math("DIVIDE", math("ADD", value, 0.055), 1.055), 2.4)
        select = math("GREATER_THAN", value, 0.04045)
        links.new(math("ADD", linear, math("MULTIPLY", select, math("SUBTRACT", curve, linear))),
                  join.inputs[channel])
    links.new(join.outputs[0], outputs.inputs[0])
    return tree


def _mix(nodes, links, blend, a, b, factor=1.0):
    node = nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend
    node.clamp_result = True
    node.inputs["Factor"].default_value = factor
    for socket, value in ((node.inputs[6], a), (node.inputs[7], b)):
        if isinstance(value, tuple):
            socket.default_value = value
        else:
            links.new(value, socket)
    return node.outputs[2]


def _build_material(item: blender_scene.SceneMaterial, result):
    """Rebuild an importer-owned material from the GLES1 fixed-function path (0x4a2b74fc).

    Stage 0: primary texture x vertex colour. Stage 1: lightmap combined by flags bits 19-21.
    The combination runs in the game's display encoding and is decoded to linear once, so a
    Standard view transform shows the game's colours. Framebuffer blend follows bits 16-18.
    """
    name = f"BOZ Material {item.resource_hash:08x}"
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    vertex = nodes.new("ShaderNodeVertexColor")
    vertex.name = "BOZ Vertex Colour"
    vertex.layer_name = "boz_native_colour"

    def texture(texture_hash, uv_map, label):
        if not texture_hash or texture_hash not in result.textures:
            return None
        image = bpy.data.images.get(f"BOZ Texture {texture_hash:08x}")
        if image is None:
            return None
        node = nodes.new("ShaderNodeTexImage")
        node.name = label
        node.image = image
        uv = nodes.new("ShaderNodeUVMap")
        uv.name = f"{label} UV"
        uv.uv_map = uv_map
        links.new(uv.outputs["UV"], node.inputs["Vector"])
        return node

    primary = texture(item.texture_hashes[0] if item.texture_hashes else 0, "UVMap",
                      "BOZ Primary")
    colour = vertex.outputs["Color"]
    alpha = vertex.outputs["Alpha"]
    if primary is not None:
        colour = _mix(nodes, links, "MULTIPLY", primary.outputs["Color"], colour)
        multiply = nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        links.new(primary.outputs["Alpha"], multiply.inputs[0])
        links.new(vertex.outputs["Alpha"], multiply.inputs[1])
        alpha = multiply.outputs[0]
    lightmap = texture(item.lightmap, "UVMap2", "BOZ Lightmap")
    stage1 = item.stage1_mode
    if lightmap is not None:
        lm = lightmap.outputs["Color"]
        if stage1 in (0, 5, 6):
            colour = _mix(nodes, links, "MULTIPLY", colour, lm)
            for _ in range({5: 1, 6: 2}.get(stage1, 0)):  # GL_RGB_SCALE 2 or 4, clamped
                colour = _mix(nodes, links, "ADD", colour, colour)
        elif stage1 == 1:  # GL_DECAL
            node = nodes.new("ShaderNodeMix")
            node.data_type = "RGBA"
            links.new(lightmap.outputs["Alpha"], node.inputs["Factor"])
            links.new(colour, node.inputs[6])
            links.new(lm, node.inputs[7])
            colour = node.outputs[2]
        elif stage1 == 2:  # GL_ADD
            colour = _mix(nodes, links, "ADD", colour, lm)
        elif stage1 == 3:  # GL_REPLACE
            colour = lm
        elif stage1 == 4:  # GL_BLEND with the default black environment colour
            invert = nodes.new("ShaderNodeInvert")
            links.new(lm, invert.inputs["Color"])
            colour = _mix(nodes, links, "MULTIPLY", colour, invert.outputs[0])
    decode = nodes.new("ShaderNodeGroup")
    decode.node_tree = _srgb_decode_group()
    emission = nodes.new("ShaderNodeEmission")
    emission.name = "BOZ Native Unlit"
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.name = "BOZ Transparent"
    alpha_mix = nodes.new("ShaderNodeMixShader")
    alpha_mix.name = "BOZ Alpha Mix"
    mode = item.blend_mode
    links.new(colour, decode.inputs[0])
    links.new(decode.outputs[0], emission.inputs["Color"])
    links.new(alpha, alpha_mix.inputs[0])
    links.new(transparent.outputs[0], alpha_mix.inputs[1])
    links.new(emission.outputs[0], alpha_mix.inputs[2])
    material["boz_native_flags"] = f"0x{item.flags:08x}"
    material["boz_blend_mode"] = mode
    material["boz_stage1_mode"] = stage1
    surface = emission.outputs[0]
    texture_flags = result.textures[item.texture_hashes[0]].flags if primary is not None else 0
    if mode in {1, 4}:  # SRC_ALPHA, ONE_MINUS_SRC_ALPHA
        surface = alpha_mix.outputs[0]
    elif mode == 5 and texture_flags & 8:
        # GL_ALPHA_TEST GREATER 0.75 when the primary texture's flag bit 3 is set.
        cutoff = nodes.new("ShaderNodeMath")
        cutoff.name = "BOZ Native Alpha Test"
        cutoff.operation = "GREATER_THAN"
        links.new(alpha, cutoff.inputs[0])
        cutoff.inputs[1].default_value = 0.75
        links.new(cutoff.outputs[0], alpha_mix.inputs[0])
        surface = alpha_mix.outputs[0]
    elif mode == 2:  # SRC_ALPHA, ONE
        scale = _mix(nodes, links, "MULTIPLY", colour, (1.0, 1.0, 1.0, 1.0))
        if primary is not None:
            links.new(alpha, scale.node.inputs[7])
        links.new(scale, decode.inputs[0])
        add = nodes.new("ShaderNodeAddShader")
        links.new(transparent.outputs[0], add.inputs[0])
        links.new(emission.outputs[0], add.inputs[1])
        surface = add.outputs[0]
    elif mode == 3:  # ZERO, ONE_MINUS_SRC_COLOR
        inverse = nodes.new("ShaderNodeInvert")
        links.new(colour, inverse.inputs["Color"])
        tint = nodes.new("ShaderNodeGroup")
        tint.node_tree = _srgb_decode_group()
        links.new(inverse.outputs[0], tint.inputs[0])
        links.new(tint.outputs[0], transparent.inputs["Color"])
        surface = transparent.outputs[0]
    links.new(surface, output.inputs["Surface"])
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    return material


def _native_materials(result):
    for texture_hash, item in result.textures.items():
        image = _upload_image(f"BOZ Texture {texture_hash:08x}", item)
        image["boz_resource_hash"] = f"0x{texture_hash:08x}"
    for item in result.materials.values():
        _build_material(item, result)


def _display_like_game(scene):
    """The preview reproduces display-encoded colours only under a neutral view transform."""
    view = scene.view_settings
    view.view_transform = "Standard"
    view.look = "None"
    view.exposure = 0.0
    view.gamma = 1.0


def _import_result(self, context, result):
    _native_materials(result)
    meshes, objects = {}, {}
    for item in result.meshes:
        _mesh_object(context, item, meshes, objects)
    _display_like_game(context.scene)
    view.apply_visibility(context)
    context.scene["boz_source_groups"] = "\n".join(result.source_groups)
    context.scene["boz_source_group"] = result.source_groups[0] if len(result.source_groups) == 1 else ""
    for warning in result.warnings:
        self.report({"INFO"}, warning)
    self.report({"INFO"}, f"Imported {len(result.meshes)} objects from "
                          f"{len(result.source_groups)} groups; view transform set to Standard")
    return {"FINISHED"}


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
            return _import_result(self, context, result)
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
            return _import_result(self, context, result)
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
                    obj.data = _build_mesh(fresh)
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


class BOZ_PT_map_tools(Panel):
    bl_label = "BOZ Redux"
    bl_idname = "BOZ_PT_map_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BOZ Redux"

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Build {BUILD}")
        settings = _settings(context)
        if settings is not None:
            box = layout.box()
            box.prop(settings, "client_root", text="Client")
            box.prop(settings, "mod_id", text="Mod")
        layout.operator(BOZ_OT_import_level.bl_idname, icon="FILE_FOLDER")
        layout.operator(BOZ_OT_validate_scene.bl_idname, icon="CHECKMARK")
        row = layout.row(align=True)
        row.operator(BOZ_OT_duplicate_entity.bl_idname, icon="DUPLICATE")
        row.operator(BOZ_OT_delete_entity.bl_idname, icon="TRASH")
        pending = len(_deletions(context.scene))
        if pending:
            layout.label(text=f"{pending} deletions waiting for save", icon="INFO")
        column = layout.column(align=True)
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


CLASSES = (BOZ_AP_preferences, BOZ_OT_import_group, BOZ_OT_import_level, BOZ_OT_export_group,
           BOZ_OT_export_level, BOZ_OT_save_to_mod, BOZ_OT_rebuild_navmesh,
           BOZ_OT_duplicate_entity, BOZ_OT_delete_entity, BOZ_OT_validate_scene, BOZ_PT_map_tools)
