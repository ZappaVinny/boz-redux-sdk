"""The asset library on a synthetic game pack (no game files)."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bozkit import derbh, group, levels, library, native, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402
from test_levels import make_dz  # noqa: E402


def raw_texture(width: int, height: int, colour: tuple[int, int, int, int]) -> bytes:
    template = bytearray(17) + bytes(4) + b'\0'
    template[4] = 0x0E
    struct.pack_into('<HHH', template, 7, 1, 1, 4)
    blue_green_red_alpha = bytes((colour[2], colour[1], colour[0], colour[3]))
    return native.build_texture(width, height, blue_green_red_alpha * (width * height),
                                bytes(template))


def resource_type(class_name: str, items: list[tuple[str, bytes]]) -> group.ResourceType:
    return group.ResourceType(iw_hash(class_name), 1, 1,
                              [group.Resource(None, iw_hash(name), body) for name, body in items])


def weapon_spec(model_name: str) -> bytes:
    prop = reflect.Property(iw_hash('CPlayerWeapon'), iw_hash('unsigned int'), iw_hash('m_name'), b'')
    reflect.set_typed_value(prop, iw_hash(model_name))
    component = resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CPlayerWeapon'),
                                    [reflect.Blob(iw_hash('CPlayerWeapon'), [prop])])
    return resources.encode_entity_spec(resources.EntitySpec([component]))


def game_pack() -> bytes:
    material = native.encode_material(native.Material(False, 0, b'\0' * 4, [(255, 255, 255, 255)] * 4,
                                                      [iw_hash('gun_skin')]))
    model = native.build_model([(0, 0, 0), (100, 0, 0), (0, 100, 0)],
                               [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], [(0, 1, 2)],
                               [iw_hash('gun_mat')])
    weapons = levels.make_group('weapons_kino', types=[
        resource_type('CIwTexture', [('gun_skin', raw_texture(8, 8, (200, 30, 30, 255)))]),
        resource_type('CIwMaterial', [('gun_mat', material)]),
        resource_type('CIwModel', [('pistol', model)]),
        resource_type('CIsEntitySpec', [('pistol', weapon_spec('pistol'))])])
    files = {'ingame/weapons/weapons_kino.group.bin': weapons,
             'levels/kino/kino.group.bin': levels.make_group('kino')}
    # The same texture name with different pictures in two maps' loading screens.
    for level, colour in (('kino', (0, 0, 255, 255)), ('callofthedead', (0, 255, 0, 255))):
        files[f'loading/{level}/loading.group.bin'] = levels.make_group('loading', types=[
            resource_type('CIwTexture', [('loading_art', raw_texture(16, 8, colour))])])
        files.setdefault(f'levels/{level}/{level}.group.bin', levels.make_group(level))
    files['deadops/skip.group.bin'] = levels.make_group('skip')
    return make_dz({path: (group.encode(value), derbh.STORED) for path, value in files.items()})


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        patcher = mock.patch.dict(os.environ, {'BOZ_SDK_HOME': str(self.root / 'home')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.root / 'client'
        (self.client / 'assets').mkdir(parents=True)
        (self.client / 'assets' / library.PACK).write_bytes(game_pack())

    def tearDown(self):
        self.temp.cleanup()

    def test_build_index_and_search(self):
        self.assertTrue(library.needs_build(self.client))
        messages = []
        folder = library.build(self.client, progress=lambda fraction, text: messages.append(fraction))
        self.assertEqual(folder, library.library_dir())
        self.assertFalse(library.needs_build(self.client))
        self.assertEqual(messages[-1], 1.0)
        self.assertTrue((folder / 'groups' / 'ingame/weapons/weapons_kino.group.bin').is_file())
        self.assertFalse((folder / 'groups' / 'deadops').exists())

        built = library.Library()
        try:
            (weapon,) = built.search(kind='weapon')
            self.assertEqual(weapon.model, iw_hash('pistol'))  # found through m_name
            self.assertTrue(built.thumb_path(weapon).is_file())
            (model,) = built.search(kind='model')
            self.assertEqual(model.triangles, 1)
            self.assertEqual(model.thumb, weapon.thumb)
            (material,) = built.search(kind='material')
            self.assertTrue(material.thumb.startswith('texture/'))  # its texture's preview
            textures = built.search(kind='texture')
            self.assertEqual(len(textures), 3)  # the gun skin and two loading screen variants
            loading = [texture for texture in textures if texture.hash == iw_hash('loading_art')]
            self.assertEqual(len({texture.variant for texture in loading}), 2)
            self.assertEqual(built.search(f'0x{iw_hash("pistol"):08x}', kind='model')[0].hash,
                             iw_hash('pistol'))
            self.assertEqual([asset.kind for asset in built.search(level='kino', kind='weapon')],
                             ['weapon'])
            maps = {item.name: item for item in built.maps()}
            self.assertEqual(set(maps), {'kino', 'callofthedead'})
            self.assertIn('ingame/weapons/weapons_kino.group.bin', maps['kino'].groups)
            kino = built.thumb_path(maps['kino'])
            dead = built.thumb_path(maps['callofthedead'])
            from PIL import Image
            self.assertEqual(Image.open(kino).convert('RGB').getpixel((0, 0)), (0, 0, 255))
            self.assertEqual(Image.open(dead).convert('RGB').getpixel((0, 0)), (0, 255, 0))
        finally:
            built.close()

    def test_cancel_keeps_the_old_library(self):
        library.build(self.client)
        with self.assertRaises(library.Cancelled):
            library.build(self.client, cancelled=lambda: True)
        self.assertTrue((library.library_dir() / 'index.sqlite').is_file())

    def test_map_of_and_template_groups(self):
        self.assertEqual(library.map_of('levels/kino/alley_shared.group.bin'), 'kino')
        self.assertEqual(library.map_of('ingame/weapons/weapons_ascension.group.bin'), 'ascension')
        self.assertEqual(library.map_of('ingame/ingame.group.bin'), 'shared')
        paths = ['levels/tutorial/tutorial.group.bin', 'ingame/weapons/weapons_kino.group.bin',
                 'ingame/characters/arms/arms_kino.group.bin', 'levels/kino/kino.group.bin']
        self.assertEqual(library.map_groups(paths, 'tutorial'), sorted(paths[:3]))


if __name__ == '__main__':
    unittest.main()
