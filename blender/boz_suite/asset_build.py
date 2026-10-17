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


def cover(obj, original, limit: float) -> float:
    """Push the reduced mesh out until it covers the original: reducing rounds corners off and
    pulls surfaces in, which thins edges and opens gaps where parts only just overlapped. For
    every original vertex outside the reduced surface, the reduced triangle under it is pushed
    out by that much (along the vertex normals, at most *limit*). Returns the largest push."""
    from mathutils.bvhtree import BVHTree
    data = obj.data
    data.calc_loop_triangles()
    if not len(data.loop_triangles):
        return 0.0
    positions = [v.co.copy() for v in data.vertices]
    tree = BVHTree.FromPolygons(positions, [tuple(t.vertices) for t in data.loop_triangles])
    push = [0.0] * len(positions)
    triangles = [tuple(t.vertices) for t in data.loop_triangles]
    for vertex in original.vertices:
        location, normal, index, _distance = tree.find_nearest(vertex.co)
        if index is None:
            continue
        outside = (vertex.co - location).dot(normal)
        if outside > 0:
            for corner in triangles[index]:
                if outside > push[corner]:
                    push[corner] = min(outside, limit)
    data.update()
    normals = [v.normal.copy() for v in data.vertices]
    for index, amount in enumerate(push):
        if amount > 0:
            data.vertices[index].co = positions[index] + normals[index] * amount
    data.update()
    return max(push)


def extend_borders(obj, margin: float) -> int:
    """Grow every open border of the reduced mesh outward along its own surface by *margin*:
    the model's shells tuck under each other, and reducing pulls their borders back, opening
    cracks you can see through; grown back, they overlap again. Returns the vertices moved."""
    from mathutils import Vector
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    mesh.normal_update()
    moves = {}
    for edge in mesh.edges:
        if not edge.is_boundary:
            continue
        face = edge.link_faces[0]
        a, b = edge.verts
        along = (b.co - a.co)
        if along.length < 1e-9:
            continue
        outward = along.cross(face.normal).normalized()
        if outward.dot(face.calc_center_median() - a.co) > 0:
            outward = -outward             # away from the face: out over the crack
        for vert in (a, b):
            moves.setdefault(vert.index, Vector()).__iadd__(outward)
    for vert in mesh.verts:
        direction = moves.get(vert.index)
        if direction is not None and direction.length > 1e-9:
            vert.co += direction.normalized() * margin
    mesh.to_mesh(obj.data)
    mesh.free()
    return len(moves)


HOLE_LIMIT = 0.0005     # see-through allowed: 0.05% of the model's area, pixel fringe along spikes
                        # (an unreduced copy scores 0.006%; what is left at this level is not a hole)
VIEWS = (((0, -1, 0), (90, 0, 0)), ((0, 1, 0), (90, 0, 180)), ((0, 0, 1), (0, 0, 0)),
         ((0, 0, -1), (180, 0, 0)), ((-1, 0, 0), (90, 0, -90)), ((1, 0, 0), (90, 0, 90)))


