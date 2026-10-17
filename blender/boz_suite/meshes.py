"""Game resources as Blender objects: meshes, materials that draw like the game, markers and the
scene an import makes (bozkit.blender_scene's results). The World tab, the previews and the
shipped-map tools build their objects with these."""
from __future__ import annotations

import json

import bpy
from mathutils import Matrix

try:
    import numpy
except ModuleNotFoundError:  # Blender bundles numpy; the fallback keeps tests portable.
    numpy = None

from ._bozkit import blender_scene

from . import scene_view as view

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


def set_corner_uvs(mesh, name, uvs):
    """Create a face-corner UV layer from per-render-vertex native UVs."""
    layer = mesh.uv_layers.new(name=name)
    corner_vertices = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", corner_vertices)
    converted = [blender_scene.uv_to_blender(value) for value in uvs]
    layer.data.foreach_set("uv", [component for vertex in corner_vertices
                                  for component in converted[vertex]])
    return layer


def build_mesh(item: blender_scene.SceneMesh):
    mesh = bpy.data.meshes.new(item.display_name)
    mesh.from_pydata(item.vertices, item.edges, item.faces)
    mesh.update(calc_edges=True)
    if item.uvs:
        native_uvs = mesh.attributes.new(name="boz_native_uv", type="FLOAT2", domain="POINT")
        native_uvs.data.foreach_set("vector", [c for uv in item.uvs for c in uv])
        set_corner_uvs(mesh, "UVMap", item.uvs).active_render = True
        # Texture stage 1 reads the second UV set. A few lightmapped models have none;
        # sampling the first set keeps them visible instead of reading one lightmap texel.
        set_corner_uvs(mesh, "UVMap2", item.uvs2 or item.uvs)
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
            mesh.materials.append(colour_material(f"BOZ Nav: {name}", NAV_COLOURS[name], 0.35))
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


def collection(context, item: blender_scene.SceneMesh):
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


def colour_material(name, colour, alpha):
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


def glyph_mesh():
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


def mesh_object(context, item: blender_scene.SceneMesh, meshes=None, objects=None):
    """Create one object. Instances of one model share a mesh datablock (``meshes``)."""
    meshes = {} if meshes is None else meshes
    objects = {} if objects is None else objects
    if item.kind in {"entity", "badge", "area"}:
        # Markers are coloured meshes: Blender cannot colour empties.
        colour = MARKER_COLOURS.get(item.category, MARKER_COLOURS["entity"])
        obj = bpy.data.objects.new(item.display_name, glyph_mesh())
        material = colour_material(f"BOZ Marker: {item.category or 'entity'}", colour, 1.0)
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material
        obj.color = (*colour, 1.0)
        obj.hide_render = True
    else:
        mesh = meshes.get(item.mesh_key) if item.mesh_key else None
        if mesh is None:
            mesh = build_mesh(item)
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
        obj.material_slots[0].material = colour_material(f"BOZ Shape: {item.category}", colour,
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
    collection(context, item).objects.link(obj)
    if item.kind in HELPER_KINDS:
        obj.hide_set(True)
    if item.key:
        objects[item.key] = obj
    return obj


def upload_image(name, item):
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


def srgb_decode_group():
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


def mix(nodes, links, blend, a, b, factor=1.0):
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


def build_material(item: blender_scene.SceneMaterial, result):
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
        colour = mix(nodes, links, "MULTIPLY", primary.outputs["Color"], colour)
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
            colour = mix(nodes, links, "MULTIPLY", colour, lm)
            for _ in range({5: 1, 6: 2}.get(stage1, 0)):  # GL_RGB_SCALE 2 or 4, clamped
                colour = mix(nodes, links, "ADD", colour, colour)
        elif stage1 == 1:  # GL_DECAL
            node = nodes.new("ShaderNodeMix")
            node.data_type = "RGBA"
            links.new(lightmap.outputs["Alpha"], node.inputs["Factor"])
            links.new(colour, node.inputs[6])
            links.new(lm, node.inputs[7])
            colour = node.outputs[2]
        elif stage1 == 2:  # GL_ADD
            colour = mix(nodes, links, "ADD", colour, lm)
        elif stage1 == 3:  # GL_REPLACE
            colour = lm
        elif stage1 == 4:  # GL_BLEND with the default black environment colour
            invert = nodes.new("ShaderNodeInvert")
            links.new(lm, invert.inputs["Color"])
            colour = mix(nodes, links, "MULTIPLY", colour, invert.outputs[0])
    decode = nodes.new("ShaderNodeGroup")
    decode.node_tree = srgb_decode_group()
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
        scale = mix(nodes, links, "MULTIPLY", colour, (1.0, 1.0, 1.0, 1.0))
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
        tint.node_tree = srgb_decode_group()
        links.new(inverse.outputs[0], tint.inputs[0])
        links.new(tint.outputs[0], transparent.inputs["Color"])
        surface = transparent.outputs[0]
    links.new(surface, output.inputs["Surface"])
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    return material


def native_materials(result):
    for texture_hash, item in result.textures.items():
        image = upload_image(f"BOZ Texture {texture_hash:08x}", item)
        image["boz_resource_hash"] = f"0x{texture_hash:08x}"
    for item in result.materials.values():
        build_material(item, result)


def display_like_game(scene):
    """The preview reproduces display-encoded colours only under a neutral view transform."""
    view = scene.view_settings
    view.view_transform = "Standard"
    view.look = "None"
    view.exposure = 0.0
    view.gamma = 1.0


def import_result(self, context, result):
    native_materials(result)
    meshes, objects = {}, {}
    for item in result.meshes:
        mesh_object(context, item, meshes, objects)
    display_like_game(context.scene)
    view.apply_visibility(context)
    context.scene["boz_source_groups"] = "\n".join(result.source_groups)
    context.scene["boz_source_group"] = result.source_groups[0] if len(result.source_groups) == 1 else ""
    for warning in result.warnings:
        self.report({"INFO"}, warning)
    self.report({"INFO"}, f"Imported {len(result.meshes)} objects from "
                          f"{len(result.source_groups)} groups; view transform set to Standard")
    return {"FINISHED"}
