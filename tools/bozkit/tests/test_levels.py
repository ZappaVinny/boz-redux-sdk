"""New levels and the .dz reader on synthetic data (no game files)."""
import lzma
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import derbh, group, levels, native, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402


def make_dz(files: dict[str, tuple[bytes, int]]) -> bytes:
    """A DTRZ archive; *files* maps 'folder/name' to (data, method)."""
    folders = sorted({path.rpartition('/')[0] for path in files} - {''})
    names = list(files)
    out = bytearray(b'DTRZ' + struct.pack('<HH', len(names), len(folders) + 1) + b'\0')
    for path in names:
        out += path.rpartition('/')[2].encode() + b'\0'
    for folder in folders:
        out += folder.replace('/', '\\').encode() + b'\0'
    for i, path in enumerate(names):
        folder = path.rpartition('/')[0]
        out += struct.pack('<HHH', folders.index(folder) + 1 if folder else 0, i, 0)
    out += b'\0\0'  # the short header before the location table
    blobs = []
    for data, method in files.values():
        if method == derbh.LZMA:
            blobs.append(lzma.compress(data, format=lzma.FORMAT_ALONE))
        else:
            blobs.append(data)
    offset = len(out) + 16 * (len(names) + 1)
    table, body = bytearray(), bytearray()
    for (data, method), blob in zip(files.values(), blobs):
        table += struct.pack('<IIII', offset + len(body), len(blob), len(data), method)
        body += blob
    table += struct.pack('<IIII', offset + len(body), 0, 0, derbh.STORED)
    return bytes(out + table + body)


class FakePack:
    def __init__(self, groups: dict[str, group.Group]):
        self.files = {f'{path}.group.bin': group.encode(value) for path, value in groups.items()}

    def read(self, path):
        return self.files[path]


def child(path, name):
    return levels.Child(path, name)


def level_pack():
    statics = levels.make_group('kino_statics', [child('levels/kino//kino_sectors.group',
                                                       'kino_sectors')], [
        group.ResourceType(levels.LEVEL, 1, 1, [group.Resource(None, iw_hash('kino'), b'LEVEL')]),
        group.ResourceType(iw_hash('CIsEntitySpec'), 1, 1,
                           [group.Resource(None, iw_hash('spawn_player_1'), b'SPAWN')])])
    loading = group.ResourceType(levels.RESOLUTION_STRING, 1, 1, [
        group.Resource(None, iw_hash('loading-kino'), b'loading/kino/loading_droid.group\0')])
    return FakePack({
        'fixed/fixed': levels.make_group('fixed', types=[loading], flags=1),
        'levels/kino/kino': levels.make_group('kino', [
            child('levels/kino//kino_dynamics.group', 'kino_dynamics'),
            child('levels/kino//kino_statics.group', 'kino_statics')]),
        'levels/kino/kino_statics': statics,
        'levels/kino/kino_sectors': levels.make_group('kino_sectors', [
            child('levels/kino//alley_shared.group', 'alley')], flags=1),
        'ingame/weapons/weapons_kino': levels.make_group('weapons_kino', [
            child('ingame/weapons//weapon_projectiles_kino.group', 'weapon_projectiles_kino')], [
            group.ResourceType(iw_hash('CPlayerWeapon'), 1, 1,
                               [group.Resource(None, iw_hash('colt45'), b'COLT')])]),
        'ingame/weapons/weapon_projectiles_kino': levels.make_group('weapon_projectiles_kino'),
        'ingame/characters/arms/arms_kino': levels.make_group('arms_kino'),
    })