def see_through(reduced, originals: dict, length: float) -> float:
    """The share of the original's area you can see through on the reduced model, drawn as the
    game draws it (one side), from six directions: background enclosed by the reduced model where
    the original has surface (holes; outlines a little thinner do not count)."""
    import math
    import tempfile
    import numpy as np
    from mathutils import Vector
    scene = bpy.context.scene
    for obj in scene.objects:
        obj.hide_render = True
    temps = []
    for name, data in originals.items():
        temp = bpy.data.objects.new(f"{name} check", data)
        scene.collection.objects.link(temp)
        temps.append(temp)
    corners = [v.co for o in reduced for v in o.data.vertices]
    centre = Vector(tuple((min(c[i] for c in corners) + max(c[i] for c in corners)) / 2 for i in range(3)))
    camera = bpy.data.objects.new("check camera", bpy.data.cameras.new("check camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = length * 1.1
    camera.data.clip_end = length * 10
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light, shading.color_type, shading.single_color = "FLAT", "SINGLE", (1, 1, 1)
    scene.world = scene.world or bpy.data.worlds.new("check")
    scene.world.color = (0, 0, 0)
    scene.render.resolution_x, scene.render.resolution_y = 600, 400
    scene.render.image_settings.file_format = "PNG"
    folder = Path(tempfile.mkdtemp())

    def shot(objects, culling, path):
        for obj in scene.objects:
            obj.hide_render = obj not in objects
        camera.hide_render = False
        shading.show_backface_culling = culling
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path))
        pixels = np.array(image.pixels[:]).reshape(image.size[1], image.size[0], 4)[..., 0] > 0.5
        bpy.data.images.remove(image)
        return pixels

    worst = 0.0
    try:
        for direction, rotation in VIEWS:
            camera.location = centre + Vector(direction) * length * 3
            camera.rotation_euler = tuple(math.radians(r) for r in rotation)
            want = shot(temps, False, folder / "original.png")
            got = shot(reduced, True, folder / "game.png")
            # Background reachable from the image's edge is outside; the rest is a hole.
            h, w = got.shape
            outside = np.zeros_like(got)
            stack = [(y, x) for y in range(h) for x in (0, w - 1) if not got[y, x]] + \
                    [(y, x) for x in range(w) for y in (0, h - 1) if not got[y, x]]
            for y, x in stack:
                outside[y, x] = True
            while stack:
                y, x = stack.pop()
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and not got[ny, nx] and not outside[ny, nx]:
                        outside[ny, nx] = True
                        stack.append((ny, nx))
            holes = (~got & ~outside & want).sum()
            worst = max(worst, holes / max(1, want.sum()))
    finally:
        for temp in temps:
            bpy.data.objects.remove(temp)
        bpy.data.objects.remove(camera)
    return worst


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
        from mathutils.geometry import barycentric_transform
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


def drop_small_pieces(meshes, budget: int) -> None:
    """Remove the smallest separate pieces (by surface) until the meshes fit *budget*: what a
    distance model can do without when collapsing cannot go lower (teeth, spikes)."""
    pieces = []
    for obj in meshes:
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        mesh.faces.ensure_lookup_table()
        seen = set()
        for face in mesh.faces:
            if face.index in seen:
                continue
            stack, members = [face], []
            seen.add(face.index)
            while stack:
                current = stack.pop()
                members.append(current.index)
                for edge in current.edges:
                    for other in edge.link_faces:
                        if other.index not in seen:
                            seen.add(other.index)
                            stack.append(other)
            area = sum(mesh.faces[i].calc_area() for i in members)
            pieces.append((area, obj, members))
        mesh.free()
    total = sum(triangle_count(o) for o in meshes)
    drop: dict = {}
    for area, obj, members in sorted(pieces, key=lambda p: p[0]):
        if total <= budget:
            break
        if len(members) >= triangle_count(obj) - len(drop.get(obj.name, ())):
            continue      # never a mesh's last piece
        drop.setdefault(obj.name, set()).update(members)
        total -= len(members)
    for obj in meshes:
        faces = drop.get(obj.name)
        if not faces:
            continue
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        mesh.faces.ensure_lookup_table()
        bmesh.ops.delete(mesh, geom=[mesh.faces[i] for i in faces], context="FACES")
        mesh.to_mesh(obj.data)
        mesh.free()


def reduce(meshes, budget: int, drop: bool = False) -> None:
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
    if drop and sum(triangle_count(o) for o in meshes) > budget:
        drop_small_pieces(meshes, budget)


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

def collect(meshes, armature, scale: float, kind: str, material_index: dict | None = None):
    """(GameModel, materials in texture order, per-material surface area). *material_index*
    (a lighter level of a weapon): reuse the main model's texture order."""
    bones, bone_index = [], {}
    if armature is not None:
        for bone in armature.data.bones:
            head = armature.matrix_world @ bone.head_local
            bone_index[bone.name.lower()] = len(bones)
            bones.append(assets.Bone(bone.name, bone.parent.name if bone.parent else "",
                                     tuple(round(c * scale, 3) for c in blender_scene.from_blender(tuple(head)))))
    vertices, uvs, triangles, faces, weights = [], [], [], [], []
    fixed_materials = material_index is not None
    materials, material_index, areas = [], dict(material_index or {}), []
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
            if fixed_materials:
                key = key if key in material_index else next(iter(material_index))
                while len(areas) <= material_index[key]:
                    areas.append(0.0)
            elif key not in material_index:
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
    return model, materials, areas, material_index


