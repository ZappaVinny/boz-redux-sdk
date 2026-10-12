"""Make an asset's game version: run in background Blender by assets_tab.py.

    blender -b --factory-startup --python asset_build.py -- <bozkit dir> <project root> <name>

Loads the asset's source (a .blend's objects, or an FBX, glTF or OBJ), scales it to centimetres,
reduces every mesh to its share of the triangle budget (Collapse decimation; vertex weights
kept), reduces each material's colour image to a power-of-two texture shaded by its normal map,
and writes the game version (bozkit.assets.write_game). Prints BOZ_ASSET_OK <stats json>, or
BOZ_ASSET_FAILED <reason>.
"""
import json
import sys
from pathlib import Path

import bpy
import bmesh

bozkit_dir, root, name = sys.argv[sys.argv.index("--") + 1:][:3]
root = Path(root)
sys.path.insert(0, bozkit_dir)
from bozkit import assets, blender_scene  # noqa: E402

IMPORTERS = {".fbx": ("import_scene", "fbx"), ".glb": ("import_scene", "gltf"),
             ".gltf": ("import_scene", "gltf"), ".obj": ("wm", "obj_import")}


def log(text: str) -> None:
    print(f"BOZ_ASSET_LOG {text}", flush=True)


def load_source(asset) -> list:
    """The source's objects, linked into the scene."""
    path = root / asset.source
    if not path.is_file():
        raise assets.AssetError(f"the source file {asset.source} is missing")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    if path.suffix.lower() == ".blend":
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            target.objects = list(source.objects)
        objects = [obj for obj in target.objects if obj is not None]
        for obj in objects:
            scene.collection.objects.link(obj)
    else:
        module, op = IMPORTERS[path.suffix.lower()]
        before = set(bpy.data.objects)
        getattr(getattr(bpy.ops, module), op)(filepath=str(path))
        objects = [obj for obj in bpy.data.objects if obj not in before]
    return objects


def armatures_of(meshes) -> list:
    out = []
    for obj in meshes:
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object is not None and modifier.object not in out:
                out.append(modifier.object)
        if obj.parent is not None and obj.parent.type == "ARMATURE" and obj.parent not in out:
            out.append(obj.parent)
    return out


def attach_armatures(armatures):
    """The main armature (the most bones) and the others snapped onto it: an attachment's
    armature (a magazine's, with its own tag_clip) goes where its bone lines up with the main
    armature's bone of the same name, the way the game attaches parts. Returns the main one."""
    if not armatures:
        return None
    main = max(armatures, key=lambda a: len(a.data.bones))
    names = {b.name.lower(): b for b in main.data.bones}
    for other in armatures:
        if other is main:
            continue
        shared = next((b for b in other.data.bones if b.name.lower() in names), None)
        if shared is None:
            continue
        target = main.matrix_world @ names[shared.name.lower()].matrix_local
        current = other.matrix_world @ shared.matrix_local
        other.matrix_world = target @ current.inverted() @ other.matrix_world
        log(f"attached {other.name} at {shared.name}")
    bpy.context.view_layer.update()
    return main


def triangle_count(obj) -> int:
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def prepare(obj, merge: float):
    """Its own mesh, modifiers (but the armature) applied, in world space, triangulated and
    welded (so it reduces as one surface, without cracks along texture seams). Returns a copy
    of that mesh, which keeps the original texture coordinates for remap_uvs."""
    obj.data = obj.data.copy()
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            continue
        with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            except RuntimeError:
                obj.modifiers.remove(modifier)
    matrix = obj.matrix_world.copy()
    if obj.parent is not None:
        bone = obj.parent_bone if obj.parent_type == "BONE" else ""
        obj["boz_bone"] = bone
        obj.parent = None
    obj.data.transform(matrix)
    obj.matrix_world.identity()
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.triangulate(mesh, faces=mesh.faces)
    bmesh.ops.remove_doubles(mesh, verts=mesh.verts, dist=merge)
    mesh.to_mesh(obj.data)
    mesh.free()
    return obj.data.copy()