class DerbhTests(unittest.TestCase):
    def test_reads_stored_and_lzma_entries_by_path(self):
        archive = make_dz({'fixed/fixed.group.bin': (b'stored bytes', derbh.STORED),
                           'levels/kino/kino.group.bin': (b'packed ' * 50, derbh.LZMA),
                           'console.bin': (b'root file', derbh.STORED)})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.dz'
            path.write_bytes(archive)
            pack = derbh.Pack(path)
            self.assertEqual(pack.names(), ['console.bin', 'fixed/fixed.group.bin',
                                            'levels/kino/kino.group.bin'])
            self.assertEqual(pack.read('fixed/fixed.group.bin'), b'stored bytes')
            self.assertEqual(pack.read('Levels/Kino/kino.group.bin'), b'packed ' * 50)
            self.assertEqual(pack.read('console.bin'), b'root file')
            self.assertIn('levels/kino/kino.group.bin', pack)
            with self.assertRaises(KeyError):
                pack.read('levels/nope.group.bin')
            pack.close()


class LevelTests(unittest.TestCase):
    def test_children_round_trip(self):
        made = levels.make_group('kino', [child('levels/kino//kino_statics.group', 'kino_statics')])
        parsed = group.parse(group.encode(made))
        self.assertEqual(parsed.name, 'kino')
        self.assertEqual([(p, h) for p, h, _ in levels.children(parsed)],
                         [('levels/kino//kino_statics.group', iw_hash('kino_statics'))])

    def test_names_must_be_new_and_plain(self):
        for bad in ('kino', 'Kino', 'my level', '', 'x' * 41):
            with self.assertRaises(levels.LevelError):
                levels.check_name(bad)
        self.assertEqual(levels.check_name('redux_test2'), 'redux_test2')

    def test_clone_renames_the_level_and_reuses_shipped_groups(self):
        files = levels.clone_level(level_pack(), 'redux_test')
        with tempfile.TemporaryDirectory() as folder:
            written = {path.name: group.parse(path.read_bytes()) for path in files.write(folder)}
        self.assertEqual(sorted(written), [
            'arms_redux_test.group.bin', 'fixed.group.bin', 'redux_test.group.bin',
            'redux_test_sectors.group.bin', 'redux_test_statics.group.bin',
            'weapon_projectiles_redux_test.group.bin', 'weapons_redux_test.group.bin'])
        root = written['redux_test.group.bin']
        self.assertEqual(root.name, 'redux_test')
        self.assertEqual([(p, h) for p, h, _ in levels.children(root)], [
            ('levels/kino//kino_dynamics.group', iw_hash('kino_dynamics')),
            ('levels/redux_test//redux_test_statics.group', iw_hash('redux_test_statics'))])
        statics = written['redux_test_statics.group.bin']
        self.assertEqual(statics.name, 'redux_test_statics')
        self.assertEqual(levels.children(statics)[0][:2], (
            'levels/redux_test//redux_test_sectors.group', iw_hash('redux_test_sectors')))
        level = next(t for t in statics.types() if t.class_hash == levels.LEVEL).resources[0]
        self.assertEqual((level.in_group_hash, level.body), (iw_hash('redux_test'), b'LEVEL'))
        sectors = written['redux_test_sectors.group.bin']
        self.assertEqual((sectors.name, levels.members_flags(sectors)), ('redux_test_sectors', 1))
        self.assertEqual(levels.children(sectors)[0][0], 'levels/kino//alley_shared.group')
        # The weapon manager reads weapons_<level> itself, so it is a renamed copy of Kino's.
        weapons = written['weapons_redux_test.group.bin']
        self.assertEqual(weapons.name, 'weapons_redux_test')
        self.assertEqual(weapons.types()[0].resources[0].body, b'COLT')
        self.assertEqual([(p, h) for p, h, _ in levels.children(weapons)], [
            ('ingame/weapons//weapon_projectiles_redux_test.group',
             iw_hash('weapon_projectiles_redux_test'))])
        self.assertEqual(written['weapon_projectiles_redux_test.group.bin'].name,
                         'weapon_projectiles_redux_test')
        strings = next(t for t in written['fixed.group.bin'].types()
                       if t.class_hash == levels.RESOLUTION_STRING).resources
        self.assertEqual({r.in_group_hash: r.body for r in strings}[iw_hash('loading-redux_test')],
                         b'loading/kino/loading_droid.group\0')

    def test_loading_screen_is_added_once(self):
        pack = level_pack()
        fixed = group.parse(pack.read('fixed/fixed.group.bin'))
        levels.add_loading_screen(fixed, 'kino', 'redux_test')
        levels.add_loading_screen(fixed, 'kino', 'redux_test')
        strings = next(t for t in fixed.types() if t.class_hash == levels.RESOLUTION_STRING)
        self.assertEqual(len(strings.resources), 2)