def reduce_closed(meshes, originals, budget: int, length: float) -> None:
    """Reduce to *budget*, then close what reducing opened: push the surface out to cover the
    original (gently) and grow the open borders back so shells overlap again."""
    reduce(meshes, budget)
    for obj in meshes:
        cover(obj, originals[obj.name], length * 0.003)
        extend_borders(obj, length * 0.015)


def make_level(meshes, originals, budget: int, armature, scale: float, kind: str, material_index,
               keep_pieces: bool = True):
    # keep_pieces: the aiming model keeps every piece; distance models may drop the smallest.
    """A lighter version of the model (a weapon's aiming or distance model), reduced from the
    welded originals to *budget* triangles, with the main model's textures."""
    scene = bpy.context.scene
    temps = []
    for obj in meshes:
        temp = bpy.data.objects.new(f"{obj.name} level", originals[obj.name].copy())
        for group in obj.vertex_groups:
            temp.vertex_groups.new(name=group.name)
        temp["boz_bone"] = obj.get("boz_bone", "")
        scene.collection.objects.link(temp)
        temps.append(temp)
    try:
        reduce(temps, budget, drop=not keep_pieces)
        length = max(max(v.co[i] for t in temps for v in t.data.vertices) -
                     min(v.co[i] for t in temps for v in t.data.vertices) for i in range(3))
        for temp, obj in zip(temps, meshes):
            cover(temp, originals[obj.name], length * 0.003)
            extend_borders(temp, length * 0.015)
        for temp, obj in zip(temps, meshes):
            remap_uvs(temp, Surface(originals[obj.name]))
        level, _materials, _areas, _index = collect(temps, armature, scale, kind, material_index)
    finally:
        for temp in temps:
            data = temp.data
            bpy.data.objects.remove(temp)
            bpy.data.meshes.remove(data)
    level.parts = {}
    return level


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
    budget, holes = asset.budget(), 0.0
    for attempt in range(6):
        if attempt:
            budget = int(budget * 1.35)
            for obj in meshes:
                obj.data = originals[obj.name].copy()       # again from the original
        reduce_closed(meshes, originals, budget, length)
        holes = see_through(meshes, originals, length)
        log(f"{sum(triangle_count(o) for o in meshes)} triangles: "
            + (f"nothing see-through ({holes * 100:.3f}%)" if holes <= HOLE_LIMIT
               else f"{holes * 100:.3f}% see-through, more triangles"))
        if holes <= HOLE_LIMIT or budget >= max(high, 1):
            break
    for obj in meshes:
        remap_uvs(obj, Surface(originals[obj.name]))
    model, materials, areas, material_index = collect(meshes, armature, scale, asset.kind)
    log(f"reduced to {len(model.triangles)} triangles, {len(model.vertices)} vertices")
    if asset.kind == "weapon":
        # The aiming-down-the-sights and distance models, from the originals (not the view model).
        for key, share in assets.WEAPON_LEVELS.items():
            # The aiming model is seen close up: every piece stays. Distance models may drop
            # the smallest when even a few triangles each is too many.
            level = make_level(meshes, originals, int(budget * share), armature, scale,
                               asset.kind, material_index, keep_pieces=key == "ads")
            model.levels[key] = level
        log("lighter models: " + ", ".join(f"{k} {len(l.triangles)}" for k, l in model.levels.items()))
    sides = assets.texture_sizes(areas, asset.max_texture())
    textures = [make_texture(m, side, asset.bake_normals) for m, side in zip(materials, sides)]
    errors, warnings = assets.check(asset, model, textures)
    if holes > HOLE_LIMIT:
        warnings.append(f"{holes * 100:.2f}% of it is still see-through: raise the triangle budget")
    elif budget > asset.budget():
        warnings.append(f"needed {budget} triangles to have no see-through parts "
                        f"(the budget is {asset.budget()})")
    stats = assets.describe(model, textures)
    stats["see_through"] = round(holes * 100, 3)
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
