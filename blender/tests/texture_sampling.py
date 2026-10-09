"""Render a synthetic texture through the actual importer, not just its image buffer."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'blender'), str(ROOT / 'tools' / 'bozkit')]
import bpy
from boz_redux.operators import _native_materials, _mesh_object, _display_like_game
from bozkit.blender_scene import SceneImport, SceneTexture, SceneMaterial, SceneMesh

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
result = SceneImport('synthetic')
result.textures[1] = SceneTexture(1, 2, 2, bytes((
    255, 0, 0, 255, 0, 255, 0, 255,
    0, 0, 255, 255, 128, 64, 32, 255)), 'synthetic')
result.materials[2] = SceneMaterial(2, [1])
_native_materials(result)
item = SceneMesh('placed_model', 0, 0, 0, 'synthetic', 'UV test', 'Test',
    vertices=[(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)],
    faces=[(0,1,2), (0,2,3)], uvs=[(0,0), (1,0), (1,1), (0,1)],
    material_hashes=[2])
obj = _mesh_object(bpy.context, item)
assert obj.data.uv_layers['UVMap'].active_render
material = obj.data.materials[0]
texture = next(n for n in material.node_tree.nodes if n.type == 'TEX_IMAGE')
assert texture.inputs['Vector'].links[0].from_node.uv_map == 'UVMap'
texture.interpolation = 'Closest'
bpy.ops.object.camera_add(location=(0,0,3))
camera = bpy.context.object
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 2
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
_display_like_game(scene)
scene.render.image_settings.file_format = 'PNG'
with tempfile.TemporaryDirectory(prefix='boz-uv-render-') as directory:
    scene.render.filepath = str(Path(directory) / 'uv.png')
    bpy.ops.render.render(write_still=True)
    rendered = bpy.data.images.load(scene.render.filepath)
    pixels = rendered.pixels[:]
    # Native UVs follow GL: v = 0 samples the first stored row (red, green), so it renders at
    # the bottom of this quad. The mid-grey texel checks that the game's display-encoded value
    # reaches the screen unchanged through the decode node and the Standard view transform.
    assert scene.view_settings.view_transform == 'Standard'
    for x, y, expected in [(16,16,(1,0,0)), (48,16,(0,1,0)),
                            (16,48,(0,0,1)), (48,48,(128/255,64/255,32/255))]:
        actual = pixels[(y*64+x)*4:(y*64+x)*4+3]
        assert all(abs(a-b)<0.01 for a,b in zip(actual,expected)), (x,y,actual)
print('BOZ_TEXTURE_SAMPLING_OK')
