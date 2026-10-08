"""Check generated/packed image pixels, including reopening a saved Blender project.

Run: ALSOFT_DRIVERS=null blender -b --factory-startup --python-exit-code 1
     --python blender/tests/texture_pixels.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'blender'), str(ROOT / 'tools' / 'bozkit')]
import bpy
from boz_redux.operators import _native_materials
from bozkit.blender_scene import SceneImport, SceneTexture, SceneMaterial

# Asymmetric rows catch vertical-flip errors as well as black/reset buffers.
rgba = bytes((255, 0, 0, 255, 0, 255, 0, 255,
              0, 0, 255, 255, 128, 64, 32, 128))
scene = SceneImport('synthetic')
scene.textures[123] = SceneTexture(123, 2, 2, rgba, 'synthetic')
scene.materials[456] = SceneMaterial(456, [123])
expected = [v / 255 for v in rgba[8:] + rgba[:8]]

def check():
    image = bpy.data.images['BOZ Texture 0000007b']
    assert image.packed_file is not None
    assert all(abs(a-b) < 1/255 for a, b in zip(image.pixels[:], expected, strict=True)), list(image.pixels[:])
    material = bpy.data.materials['BOZ Material 000001c8']
    texture = next(n for n in material.node_tree.nodes if n.type == 'TEX_IMAGE')
    assert texture.image == image
    assert texture.inputs['Vector'].links[0].from_node.uv_map == 'UVMap'

_native_materials(scene)
bpy.data.objects['Cube'].data.materials.append(bpy.data.materials['BOZ Material 000001c8'])
check()
_native_materials(scene)  # Reimport must also preserve the pixels.
check()
with tempfile.TemporaryDirectory(prefix='boz-texture-test-') as directory:
    path = str(Path(directory) / 'texture.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    check()

# Reimport must replace the shader graph, including when native blend mode changes.
for mode, shader in [(0, 'EMISSION'), (1, 'MIX_SHADER'), (2, 'ADD_SHADER'),
                     (3, 'BSDF_TRANSPARENT'), (4, 'MIX_SHADER'), (5, 'EMISSION'),
                     (0, 'EMISSION')]:
    scene.materials[456].flags = mode << 16
    _native_materials(scene)
    material = bpy.data.materials['BOZ Material 000001c8']
    output = next(n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL')
    assert output.inputs['Surface'].links[0].from_node.type == shader
    assert len([n for n in material.node_tree.nodes if n.type == 'UVMAP']) == 1
scene.textures[123].flags = 8
scene.materials[456].flags = 5 << 16
_native_materials(scene)
material = bpy.data.materials['BOZ Material 000001c8']
cutoff = material.node_tree.nodes['BOZ Native Alpha Test']
assert cutoff.operation == 'GREATER_THAN'
assert cutoff.inputs[1].default_value == 0.75
assert material.node_tree.nodes['BOZ Alpha Mix'].inputs[0].links[0].from_node == cutoff
print('BOZ_TEXTURE_PIXELS_OK')