class GeneratedAssetTests(unittest.TestCase):
    def test_new_model_decodes_back(self):
        vertices = [(0, 0, 0), (100, 0, 0), (100, 0, 100), (0, 300, 100)]
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        triangles = [(0, 1, 2), (0, 2, 3)]
        body = native.build_model(vertices, uvs, triangles, [iw_hash('a'), iw_hash('b')], [0, 1])
        model = native.decode_model(body)
        self.assertEqual(model.vertices, vertices)
        self.assertEqual(model.uvs, uvs)
        self.assertEqual(model.triangles, triangles)
        self.assertEqual(model.face_materials, [0, 1])
        self.assertEqual(struct.unpack_from('<2I', body, len(body) - 8),
                         (iw_hash('a'), iw_hash('b')))
        with self.assertRaises(ValueError):
            native.build_model([(40000, 0, 0)], [(0.0, 0.0)], [], [1])

    def test_new_texture_keeps_template_header(self):
        template = bytearray(17) + bytes(2 * 2 * 4) + b'\0'
        template[4] = 0x0E
        struct.pack_into('<HHH', template, 7, 2, 2, 8)
        texels = bytes(range(64))
        body = native.build_texture(4, 4, texels, bytes(template))
        self.assertEqual(len(body), 17 + 64 + 1)  # header, texels, "has mipmaps" = 0
        decoded = native.decode_texture_rgba(body)
        self.assertEqual((decoded.width, decoded.height, decoded.format), (4, 4, 'BGRA8888'))
        self.assertEqual(decoded.rgba[:4], bytes((2, 1, 0, 3)))

    def test_prop_box_from_collision_box_is_placed_and_turned(self):
        def typed(owner, type_name, name, value):
            prop = reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), b'')
            reflect.set_typed_value(prop, value)
            return prop

        def component(name, props):
            return resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash(name),
                                       [reflect.Blob(iw_hash(name), props)])

        quarter = levels._yaw(90)
        spec = resources.EntitySpec([
            component('CIsTransform', [
                typed('CIsTransform', 'CIwFVec3', 'm_localPosition', (1000.0, 0.0, 0.0)),
                typed('CIsTransform', 'CIwFQuat', 'm_localRotation', quarter)]),
            component('CIsCollisionBox', [
                typed('CIsCollisionBox', 'CIwFVec3', 'm_halfAxis', (100.0, 50.0, 10.0)),
                typed('CIsCollisionBox', 'CIwFVec3', 'm_Offset', (0.0, 50.0, 0.0))])])
        (box,) = levels.prop_boxes(spec, {})
        spans = [(round(min(c[i] for c in box)), round(max(c[i] for c in box))) for i in range(3)]
        self.assertEqual(spans, [(990, 1010), (0, 100), (-100, 100)])  # turned 90 degrees
        self.assertEqual(len(levels.box_triangles(0)), 12)

    def test_arena_geometry_is_closed_and_double_sided(self):
        arena = levels.Arena(half_size=400, wall_height=300, cell=200)
        vertices, uvs, triangles = levels.arena_geometry(arena)
        floor_quads, wall_quads = 16, 4 * 4 * 2
        self.assertEqual(len(vertices), 4 * (floor_quads + wall_quads))
        self.assertEqual(len(triangles), 4 * (floor_quads + wall_quads))
        a, b, c = triangles[0]
        self.assertEqual(triangles[2], (a, c, b))  # the same face, wound the other way
        xs = [v[0] for v in vertices]
        self.assertEqual((min(xs), max(xs)), (-400, 400))
        self.assertEqual(max(v[1] for v in vertices), 300)
        self.assertEqual(len(levels.arena_texture(64)), 64 * 64 * 4)


if __name__ == '__main__':
    unittest.main()
