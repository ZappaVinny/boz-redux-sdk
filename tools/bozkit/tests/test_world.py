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
        self.assertEqual(mesh.texture, original.meshes[0].texture)  # PNG keeps the texels
        data = json.loads((self.source / 'world.json').read_text())
        self.assertEqual(data['meshes'][0]['texture'], 'textures/floor.png')

    def test_double_sided_adds_backs(self):
        mesh = world.empty_world().meshes[0]
        front = mesh.model_triangles()[:len(mesh.triangles)]
        backs = mesh.model_triangles()[len(mesh.triangles):]
        self.assertEqual(front, mesh.triangles)
        self.assertEqual(backs, [(a, c, b) for a, b, c in mesh.triangles])

    def test_validation_finds_problems(self):
        broken = world.empty_world()
        mesh = broken.meshes[0]
        mesh.name = 'Bad Name'
        mesh.collision = 'sticky'
        mesh.texture = world.Texture(100, 64, bytes(100 * 64 * 4))
        mesh.vertices[0] = (40000, 0, 0)
        broken.entities = [world.Placement('Juggernog', (0, 0, 0))] * 2
        problems = ' | '.join(world.validate(broken))
        for text in ('names use', 'collision must be', 'powers of two', '±327 m',
                     'placed more than once', 'player spawn'):
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

    def test_hash_sources(self):
        self.assertEqual(world.Placement('0x0000002a', (0, 0, 0)).hash, 42)
        with self.assertRaises(world.WorldError):
            world.template_world('debug')  # needs the game's data
        with self.assertRaises(world.WorldError):
            world.template_world('kino')


if __name__ == '__main__':
    unittest.main()
