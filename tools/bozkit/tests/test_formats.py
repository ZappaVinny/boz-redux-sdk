"""bozkit format tests on synthetic data (no game files). Run: python3 -m unittest discover tools/bozkit/tests"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import group, reflect, resources, save  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402


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


if __name__ == '__main__':
    unittest.main()
