"""Map world source files (synthetic; compiling against the game is checked with real data)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import world  # noqa: E402


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / 'source'

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_world_round_trips(self):
        original = world.empty_world()
        self.assertEqual(world.validate(original), [])
        world.save(original, self.source)
        loaded = world.load(self.source)
        self.assertEqual(loaded.base, 'kino')
        self.assertEqual(loaded.entities, original.entities)
        (mesh,) = loaded.meshes
        self.assertEqual((mesh.name, mesh.collision, mesh.double_sided), ('floor', 'floor', True))
        self.assertEqual(mesh.vertices, original.meshes[0].vertices)
        self.assertEqual(mesh.triangles, original.meshes[0].triangles)
        self.assertEqual(mesh.textures, original.meshes[0].textures)  # PNG keeps the texels
        data = json.loads((self.source / 'world.json').read_text())
        self.assertEqual(data['meshes'][0]['textures'], ['textures/floor.png'])

    def test_double_sided_adds_backs(self):
        mesh = world.empty_world().meshes[0]
        triangles, faces = mesh.model_triangles()
        self.assertEqual(triangles[:len(mesh.triangles)], mesh.triangles)
        self.assertEqual(triangles[len(mesh.triangles):], [(a, c, b) for a, b, c in mesh.triangles])
        self.assertEqual(faces, [0] * len(triangles))

    def test_validation_finds_problems(self):
        broken = world.empty_world()
        mesh = broken.meshes[0]
        mesh.name = 'Bad Name'
        mesh.collision = 'sticky'
        mesh.textures = [world.Texture(100, 64, bytes(100 * 64 * 4))]
        mesh.vertices[0] = (40000, 0, 0)
        broken.entities = [world.Placement('Juggernog', (0, 0, 0), prop='missing')]
        problems = ' | '.join(world.validate(broken))
        for text in ('names use', 'collision must be', 'powers of two', '±327 m',
                     "draws prop 'missing'", 'player spawn'):
            self.assertIn(text, problems)

    def test_removed_meshes_lose_their_files(self):
        first = world.empty_world()
        world.save(first, self.source)
        first.meshes[0].name = 'ground'
        world.save(first, self.source)
        self.assertEqual(sorted(p.name for p in (self.source / 'meshes').iterdir()), ['ground.json'])

    def test_files_must_stay_inside_the_source(self):
        world.save(world.empty_world(), self.source)
        data = json.loads((self.source / 'world.json').read_text())
        data['meshes'][0]['file'] = '../../etc/passwd'
        (self.source / 'world.json').write_text(json.dumps(data))
        with self.assertRaises(world.WorldError):
            world.load(self.source)

    def test_props_instances_and_several_textures(self):
        built = world.empty_world()
        floor = built.meshes[0]
        second = world.Texture(4, 4, bytes(range(64)))
        floor.textures.append(second)
        floor.face_textures = [i % 2 for i in range(len(floor.triangles))]
        crate = world.Mesh('crate', [(0, 0, 0), (100, 0, 0), (0, 100, 0)],
                           [(0.0, 0.0)] * 3, [(0, 1, 2)], [second], 'solid', shape='box')
        built.props.append(crate)
        built.instances = [world.Instance((10.0, 0.0, 20.0), 45.0, prop='crate'),
                           world.Instance((0.0, 0.0, 0.0), model='ingame/ingame.group.bin#0x0000002a')]
        built.entities.append(world.Placement('0x0000abcd', (1.0, 2.0, 3.0), 0.0,
                                              'ingame/ingame.group.bin'))
        self.assertEqual(world.validate(built), [])
        world.save(built, self.source)
        loaded = world.load(self.source)
        self.assertEqual(loaded.meshes[0].face_textures, floor.face_textures)
        self.assertEqual(loaded.meshes[0].textures[1], second)
        self.assertEqual((loaded.props[0].name, loaded.props[0].shape), ('crate', 'box'))
        self.assertEqual(loaded.instances, built.instances)
        self.assertEqual(loaded.instances[1].model_ref(), ('ingame/ingame.group.bin', 42))
        self.assertEqual(loaded.entities[-1].group, 'ingame/ingame.group.bin')
        self.assertTrue((self.source / 'textures' / 'floor_1.png').is_file())
        built.instances.append(world.Instance((0.0, 0.0, 0.0), prop='barrel'))
        self.assertTrue(any('barrel' in p for p in world.validate(built)))

    def test_format_1_still_loads(self):
        world.save(world.empty_world(), self.source)
        data = json.loads((self.source / 'world.json').read_text())
        data['format'] = 1
        mesh = data['meshes'][0]
        mesh['texture'] = mesh.pop('textures')[0]
        (self.source / 'world.json').write_text(json.dumps(data))
        self.assertEqual(len(world.load(self.source).meshes[0].textures), 1)

    def test_full_transforms_round_trip(self):
        built = world.empty_world()
        built.entities[0] = world.Placement('spawn_player_1', (1.0, 2.0, 3.0),
                                            rotation=(0.5, 0.5, 0.5, 0.5), scale=(2.0, 1.0, 1.0),
                                            fields={'CSpawnPoint.spawnType': 'hole'})
        world.save(built, self.source)
        loaded = world.load(self.source).entities[0]
        self.assertEqual((loaded.rotation, loaded.scale, loaded.fields),
                         ((0.5, 0.5, 0.5, 0.5), (2.0, 1.0, 1.0), {'CSpawnPoint.spawnType': 'hole'}))
        self.assertEqual(world.load(self.source).entities[1].quaternion(), (0.0, 0.0, 0.0, 1.0))

    def test_inherited_worlds(self):
        with self.assertRaises(world.WorldError):
            world.template_world('kino')          # needs the game's data
        inherited = world.World('kino', inherit=True)
        self.assertEqual(world.validate(inherited), [])   # the base brings floors and spawns
        world.save(inherited, self.source)
        self.assertTrue(world.load(self.source).inherit)
        self.assertIn('"inherit": true', (self.source / 'world.json').read_text())
        inherited.removed = ['0x88ec4490']   # base entities deleted in the editor
        world.save(inherited, self.source)
        self.assertEqual(world.load(self.source).removed, ['0x88ec4490'])

    def test_script_settings(self):
        scripted = world.World('kino', inherit=True)
        scripted.instances.append(world.Instance((0.0, 0.0, 0.0), model='levels/kino/x#0x00000001',
                                                 script={'name': 'Secret_Wall', 'visible': False,
                                                         'blocks': True}))
        scripted.entities.append(world.Placement('Juggernog', (0.0, 0.0, 0.0), piece='juggernog',
                                                 script={'name': 'Hidden_Jug'}))
        world.save(scripted, self.source)
        loaded = world.load(self.source)
        self.assertEqual(world.script_of(loaded.instances[0]),
                         {'name': 'Secret_Wall', 'visible': False, 'collision': True, 'blocks': True})
        self.assertEqual(loaded.entities[0].script, {'name': 'Hidden_Jug'})
        self.assertEqual(world.validate(loaded), [])
        loaded.entities[0].script['name'] = 'secret_wall'
        self.assertTrue(any('two objects' in p for p in world.validate(loaded)))
        loaded.entities[0].script['name'] = '9 bad'
        self.assertTrue(any('script name' in p for p in world.validate(loaded)))

    def test_hash_sources(self):
        self.assertEqual(world.Placement('0x0000002a', (0, 0, 0)).hash, 42)
        with self.assertRaises(world.WorldError):
            world.template_world('debug')  # needs the game's data
        with self.assertRaises(world.WorldError):
            world.template_world('nowhere')


if __name__ == '__main__':
    unittest.main()
