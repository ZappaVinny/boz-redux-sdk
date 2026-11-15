import json
import tempfile
import unittest
from pathlib import Path

from bozkit import assets


class LinkedFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.src = self.base / 'rip'
        (self.src / '_images').mkdir(parents=True)
        for name in ('a_c.png', 'a_n.png', 'b_c.png'):
            (self.src / '_images' / name).write_bytes(b'png')

    def tearDown(self):
        self.tmp.cleanup()

    def test_obj_mtl(self):
        (self.src / 'm.mtl').write_text('newmtl x\nmap_Kd _images/a_c.png\nmap_Bump -bm 1 _images/a_n.png\n')
        (self.src / 'm.obj').write_text('mtllib m.mtl\nv 0 0 0\n')
        names = sorted(f.name for f in assets.referenced_files(self.src / 'm.obj'))
        self.assertEqual(names, ['a_c.png', 'a_n.png', 'm.mtl'])

    def test_gltf(self):
        (self.src / 'm.bin').write_bytes(b'\0')
        (self.src / 'm.gltf').write_text(json.dumps({'buffers': [{'uri': 'm.bin'}],
                                                     'images': [{'uri': '_images/b_c.png'}, {'uri': 'data:x'}]}))
        self.assertEqual(sorted(f.name for f in assets.referenced_files(self.src / 'm.gltf')), ['b_c.png', 'm.bin'])

    def test_binary_paths_copied_beside(self):
        # Like a .blend: Blender's //-relative paths inside binary data, with junk around them.
        (self.src / 'm.blend').write_bytes(b'BLENDER\x00\x01//_images/a_c.png\x00\xff\x02IM//_images/b_c.png\x00')
        root = self.base / 'project'
        copy = assets.copy_source(root, 'staff', self.src / 'm.blend')
        self.assertEqual(copy, 'assets/staff/m.blend')
        self.assertTrue((root / 'assets/staff/_images/a_c.png').is_file())
        self.assertTrue((root / 'assets/staff/_images/b_c.png').is_file())

    def test_repair_from_original(self):
        root = self.base / 'project'
        (root / 'assets/staff').mkdir(parents=True)
        asset = assets.AssetDef('staff', 'weapon', 'assets/staff/m.blend', str(self.src / 'm.blend'))
        found = assets.find_linked(root, asset, 'A_N.png')
        self.assertEqual(found, root / 'assets/staff/_images/a_n.png')
        self.assertTrue(found.is_file())
        self.assertIsNone(assets.find_linked(root, asset, 'nowhere.png'))


if __name__ == '__main__':
    unittest.main()
