"""The project's world (bozkit.world format 3) and the Blender scene, both ways.

Every object is one of three kinds (object.boz.role):

- **model**: a mesh you see and bump into. A game model (boz.source = '<group>#0x<hash>') or
  your own mesh (boz.source empty; objects sharing mesh data, made with Alt+D, share one mesh).
- **volume**: an invisible box that sends script events (boz.volume: trigger, hit, use). Its
  size is 100 cm times its scale. It is an Empty showing its kind's coloured box (a collection
  instance), so the outliner gives volumes their own icon.
- **prefab**: either yours, an Empty whose children are its parts (models, volumes, prefabs), or
  a game prefab: one of the game's entities (boz.source: entity name or 0x hash), shown with the
  model the game draws for it or a coloured marker cube. boz.original marks the inherited base
  level's own entities: edited ones are written as changes, deleted ones go in ``removed``.

**reference** objects are the rest of the base level (rooms, their models, decals), read only.
An object's name is its name in the game and in scripts; a prefab part's is
'<Prefab>.<Part>' (boz.part_name, kept when copies are made).

One Blender unit is one game centimetre; Blender's Z is the game's Y.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import bpy

from ._bozkit import blender_scene, toolkit, world
from ._bozkit import spec_fields

from . import game, meshes

_SAFE = str.maketrans({c: "_" for c in " .-/\\()[]{}:;,'\"!?"})


def game_name(text: str) -> str:
    """A name the world format accepts, made from an object or mesh name."""
    name = text.lower().translate(_SAFE)
    name = "".join(c for c in name if c.isalnum() or c == "_").strip("_")[:32] or "mesh"
    return name if name[0].isalpha() else f"m_{name}"[:32]


def mesh_name(obj) -> str:
    """The world's name for an object's own mesh (from the mesh data: copies share it)."""
    return game_name(obj.data.name if obj.data else obj.name)


def object_name(obj) -> str:
    """The name scripts and the game know an object by (letters, digits and _)."""
    if obj.boz.role == "prefab" and obj.boz.original and obj.get("boz_entity_name"):
        return str(obj["boz_entity_name"])
    text = obj.boz.part_name if is_part(obj) and obj.boz.part_name else obj.name
    return clean_name(text)


def clean_name(text: str) -> str:
    text = "".join(c if c.isalnum() and c.isascii() else "_" for c in text).strip("_")
    text = "_".join(part for part in text.split("_") if part) or "object"
    return ("obj_" + text if not text[0].isalpha() else text)[:48]


def is_prefab_group(obj) -> bool:
    """One of your prefabs (an Empty holding parts), not a game prefab."""
    return obj is not None and obj.boz.role == "prefab" and not obj.boz.source and obj.type == "EMPTY"


def is_part(obj) -> bool:
    return is_prefab_group(obj.parent)


PART_SEPARATOR = " › "   # a part's object is "<Prefab> › <Part>": outliner searches find it


def without_suffix(text: str) -> str:
    """'Door.001' -> 'Door' (Blender's suffix for a name already taken)."""
    head, dot, tail = text.rpartition(".")
    return head if dot and tail.isdigit() and len(tail) == 3 else text


def sync_part_names(scene) -> int:
    """Name each prefab part's object '<Prefab> › <Part>', following the prefab's name and the
    part name; an object renamed in the outliner (keeping the prefix) sets its part name.
    Returns how many objects were renamed."""
    renamed = 0
    for obj in list(scene.objects):
        if not is_part(obj):
            continue
        prefix = obj.parent.name + PART_SEPARATOR
        if obj.name.startswith(prefix):
            part = clean_name(without_suffix(obj.name[len(prefix):]))
            if obj.boz.part_name != part:
                obj.boz.part_name = part
            continue
        part = obj.boz.part_name or clean_name(without_suffix(obj.name.split(PART_SEPARATOR)[-1]))
        obj.boz.part_name = part
        obj.name = prefix + part
        renamed += 1
    return renamed


def strip_part_name(obj) -> None:
    """A part leaving its prefab goes back to its own name."""
    if PART_SEPARATOR in obj.name:
        obj.name = obj.boz.part_name or without_suffix(obj.name.split(PART_SEPARATOR)[-1])


def image_from_texture(name: str, texture: "world.Texture", path: Path | None):
    if path is not None and path.is_file():
        image = bpy.data.images.load(str(path), check_existing=True)
        image.reload()
        return image
    image = bpy.data.images.new(name, width=texture.width, height=texture.height, alpha=True)
    stride = texture.width * 4
    rgba = world.bgra_to_rgba(texture.bgra)
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


def mesh_data(mesh: "world.Mesh", source: Path, data_name: str):
    data = bpy.data.meshes.new(data_name)
    data.from_pydata([blender_scene.to_blender(v) for v in mesh.vertices], [],
                     [tuple(t) for t in mesh.triangles])
    layer = data.uv_layers.new(name="UVMap")
    corner_vertices = [0] * len(data.loops)
    data.loops.foreach_get("vertex_index", corner_vertices)
    layer.data.foreach_set("uv", [c for v in corner_vertices
                                  for c in blender_scene.uv_to_blender(mesh.uvs[v])])
    files = world.texture_files(mesh.name, len(mesh.textures))
    for index, (texture, relative) in enumerate(zip(mesh.textures, files)):
        image = image_from_texture(Path(relative).stem, texture, source / relative)
        data.materials.append(material_for(f"{mesh.name}_{index}" if index else mesh.name, image))
    if mesh.face_textures:
        data.polygons.foreach_set("material_index", mesh.face_textures)
    data.update()
    return data


FIELD_PREFIX = "boz_f:"   # object custom properties holding a piece's settings


MAP_COLLECTION = "Map"


def map_collection(scene):
    """The collection every object of the map lives in (the base level has its own)."""
    collection = bpy.data.collections.get(MAP_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(MAP_COLLECTION)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def move_to(obj, collection) -> None:
    """Make *collection* obj's only collection (and its parts', for a prefab)."""
    if collection not in obj.users_collection:
        collection.objects.link(obj)
    for other in list(obj.users_collection):
        if other is not collection:
            other.objects.unlink(obj)
    for child in obj.children:
        if child.boz.role in ("model", "volume", "prefab") or child.get("boz_chalk"):
            move_to(child, collection)


def tidy_collections(scene) -> int:
    """Put map objects lying loose (in the scene itself or Blender's default "Collection") into
    the Map collection, so prefabs and their parts sit together in the outliner."""
    loose = {scene.collection}
    default = bpy.data.collections.get("Collection")
    if default is not None:
        loose.add(default)
    moved = 0
    for obj in list(scene.objects):
        if obj.parent is not None or obj.boz.role not in ("model", "volume", "prefab") \
                or obj.boz.original:
            continue
        if any(c in loose for c in obj.users_collection):
            move_to(obj, map_collection(scene))
            moved += 1
    if default is not None and not default.objects and not default.children:
        bpy.data.collections.remove(default)
    return moved


def unwrap_single_prefabs(scene) -> int:
    """Remove prefabs that only hold one other prefab and add nothing (no script, no properties):
    left behind when Make prefab was pressed twice."""
    from mathutils import Matrix

    removed = 0
    for obj in list(scene.objects):
        if not is_prefab_group(obj) or obj.boz.script:
            continue
        children = [c for c in obj.children if c.boz.role in ("model", "volume", "prefab")]
        if len(children) != 1 or not is_prefab_group(children[0]) or len(obj.children) != 1:
            continue
        inner, outer = children[0], obj.parent
        matrix = world_matrix(inner)
        inner.parent = outer
        inner.matrix_parent_inverse = Matrix.Identity(4)
        inner.matrix_basis = (world_matrix(outer).inverted() @ matrix) if outer else matrix
        if not is_prefab_group(outer):
            inner.boz.part_name = ""
        bpy.data.objects.remove(obj)
        removed += 1
    return removed


def _place(obj, item, scene, parent=None) -> None:
    """Position, rotation and scale of a world object (in its prefab's space when *parent*),
    in Blender's axes; links it to the scene."""
    from mathutils import Matrix, Quaternion

    rotation = item.quaternion() if hasattr(item, "quaternion") else tuple(item.rotation)
    x, y, z, w = blender_scene.rotation_to_blender(rotation)
    obj.location = blender_scene.to_blender(item.position)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion((w, x, y, z))
    scale = getattr(item, "scale", None)
    if isinstance(item, world.Volume):
        scale = tuple(c / world.TRIGGER_SIZE for c in item.size)
    obj.scale = blender_scene.scale_to_blender(scale or world.UNIT)
    collection = parent.users_collection[0] if parent is not None and parent.users_collection \
        else map_collection(scene)
    collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
        obj.matrix_parent_inverse = Matrix.Identity(4)


def world_matrix(obj):
    """An object's world matrix from its own location, rotation and scale (and its parents').
    obj.matrix_world is only updated when Blender evaluates the scene, so it is stale for an
    object made or moved in the same operation (a dropped palette asset)."""
    matrix = obj.matrix_basis.copy()
    if obj.parent is not None:
        matrix = world_matrix(obj.parent) @ obj.matrix_parent_inverse @ matrix
    return matrix


def game_transform(obj, relative_to=None):
    """(position, x/y/z/w rotation, scale) of an object in the game's axes: in the world, or in
    *relative_to*'s space (a prefab part)."""
    matrix = world_matrix(obj)
    if relative_to is not None:
        matrix = world_matrix(relative_to).inverted() @ matrix
    location, rotation, scale = matrix.decompose()
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
    if obj.boz.role != "prefab" or obj.boz.original or not weapon:
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
    return blender_scene.category_of(blender_scene.component_names(spec))


def colour_marker(obj, category: str) -> None:
    """Make *obj* a marker cube coloured by what the entity is (the shipped-map add-on's
    colours: perks violet, doors orange, wall buys green, triggers teal, ...)."""
    colour = meshes.MARKER_COLOURS.get(category, meshes.MARKER_COLOURS["entity"])
    if obj.data is not marker_mesh():
        obj.data = marker_mesh()
    obj.material_slots[0].link = "OBJECT"
    obj.material_slots[0].material = meshes.colour_material(f"BOZ Marker: {category}", colour, 1.0)
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


def game_prefab_object(prefab: "world.Prefab", base: str, scene, parent=None, custom=None):
    """An object for a game prefab: the model the game draws for it (or *custom*, mesh data of
    your own, or the game model it was given), or a coloured marker cube when it draws nothing."""
    weapon = (prefab.settings or prefab.fields).get(toolkit.WEAPON_FIELD)
    override, own = None, None
    if weapon:
        from . import weapons_tab
        override, own = weapons_tab.wall_display(bpy.context, str(weapon), base)
    drawn = game.model_mesh(*world.Instance((0, 0, 0), model=prefab.game).model_ref()) \
        if prefab.game and custom is None else None
    data = custom or drawn or game.entity_mesh(base, prefab.hash, prefab.group, override, own)
    obj = bpy.data.objects.new(prefab.name or prefab.source, data or marker_mesh())
    if data is None:
        colour_marker(obj, entity_category(base, prefab.hash, prefab.group))
    obj.boz.role = "prefab"
    set_links(obj, base, prefab.hash, prefab.group)
    obj.boz.source = prefab.source
    obj.boz.group = prefab.group
    if custom is not None:
        obj["boz_custom_model"] = True
    if drawn is not None:
        obj["boz_game_model"] = prefab.game
    if prefab.piece:
        obj["boz_piece"] = prefab.piece
    _field_props(obj, prefab.settings or prefab.fields)
    _place(obj, prefab, scene, parent)
    set_common(obj, prefab)
    if weapon:
        refresh_chalk(obj, base)
    return obj


def set_links(obj, base: str, source_hash: int, group_path: str = "") -> None:
    """The links the add-on draws (Show → Links): which power switch a machine waits for, which
    traps a switch fires, what a door unlocks."""
    spec = game.entity_spec(base, source_hash, group_path)
    if spec is None:
        return
    links = blender_scene.node_links(spec)
    if links:
        obj["boz_links"] = json.dumps(links)
    named = spec_fields.value(spec_fields.component_blob(spec, "CIsNamed"), "name", None)
    if isinstance(named, str):
        obj["boz_link_id"] = f"0x{world.iw_hash(named):08x}"
        # The add-on draws links between markers and placed models (not hidden with markers).
        obj["boz_kind"] = obj.get("boz_kind") or ("entity" if is_marker(obj) else "placed_model")


def model_object(model: "world.Model", scene, parent=None, data=None):
    """An object for a model: a game model, or *data* (mesh data of your own)."""
    if data is None and model.asset:
        from . import assets_tab
        data = assets_tab.asset_mesh(model.asset)
    elif data is None and model.game:
        path, model_hash = world.Instance((0, 0, 0), model=model.game).model_ref()
        data = game.model_mesh(path, model_hash)
    obj = bpy.data.objects.new(model.name, data)
    if model.asset:
        obj["boz_asset"] = model.asset
    if data is None:
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 50.0
    obj.boz.role = "model"
    obj.boz.source = model.game
    obj.boz.collision = model.collision
    obj.boz.shape = model.shape
    obj.boz.padding = model.padding
    obj.boz.block_margin = model.block_margin
    _place(obj, model, scene, parent)
    set_common(obj, model)
    return obj


VOLUME_MESH = "BOZ Volume"
VOLUME_COLOURS = {"trigger": (0.2, 0.85, 0.75), "hit": (1.0, 0.25, 0.15), "use": (0.35, 1.0, 0.3)}


def volume_mesh():
    """A 100 cm cube, centred: a volume's size is its scale."""
    mesh = bpy.data.meshes.get(VOLUME_MESH)
    if mesh is None:
        h = world.TRIGGER_SIZE / 2
        vertices = [(x, y, z) for x in (-h, h) for y in (-h, h) for z in (-h, h)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        mesh = bpy.data.meshes.new(VOLUME_MESH)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        mesh.materials.append(None)
    return mesh


def volume_box(kind: str):
    """The collection a volume of *kind* instances: one coloured, see-through box. It is not in
    the scene, so it is drawn only where volumes show it."""
    name = f"BOZ Volume: {kind}"
    collection = bpy.data.collections.get(name)
    if collection is not None and collection.objects:
        return collection
    collection = collection or bpy.data.collections.new(name)
    colour = VOLUME_COLOURS.get(kind, VOLUME_COLOURS["trigger"])
    box = bpy.data.objects.new(name, volume_mesh())
    box.material_slots[0].link = "OBJECT"
    box.material_slots[0].material = meshes.colour_material(name, colour, 0.25)
    box.color = (*colour, 0.25)
    box.show_wire = True
    box.show_transparent = True
    box.hide_render = True
    box.hide_select = True
    collection.objects.link(box)
    return collection


def colour_volume(obj) -> None:
    if obj.type != "EMPTY":
        return
    obj.instance_type = "COLLECTION"
    obj.instance_collection = volume_box(obj.boz.volume)
    obj.empty_display_type = "CUBE"
    obj.empty_display_size = world.TRIGGER_SIZE / 2
    obj.hide_render = True


def volume_object(volume: "world.Volume", scene, parent=None):
    obj = bpy.data.objects.new(volume.name, None)
    obj.boz.role = "volume"
    obj.boz.volume = volume.kind_of
    obj.boz.who = volume.who
    obj.boz.once = volume.once
    obj.boz.prompt = volume.prompt
    obj.boz.cost = volume.cost
    colour_volume(obj)
    _place(obj, volume, scene, parent)
    set_common(obj, volume)
    return obj


def prefab_object(prefab: "world.Prefab", base: str, scene, meshes: dict, parent=None):
    """An object for a prefab: a game prefab, or an Empty holding its parts."""
    if prefab.is_game:
        return game_prefab_object(prefab, base, scene, parent,
                                  meshes.get(prefab.mesh) if prefab.mesh else None)
    obj = bpy.data.objects.new(prefab.name, None)
    obj.empty_display_type = "CUBE"
    obj.empty_display_size = 20.0
    obj.show_name = True
    obj.boz.role = "prefab"
    if prefab.library:
        obj["boz_library"] = prefab.library
    _place(obj, prefab, scene, parent)
    set_common(obj, prefab)
    for part in prefab.parts:
        child = object_for(part, base, scene, meshes, obj)
        child.boz.part_name = part.name
        child.name = obj.name + PART_SEPARATOR + part.name
    return obj


def object_for(item, base: str, scene, meshes: dict, parent=None):
    if isinstance(item, world.Model):
        data = meshes.get(item.mesh) if item.mesh else None
        obj = model_object(item, scene, parent, data)
        if data is not None:
            obj.boz.double_sided = bool(data.get("boz_double_sided", False))
        return obj
    if isinstance(item, world.Volume):
        return volume_object(item, scene, parent)
    return prefab_object(item, base, scene, meshes, parent)


PROPERTY_PREFIX = "boz_p:"   # object custom properties holding script property values


def set_common(obj, item) -> None:
    """Start state, script and script property values."""
    start = {**world.START_DEFAULTS, **getattr(item, "start", {})}
    obj.boz.start_visible = bool(start["visible"])
    obj.boz.start_collision = bool(start["collision"])
    obj.boz.blocks = bool(start["blocks"])
    obj.boz.script = item.script
    for key, value in item.properties.items():
        obj[PROPERTY_PREFIX + key] = value


def start_of(obj) -> dict:
    start = {"visible": obj.boz.start_visible, "collision": obj.boz.start_collision,
             "blocks": obj.boz.blocks and not obj.boz.original}
    return {key: value for key, value in start.items() if world.START_DEFAULTS[key] != value}


def properties_of(obj) -> dict:
    return {name[len(PROPERTY_PREFIX):]: (value if isinstance(value, (bool, int, float, str))
                                          else str(value))
            for name, value in obj.items() if name.startswith(PROPERTY_PREFIX)}


BASE_COLLECTION = "Base level (read only)"


class _Reports:
    def __init__(self):
        self.messages = []

    def report(self, _kind, message):
        self.messages.append(message)


def show_base_level(scene, base: str) -> int:
    """Show the base level an inherited map starts from, read only (its rooms, models and
    entities, through the shipped-map tools). Returns the number of objects shown."""
    from ._bozkit import library
    folder = library.library_dir() / "groups" / "levels" / base
    editable, references = blender_scene.level_groups(str(folder), None)
    result = blender_scene.import_groups(editable, references, include_models=False,
                                               include_collision=False, include_portals=False,
                                               include_navigation=False)
    before = set(bpy.data.objects)
    scene.boz_show_markers = True   # markers of triggers, effects, spawns, ...
    meshes.import_result(_Reports(), bpy.context, result)
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
    from ._bozkit import group, levels, library, resources
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
    """Make the base level's own entities (perks, doors, wall buys, spawns, triggers, ...) game
    prefabs marked original: selectable, with their settings, written when they change. Room
    geometry stays read only. Entities without a model show as coloured cubes."""
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
        category = obj.get("boz_category") or blender_scene.category_of(
            blender_scene.component_names(spec))
        if category in ("collision", "area"):
            continue
        if obj.get("boz_kind") == "entity":
            colour_marker(obj, category)
        obj.boz.role = "prefab"
        obj.boz.original = True
        obj.boz.source = source
        obj.boz.group = ""
        obj.hide_select = False
        obj["boz_base_origin"] = [c for part in game_transform(obj) for c in part]
        named = spec_fields.value(spec_fields.component_blob(spec, "CIsNamed"), "name", None)
        if isinstance(named, str):
            obj["boz_entity_name"] = named
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


def base_changes(obj) -> tuple[dict, bool]:
    """(changed settings, whether the object moved) of a base entity."""
    origin = list(obj.get("boz_base_origin", []))
    position, rotation, scale = game_transform(obj)
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
    """Build the scene from a world: the base level (inherited maps), then every object."""
    scene.boz.base = source_world.base
    scene.boz.inherit = source_world.inherit
    if source_world.inherit:
        show_base_level(scene, source_world.base)
    meshes = {mesh.name: mesh_data(mesh, source, mesh.name) for mesh in source_world.meshes}
    for mesh in source_world.meshes:
        meshes[mesh.name]["boz_double_sided"] = mesh.double_sided
    base_objects = defaultdict(list)
    for obj in scene.objects:
        if obj.boz.role == "prefab" and obj.boz.original:
            base_objects[obj.boz.source].append(obj)
    for source_hash in source_world.removed:
        for obj in base_objects.pop(source_hash, []):
            bpy.data.objects.remove(obj)
    edited = set()
    for item in source_world.objects():
        if isinstance(item, world.Prefab) and item.source.startswith("0x") and not item.group \
                and not item.piece and base_objects.get(item.source):
            obj = base_objects[item.source][0]
            if item.source in edited or not item.base:
                # A copy of a base entity.
                obj = obj.copy()
                obj.boz.original = False
                for collection in base_objects[item.source][0].users_collection:
                    collection.objects.link(obj)
            edited.add(item.source)
            _apply_base_edit(obj, item, meshes.get(item.mesh) if item.mesh else None)
            set_common(obj, item)
            if not obj.boz.original:
                obj.name = item.name
            continue
        object_for(item, source_world.base, scene, meshes)


def show_game_models(scene) -> int:
    """Give game prefabs and game models that are still empties their game mesh, or a coloured
    marker cube when they draw nothing (maps made before the editor could show them, or before
    the asset library was built)."""
    changed = 0
    if game.game_models() is None:
        return 0
    for obj in list(scene.objects):
        if obj.type != "EMPTY" or obj.boz.role not in ("prefab", "model") or not obj.boz.source:
            continue
        if obj.boz.role == "prefab":
            item = world.Prefab(obj.name, source=obj.boz.source, group=obj.boz.group)
            data = game.entity_mesh(scene.boz.base, item.hash, obj.boz.group)
        else:
            data = game.model_mesh(*world.Instance((0, 0, 0), model=obj.boz.source).model_ref())
            if data is None:
                continue
        replacement = bpy.data.objects.new(obj.name, data or marker_mesh())
        if data is None:
            colour_marker(replacement, entity_category(scene.boz.base, item.hash, obj.boz.group))
        replacement.matrix_world = world_matrix(obj)
        for key in ("role", "source", "group", "collision", "shape", "double_sided", "original",
                    "start_visible", "start_collision", "blocks", "script", "part_name"):
            setattr(replacement.boz, key, getattr(obj.boz, key))
        for key, value in obj.items():
            replacement[key] = value
        for collection in obj.users_collection:
            collection.objects.link(replacement)
        bpy.data.objects.remove(obj)
        replacement.name = replacement.name.split(".")[0]
        changed += 1
    return changed


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


TINY = 5.0   # centimetres: smaller is Blender's 2 cm default cube, not a game object


def scene_to_world(scene, problems: list | None = None) -> "world.World":
    """The world the scene's objects describe. *problems* collects (message, object name)."""
    from mathutils import Matrix

    problems = problems if problems is not None else []
    result = world.World(scene.boz.base, inherit=scene.boz.inherit)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    meshes: dict[str, str] = {}    # mesh data name -> world mesh name
    taken: dict[str, str] = {}     # world mesh name -> mesh data name
    base_objects = defaultdict(list)

    def own_mesh(obj) -> str | None:
        name = meshes.get(obj.data.name)
        if name is None:
            name = mesh_name(obj)
            if name in taken and taken[name] != obj.data.name:
                problems.append((f"{obj.name}: its mesh name {name} is taken by another mesh "
                                 "(rename the mesh data)", obj.name))
                return None
            mesh = _mesh_of(obj, depsgraph, Matrix.Identity(4), name, problems)
            if mesh is None:
                return None
            mesh.double_sided = obj.boz.double_sided
            taken[name] = obj.data.name
            meshes[obj.data.name] = name
            result.meshes.append(mesh)
        return name

    def build(obj, parent=None):
        """The world object for a scene object (None for what is not written)."""
        role = obj.boz.role
        name = object_name(obj)
        position, rotation, scale = game_transform(obj, parent)
        common = {"script": obj.boz.script, "properties": properties_of(obj)}
        if role == "model" and obj.type == "MESH":
            if max(obj.dimensions) < TINY:
                problems.append((f"{obj.name} is only {max(obj.dimensions):.1f} cm across (one "
                                 "Blender unit is a centimetre): scale it up, or use Add → Game "
                                 "shapes", obj.name))
                return None
            if obj.get("boz_asset"):
                return world.Model(name, position, rotation, scale, asset=str(obj["boz_asset"]),
                                   collision=obj.boz.collision, shape=obj.boz.shape,
                                   padding=round(obj.boz.padding, 2) if obj.boz.shape == "box" else 0.0,
                                   block_margin=round(obj.boz.block_margin, 2),
                                   start=start_of(obj), **common)
            mesh = "" if obj.boz.source else own_mesh(obj)
            if mesh is None:
                return None
            return world.Model(name, position, rotation, scale, mesh=mesh, game=obj.boz.source,
                               collision=obj.boz.collision, shape=obj.boz.shape,
                               padding=round(obj.boz.padding, 2) if obj.boz.shape == "box" else 0.0,
                               block_margin=round(obj.boz.block_margin, 2),
                               start=start_of(obj), **common)
        if role == "volume":
            return world.Volume(name, obj.boz.volume, position, rotation,
                                size=tuple(round(c * world.TRIGGER_SIZE, 3) for c in scale),
                                who=obj.boz.who, once=obj.boz.once, prompt=obj.boz.prompt,
                                cost=obj.boz.cost, **common)
        if role != "prefab":
            return None
        if obj.boz.source:
            custom = own_mesh(obj) if obj.get("boz_custom_model") and obj.type == "MESH" else ""
            return world.Prefab(name, position, rotation, scale, source=obj.boz.source,
                                group=obj.boz.group, piece=obj.get("boz_piece", ""),
                                settings=_panel_values(obj), fields=_fields(obj),
                                mesh=custom or "",
                                game="" if custom else obj.get("boz_game_model", ""),
                                start=start_of(obj), **common)
        children = sorted(obj.children, key=object_name)   # stable files, small diffs
        parts = [part for part in (build(child, obj) for child in children
                                   if child.boz.role in ("model", "volume", "prefab")
                                   and not child.boz.original) if part is not None]
        return world.Prefab(name, position, rotation, scale, parts=parts, start=start_of(obj),
                            library=obj.get("boz_library", ""), **common)

    for obj in scene.objects:
        if obj.boz.role == "prefab" and obj.boz.original and obj.boz.source:
            base_objects[obj.boz.source].append(obj)
            continue
        if is_part(obj):
            continue   # written with its prefab
        item = build(obj)
        if isinstance(item, world.Model):
            result.models.append(item)
        elif isinstance(item, world.Volume):
            result.volumes.append(item)
        elif isinstance(item, world.Prefab):
            result.prefabs.append(item)
    if scene.boz.inherit:
        present = set(base_objects)
        result.removed = [source for source in scene.get("boz_base_entities", [])
                          if source not in present]
    for source, objects in base_objects.items():
        for number, obj in enumerate(objects):
            changed, moved = base_changes(obj)
            custom = own_mesh(obj) if obj.get("boz_custom_model") and obj.type == "MESH" else ""
            start = start_of(obj)
            if len(objects) == 1 and not (changed or moved or custom or start or obj.boz.script):
                continue   # as the level has it
            settings = _settings_of(obj)
            fields = {}
            for key, value in changed.items():
                setting = settings.get(key)
                fields.update(toolkit.fields_for(setting, value) if setting else {key: value})
            position, rotation, scale = game_transform(obj)
            origin = list(obj.get("boz_base_origin", []))
            own = origin[7:10] if len(origin) == 10 else (1.0, 1.0, 1.0)
            relative = tuple(round(scale[i] / own[i], 5) if own[i] else 1.0 for i in range(3))
            original = number == 0
            # The first is the base entity itself (moved, edited); others are copies of it.
            name = object_name(obj) if original else clean_name(obj.name)
            result.prefabs.append(world.Prefab(
                name, position, rotation, relative, source=source, base=original,
                settings=changed, fields=fields, mesh=custom or "",
                start=start if original else {}, script=obj.boz.script if original else "",
                properties=properties_of(obj) if original else {}))
    for message in world.validate(result):
        problems.append((message, ""))
    return result


def prefab_of(obj, problems: list | None = None):
    """(Prefab, meshes it uses) for one prefab object (Save as new prefab)."""
    from . import link
    whole = scene_to_world(link.map_scene(), problems)
    names = [object_name(obj)]
    parent = obj.parent
    while is_prefab_group(parent):
        names.insert(0, object_name(parent))
        parent = parent.parent
    full = ".".join(names)
    found = next((item for name, item in world.walk(whole.prefabs) if name == full), None)
    if found is None:
        raise ValueError(f"{obj.name} is not a prefab of this map")
    used = world.meshes_used([found])
    return found, [mesh for mesh in whole.meshes if mesh.name in used]


def make_editable(obj, name: str) -> None:
    """Give an object its own editable mesh (with copies of its textures). A game model becomes
    a model of your own (origin kept); a game prefab keeps its behaviour and draws the new mesh
    instead of the game's model."""
    if obj.type != "MESH":
        raise ValueError(f"{obj.name} has no mesh to edit")
    data = obj.data.copy()
    data.name = game_name(name)
    for key in list(data.keys()):
        del data[key]
    for index, material in enumerate(data.materials):
        if material is not None and material.name.startswith((game.PREFIX, game.MATERIAL_PREFIX)):
            copy = material.copy()
            copy.name = f"{data.name}_{index}" if index else data.name
            data.materials[index] = copy
    obj.data = data
    if obj.boz.role == "prefab":
        # It keeps its game behaviour (buying, power, ...) and draws this mesh instead.
        obj["boz_custom_model"] = True
        if "boz_game_model" in obj:
            del obj["boz_game_model"]
        return
    obj.boz.source = ""
