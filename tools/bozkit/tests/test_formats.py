"""bozkit format tests on synthetic data (no game files). Run: python3 -m unittest discover tools/bozkit/tests"""
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import collision, corpus, gltf, group, map_resources, native, navigation, reflect, resources, save  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402
from bozkit.__main__ import main as cli_main  # noqa: E402


def record(owner, type_name, name, raw):
    return struct.pack('<IIIIII', iw_hash(owner), iw_hash(type_name), 1, iw_hash(name), 1, len(raw)) + raw


def blob(cls, records, size_delta=0):
    body = b''.join(records)
    return b'LFER' + struct.pack('<III', iw_hash(cls), 16 + len(body) + size_delta, len(records)) + body


class FormatTests(unittest.TestCase):
    def test_hash(self):
        self.assertEqual(iw_hash('CWave'), 0x0F41675B)
        self.assertEqual(iw_hash('m_ZombieCount'), iw_hash('M_ZOMBIECOUNT'))

    def test_blob_roundtrip_and_values(self):
        data = blob('CWave', [record('CWave', 'unsigned int', 'm_ZombieCount', struct.pack('<I', 6)),
                              record('CWave', 'float', 'm_ZombieWalk', struct.pack('<f', 1.0)),
                              record('CWave', 'string', 'm_Name', b'wave1\0')])
        b, end = reflect.decode(data)
        self.assertEqual(end, len(data))
        self.assertEqual([reflect.typed_value(p) for p in b.properties], [6, 1.0, 'wave1'])
        self.assertEqual(reflect.encode(b), data)
        reflect.set_typed_value(b.properties[0], 24)
        self.assertEqual(reflect.typed_value(reflect.decode(reflect.encode(b))[0].properties[0]), 24)

    def test_stale_size_and_empty(self):
        data = blob('CIsTransform', [record('CIsTransform', 'bool', 'a', b'\1'),
                                     record('CIsTransform', 'bool', 'b', b'\0')], size_delta=-25)
        b, end = reflect.decode(data)
        self.assertEqual(end, len(data))
        self.assertEqual(reflect.encode(b), data)
        empty = b'LFER' + bytes(12)
        self.assertEqual(reflect.encode(reflect.decode(empty)[0]), empty)

    def test_nested(self):
        inner = blob('CWeaponDamage', [record('CWeaponDamage', 'unsigned int', 'm_headDamage', struct.pack('<I', 100))])
        data = blob('CPlayerWeapon', [record('CPlayerWeapon', 'CWeaponDamage', 'damage', inner)])
        b, _ = reflect.decode(data)
        self.assertIsNotNone(b.properties[0].nested)
        self.assertEqual(reflect.encode(b), data)

    def test_entity_spec(self):
        comp = blob('CPlayerWeapon', [record('CPlayerWeapon', 'unsigned int', 'm_clipSize', struct.pack('<I', 8))])
        child = struct.pack('<I', 0) + struct.pack('<I', 0)
        body = (struct.pack('<I', 1) + struct.pack('<IIII', iw_hash('CIsComponentSpec'), 0, iw_hash('CPlayerWeapon'), len(comp))
                + comp + struct.pack('<I', 1) + struct.pack('<II', iw_hash('CIsEntitySpec'), 0) + child)
        spec = resources.decode_entity_spec(body)
        self.assertEqual(len(spec.components), 1)
        self.assertEqual(len(spec.children), 1)
        self.assertEqual(resources.encode_entity_spec(spec), body)

    def test_group(self):
        res = blob('CWave', [record('CWave', 'unsigned int', 'm_ZombieCount', struct.pack('<I', 6))])
        body = struct.pack('<I', len(res)) + res
        payload = (struct.pack('<I', 1) + struct.pack('<II', iw_hash('CWave'), 1) + bytes([1, 1])
                   + struct.pack('<II', 8 + len(body), 0x1234) + body)
        members = b'test\0'
        data = (bytes([0x3D, 0, 0, 0, 0, 0]) + struct.pack('<II', iw_hash('ResGroupMembers'), len(members) + 4) + members
                + struct.pack('<II', iw_hash('ResGroupResources'), len(payload) + 4) + payload + struct.pack('<I', 0))
        g = group.parse(data)
        self.assertEqual(g.name, 'test')
        self.assertEqual(group.encode(g), data)
        self.assertEqual(reflect.typed_value(resources.decode_reflected(g.types()[0].resources[0].body).properties[0]), 6)

    def test_object_list(self):
        elem = blob('CDOZombieConfig', [record('CDOZombieConfig', 'float', 'baseSpawnRate', struct.pack('<f', 4.0))])
        raw = struct.pack('<I', 2) + elem + elem
        data = blob('CDOZombieSpawner', [record('CDOZombieSpawner', 'std::list<CDOZombieConfig>', 'zombiesTypes', raw)])
        b, _ = reflect.decode(data)
        self.assertEqual(len(b.properties[0].elements), 2)
        self.assertEqual(reflect.encode(b), data)

    def test_game_save_and_settings(self):
        body = b'kino\0' + struct.pack('<I', 0) + struct.pack('<I', 1) + struct.pack('<III', 1, iw_hash('CScoreManager'), 4) + struct.pack('<I', 500)
        data = save.sign(struct.pack('<II', 0x493E1, 0) + body)
        g = save.parse_game_save(data)
        self.assertEqual((g.level, len(g.sections)), ('kino', 1))
        self.assertEqual(save.encode_game_save(g), data)
        values = {name: ('kino' if fmt == 'cstring' else ([False] * 4 if fmt == '<4?' else 0)) for name, fmt, _ in save.SETTINGS_FIELDS}
        values['sensitivity_x'] = 1.5
        settings = save.encode_settings(0x493E0, values)
        self.assertEqual(save.parse_settings(settings)[1]['sensitivity_x'], 1.5)
        with self.assertRaises(ValueError):
            save.parse_settings(settings[:-1] + b'\1')

    def test_writable_texture_preserves_unknown_header(self):
        header = bytearray(range(16))
        header[4] = 0x0E
        struct.pack_into('<HHH', header, 7, 2, 1, 8)
        source = bytes(header) + bytes((1, 2, 3, 4, 5, 6, 7, 8))
        image = Image.new('RGBA', (3, 2), (20, 40, 60, 80))
        encoded = native.encode_texture(image, source)
        layout = native.texture_layout(encoded)
        self.assertEqual((layout.width, layout.height, layout.pitch), (3, 2, 12))
        self.assertEqual(encoded[:7], source[:7])
        self.assertEqual(encoded[13:16], source[13:16])
        self.assertEqual(native.decode_texture(encoded).getpixel((0, 0)), (20, 40, 60, 80))

    def test_visual_exports_reach_input_validation(self):
        errors = StringIO()
        with redirect_stderr(errors):
            self.assertEqual(cli_main(['texture-export', 'missing.group.bin', '0x1', 'out.png']), 1)
            self.assertEqual(cli_main(['model-export', 'missing.group.bin', '0x1', 'out.gltf']), 1)
        self.assertNotIn('experimental', errors.getvalue())

    def test_writable_texture_png_and_rgb565(self):
        image = Image.new('RGB', (2, 2), (255, 128, 0))
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / 'source.png'
            image.save(png)
            body = native.encode_texture_png(png, bytes_per_pixel=2)
        self.assertEqual(native.texture_layout(body).bytes_per_pixel, 2)
        red, green, blue = native.decode_texture(body).getpixel((0, 0))
        self.assertGreater(red, 245)
        self.assertGreater(green, 120)
        self.assertLess(blue, 10)

    def test_bgra8888_native_channel_order(self):
        header = bytearray(16)
        header[4] = 0x0E
        struct.pack_into('<HHH', header, 7, 1, 1, 4)
        image = native.decode_texture(bytes(header) + bytes((0, 0, 255, 255)))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_material_roundtrip_and_edit(self):
        source = (b'\0' + struct.pack('<I', 0x12345678) + b'abcd' +
                  bytes(range(16)) + struct.pack('<III', 2, 0x11111111, 0x22222222) + b'tail')
        material = native.decode_material(source)
        self.assertEqual(native.encode_material(material), source)
        material.textures[1] = 0x33333333
        encoded = native.encode_material(material)
        self.assertEqual(encoded[-4:], b'tail')
        self.assertEqual(native.decode_material(encoded).textures[1], 0x33333333)

    def test_model_create_patch_and_validation(self):
        model = native.Model([(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)],
                             [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        source = native.encode_model(model)
        self.assertEqual(native.decode_model(source), model)
        model.vertices[1] = (12, 0, 0)
        patched = native.encode_model(model, source)
        self.assertEqual(native.decode_model(patched).vertices[1], (12, 0, 0))
        with self.assertRaises(ValueError):
            native.encode_model(native.Model([(0, 0, 0)], [(0, 1, 2)]))

    def test_model_preserves_degenerate_triangles(self):
        authored = native.Model([(0, 0, 0), (10, 0, 0), (0, 10, 0), (5, 5, 0)],
                                [(0, 1, 2), (2, 0, 3), (0, 0, 1)])
        source = native.encode_model(authored)
        decoded = native.decode_model(source)
        self.assertEqual(decoded.triangles, [(0, 1, 2), (2, 0, 3)])
        self.assertEqual(native.encode_model(decoded, source), source)

    def test_model_gltf_roundtrip(self):
        model = native.Model([(-2, 0, 1), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)],
                             [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.gltf'
            gltf.export_model(model, path, 'synthetic')
            imported = gltf.import_model(path)
        self.assertEqual(imported, model)

    def test_navigation_roundtrip_and_settings_edit(self):
        config = bytearray(80)
        struct.pack_into('<6f', config, 0, 0.1, 0.15, 1.5, 0.4, 0.4, 50.0)
        tile = b'VAND' + struct.pack('<I', 7) + bytes(24)
        source = (bytes(config) + b'TESM' +
                  struct.pack('<II3f2fII', 1, 1, 0.0, 0.0, 0.0, 20.0, 20.0, 16, 262144) +
                  struct.pack('<II', 0x400000, len(tile)) + tile + b'trailer')
        mesh = navigation.decode(source)
        self.assertEqual(navigation.encode(mesh), source)
        self.assertAlmostEqual(mesh.config.agent_radius, 0.4)
        mesh.config.agent_radius = 0.5
        edited = navigation.encode(mesh)
        self.assertEqual(edited[80:], source[80:])
        self.assertAlmostEqual(navigation.decode(edited).config.agent_radius, 0.5)

    def test_navigation_connection_roundtrip(self):
        connection = navigation.NavMeshConnection((1.0, 2.0, 3.0), (4.0, 5.0, 6.0),
                                                   (0.0, 0.0, 0.0, 1.0), 2, 128,
                                                   100.0, 90.0, True, False)
        encoded = navigation.encode_connection(connection)
        self.assertEqual(len(encoded), 55)
        self.assertEqual(navigation.decode_connection(encoded), connection)

    def test_portal_roundtrip_and_sector_edit(self):
        portal = map_resources.Portal([(0.0, 0.0, 0.0), (0.0, 2.0, 0.0),
                                       (0.0, 2.0, 3.0), (0.0, 0.0, 3.0)],
                                      (1.0, 0.0, 0.0), 0.0, 'lobby', 'stage')
        encoded = map_resources.encode_portal(portal)
        self.assertEqual(map_resources.decode_portal(encoded), portal)
        portal.back_sector = 'theatre'
        edited = map_resources.decode_portal(map_resources.encode_portal(portal))
        self.assertEqual(edited.back_sector, 'theatre')

    def test_collision_mesh_roundtrip_and_edit(self):
        mesh = collision.CollisionMesh(b'BULLET',
                                       [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                        (0.0, 1.0, 0.0)], [0, 1, 2], b'\x07')
        encoded = collision.encode(mesh)
        self.assertEqual(collision.decode(encoded), mesh)
        mesh.vertices[1] = (2.0, 0.0, 0.0)
        self.assertEqual(collision.decode(collision.encode(mesh)).vertices[1], (2.0, 0.0, 0.0))

    def test_private_corpus_report_contains_hashes_not_bodies(self):
        res = blob('CWave', [record('CWave', 'unsigned int', 'm_ZombieCount', struct.pack('<I', 6))])
        body = struct.pack('<I', len(res)) + res
        payload = (struct.pack('<I', 1) + struct.pack('<II', iw_hash('CWave'), 1) + bytes([1, 1]) +
                   struct.pack('<II', 8 + len(body), 0x1234) + body)
        data = (bytes([0x3D, 0, 0, 0, 0, 0]) +
                struct.pack('<II', iw_hash('ResGroupResources'), len(payload) + 4) + payload +
                struct.pack('<I', 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.group.bin'
            path.write_bytes(data)
            report = corpus.audit([directory])
        self.assertTrue(report['summary']['all_byte_identical'])
        self.assertEqual(report['summary']['groups'], 1)
        self.assertEqual(report['groups'][0]['input_sha256'], report['groups'][0]['roundtrip_sha256'])
        self.assertEqual(report['classes'][0]['codec_coverage'], 'full')
        self.assertNotIn(res.hex(), str(report))

    def test_private_corpus_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deadops-test.group.bin'
            path.write_bytes(bytes([0x3D, 0, 0, 0, 0, 0]) + struct.pack('<I', 0))
            report = corpus.audit([directory], ('*deadops*',))
        self.assertEqual(report['summary']['groups'], 0)


if __name__ == '__main__':
    unittest.main()
