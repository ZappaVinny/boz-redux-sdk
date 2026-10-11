"""The project's world (bozkit.world) and the Blender scene, both ways.

Every object has a role (object.boz.role):

- **mesh**: level geometry; written in world space with its collision setting.
- **prop**: a project prop instance. Objects that share mesh data (Alt+D) are instances of one
  prop; the mesh is written in its own space, and each object places it.
- **model**: an instance of a game model from the asset library (``group#0xhash``).
- **entity**: a copy of a game entity (perks, spawns, the power switch, ...), shown with the
  model the game draws for it when it has one.
- **base**: one of the base level's own entities in a map that inherits it (perks, doors, wall
  buys, spawns, ...). Moved, edited or duplicated ones are written as placements of the base
  entity; deleted ones go in the world's ``removed`` list.
- **reference**: the rest of the base level (rooms, their models, decals), shown read only; the
  game gets the level itself, so these are never written.

One Blender unit is one game centimetre; Blender's Z is the game's Y.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import bpy

try:
    from bozkit import blender_scene, toolkit, world
except ModuleNotFoundError:
    from ._vendor.bozkit import blender_scene, toolkit, world

from . import game

_SAFE = str.maketrans({c: "_" for c in " .-/\\()[]{}:;,'\"!?"})


def game_name(text: str) -> str:
    """A name the world format accepts, made from an object or mesh name."""
    name = text.lower().translate(_SAFE)
    name = "".join(c for c in name if c.isalnum() or c == "_").strip("_")[:32] or "mesh"
    return name if name[0].isalpha() else f"m_{name}"[:32]


def mesh_name(obj) -> str:
    uses_data = obj.boz.role == "prop" or obj.get("boz_custom_model")
    return game_name(obj.data.name if uses_data and obj.data else obj.name)


# Images and materials


def _image_from_texture(name: str, texture: "world.Texture", path: Path | None):
    if path is not None and path.is_file():
        image = bpy.data.images.load(str(path), check_existing=True)
        image.reload()
        return image
    image = bpy.data.images.new(name, width=texture.width, height=texture.height, alpha=True)
    stride = texture.width * 4
    rgba = world._bgra_to_rgba(texture.bgra)
    values = []
    for row in range(texture.height - 1, -1, -1):
        values.extend(channel / 255.0 for channel in rgba[row * stride:(row + 1) * stride])
    image.pixels.foreach_set(values)
    image.update()
    image.pack()
    return image


def material_for(name: str, image):
    """A project material as the game draws it: the texture, unlit (no scene lighting)."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    node = nodes.new("ShaderNodeTexImage")
    node.name = "BOZ Primary"
    node.image = image
    node.interpolation = "Closest"
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(node.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def image_of(material):
    """A material's main texture: the game material's primary stage, else the first image."""
    if material is None or not material.use_nodes:
        return None
    nodes = material.node_tree.nodes
    primary = nodes.get("BOZ Primary")
    if primary is not None and primary.type == "TEX_IMAGE" and primary.image is not None:
        return primary.image
    return next((node.image for node in nodes
                 if node.type == "TEX_IMAGE" and node.image is not None
                 and node.name != "BOZ Lightmap"), None)


def texture_of_image(image) -> "world.Texture":
    path = Path(bpy.path.abspath(image.filepath)) if image.filepath and not image.packed_file else None
    if path and path.is_file() and not image.is_dirty:
        return world.read_texture(path)
    width, height = image.size
    pixels = [0.0] * (width * height * 4)
    image.pixels.foreach_get(pixels)    # floats, bottom row first
    out = bytearray()
    for y in range(height - 1, -1, -1):
        row = pixels[y * width * 4:(y + 1) * width * 4]
        for x in range(width):
            r, g, b, a = row[x * 4:x * 4 + 4]
            out += bytes((int(b * 255 + 0.5), int(g * 255 + 0.5), int(r * 255 + 0.5),
                          int(a * 255 + 0.5)))
    return world.Texture(width, height, bytes(out))


# World -> scene


def _mesh_data(mesh: "world.Mesh", source: Path, data_name: str):
    data = bpy.data.meshes.new(data_name)
    data.from_pydata([blender_scene.to_blender(v) for v in mesh.vertices], [],
                     [tuple(t) for t in mesh.triangles])
    layer = data.uv_layers.new(name="UVMap")
    corner_vertices = [0] * len(data.loops)
    data.loops.foreach_get("vertex_index", corner_vertices)
    layer.data.foreach_set("uv", [c for v in corner_vertices
                                  for c in blender_scene.uv_to_blender(mesh.uvs[v])])
    files = world._texture_files(mesh.name, len(mesh.textures))
    for index, (texture, relative) in enumerate(zip(mesh.textures, files)):
        image = _image_from_texture(Path(relative).stem, texture, source / relative)
        data.materials.append(material_for(f"{mesh.name}_{index}" if index else mesh.name, image))
    if mesh.face_textures:
        data.polygons.foreach_set("material_index", mesh.face_textures)
    data.update()
    return data


FIELD_PREFIX = "boz_f:"   # object custom properties holding a piece's settings


def _place(obj, item, scene) -> None:
    """Position, rotation and scale of a world instance or entity, in Blender's axes."""
    from mathutils import Quaternion

    x, y, z, w = blender_scene.rotation_to_blender(item.quaternion())
    obj.location = blender_scene.to_blender(item.position)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion((w, x, y, z))
    obj.scale = blender_scene.scale_to_blender(item.scale)
    scene.collection.objects.link(obj)


def _transform(obj):
    """(position, x/y/z/w rotation, scale) of an object in the game's axes."""
    location, rotation, scale = obj.matrix_world.decompose()
    native = blender_scene.rotation_from_blender((rotation.x, rotation.y, rotation.z, rotation.w))
    return (tuple(blender_scene.from_blender(tuple(location))),
            tuple(round(c, 6) for c in native),
            tuple(round(c, 5) for c in blender_scene.scale_from_blender(tuple(scale))))


CHALK_NAME = "chalk"


def refresh_chalk(obj, base: str) -> None:
    """Show a wall buy's chalk as a locked child object (written by the compiler, not by the
    editor: bozkit.world adds the decal from the wall buy's settings)."""
    from mathutils import Quaternion

    for child in list(obj.children):
        if child.get("boz_chalk"):
            bpy.data.objects.remove(child)
    weapon = obj.get(FIELD_PREFIX + toolkit.WEAPON_FIELD)
    if obj.boz.role != "entity" or not weapon:
        return
    from . import link
    root = link.project_root()
    mode = str(obj.get(FIELD_PREFIX + world.CHALK_FIELD, ""))
    found = game.chalk_preview(base, str(weapon), mode, root / "source" if root else None)
    if found is None:
        return
    mesh, decal = found
    child = bpy.data.objects.new(f"{obj.name} {CHALK_NAME}", mesh)
    child["boz_chalk"] = True
    child.boz.role = "reference"
    child.hide_select = True
    for collection in obj.users_collection:
        collection.objects.link(child)
    child.parent = obj
    x, y, z, w = blender_scene.rotation_to_blender(decal.rotation)
    child.location = blender_scene.to_blender(decal.position)
    child.rotation_mode = "QUATERNION"
    child.rotation_quaternion = Quaternion((w, x, y, z))
    child.scale = blender_scene.scale_to_blender(decal.scale)


MARKER_MESH = "BOZ Marker Cube"
MARKER_SIZE = 12.0


def marker_mesh():
    """A small cube shared by every marker (entities that draw no model of their own)."""
    mesh = bpy.data.meshes.get(MARKER_MESH)
    if mesh is None:
        s = MARKER_SIZE
        vertices = [(x, y, z) for x in (-s, s) for y in (-s, s) for z in (0.0, 2 * s)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        mesh = bpy.data.meshes.new(MARKER_MESH)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        mesh.materials.append(None)   # one slot; each marker links its own colour to it
    return mesh


def entity_category(base: str, source_hash: int, group_path: str = "") -> str:
    spec = game.entity_spec(base, source_hash, group_path)
    if spec is None:
        return "entity"
    return blender_scene._category(blender_scene._component_names(spec))


def colour_marker(obj, category: str) -> None:
    """Make *obj* a marker cube coloured by what the entity is (the shipped-map add-on's
    colours: perks violet, doors orange, wall buys green, triggers teal, ...)."""
    tools = game._tools()
    colour = tools.MARKER_COLOURS.get(category, tools.MARKER_COLOURS["entity"])
    if obj.data is not marker_mesh():
        obj.data = marker_mesh()
    obj.material_slots[0].link = "OBJECT"
    obj.material_slots[0].material = tools._colour_material(f"BOZ Marker: {category}", colour, 1.0)
    obj.color = (*colour, 1.0)
    obj.hide_render = True
    obj["boz_marker"] = category
    # The add-on's Markers switch (and its marker types) shows and hides it.
    obj["boz_kind"] = obj.get("boz_kind", "entity")
    obj["boz_category"] = category


def is_marker(obj) -> bool:
    return obj.type == "MESH" and obj.data is not None and obj.data.name.startswith(MARKER_MESH)


def show_mesh(obj, data) -> None:
    """Draw *data* on *obj* (a game model in place of a marker, or another weapon)."""
    obj.data = data
    for slot in obj.material_slots:
        slot.link = "DATA"
    obj.color = (1.0, 1.0, 1.0, 1.0)
    for key in ("boz_marker", "boz_category"):
        if key in obj:
            del obj[key]
    if obj.get("boz_kind") == "entity":
        del obj["boz_kind"]   # a model now: not hidden with the markers


def entity_object(entity: "world.Placement", base: str, scene, custom=None):
    """An object for a game entity: its game model (or *custom*, a project prop's mesh), or a
    coloured marker cube when it draws nothing."""
    weapon = (entity.settings or entity.fields).get(toolkit.WEAPON_FIELD)
    override = game.weapon_model(base, str(weapon)) if weapon else None
    data = custom or game.entity_mesh(base, entity.hash, entity.group, override)
    obj = bpy.data.objects.new(entity.source, data or marker_mesh())
    if data is None:
        colour_marker(obj, entity_category(base, entity.hash, entity.group))
    obj.boz.role = "entity"
    obj.boz.source = entity.source
    obj.boz.group = entity.group
    if custom is not None:
        obj["boz_custom_model"] = True
    if entity.piece:
        obj["boz_piece"] = entity.piece
    _field_props(obj, entity.settings or entity.fields)
    _place(obj, entity, scene)
    if weapon:
        refresh_chalk(obj, base)
    return obj


def model_object(instance: "world.Instance", scene):
    path, model_hash = instance.model_ref()
    data = game.model_mesh(path, model_hash)
    obj = bpy.data.objects.new(f"model {model_hash:08x}", data)
    if data is None:
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 50.0
    obj.boz.role = "model"
    obj.boz.source = instance.model
    obj.boz.collision = instance.collision
    obj.boz.shape = instance.shape
    _place(obj, instance, scene)
    return obj


BASE_COLLECTION = "Base level (read only)"


class _Reports:
    def __init__(self):
        self.messages = []

    def report(self, _kind, message):
        self.messages.append(message)


def show_base_level(scene, base: str) -> int:
    """Show the base level an inherited map starts from, read only (its rooms, models and
    entities, through the shipped-map tools). Returns the number of objects shown."""
    import importlib

    try:
        from bozkit import library
    except ModuleNotFoundError:
        from ._vendor.bozkit import library
    tools = importlib.import_module("boz_redux.operators")
    folder = library.library_dir() / "groups" / "levels" / base
    editable, references = tools.blender_scene.level_groups(str(folder), None)
    result = tools.blender_scene.import_groups(editable, references, include_models=False,
                                               include_collision=False, include_portals=False,
                                               include_navigation=False)
    before = set(bpy.data.objects)
    scene.boz_show_markers = True   # markers of triggers, effects, spawns, ...
    tools._import_result(_Reports(), bpy.context, result)
    shown = [obj for obj in bpy.data.objects if obj not in before]
    collection = bpy.data.collections.get(BASE_COLLECTION) or bpy.data.collections.new(BASE_COLLECTION)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    for obj in shown:
        obj.boz.role = "reference"
        obj.hide_select = True
        if collection not in obj.users_collection:
            collection.objects.link(obj)
    make_base_editable(scene, base)
    return len(shown)


BASE_ENTITIES = "Base level entities"
BASE_KINDS = ("placed_model", "entity")


def _entity_hash(obj) -> str:
    kind = obj.get("boz_kind")
    if kind == "placed_model" and not obj.get("boz_instance_path"):
        return str(obj.get("boz_instance_resource_hash", ""))
    if kind == "entity":
        return str(obj.get("boz_resource_hash", ""))
    return ""


def _base_specs(base: str) -> dict:
    """The base level's own entities (its statics group): "0x<hash>" -> EntitySpec."""
    try:
        from bozkit import group, levels, library, resources
    except ModuleNotFoundError:
        from ._vendor.bozkit import group, levels, library, resources
    path = library.library_dir() / "groups" / "levels" / base / f"{base}_statics.group.bin"
    try:
        parsed = group.parse(path.read_bytes())
    except (OSError, ValueError):
        return {}
    specs = {}
    for resource_type in parsed.types():
        if resource_type.class_hash != levels.ENTITY_SPEC:
            continue
        for item in resource_type.resources:
            try:
                specs[f"0x{item.in_group_hash:08x}"] = resources.decode_entity_spec(item.body)
            except ValueError:
                continue
    return specs


def make_base_editable(scene, base: str) -> int:
    """Give the base level's own entities (perks, doors, wall buys, spawns, triggers, ...) the
    base role: selectable, with their settings, written when they change. Room geometry stays
    read only. Entities without a model show as coloured cubes."""
    specs = _base_specs(base)
    collection = bpy.data.collections.get(BASE_ENTITIES) or bpy.data.collections.new(BASE_ENTITIES)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    names = game.names()
    known = []
    bpy.context.view_layer.update()   # world matrices of the objects just made
    for obj in list(scene.objects):
        if obj.boz.role != "reference" or obj.get("boz_kind") not in BASE_KINDS:
            continue
        source = _entity_hash(obj)
        spec = specs.get(source)
        if spec is None or source in known or source == "0x00000000" or (
                obj.parent is not None and _entity_hash(obj.parent) == source):
            continue   # unnamed entities cannot be told apart; one object edits each entity
        category = obj.get("boz_category") or blender_scene._category(
            blender_scene._component_names(spec))
        if category in ("collision", "area"):
            continue
        if obj.get("boz_kind") == "entity":
            colour_marker(obj, category)
        obj.boz.role = "base"
        obj.boz.source = source
        obj.boz.group = ""
        obj.hide_select = False
        obj["boz_base_origin"] = [c for part in _transform(obj) for c in part]
        key, values = toolkit.settings_for(spec, names)
        if key:
            obj["boz_piece"] = key
            _field_props(obj, values)
            obj["boz_base_values"] = json.dumps(values, sort_keys=True)
        for users in list(obj.users_collection):
            users.objects.unlink(obj)
        collection.objects.link(obj)
        known.append(source)
    for obj in scene.objects:
        # Effects, triggers and sounds of the rooms stay read only, as cubes too.
        if obj.boz.role == "reference" and obj.get("boz_kind") == "entity" and not is_marker(obj):
            colour_marker(obj, obj.get("boz_category") or "entity")
    scene["boz_base_entities"] = sorted(set(known))
    return len(known)


def tidy_removed(scene, removed) -> None:
    """Drop what was shown on base entities taken out of the map (their badges and volumes are
    left behind, unparented, when the entity is deleted)."""
    removed = set(removed)
    for obj in list(scene.objects):
        if obj.boz.role != "reference" or obj.parent is not None:
            continue
        if str(obj.get("boz_instance_resource_hash") or obj.get("boz_resource_hash")) in removed \
                and obj.get("boz_kind") in ("badge", "shape", "placed_model", "entity"):
            bpy.data.objects.remove(obj)


def base_values(obj) -> dict:
    try:
        return json.loads(obj.get("boz_base_values", "{}"))
    except ValueError:
        return {}


def _base_changes(obj) -> tuple[dict, bool]:
    """(changed settings, whether the object moved) of a base entity."""
    origin = list(obj.get("boz_base_origin", []))
    position, rotation, scale = _transform(obj)
    now = [*position, *rotation, *scale]
    moved = len(origin) != 10 or any(abs(a - b) > 1e-3 for a, b in zip(now, origin))
    if not moved and len(origin) == 10:
        # The same rotation can come back negated.
        flipped = [*position, *(-c for c in rotation), *scale]
        moved = any(abs(a - b) > 1e-3 for a, b in zip(flipped, origin)) and \
            any(abs(a - b) > 1e-3 for a, b in zip(now, origin))
    original = base_values(obj)
    changed = {key: value for key, value in _panel_values(obj).items()
               if key != world.CHALK_FIELD and original.get(key) != value}
    return changed, moved


def reset_base(obj) -> None:
    """Put a base entity back where the level has it, with its own settings."""
    from mathutils import Quaternion

    origin = list(obj.get("boz_base_origin", []))
    if len(origin) == 10:
        obj.matrix_parent_inverse.identity()
        obj.parent = None
        x, y, z, w = blender_scene.rotation_to_blender(tuple(origin[3:7]))
        obj.location = blender_scene.to_blender(tuple(origin[0:3]))
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = Quaternion((w, x, y, z))
        obj.scale = blender_scene.scale_to_blender(tuple(origin[7:10]))
    _field_props(obj, base_values(obj))


def _apply_base_edit(obj, entity: "world.Placement", custom=None) -> None:
    """Show a saved edit of a base entity (when map.blend is rebuilt from the world source)."""
    from mathutils import Quaternion

    origin = list(obj.get("boz_base_origin", []))
    x, y, z, w = blender_scene.rotation_to_blender(entity.quaternion())
    obj.location = blender_scene.to_blender(entity.position)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion((w, x, y, z))
    own = origin[7:10] if len(origin) == 10 else (1.0, 1.0, 1.0)
    obj.scale = blender_scene.scale_to_blender(tuple(own[i] * entity.scale[i] for i in range(3)))
    _field_props(obj, entity.settings)
    if custom is not None:
        show_mesh(obj, custom)
        obj["boz_custom_model"] = True


def world_to_scene(source_world: "world.World", source: Path, scene) -> None:
    scene.boz.base = source_world.base
    scene.boz.inherit = source_world.inherit
    if source_world.inherit:
        show_base_level(scene, source_world.base)
    for mesh in source_world.meshes:
        obj = bpy.data.objects.new(mesh.name, _mesh_data(mesh, source, mesh.name))
        obj.boz.role = "mesh"
        obj.boz.collision = mesh.collision
        obj.boz.double_sided = mesh.double_sided
        scene.collection.objects.link(obj)
    props = {prop.name: _mesh_data(prop, source, prop.name) for prop in source_world.props}
    settings = {prop.name: prop for prop in source_world.props}
    for instance in source_world.instances:
        if instance.prop:
            prop = settings[instance.prop]
            obj = bpy.data.objects.new(prop.name, props[prop.name])
            obj.boz.role = "prop"
            obj.boz.collision = prop.collision
            obj.boz.shape = prop.shape
            obj.boz.double_sided = prop.double_sided
            _place(obj, instance, scene)
        else:
            model_object(instance, scene)
    base_objects = defaultdict(list)
    for obj in scene.objects:
        if obj.boz.role == "base":
            base_objects[obj.boz.source].append(obj)
    for source in source_world.removed:
        for obj in base_objects.pop(source, []):
            bpy.data.objects.remove(obj)
    edited = set()
    for entity in source_world.entities:
        custom = props.get(entity.prop) if entity.prop else None
        source = f"0x{entity.hash:08x}"
        if not entity.piece and not entity.group and base_objects.get(source):
            obj = base_objects[source][0]
            if source in edited:
                # A second placement of the same base entity: a copy of it.
                obj = obj.copy()
                for collection in base_objects[source][0].users_collection:
                    collection.objects.link(obj)
            edited.add(source)
            _apply_base_edit(obj, entity, custom)
            continue
        entity_object(entity, source_world.base, scene, custom)


def show_game_models(scene) -> int:
    """Give entities and game models that are still empties their game mesh, or a coloured
    marker cube when they draw nothing (maps made before the editor could show them, or before
    the asset library was built)."""
    changed = 0
    if game.game_models() is None:
        return 0
    for obj in list(scene.objects):
        if obj.type != "EMPTY" or obj.boz.role not in ("entity", "model") or not obj.boz.source:
            continue
        if obj.boz.role == "entity":
            entity = world.Placement(obj.boz.source, (0.0, 0.0, 0.0), 0.0, obj.boz.group)
            data = game.entity_mesh(scene.boz.base, entity.hash, obj.boz.group)
        else:
            data = game.model_mesh(*world.Instance((0, 0, 0), model=obj.boz.source).model_ref())
            if data is None:
                continue
        replacement = bpy.data.objects.new(obj.name, data or marker_mesh())
        if data is None:
            colour_marker(replacement, entity_category(scene.boz.base, entity.hash, obj.boz.group)
                          if obj.boz.role == "entity" else "entity")
        replacement.matrix_world = obj.matrix_world
        for key in ("role", "source", "group", "collision", "shape", "double_sided"):
            setattr(replacement.boz, key, getattr(obj.boz, key))
        for key, value in obj.items():
            replacement[key] = value
        for collection in obj.users_collection:
            collection.objects.link(replacement)
        bpy.data.objects.remove(obj)
        replacement.name = replacement.name.split(".")[0]
        changed += 1
    return changed


# Scene -> world


def _geometry(obj, data, matrix):
    """(vertices, uvs, triangles, triangle material slots) of evaluated mesh data; positions go
    through *matrix* (world space for level meshes, identity for props)."""
    data.calc_loop_triangles()
    uv_layer = data.uv_layers.active
    vertices, uvs, triangles, slots, index = [], [], [], [], {}
    for triangle in data.loop_triangles:
        corners = []
        for loop_index in triangle.loops:
            loop = data.loops[loop_index]
            uv = tuple(uv_layer.data[loop_index].uv) if uv_layer else (0.0, 0.0)
            key = (loop.vertex_index, round(uv[0], 6), round(uv[1], 6))
            if key not in index:
                index[key] = len(vertices)
                position = matrix @ data.vertices[loop.vertex_index].co
                native = blender_scene.from_blender(tuple(position))
                vertices.append(tuple(int(round(c)) for c in native))
                uvs.append(blender_scene.uv_from_blender(uv))
            corners.append(index[key])
        triangles.append(tuple(corners))
        slots.append(triangle.material_index)
    return vertices, uvs, triangles, slots


def _textures(obj, slots: list[int], problems: list):
    """(textures, per-triangle texture index) from the object's material slots."""
    textures, by_image, slot_texture = [], {}, {}
    for slot in sorted(set(slots)):
        material = obj.material_slots[slot].material if slot < len(obj.material_slots) else None
        image = image_of(material)
        if image is None:
            problems.append((f"{obj.name}: every material needs an image texture", obj.name))
            return None, None
        if image.name not in by_image:
            try:
                by_image[image.name] = len(textures)
                textures.append(texture_of_image(image))
            except (OSError, ValueError) as exc:
                problems.append((f"{obj.name}: {exc}", obj.name))
                return None, None
        slot_texture[slot] = by_image[image.name]
    faces = [slot_texture[slot] for slot in slots]
    return textures, faces if any(faces) else []


def _mesh_of(obj, depsgraph, matrix, name: str, problems: list):
    evaluated = obj.evaluated_get(depsgraph)
    data = evaluated.to_mesh()
    try:
        vertices, uvs, triangles, slots = _geometry(obj, data, matrix)
    finally:
        evaluated.to_mesh_clear()
    textures, faces = _textures(obj, slots, problems)
    if textures is None:
        return None
    return world.Mesh(name, vertices, uvs, triangles, textures, obj.boz.collision,
                      obj.boz.double_sided, faces, obj.boz.shape)


def _settings_of(obj) -> dict:
    key = obj.get("boz_piece")
    try:
        return {setting.key: setting for setting in toolkit.piece(key).settings} if key else {}
    except KeyError:
        return {}


def _panel_values(obj) -> dict:
    """A piece's settings as the panel shows them."""
    return {name[len(FIELD_PREFIX):]: value for name, value in obj.items()
            if name.startswith(FIELD_PREFIX)}


def _fields(obj) -> dict:
    """What the panel's settings write over the game entity's own fields (toolkit.fields_for:
    "Needs power" off powers machines from the start)."""
    settings = _settings_of(obj)
    out = {}
    for key, value in _panel_values(obj).items():
        setting = settings.get(key)
        out.update(toolkit.fields_for(setting, value) if setting else {key: value})
    return out


def _field_props(obj, values: dict) -> None:
    for key, value in values.items():
        obj[FIELD_PREFIX + key] = value


def scene_to_world(scene, problems: list | None = None) -> "world.World":
    """The world the scene's objects describe. *problems* collects (message, object name)."""
    from mathutils import Matrix

    problems = problems if problems is not None else []
    result = world.World(scene.boz.base, inherit=scene.boz.inherit)
    base_objects = defaultdict(list)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    names: dict[str, str] = {}
    props: dict[str, str] = {}   # mesh data name -> prop name

    def claim(name: str, owner: str, obj) -> bool:
        if name in names and names[name] != owner:
            problems.append((f"{obj.name}: its game name {name} is taken by {names[name]}",
                             obj.name))
            return False
        names[name] = owner
        return True

    def prop_of(obj):
        """The prop an object's mesh is (written once per mesh data)."""
        name = props.get(obj.data.name)
        if name is None:
            name = mesh_name(obj)
            if not claim(name, f"mesh:{obj.data.name}", obj):
                return None
            mesh = _mesh_of(obj, depsgraph, Matrix.Identity(4), name, problems)
            if mesh is None:
                return None
            props[obj.data.name] = name
            result.props.append(mesh)
        return name

    for obj in scene.objects:
        role = obj.boz.role
        if role == "mesh" and obj.type == "MESH":
            name = mesh_name(obj)
            if claim(name, obj.name, obj):
                mesh = _mesh_of(obj, depsgraph, obj.matrix_world, name, problems)
                if mesh is not None:
                    result.meshes.append(mesh)
        elif role == "prop" and obj.type == "MESH":
            name = prop_of(obj)
            if name is None:
                continue
            position, rotation, scale = _transform(obj)
            result.instances.append(world.Instance(position, prop=name, rotation=rotation,
                                                   scale=scale))
        elif role == "model" and obj.boz.source:
            position, rotation, scale = _transform(obj)
            result.instances.append(world.Instance(position, model=obj.boz.source,
                                                   collision=obj.boz.collision,
                                                   shape=obj.boz.shape, rotation=rotation,
                                                   scale=scale))
        elif role == "entity" and obj.boz.source:
            position, rotation, scale = _transform(obj)
            custom = prop_of(obj) if obj.get("boz_custom_model") and obj.type == "MESH" else ""
            result.entities.append(world.Placement(obj.boz.source, position, group=obj.boz.group,
                                                   rotation=rotation, scale=scale,
                                                   prop=custom or "", fields=_fields(obj),
                                                   piece=obj.get("boz_piece", ""),
                                                   settings=_panel_values(obj)))
        elif role == "base" and obj.boz.source:
            base_objects[obj.boz.source].append(obj)
    if scene.boz.inherit:
        present = set(base_objects)
        result.removed = [source for source in scene.get("boz_base_entities", [])
                          if source not in present]
    for source, objects in base_objects.items():
        for obj in objects:
            changed, moved = _base_changes(obj)
            custom = prop_of(obj) if obj.get("boz_custom_model") and obj.type == "MESH" else ""
            if len(objects) == 1 and not (changed or moved or custom):
                continue   # as the level has it
            settings = _settings_of(obj)
            fields = {}
            for key, value in changed.items():
                setting = settings.get(key)
                fields.update(toolkit.fields_for(setting, value) if setting else {key: value})
            position, rotation, scale = _transform(obj)
            origin = list(obj.get("boz_base_origin", []))
            own = origin[7:10] if len(origin) == 10 else (1.0, 1.0, 1.0)
            relative = tuple(round(scale[i] / own[i], 5) if own[i] else 1.0 for i in range(3))
            result.entities.append(world.Placement(source, position, rotation=rotation,
                                                   scale=relative, prop=custom or "",
                                                   fields=fields, settings=changed))
    for message in world.validate(result):
        problems.append((message, ""))
    return result


# Make prop


def make_prop(obj, name: str) -> None:
    """Give an object its own editable mesh (with copies of its textures). A level mesh or game
    model becomes a project prop placed by the object (origin at the bottom centre); a game
    entity keeps its behaviour and draws the new mesh instead of the game's model."""
    from mathutils import Matrix, Vector

    if obj.type != "MESH":
        raise ValueError(f"{obj.name} has no mesh to make a prop from")
    data = obj.data.copy()
    data.name = game_name(name)
    for key in list(data.keys()):
        del data[key]
    if obj.boz.role == "mesh":
        # Level meshes are in world space: move the geometry to its own origin.
        data.transform(obj.matrix_world)
        corners = [v.co for v in data.vertices]
        low = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
        high = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
        origin = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
        data.transform(Matrix.Translation(-origin))
        obj.matrix_world = Matrix.Translation(origin)
    for index, material in enumerate(data.materials):
        if material is not None and material.name.startswith((game.PREFIX, game.MATERIAL_PREFIX)):
            copy = material.copy()
            copy.name = f"{data.name}_{index}" if index else data.name
            data.materials[index] = copy
    obj.data = data
    if obj.boz.role in ("entity", "base"):
        # The entity keeps its game behaviour (buying, power, ...) and draws this mesh instead.
        obj["boz_custom_model"] = True
        return
    obj.name = data.name
    if obj.boz.role == "model":
        obj.boz.collision = "solid"
        obj.boz.shape = "box"
    obj.boz.role = "prop"
    obj.boz.source = ""
    obj.boz.group = ""
