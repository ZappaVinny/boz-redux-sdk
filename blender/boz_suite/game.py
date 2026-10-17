"""Game models in the editor: meshes built from the SDK's asset library, cached per model.

Placed game entities (perks, the power switch, ...) and game model instances show the model the
game will draw. These meshes are previews: editing them changes nothing in the game unless the
object is turned into a project prop (Make prop).
"""
from __future__ import annotations

import bpy

from ._bozkit import blender_scene, chalk, levels, library, maps, native, resources, toolkit, world
from ._bozkit import spec_fields
from ._bozkit import hashing
from . import meshes
iw_hash = hashing.iw_hash

PREFIX = "BOZ game"
MATERIAL_PREFIX = "BOZ Material"   # the add-on's game materials
_state: dict = {}


def game_models():
    """world._GameModels over the asset library, or None when there is no library."""
    if "models" not in _state:
        try:
            _state["models"] = world._GameModels(library.LibraryPack())
        except library.LibraryError:
            _state["models"] = None
    return _state["models"]


class _Found:
    """What the mesh builders (boz_suite.meshes) read: decoded textures and materials of one model."""

    def __init__(self):
        self.textures, self.materials = {}, {}


def model_mesh(path: str, model_hash: int):
    """The Blender mesh of a game model (built once, then shared), or None."""
    name = f"{PREFIX} model {model_hash:08x}"
    mesh = bpy.data.meshes.get(name)
    if mesh is not None:
        return mesh
    models = game_models()
    if models is None:
        return None
    try:
        found = models.resources(path, model_hash)
        body = found[levels.MODEL][0][1]
        model = native.decode_model(body)
    except (world.WorldError, ValueError, IndexError, KeyError):
        return None
    materials = dict(found[levels.MATERIAL])
    textures = dict(found[levels.TEXTURE])
    result = _Found()
    for material_hash, material_body in materials.items():
        try:
            material = native.decode_material(material_body)
        except ValueError:
            continue
        diffuse = tuple(material.colours[0]) if material.colours else (255, 255, 255, 255)
        result.materials[material_hash] = blender_scene.SceneMaterial(
            material_hash, list(material.textures), diffuse, material.flags)
        for texture_hash in material.textures[:2]:
            if texture_hash in textures and texture_hash not in result.textures:
                try:
                    decoded = native.decode_texture_rgba(textures[texture_hash])
                except ValueError:
                    continue
                result.textures[texture_hash] = blender_scene.SceneTexture(
                    texture_hash, decoded.width, decoded.height, decoded.rgba, decoded.format,
                    int.from_bytes(textures[texture_hash][:4], "little"))
    meshes.native_materials(result)
    item = blender_scene.SceneMesh(
        "model", levels.MODEL, model_hash, 0, path, name, "BOZ game models",
        [blender_scene.to_blender(tuple(map(float, v))) for v in model.vertices],
        list(model.triangles), uvs=model.uvs, face_materials=model.face_materials,
        material_hashes=blender_scene.model_materials(body, set(materials)),
        vertex_colours=model.vertex_colours, uvs2=model.uvs2)
    mesh = meshes.build_mesh(item)
    mesh.name = name
    mesh["boz_game_model"] = f"{path}#0x{model_hash:08x}"
    return mesh


def _native_matrix(position, rotation, scale):
    """A game (position, x/y/z/w rotation, scale) transform as a Blender-axes matrix."""
    from mathutils import Matrix, Quaternion, Vector

    x, y, z, w = rotation
    native = (Matrix.Translation(Vector(position)) @ Quaternion((w, x, y, z)).to_matrix().to_4x4()
              @ Matrix.Diagonal((*scale, 1.0)))
    to_native = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
    return to_native.inverted() @ native @ to_native


def _drawn_model(spec):
    """(model hash, game transform of the drawing entity relative to *spec*'s position and
    rotation: *spec*'s own scale, then its children's transforms) of the first model an entity
    or its children draw, or None."""
    model = spec_fields.model_reference(spec)
    own_scale = spec_fields.local_transform(spec)[2]
    if model:
        return model, [((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), own_scale)]
    for _cls, _reserved, child in spec.children:
        renderable = spec_fields.component(child, "CIsRenderableModel")
        if renderable is None or renderable.blob is None:
            continue
        assets = world.blob_assets(renderable.blob)
        if assets:
            return assets[0][1][0], [spec_fields.local_transform(child),
                                     ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), own_scale)]
    return None