class Surface:
    """The original surface of a mesh, to read texture coordinates back from after reducing:
    its triangles grouped into texture islands (triangles joined by an edge whose two corners
    have the same coordinates on both sides), with a BVH for all and for each island."""

    def __init__(self, data):
        from mathutils.bvhtree import BVHTree
        data.calc_loop_triangles()
        uv_layer = data.uv_layers.active
        self.positions = [v.co.copy() for v in data.vertices]
        self.triangles = [tuple(t.vertices) for t in data.loop_triangles]
        self.uvs = [tuple(tuple(uv_layer.data[l].uv) if uv_layer else (0.0, 0.0) for l in t.loops)
                    for t in data.loop_triangles]
        parent = list(range(len(self.triangles)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        edges = {}
        for index, (tri, uvs) in enumerate(zip(self.triangles, self.uvs)):
            corner = {v: (round(uv[0], 4), round(uv[1], 4)) for v, uv in zip(tri, uvs)}
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                key = (min(a, b), max(a, b))
                other = edges.get(key)
                if other is None:
                    edges[key] = (index, corner)
                elif other[1][a] == corner[a] and other[1][b] == corner[b]:
                    parent[find(index)] = find(other[0])
        self.island = [find(i) for i in range(len(self.triangles))]
        self.all = BVHTree.FromPolygons(self.positions, self.triangles)
        by_island = {}
        for index, island in enumerate(self.island):
            by_island.setdefault(island, []).append(index)
        self.trees = {}
        for island, members in by_island.items():
            tree = BVHTree.FromPolygons(self.positions, [self.triangles[i] for i in members])
            self.trees[island] = (tree, members)

    def uv_at(self, point, island):
        """The texture coordinates at *point*, read from *island* (projected onto its nearest
        triangle, extrapolated a little past its edges rather than clamped)."""
        from mathutils.geometry import barycentric_transform, intersect_point_tri
        tree, members = self.trees[island]
        found = tree.find_nearest(point)
        if found[2] is None:
            return (0.0, 0.0)
        tri = members[found[2]]
        a, b, c = (self.positions[v] for v in self.triangles[tri])
        normal = (b - a).cross(c - a)
        if normal.length < 1e-12:
            return self.uvs[tri][0]
        normal.normalize()
        projected = point - normal * normal.dot(point - a)
        ua, ub, uc = (__import__("mathutils").Vector((u, v, 0.0)) for u, v in self.uvs[tri])
        uv = barycentric_transform(projected, a, b, c, ua, ub, uc)
        return (uv.x, uv.y)

    def island_at(self, point):
        found = self.all.find_nearest(point)
        return self.island[found[2]] if found[2] is not None else self.island[0]


def remap_uvs(obj, surface: "Surface") -> None:
    """Texture coordinates of the reduced mesh from the original surface: each triangle reads
    all three corners from the texture island under its centre, so no triangle spans a seam."""
    data = obj.data
    uv_layer = data.uv_layers.active or data.uv_layers.new(name="UVMap")
    cache = {}     # (vertex, island) -> uv: corners on one island share their vertex
    for polygon in data.polygons:
        island = surface.island_at(polygon.center)
        for loop_index in polygon.loop_indices:
            vertex = data.loops[loop_index].vertex_index
            key = (vertex, island)
            if key not in cache:
                cache[key] = surface.uv_at(data.vertices[vertex].co, island)
            uv_layer.data[loop_index].uv = cache[key]


def decimate(obj, target: int) -> None:
    count = triangle_count(obj)
    if count <= target:
        return
    modifier = obj.modifiers.new("BOZ reduce", "DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = max(0.001, target / count)
    modifier.use_collapse_triangulate = True
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def reduce(meshes, budget: int) -> None:
    targets = assets.split_budget([triangle_count(o) for o in meshes], budget)
    for obj, target in zip(meshes, targets):
        decimate(obj, target)
    for _round in range(4):
        total = sum(triangle_count(o) for o in meshes)
        if total <= budget:
            return
        ratio = budget / total * 0.97
        for obj in meshes:
            decimate(obj, max(assets.MIN_PART_TRIANGLES, int(triangle_count(obj) * ratio)))


# --- Materials and textures --------------------------------------------------------------------

def _image_from(socket, depth: int = 0):
    """The image feeding *socket* (through other nodes), or None."""
    if socket is None or not socket.is_linked or depth > 5:
        return None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE":
        return node.image
    for candidate in node.inputs:
        found = _image_from(candidate, depth + 1)
        if found is not None:
            return found
    return None


def images_of(material):
    """(colour image, normal image, flat colour) of a material."""
    if material is None:
        return None, None, (0.8, 0.8, 0.8, 1.0)
    colour = normal = None
    flat = tuple(material.diffuse_color)
    if material.use_nodes and material.node_tree:
        principled = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if principled is not None:
            colour = _image_from(principled.inputs.get("Base Color"))
            normal = _image_from(principled.inputs.get("Normal"))
            base = principled.inputs.get("Base Color")
            if base is not None and not base.is_linked:
                flat = tuple(base.default_value)
        images = [n.image for n in material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
        colour = colour or next((i for i in images if not i.name.lower().split(".")[0].endswith("_n")), None)
        normal = normal or next((i for i in images if i.name.lower().split(".")[0].endswith("_n")), None)
    return colour, normal, flat


def pixels_at(image, width: int, height: int):
    import numpy as np
    copy = image.copy()
    try:
        if tuple(copy.size) != (width, height):
            copy.scale(width, height)
        data = np.empty(width * height * 4, dtype=np.float32)
        copy.pixels.foreach_get(data)
    finally:
        bpy.data.images.remove(copy)
    return data.reshape(height, width, 4)


def make_texture(material, side: int, bake_normals: bool):
    colour, normal, flat = images_of(material)
    if colour is None or not colour.size[0]:
        return assets.flat_texture(flat)
    width, height = colour.size
    if width >= height:
        tw = assets.texture_side(width, side)
        th = assets.texture_side(height, max(4, tw * height // width))
    else:
        th = assets.texture_side(height, side)
        tw = assets.texture_side(width, max(4, th * width // height))
    rgba = pixels_at(colour, tw, th)
    if bake_normals and normal is not None and normal.size[0]:
        rgba = assets.shade(rgba, pixels_at(normal, tw, th)[..., :3])
    return assets.texture_from_rgba(rgba, bottom_up=True)


# --- The game version ------------------------------------------------------------------------

def collect(meshes, armature, scale: float, kind: str):
    """(GameModel, materials in texture order, per-material surface area)."""
    bones, bone_index = [], {}
    if armature is not None:
        for bone in armature.data.bones:
            head = armature.matrix_world @ bone.head_local
            bone_index[bone.name.lower()] = len(bones)
            bones.append(assets.Bone(bone.name, bone.parent.name if bone.parent else "",
                                     tuple(round(c * scale, 3) for c in blender_scene.from_blender(tuple(head)))))
    vertices, uvs, triangles, faces, weights = [], [], [], [], []
    materials, material_index, areas = [], {}, []
    for obj in meshes:
        data = obj.data
        data.calc_loop_triangles()
        uv_layer = data.uv_layers.active
        groups = {g.index: bone_index.get(g.name.lower()) for g in obj.vertex_groups}
        fixed_bone = bone_index.get(str(obj.get("boz_bone", "")).lower())
        index = {}
        for triangle in data.loop_triangles:
            material = obj.material_slots[triangle.material_index].material \
                if triangle.material_index < len(obj.material_slots) else None
            key = material.name if material else f"{obj.name} flat"
            if key not in material_index:
                material_index[key] = len(materials)
                materials.append(material)
                areas.append(0.0)
            slot = material_index[key]
            corners, corner_uvs = [], []
            for loop_index in triangle.loops:
                loop = data.loops[loop_index]
                uv = tuple(uv_layer.data[loop_index].uv) if uv_layer else (0.0, 0.0)
                corner_uvs.append(uv)
                vkey = (loop.vertex_index, round(uv[0], 5), round(uv[1], 5), slot)
                if vkey not in index:
                    index[vkey] = len(vertices)
                    co = data.vertices[loop.vertex_index].co
                    native = blender_scene.from_blender(tuple(co))
                    vertices.append(tuple(int(round(c * scale)) for c in native))
                    uvs.append(blender_scene.uv_from_blender(uv))
                    if bones:
                        if fixed_bone is not None:
                            weight = [(fixed_bone, 1.0)]
                        else:
                            weight = [(groups[g.group], g.weight)
                                      for g in data.vertices[loop.vertex_index].groups
                                      if groups.get(g.group) is not None and g.weight > 0.0]
                            weight = sorted(weight, key=lambda w: -w[1])[:assets.MAX_BONES_PER_VERTEX]
                            total = sum(w for _b, w in weight)
                            weight = [(b, w / total) for b, w in weight] if total else [(0, 1.0)]
                        weights.append(weight)
                corners.append(index[vkey])
            a, b, c = (data.vertices[data.loops[i].vertex_index].co for i in triangle.loops)
            areas[slot] += (b - a).cross(c - a).length / 2     # surface: texel density
            triangles.append(tuple(corners))
            faces.append(slot)
    parts = {}
    if kind == "weapon" and bones:
        for tag, label in assets.WEAPON_PARTS:
            bone = bone_index.get(tag)
            if bone is None:
                continue
            owned = [i for i, t in enumerate(triangles)
                     if all(weights[v] and max(weights[v], key=lambda w: w[1])[0] == bone for v in t)]
            if owned:
                parts[label] = owned
    model = assets.GameModel(vertices, uvs, triangles, faces,
                             [m.name if m else "flat" for m in materials], bones,
                             weights if bones else [], parts)
    return model, materials, areas


def main() -> None:
    source = root / "source"
    asset = assets.load_def(source, name)
    log(f"loading {asset.source}")
    objects = load_source(asset)
    meshes = [o for o in objects if o.type == "MESH" and (not asset.objects or o.name in asset.objects)]
    if not meshes:
        raise assets.AssetError("the source has no meshes")
    armature = attach_armatures(armatures_of(meshes))
    high = sum(triangle_count(o) for o in meshes)
    # The size: the source's length in its own units, then the unit.
    corners = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
    length = max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3))
    unit = asset.unit or assets.guess_unit(length, asset.kind)
    scale = assets.UNITS[unit] * assets.ASSET_UNIT
    log(f"{len(meshes)} meshes, {high} triangles, {length * assets.UNITS[unit]:.0f} cm long "
        f"(unit: {unit})")
    originals = {obj.name: prepare(obj, max(length * 1e-5, 1e-6)) for obj in meshes}
    reduce(meshes, asset.budget())
    for obj in meshes:
        remap_uvs(obj, Surface(originals[obj.name]))
    model, materials, areas = collect(meshes, armature, scale, asset.kind)
    log(f"reduced to {len(model.triangles)} triangles, {len(model.vertices)} vertices")
    sides = assets.texture_sizes(areas, asset.max_texture())
    textures = [make_texture(m, side, asset.bake_normals) for m, side in zip(materials, sides)]
    errors, warnings = assets.check(asset, model, textures)
    stats = assets.describe(model, textures)
    stats.update({"high_triangles": high, "unit": unit, "length_cm": round(length * assets.UNITS[unit], 1),
                  "errors": errors, "warnings": warnings, "materials": model.texture_names})
    assets.write_game(source, name, model, textures, stats)
    if not asset.unit or asset.edited:
        asset.unit, asset.edited = unit, False
        assets.save_def(source, asset)
    print("BOZ_ASSET_OK " + json.dumps(stats), flush=True)


try:
    main()
except (assets.AssetError, RuntimeError, KeyError, ValueError, OSError) as exc:
    import traceback
    traceback.print_exc()
    print(f"BOZ_ASSET_FAILED {exc}", flush=True)
