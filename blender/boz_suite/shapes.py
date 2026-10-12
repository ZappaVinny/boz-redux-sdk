"""Game-sized building shapes and model import.

One Blender unit is one game centimetre, so Blender's own Add → Mesh primitives come out 2 cm big.
Add → Game shapes makes blocks, walls, floors, ramps, stairs and pillars at game sizes, with a
default texture that tiles every metre and the right Collision setting. Project → Import model…
brings in FBX, glTF and OBJ files scaled from metres to centimetres.
"""
from __future__ import annotations

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Menu, Operator

try:
    from bozkit import world
except ModuleNotFoundError:
    from ._vendor.bozkit import world

from . import convert

TILE = 100.0          # centimetres per texture repeat
MAX_REPEATS = 7.5     # game UVs stay within -8..8
DEFAULT_TEXTURE = "BOZ Default"

BOX_SHAPES = ("block", "wall", "floor", "pillar")   # collide as their box; ramps and stairs as their mesh
# kind: (label, icon, collision, description)
SHAPES = {
    "block": ("Block", "MESH_CUBE", "solid", "A 1 m cube"),
    "wall": ("Wall", "MOD_BUILD", "solid", "A wall 3 m wide, 3 m tall and 20 cm thick"),
    "floor": ("Floor", "MESH_PLANE", "floor", "A floor slab 4 m square and 10 cm thick"),
    "ramp": ("Ramp", "IPO_LINEAR", "floor", "A ramp 2 m wide rising 2 m over 4 m"),
    "stairs": ("Stairs", "NLA_PUSHDOWN", "floor", "Eight steps, 2 m wide, rising 2 m"),
    "pillar": ("Pillar", "MESH_CYLINDER", "solid", "A round pillar 60 cm across and 3 m tall"),
}


def _box(x0, x1, y0, y1, z0, z1) -> list:
    """Six outward-facing quads (Blender axes, centimetres)."""
    return [
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],   # bottom
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],   # top
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],   # front (-y)
        [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)],   # back (+y)
        [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)],   # left (-x)
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],   # right (+x)
    ]


def _faces(kind: str) -> list:
    if kind == "block":
        return _box(-50, 50, -50, 50, 0, 100)
    if kind == "wall":
        return _box(-150, 150, -10, 10, 0, 300)
    if kind == "floor":
        return _box(-200, 200, -200, 200, -10, 0)
    if kind == "ramp":
        x0, x1, y0, y1, h = -100, 100, -200, 200, 200
        return [
            [(x0, y0, 0), (x0, y1, 0), (x1, y1, 0), (x1, y0, 0)],          # bottom
            [(x0, y0, 0), (x1, y0, 0), (x1, y1, h), (x0, y1, h)],          # slope
            [(x1, y1, 0), (x0, y1, 0), (x0, y1, h), (x1, y1, h)],          # back
            [(x0, y1, 0), (x0, y0, 0), (x0, y1, h)],                       # left
            [(x1, y0, 0), (x1, y1, 0), (x1, y1, h)],                       # right
        ]
    if kind == "stairs":
        faces = []
        steps, rise, run = 8, 25, 30
        for step in range(steps):
            y0 = -steps * run / 2 + step * run
            faces += _box(-100, 100, y0, y0 + run, 0, rise * (step + 1))
        return faces
    if kind == "pillar":
        sides, radius, height = 12, 30, 300
        ring = [(radius * math.cos(2 * math.pi * i / sides),
                 radius * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
        faces = [[(x, y, 0) for x, y in reversed(ring)], [(x, y, height) for x, y in ring]]
        for i in range(sides):
            (ax, ay), (bx, by) = ring[i], ring[(i + 1) % sides]
            faces.append([(ax, ay, 0), (bx, by, 0), (bx, by, height), (ax, ay, height)])
        return faces
    raise ValueError(kind)


def _uv(face) -> list:
    """Planar UVs for one face: the two axes across its normal, one repeat per metre (fewer on
    big faces, so the game's UV range holds)."""
    a, b, c = face[0], face[1], face[2]
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    normal = [abs(u[1] * v[2] - u[2] * v[1]), abs(u[2] * v[0] - u[0] * v[2]),
              abs(u[0] * v[1] - u[1] * v[0])]
    drop = normal.index(max(normal))
    axes = [i for i in range(3) if i != drop]
    lows = [min(p[i] for p in face) for i in axes]
    spans = [max(p[i] for p in face) - lows[k] for k, i in enumerate(axes)]
    tile = max(TILE, max(spans) / MAX_REPEATS)
    return [((p[axes[0]] - lows[0]) / tile, (p[axes[1]] - lows[1]) / tile) for p in face]


def shape_mesh(kind: str, name: str):
    faces = _faces(kind)
    vertices, polygons, uvs = [], [], []
    for face in faces:
        start = len(vertices)
        vertices.extend(face)
        polygons.append(list(range(start, start + len(face))))
        uvs.extend(_uv(face))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], polygons)
    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", [c for uv in uvs for c in uv])   # one loop per face corner
    mesh.update()
    mesh.materials.append(default_material())
    return mesh