def _model_group(models, base: str, model: int, group_path: str):
    """The group with an entity's model: its own map's groups first (a door from another map
    keeps its model in that map's rooms), then the base level's, then any level's."""
    gear = maps.gear(base)
    prefer = (models.map_paths(group_path) if group_path else []) + [
        f"levels/{base}/{base}_dynamics.group.bin", world.INGAME,
        f"levels/{base}/{base}_statics.group.bin", f"ingame/weapons/weapons_{gear}.group.bin"]
    return models.find_model(model, [p for p in dict.fromkeys(prefer) if p])


def entity_spec(base: str, source_hash: int, group_path: str = ""):
    models = game_models()
    if models is None:
        return None
    statics = f"levels/{base}/{base}_statics.group.bin"
    try:
        body = models.find(levels.ENTITY_SPEC, source_hash, [group_path or statics])
        return resources.decode_entity_spec(body) if body else None
    except (world.WorldError, ValueError, KeyError):
        return None


def entity_mesh(base: str, source_hash: int, group_path: str = "", model_override=None,
                source_mesh=None):
    """The mesh an entity draws, placed as the game places it (its own scale, children's
    transforms), or None. *model_override*: (group path, model hash) of a different model for
    the same drawing entity (a wall buy's chosen weapon); *source_mesh*: mesh data in that model's
    units instead (a weapon's own model)."""
    spec = entity_spec(base, source_hash, group_path)
    if spec is None:
        return None
    drawn = _drawn_model(spec)
    if drawn is None:
        return None
    model, chain = drawn
    if source_mesh is not None:
        source = source_mesh
        model = iw_hash(source_mesh.name)
    else:
        models = game_models()
        path = model_override[0] if model_override else _model_group(models, base, model, group_path)
        if model_override:
            model = model_override[1]
        if path is None:
            return None
        source = model_mesh(path, model)
    if source is None:
        return None
    from mathutils import Matrix

    matrix = Matrix.Identity(4)
    for position, rotation, scale in chain:
        matrix = _native_matrix(position, rotation, scale) @ matrix
    if all(abs(matrix[i][j] - (1.0 if i == j else 0.0)) < 1e-6 for i in range(4) for j in range(4)):
        return source
    name = f"{PREFIX} entity {source_hash:08x} {model:08x}"
    mesh = bpy.data.meshes.get(name)
    if mesh is not None and source_mesh is not None:
        bpy.data.meshes.remove(mesh)           # your model may have changed: placed again
        mesh = None
    if mesh is None:
        mesh = source.copy()
        mesh.name = name
        mesh.transform(matrix)
    return mesh


def weapon_model(base: str, weapon: str):
    """(group path, model hash) a wall buy shows for a weapon of the level, or None."""
    models = game_models()
    if models is None:
        return None
    gear = maps.gear(base)
    path = f"ingame/weapons/weapons_{gear}.group.bin"
    value = int(weapon, 16) if weapon.startswith("0x") else iw_hash(weapon)
    try:
        weapons = models.group(path)
    except world.WorldError:
        return None
    for resource_type in weapons.types():
        if resource_type.class_hash != levels.ENTITY_SPEC:
            continue
        for resource in resource_type.resources:
            if resource.in_group_hash != value:
                continue
            blob = resources.decode_entity_spec(resource.body).components[0].blob
            found = []
            for prop in blob.properties:
                if prop.nested is not None:
                    found += world.blob_assets(prop.nested)
            low = next((pair for name, pair in found if name == iw_hash("LOD1")), None)
            pair = low or (found[-1][1] if found else None)
            return (path, pair[0]) if pair else None
    return None


def weapon_names(base: str) -> list[str]:
    """Names of the weapons in a level's weapons group (what a wall buy can sell)."""
    models = game_models()
    if models is None:
        return []
    gear = maps.gear(base)
    try:
        weapons = models.group(f"ingame/weapons/weapons_{gear}.group.bin")
    except world.WorldError:
        return []
    known = names()
    out = []
    for resource_type in weapons.types():
        if resource_type.class_hash == levels.ENTITY_SPEC:
            out += [known.get(r.in_group_hash, f"0x{r.in_group_hash:08x}")
                    for r in resource_type.resources]
    return sorted(set(out), key=str.lower)


def names() -> dict[int, str]:
    """Hash -> name from the asset library's recovered names."""
    if "names" not in _state:
        found = {}
        try:
            text = (library.library_dir() / "names.txt").read_text(encoding="latin-1")
        except OSError:
            text = ""
        for line in text.split():
            found.setdefault(iw_hash(line), line)
        _state["names"] = found
    return _state["names"]


