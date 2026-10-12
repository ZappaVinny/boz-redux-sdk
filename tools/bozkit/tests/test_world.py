"""Map world source files (synthetic; compiling against the game is checked with real data)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import world  # noqa: E402

GAME_MODEL = 'ingame/ingame.group.bin#0x0000002a'


def crate_mesh(texture=None):
    texture = texture or world.Texture(4, 4, bytes(range(64)))
    return world.Mesh('crate', [(0, 0, 0), (100, 0, 0), (0, 100, 0)], [(0.0, 0.0)] * 3,
                      [(0, 1, 2)], [texture])


def vault(name='Vault_1'):
    """A prefab: a door model, a hit volume and a perk machine, with a script."""
    return world.Prefab(name, position=(100.0, 0.0, 50.0), script='prefabs/Vault.lua',
                        properties={'delay': 2.0},
                        parts=[world.Model('Door', mesh='crate', position=(0.0, 0.0, 10.0),
                                           start={'blocks': True}),
                               world.Volume('Skull', 'hit', position=(0.0, 50.0, 0.0),
                                            size=(30.0, 30.0, 30.0), once=True),
                               world.Prefab('Jug', source='Juggernog', piece='juggernog',
                                            settings={'CPerk.m_perkSinglePCost': 2500})])


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
        self.assertEqual(loaded.models, original.models)
        self.assertEqual(loaded.prefabs, original.prefabs)
        (mesh,) = loaded.meshes
        self.assertEqual((mesh.name, mesh.double_sided), ('floor', True))
        self.assertEqual(mesh.vertices, original.meshes[0].vertices)
        self.assertEqual(mesh.textures, original.meshes[0].textures)  # PNG keeps the texels
        self.assertEqual(loaded.models[0].collision, 'floor')
        data = json.loads((self.source / 'world.json').read_text())
        self.assertEqual(data['format'], 3)
        self.assertEqual(data['meshes'][0]['textures'], ['textures/floor.png'])
        spawns = [p for p in loaded.prefabs if p.source.startswith('spawn_player_')]
        self.assertEqual(len(spawns), 4)

    def test_double_sided_adds_backs(self):
        mesh = world.empty_world().meshes[0]
        triangles, faces = mesh.model_triangles()
        self.assertEqual(triangles[len(mesh.triangles):], [(a, c, b) for a, b, c in mesh.triangles])
        self.assertEqual(faces, [0] * len(triangles))

    def test_all_three_kinds_round_trip(self):
        built = world.empty_world()
        built.meshes.append(crate_mesh())
        built.models += [world.Model('Crate_1', mesh='crate', position=(10.0, 0.0, 20.0),
                                     rotation=(0.0, 0.38268, 0.0, 0.92388), scale=(2.0, 1.0, 1.0),
                                     collision='solid', shape='box', padding=12.5,
                                     start={'blocks': True}, block_margin=60.0),
                         world.Model('Rock', game=GAME_MODEL, start={'visible': False},
                                     script='prefabs/Rock.lua', properties={'speed': 3})]
        built.volumes.append(world.Volume('Room_Trigger', 'trigger', size=(400.0, 300.0, 400.0),
                                          who='anyone'))
        built.volumes.append(world.Volume('Radio', 'use', prompt='Hold to listen', cost=500))
        built.prefabs.append(vault())
        self.assertEqual(world.validate(built), [])
        world.save(built, self.source)
        loaded = world.load(self.source)
        self.assertEqual(loaded.models, built.models)
        self.assertEqual(loaded.volumes, built.volumes)
        self.assertEqual(loaded.prefabs[-1], built.prefabs[-1])
        self.assertEqual([p.kind for p in loaded.prefabs[-1].parts], ['model', 'volume', 'prefab'])

    def test_validation_finds_problems(self):
        broken = world.empty_world()
        mesh = broken.meshes[0]
        mesh.textures = [world.Texture(100, 64, bytes(100 * 64 * 4))]
        mesh.vertices[0] = (40000, 0, 0)
        broken.models.append(world.Model('Bad Name', mesh='missing', collision='sticky'))
        broken.models.append(world.Model('Both', mesh='floor', game=GAME_MODEL))
        broken.volumes.append(world.Volume('floor', 'boom', size=(0.0, 1.0, 1.0)))
        broken.prefabs = [world.Prefab('Odd', source='Juggernog',
                                       parts=[world.Model('X', game=GAME_MODEL)])]
        problems = ' | '.join(world.validate(broken))
        for text in ('names use', "mesh 'missing' does not exist", 'collision must be',
                     'either its own mesh, an asset or a game model', 'powers of two', '±327 m',
                     'two objects have this name', 'kind must be trigger', 'size must be',
                     'a game prefab has no parts', 'player spawn'):
            self.assertIn(text, problems)

    def test_part_names_are_scoped_by_their_prefab(self):
        built = world.World('kino', inherit=True, meshes=[crate_mesh()])
        built.prefabs = [vault('Vault_1'), vault('Vault_2')]
        self.assertEqual(world.validate(built), [])   # both have a Door: Vault_1.Door, Vault_2.Door
        built.models.append(world.Model('vault_1', game=GAME_MODEL))
        self.assertTrue(any('two objects' in p for p in world.validate(built)))

    def test_removed_meshes_lose_their_files(self):
        first = world.empty_world()
        world.save(first, self.source)
        first.meshes[0].name = 'ground'
        first.models[0].mesh = 'ground'
        world.save(first, self.source)
        self.assertEqual(sorted(p.name for p in (self.source / 'meshes').iterdir()), ['ground.json'])

    def test_files_must_stay_inside_the_source(self):
        world.save(world.empty_world(), self.source)
        data = json.loads((self.source / 'world.json').read_text())
        data['meshes'][0]['file'] = '../../etc/passwd'
        (self.source / 'world.json').write_text(json.dumps(data))
        with self.assertRaises(world.WorldError):
            world.load(self.source)

    def test_format_2_migrates(self):
        layout = world._empty_layout()
        crate = crate_mesh()
        crate.collision, crate.shape = 'solid', 'box'
        layout.props.append(crate)
        layout.instances = [world.Instance((10.0, 0.0, 20.0), 45.0, prop='crate',
                                           script={'name': 'Secret_Wall', 'visible': False}),
                            world.Instance((0.0, 0.0, 0.0), model=GAME_MODEL)]
        layout.entities.append(world.Placement('Juggernog', (1.0, 2.0, 3.0), piece='juggernog',
                                               settings={'CPerk.powerSwitch': False}))
        world._save_layout(layout, self.source)
        self.assertEqual(json.loads((self.source / 'world.json').read_text())['format'], 2)
        migrated = world.load(self.source)
        self.assertEqual(world.validate(migrated), [])
        names = {m.name: m for m in migrated.models}
        self.assertEqual((names['Secret_Wall'].mesh, names['Secret_Wall'].shape,
                          names['Secret_Wall'].start), ('crate', 'box', {'visible': False}))
        self.assertEqual(names['model_1'].game, GAME_MODEL)
        jug = next(p for p in migrated.prefabs if p.piece == 'juggernog')
        self.assertEqual((jug.source, jug.settings), ('Juggernog', {'CPerk.powerSwitch': False}))
        world.save(migrated, self.source)                 # and saves as format 3
        saved = world.load(self.source)
        world.save(saved, self.source)
        self.assertEqual(world.load(self.source).models, saved.models)
        self.assertEqual([m.name for m in saved.models], [m.name for m in migrated.models])

    def test_format_1_still_loads(self):
        world._save_layout(world._empty_layout(), self.source)
        data = json.loads((self.source / 'world.json').read_text())
        data['format'] = 1
        mesh = data['meshes'][0]
        mesh['texture'] = mesh.pop('textures')[0]
        (self.source / 'world.json').write_text(json.dumps(data))
        self.assertEqual(len(world.load(self.source).meshes[0].textures), 1)

    def test_inherited_base_entities(self):
        migrated = world.from_layout(world.Layout('kino', inherit=True, entities=[
            world.Placement('0x88ec4490', (0.0, 0.0, 0.0), script={'name': 'Lobby_To_Atrium'})]))
        (door,) = migrated.prefabs
        self.assertTrue(door.base)
        self.assertEqual(door.name, 'Lobby_To_Atrium')
        migrated.removed = ['0x12345678']
        world.save(migrated, self.source)
        loaded = world.load(self.source)
        self.assertEqual((loaded.removed, loaded.prefabs[0].base), (['0x12345678'], True))
        nested = world.Prefab('Group', parts=[loaded.prefabs[0]])
        loaded.prefabs = [nested]
        self.assertTrue(any('cannot be prefab parts' in p for p in world.validate(loaded)))

    def test_lowering_flattens_prefabs(self):
        built = world.World('kino', inherit=True, meshes=[crate_mesh()])
        built.prefabs = [vault()]
        built.models = [world.Model('Plain', game=GAME_MODEL, position=(5.0, 0.0, 0.0))]
        layout = world.lower(built)
        names = {world.script_of(i)['name']: i for i in layout.instances}
        door = names['Vault_1.Door']
        self.assertEqual(tuple(round(c, 3) for c in door.position), (100.0, 0.0, 60.0))
        self.assertTrue(world.script_of(door)['dynamic'])          # its prefab has a script
        self.assertTrue(world.script_of(door)['blocks'])
        self.assertFalse(world.script_of(names['Plain'])['dynamic'])  # nothing changes it
        entities = {world.script_of(e)['name']: e for e in layout.entities}
        self.assertEqual(entities['Vault_1.Skull'].source, world.HIT_SOURCE)
        self.assertAlmostEqual(entities['Vault_1.Skull'].scale[0], 0.3)
        self.assertEqual(entities['Vault_1.Jug'].settings, {'CPerk.m_perkSinglePCost': 2500})
        self.assertEqual([p.name for p in layout.props], ['crate'])

    def test_describe_lists_scripts_and_volumes(self):
        built = world.World('kino', inherit=True, meshes=[crate_mesh()])
        built.prefabs = [vault()]
        built.volumes = [world.Volume('Loose', 'trigger')]
        described = {d['name']: d for d in world.describe(built)}
        self.assertEqual(described['Vault_1']['script'], 'prefabs.Vault')
        self.assertEqual([p['part'] for p in described['Vault_1']['parts']], ['Door', 'Skull', 'Jug'])
        self.assertEqual((described['Vault_1.Skull']['owner'], described['Vault_1.Skull']['once']),
                         ('Vault_1', True))
        self.assertEqual(described['Loose']['owner'], '')
        self.assertEqual(described['Vault_1']['members'], ['Vault_1.Door', 'Vault_1.Skull', 'Vault_1.Jug'])
        self.assertEqual(world.object_names(built),
                         ['Loose', 'Vault_1', 'Vault_1.Door', 'Vault_1.Jug', 'Vault_1.Skull'])

    def test_prefab_library(self):
        meshes = [crate_mesh(), world.Mesh('unused', [(0, 0, 0)] * 3, [(0.0, 0.0)] * 3,
                                           [(0, 1, 2)], [world.Texture(4, 4, bytes(64))])]
        path = world.save_prefab(self.source, vault('Vault'), meshes)
        self.assertTrue(path.is_file())
        self.assertEqual(world.library_names(self.source), ['Vault'])
        prefab, used = world.load_prefab(self.source, 'Vault')
        self.assertEqual([m.name for m in used], ['crate'])
        self.assertEqual((prefab.position, prefab.library), ((0.0, 0.0, 0.0), 'Vault'))
        self.assertEqual([p.name for p in prefab.parts], ['Door', 'Skull', 'Jug'])
        with self.assertRaises(world.WorldError):
            world.save_prefab(self.source, world.Prefab('bad name'), meshes)

    def test_templates_need_the_game(self):
        for template in ('kino', 'debug'):
            with self.assertRaises(world.WorldError):
                world.template_world(template)
        with self.assertRaises(world.WorldError):
            world.template_world('nowhere')
        self.assertEqual(world.Placement('0x0000002a', (0, 0, 0)).hash, 42)


if __name__ == '__main__':
    unittest.main()