def default_material():
    """A grey grid texture: shows the shape in the game until a real texture is dropped on it."""
    material = bpy.data.materials.get(DEFAULT_TEXTURE)
    if material is not None:
        return material
    size = 64
    bgra = bytearray()
    for y in range(size):
        for x in range(size):
            edge = x % 32 in (0, 31) or y % 32 in (0, 31)
            value = 96 if edge else 150 + ((x // 32 + y // 32) % 2) * 20
            bgra += bytes((value, value, value, 255))
    image = convert._image_from_texture(DEFAULT_TEXTURE, world.Texture(size, size, bytes(bgra)), None)
    return convert.material_for(DEFAULT_TEXTURE, image)


class BOZ_OT_add_shape(Operator):
    bl_idname = "boz.add_shape"
    bl_label = "Add game shape"
    bl_description = "Add a game-sized shape at the 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(items=[(key, label, description, icon, index) for index, (key, (
        label, icon, _collision, description)) in enumerate(SHAPES.items())])

    @classmethod
    def description(cls, context, properties):
        return SHAPES[properties.kind][3]

    def execute(self, context):
        label, _icon, collision, _description = SHAPES[self.kind]
        obj = bpy.data.objects.new(label.lower(), shape_mesh(self.kind, label.lower()))
        obj.boz.role = "model"
        obj.boz.collision = collision
        obj.boz.shape = "box" if self.kind in BOX_SHAPES else "mesh"
        obj.location = context.scene.cursor.location
        convert.map_collection(context.scene).objects.link(obj)
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class BOZ_MT_shapes(Menu):
    bl_label = "Game shapes"
    bl_idname = "BOZ_MT_shapes"

    def draw(self, context):
        for key, (label, icon, _collision, _description) in SHAPES.items():
            self.layout.operator(BOZ_OT_add_shape.bl_idname, text=label, icon=icon).kind = key


IMPORTERS = {".fbx": ("import_scene", "fbx"), ".glb": ("import_scene", "gltf"),
             ".gltf": ("import_scene", "gltf"), ".obj": ("wm", "obj_import")}


class BOZ_OT_import_model(Operator):
    bl_idname = "boz.import_model"
    bl_label = "Import model…"
    bl_description = ("Bring in an FBX, glTF or OBJ model as level geometry (scaled from metres "
                      "to the game's centimetres)")
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.fbx;*.glb;*.gltf;*.obj", options={"HIDDEN"})
    metres: BoolProperty(name="The file is in metres", default=True,
                         description="Most tools export metres; the game uses centimetres")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import os
        extension = os.path.splitext(self.filepath)[1].lower()
        if extension not in IMPORTERS:
            self.report({"ERROR"}, "Pick an .fbx, .glb, .gltf or .obj file")
            return {"CANCELLED"}
        module, name = IMPORTERS[extension]
        importer = getattr(getattr(bpy.ops, module), name, None)
        before = set(bpy.data.objects)
        try:
            importer(filepath=self.filepath)
        except (RuntimeError, AttributeError) as exc:
            self.report({"ERROR"}, f"Import failed: {exc}")
            return {"CANCELLED"}
        new = [obj for obj in bpy.data.objects if obj not in before]
        roots = [obj for obj in new if obj.parent not in new]
        for obj in new:
            if obj.parent is None or obj.parent not in new:
                convert.move_to(obj, convert.map_collection(context.scene))
        for obj in roots:
            obj.location = context.scene.cursor.location
            if self.metres:
                obj.scale = tuple(c * 100.0 for c in obj.scale)
        meshes = [obj for obj in new if obj.type == "MESH"]
        for obj in meshes:
            obj.boz.role = "model"
            obj.boz.collision = "solid"
        untextured = [obj.name for obj in meshes
                      if not any(convert.image_of(slot.material) for slot in obj.material_slots)]
        for obj in meshes:
            if obj.name in untextured:
                obj.data.materials.clear()
                obj.data.materials.append(default_material())
        message = f"Imported {len(meshes)} meshes (Collision: Blocking)"
        if untextured:
            message += f"; {len(untextured)} had no texture and got the default one"
        self.report({"INFO"}, message)
        return {"FINISHED"}


def draw_add_menu(self, context):
    self.layout.menu(BOZ_MT_shapes.bl_idname, icon="MESH_CUBE")
    self.layout.operator(BOZ_OT_import_model.bl_idname, icon="IMPORT")
    self.layout.separator()


CLASSES = (BOZ_OT_add_shape, BOZ_MT_shapes, BOZ_OT_import_model)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_add.prepend(draw_add_menu)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_add_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