def resolve_piece(base: str, key: str):
    """The toolkit piece *key* on *base* (bozkit.toolkit.Resolved), or None."""
    models = game_models()
    if models is None:
        return None
    return toolkit.resolve(models.pack, base, key, names())


def ensure_colour(mesh) -> None:
    """Game materials multiply by the vertex colour attribute; meshes without one get white."""
    if mesh is None or mesh.color_attributes.get("boz_native_colour") is not None:
        return
    colours = mesh.color_attributes.new(name="boz_native_colour", type="FLOAT_COLOR",
                                        domain="CORNER")
    colours.data.foreach_set("color", [1.0] * (4 * len(mesh.loops)))


def texture_material(path: str, texture_hash: int):
    """A material that draws a game texture the way the game draws it (the shipped-map tools'
    game shading), or None."""
    models = game_models()
    if models is None:
        return None
    body = models.find(levels.TEXTURE, texture_hash, [path, world.INGAME])
    if body is None:
        return None
    try:
        decoded = native.decode_texture_rgba(body)
    except ValueError:
        return None
    result = _Found()
    result.textures[texture_hash] = blender_scene.SceneTexture(
        texture_hash, decoded.width, decoded.height, decoded.rgba, decoded.format,
        int.from_bytes(body[:4], "little"))
    meshes.native_materials(result)   # uploads "BOZ Texture <hash>"
    item = blender_scene.SceneMaterial(texture_hash, [texture_hash])
    material = meshes.build_material(item, result)
    material["boz_texture_source"] = f"{path}#0x{texture_hash:08x}"
    return material


def decals():
    """Each weapon's shipped chalk decal (bozkit.chalk.find_decals, cached in the library)."""
    if "decals" not in _state:
        models = game_models()
        _state["decals"] = chalk.find_decals(models.pack, library.library_dir() / "chalks.json") \
            if models else {}
    return _state["decals"]


def _image_from_bgra(name: str, width: int, height: int, bgra: bytes):
    image = bpy.data.images.get(name) or bpy.data.images.new(name, width=width, height=height,
                                                                alpha=True)
    if tuple(image.size) != (width, height):
        image.scale(width, height)
    values = []
    stride = width * 4
    for row in range(height - 1, -1, -1):
        line = bgra[row * stride:(row + 1) * stride]
        for x in range(width):
            b, g, r, a = line[x * 4:x * 4 + 4]
            values += (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    image.pixels.foreach_set(values)
    image.update()
    image.pack()
    return image


def chalk_preview(base: str, weapon: str, mode: str, project_source=None):
    """(mesh, decal) of the chalk a wall buy gets: the weapon's shipped decal, an image, or an
    outline drawn from the weapon model; None for no chalk."""
    if mode == "none":
        return None
    found = decals()
    if not found:
        return None
    value = int(weapon, 16) if weapon.startswith("0x") else iw_hash(weapon)
    template = found.get(iw_hash("KQX")) or next(iter(found.values()))
    decal = found.get(value) if mode == "" else None
    models = game_models()
    if decal is not None:
        path = models.find_model(decal.model, models.map_paths(decal.group))
        mesh = model_mesh(path, decal.model) if path else None
        return (mesh, decal) if mesh else None
    if mode and project_source is not None:
        try:
            texture = world.read_texture(project_source / mode)
        except (OSError, ValueError):
            return None
        name = f"{PREFIX} chalk {mode}"
    else:
        located = weapon_model(base, weapon)
        if located is None:
            return None
        body = models.find(levels.MODEL, located[1], [located[0]])
        if body is None:
            return None
        model = native.decode_model(body)
        width, height = chalk.SIZE
        texture = world.Texture(width, height, chalk.draw(model.vertices, model.triangles, value))
        name = f"{PREFIX} chalk {weapon}"
    path = models.find_model(template.model, models.map_paths(template.group))
    quad = model_mesh(path, template.model) if path else None
    if quad is None:
        return None
    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        mesh = quad.copy()
        mesh.name = name
        mesh.materials.clear()
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.name = "BOZ Primary"
        image_node.image = _image_from_bgra(name, texture.width, texture.height, texture.bgra)
        emission = nodes.new("ShaderNodeEmission")
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        add = nodes.new("ShaderNodeAddShader")   # chalk is white on black: add it like a decal
        output = nodes.new("ShaderNodeOutputMaterial")
        links.new(image_node.outputs["Color"], emission.inputs["Color"])
        links.new(emission.outputs[0], add.inputs[0])
        links.new(transparent.outputs[0], add.inputs[1])
        links.new(add.outputs[0], output.inputs["Surface"])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "BLENDED"
        mesh.materials.append(material)
    return mesh, template
