"""Multi-group Blender scene boundary on synthetic groups (no game files)."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import blender_scene, bullet, collision, group, native, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402


def typed(type_name, name, value, owner='CIsTransform'):
    prop = reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), b'')
    reflect.set_typed_value(prop, value)
    return prop


def placed(model_name, position, scale=None, children=()):
    transform = [typed('CIwFVec3', 'm_localPosition', position),
                 typed('CIwFQuat', 'm_localRotation', (0.0, 0.0, 0.0, 1.0))]
    if scale is not None:
        transform.append(typed('CIwFVec3', 'm_localScale', scale))
    components = [resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsTransform'),
                                      [reflect.Blob(iw_hash('CIsTransform'), transform)])]
    if model_name:
        asset = reflect.Blob(iw_hash('CIsRenderableAsset'), [
            typed('unsigned int', 'model', iw_hash(model_name), 'CIsRenderableAsset')])
        assets = reflect.Property(iw_hash('CIsRenderableModel'), iw_hash('asset_list'),
                                  iw_hash('assets'), b'', elements=[asset])
        components.append(resources.Component(
            iw_hash('CIsComponentSpec'), 0, iw_hash('CIsRenderableModel'),
            [reflect.Blob(iw_hash('CIsRenderableModel'), [assets])]))
    return resources.EntitySpec(components, [(iw_hash('CIsEntitySpec'), 0, child)
                                             for child in children])


def write_group(path, types):
    path.write_bytes(group.encode(group.Group(bytes((0x3D, 0, 0, 0, 0, 0)),
                                              [group.Section(group.RESOURCES, b'', types)])))


def model_type(*names):
    model = native.Model([(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)],
                         [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    return group.ResourceType(iw_hash('CIwModel'), 0, 1, [
        group.Resource(iw_hash(name), iw_hash(name), native.encode_model(model)) for name in names])


def spec_type(*specs):
    return group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
        group.Resource(iw_hash(name), iw_hash(name), resources.encode_entity_spec(spec))
        for name, spec in specs])


def edits_for(imported):
    return [blender_scene.SceneEdit(
        kind=item.kind, class_hash=item.class_hash, resource_hash=item.resource_hash,
        resource_index=item.resource_index, vertices=item.vertices, faces=item.faces,
        edges=item.edges, uvs=item.uvs, uvs2=item.uvs2, face_materials=item.face_materials,
        front_sector=item.front_sector, back_sector=item.back_sector,
        location=item.location, rotation=item.rotation, scale=item.scale,
        instance_resource_hash=item.instance_resource_hash,
        instance_resource_index=item.instance_resource_index, source_group=item.source_group,
        instance_source_group=item.instance_source_group, instance_path=item.instance_path)
        for item in imported.meshes]


def collision_type(vertices, indices):
    mesh = collision.CollisionMesh(bullet.synthetic_triangle_mesh(vertices, indices), vertices,
                                   indices, bytes(range(len(indices) // 3)), ['a', 'b'])
    component = resources.Component(resources.COLLISION_MESH_SPEC, 0,
                                    iw_hash('CIsCollisionMeshSpec'), [], collision.encode(mesh))
    return ('collision', resources.EntitySpec([component]))


class AttachedCollisionTests(unittest.TestCase):
    """World collision triangles built from a placed model follow that model."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'level.group.bin'
        # The crate (native (0,0,0) (10,0,0) (0,10,0)) is placed at x = 100. Triangle 0 of the
        # collision lies on it; triangle 1 is collision-only and shares a vertex with it.
        vertices = [(100.0, 0.0, 0.0), (110.0, 0.0, 0.0), (100.0, 10.0, 0.0), (100.0, 0.0, 50.0)]
        write_group(self.path, [model_type('crate'), spec_type(
            ('a', placed('crate', (100.0, 0.0, 0.0))), collision_type(vertices, [0, 1, 2, 0, 2, 3]))])

    def tearDown(self):
        self.directory.cleanup()

    def edits(self, imported):
        edits = edits_for(imported)
        chain = blender_scene._chains(imported.meshes)
        for edit, item in zip(edits, imported.meshes):
            edit.collision_triangles = item.collision_triangles
            if item.kind == 'collision_piece':  # the add-on sends pieces in world space
                edit.vertices = [blender_scene._to_world(chain(item), v) for v in item.vertices]
        return edits

    def test_piece_follows_its_model_and_splits_shared_vertices(self):
        imported = blender_scene.import_group(self.path)
        piece = next(item for item in imported.meshes if item.kind == 'collision_piece')
        world = next(item for item in imported.meshes if item.kind == 'collision')
        self.assertEqual((piece.collision_triangles, world.collision_triangles), ([0], [1]))
        crate = next(item for item in imported.meshes if item.kind == 'placed_model')
        self.assertEqual(piece.parent_key, crate.key)
        output = Path(self.directory.name) / 'out.group.bin'
        blender_scene.export_group(self.path, output, self.edits(imported))
        self.assertEqual(output.read_bytes(), self.path.read_bytes())  # untouched round trip
        crate.location = (crate.location[0] + 5.0, crate.location[1], crate.location[2])
        blender_scene.export_group(self.path, output, self.edits(imported))
        parsed = group.parse(output.read_bytes())
        spec = next(resources.decode_entity_spec(item.body) for resource_type in parsed.types()
                    if resource_type.class_hash == blender_scene.ENTITY_SPEC
                    for item in resource_type.resources if item.name_hash == iw_hash('collision'))
        mesh = collision.decode(spec.components[0].extra)
        # Triangle 0 moved 5 units with the crate; the vertex it shared with triangle 1 was split.
        self.assertEqual([mesh.vertices[i] for i in mesh.indices[:3]],
                         [(105.0, 0.0, 0.0), (115.0, 0.0, 0.0), (105.0, 10.0, 0.0)])
        self.assertEqual([mesh.vertices[i] for i in mesh.indices[3:]],
                         [(100.0, 0.0, 0.0), (100.0, 10.0, 0.0), (100.0, 0.0, 50.0)])
        self.assertEqual(len(mesh.vertices), 6)
        self.assertEqual(mesh.materials, bytes((0, 1)))
        self.assertEqual(bullet.triangle_mesh(mesh.bullet_shape), (mesh.vertices, mesh.indices))

    def test_deleted_piece_is_reported(self):
        imported = blender_scene.import_group(self.path)
        edits = [edit for edit in self.edits(imported) if edit.kind != 'collision_piece']
        with self.assertRaisesRegex(ValueError, 'missing'):
            blender_scene.export_group(self.path, Path(self.directory.name) / 'x.group.bin', edits)


def marker(components, position=(0.0, 0.0, 0.0)):
    """An entity with only a transform plus the given (component name, properties) pairs."""
    spec = placed(None, position)
    for name, properties in components:
        spec.components.append(resources.Component(
            iw_hash('CIsComponentSpec'), 0, iw_hash(name),
            [reflect.Blob(iw_hash(name), [typed(t, n, v, name) for t, n, v in properties])]))
    return spec


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'markers.group.bin'
        write_group(self.path, [spec_type(
            ('spawn', marker([('CSpawnPoint', [('bool', 'm_StartActive', False)])], (1.0, 2.0, 3.0))),
            ('glow', marker([('CIsRenderableGFXEmitter', [('unsigned int', 'emitterSpec', 7)])])),
            ('perk', marker([('CPOI', [('float', 'm_MaxDistance', 170.0),
                                       ('float', 'm_HeightOffset', 55.0)]),
                             ('CIsCollisionBox', [('CIwFVec3', 'm_halfAxis', (10.0, 20.0, 30.0)),
                                                  ('CIwFVec3', 'm_Offset', (0.0, 20.0, 0.0))])])))])

    def tearDown(self):
        self.directory.cleanup()

    def test_every_entity_is_a_marker_with_editable_shapes(self):
        imported = blender_scene.import_group(self.path)
        markers = {item.category: item for item in imported.meshes if item.kind == 'entity'}
        self.assertEqual(set(markers), {'spawn', 'effect', 'interact'})
        self.assertEqual(markers['spawn'].location, (1.0, -3.0, 2.0))
        self.assertIn('CSpawnPoint', markers['spawn'].components)
        shapes = {item.shape: item for item in imported.meshes if item.kind == 'shape'}
        self.assertEqual(shapes['box'].scale, (10.0, 30.0, 20.0))  # native Y-up half axes
        self.assertEqual(shapes['box'].location, (0.0, -0.0, 20.0))
        self.assertEqual((shapes['reach'].scale[0], shapes['reach'].location[2]), (170.0, 55.0))
        self.assertTrue(all(item.parent_key == markers['interact'].key for item in shapes.values()))

        output = Path(self.directory.name) / 'out.group.bin'
        edits = edits_for(imported)
        for edit, item in zip(edits, imported.meshes):
            edit.shape, edit.shape_component = item.shape, item.shape_component
        blender_scene.export_group(self.path, output, edits)
        self.assertEqual(output.read_bytes(), self.path.read_bytes())
        box = next(edit for edit in edits if edit.shape == 'box')
        box.scale = (15.0, 30.0, 20.0)
        reach = next(edit for edit in edits if edit.shape == 'reach')
        reach.scale = (250.0, 250.0, 1.0)
        glow = next(edit for edit in edits if edit.kind == 'entity'
                    and edit.resource_hash == iw_hash('glow'))
        glow.location = (5.0, 0.0, 0.0)
        blender_scene.export_group(self.path, output, edits)
        rebuilt = blender_scene.import_group(output)
        shapes = {item.shape: item for item in rebuilt.meshes if item.kind == 'shape'}
        self.assertEqual(shapes['box'].scale, (15.0, 30.0, 20.0))
        self.assertEqual(shapes['reach'].scale[0], 250.0)
        moved = next(item for item in rebuilt.meshes if item.category == 'effect')
        self.assertEqual(moved.location, (5.0, 0.0, 0.0))
        box.rotation = (0.0, 0.0, 0.3826834, 0.9238795)
        with self.assertRaisesRegex(ValueError, 'rotated'):
            blender_scene.export_group(self.path, output, edits)


def named(name, components, position=(0.0, 0.0, 0.0)):
    return marker([('CIsNamed', [('string', 'name', name)])] + components, position)


def u32_list(owner, name, values):
    return reflect.Property(iw_hash(owner), iw_hash('std::list<unsigned int>'), iw_hash(name),
                            struct.pack(f'<I{len(values)}I', len(values), *values))


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'links.group.bin'
        door = named('Lobby_Door', [('CDoor', [('unsigned int', 'powerSwitch', iw_hash('Power'))])])
        door.components[-1].blobs[0].properties.append(
            u32_list('CDoor', 'm_AreasUnlock', [iw_hash('atrium')]))
        area = reflect.Blob(iw_hash('CArea'), [u32_list('CArea', 'm_SpawnPoints',
                                                        [iw_hash('Spawn_A'), iw_hash('Spawn_B')])])
        write_group(self.path, [
            spec_type(('power', named('Power', [('CPowerSwitch', [('bool', 'StartEnabled', False)])],
                                      (100.0, 0.0, 0.0))),
                      ('door', door),
                      ('a', named('Spawn_A', [('CSpawnPoint', [('bool', 'm_StartActive', True)])],
                                  (0.0, 0.0, 10.0))),
                      ('b', named('Spawn_B', [('CSpawnPoint', [('bool', 'm_StartActive', True)])],
                                  (0.0, 0.0, 30.0)))),
            group.ResourceType(iw_hash('CArea'), 0, 1, [group.Resource(
                iw_hash('atrium'), iw_hash('atrium'), resources.encode_reflected(area))])])

    def tearDown(self):
        self.directory.cleanup()

    def test_links_areas_and_edits(self):
        imported = blender_scene.import_group(self.path)
        by_name = {item.display_name.split(':', 1)[1].split(' "')[0]: item
                   for item in imported.meshes if item.kind in ('entity', 'area')}
        door = next(item for item in imported.meshes if item.category == 'door')
        area = next(item for item in imported.meshes if item.kind == 'area')
        self.assertEqual({(link['kind'], tuple(link['targets'])) for link in door.links},
                         {('power', (iw_hash('Power'),)), ('unlocks', (iw_hash('atrium'),))})
        self.assertEqual(area.link_id, iw_hash('atrium'))
        self.assertEqual(area.links[0]['targets'], [iw_hash('Spawn_A'), iw_hash('Spawn_B')])
        self.assertEqual(area.location, (0.0, -20.0, 0.0))  # centre of its two spawns (Blender)
        self.assertTrue(any(name.startswith('Power switch') for name in by_name))

        output = Path(self.directory.name) / 'out.group.bin'
        edits = edits_for(imported)
        for edit, item in zip(edits, imported.meshes):
            edit.links = [dict(link, targets=list(link['targets'])) for link in item.links]
        blender_scene.export_group(self.path, output, edits)
        self.assertEqual(output.read_bytes(), self.path.read_bytes())
        door_edit = next(edit for edit, item in zip(edits, imported.meshes) if item is door)
        next(link for link in door_edit.links if link['kind'] == 'power')['targets'] = []
        area_edit = next(edit for edit in edits if edit.kind == 'area')
        area_edit.links[0]['targets'] = [iw_hash('Spawn_B')]
        blender_scene.export_group(self.path, output, edits)
        rebuilt = blender_scene.import_group(output)
        door = next(item for item in rebuilt.meshes if item.category == 'door')
        self.assertEqual([link['targets'] for link in door.links if link['kind'] == 'power'], [[]])
        area = next(item for item in rebuilt.meshes if item.kind == 'area')
        self.assertEqual(area.links[0]['targets'], [iw_hash('Spawn_B')])


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / 'levels' / 'test').mkdir(parents=True)
        (root / 'ingame').mkdir()
        self.statics = root / 'levels' / 'test' / 'test_statics.group.bin'
        self.shared = root / 'ingame' / 'ingame.group.bin'
        # Two placements of one shared model, plus a non-renderable parent whose scaled child
        # draws a model from the same group.
        write_group(self.statics, [
            model_type('local'),
            spec_type(('a', placed('crate', (1.0, 2.0, 3.0))),
                      ('b', placed('crate', (4.0, 5.0, 6.0))),
                      ('parent', placed(None, (100.0, 0.0, 0.0), children=[
                          placed('local', (1.0, 0.0, 0.0), scale=(0.5, 0.5, 0.5))])),
                      ('missing', placed('nowhere', (0.0, 0.0, 0.0))))])
        write_group(self.shared, [model_type('crate')])
        self.out = root / 'out'

    def tearDown(self):
        self.directory.cleanup()

    def load(self):
        editable, references = blender_scene.level_groups(self.statics.parent)
        self.assertEqual(references, [self.shared.resolve()])
        return blender_scene.import_groups(editable, references)

    def test_level_groups_include_the_level_weapon_group(self):
        weapons = Path(self.directory.name) / 'ingame' / 'weapons' / 'weapons_test.group.bin'
        weapons.parent.mkdir()
        write_group(weapons, [model_type('nowhere')])
        editable, references = blender_scene.level_groups(self.statics.parent)
        self.assertEqual(references, [self.shared.resolve(), weapons.resolve()])
        imported = blender_scene.import_groups(editable, references)
        self.assertEqual(imported.warnings, [])
        self.assertTrue(any(item.resource_hash == iw_hash('nowhere') for item in imported.meshes))

    def test_cross_group_placements_hierarchy_and_warnings(self):
        imported = self.load()
        kinds = sorted(item.kind for item in imported.meshes)
        # The placement whose model is missing still appears, as a marker.
        self.assertEqual(kinds, ['entity', 'entity', 'placed_model', 'placed_model', 'placed_model'])
        crates = [item for item in imported.meshes if item.resource_hash == iw_hash('crate')]
        self.assertEqual({item.source_group for item in crates}, {str(self.shared.resolve())})
        self.assertEqual(len({item.mesh_key for item in crates}), 1)
        child = next(item for item in imported.meshes if item.instance_path == (0,))
        parent = next(item for item in imported.meshes if item.kind == 'entity')
        self.assertEqual(child.parent_key, parent.key)
        self.assertEqual(child.scale, (0.5, 0.5, 0.5))
        self.assertEqual(child.location, (1.0, 0.0, 0.0))  # parent-relative
        self.assertTrue(any('not in the loaded' in warning for warning in imported.warnings))

    def test_unchanged_export_writes_nothing_and_edits_route_to_owner(self):
        imported = self.load()
        edits = edits_for(imported)
        outputs = {path: self.out / Path(path).name
                   for path in imported.source_groups + imported.reference_groups}
        report = blender_scene.export_groups(edits, outputs)
        self.assertEqual((report.edited, report.written), (0, ()))
        # Moving one crate changes only the statics entity; editing the shared crate mesh
        # (identically on both instances) changes only the ingame group.
        crates = [edit for edit in edits if edit.resource_hash == iw_hash('crate')]
        crates[0].location = (9.0, 9.0, 9.0)
        moved = [(x + 1, y, z) for x, y, z in crates[0].vertices]
        for crate in crates:
            crate.vertices = moved
        child = next(edit for edit in edits if edit.instance_path == (0,))
        child.scale = (2.0, 2.0, 2.0)
        report = blender_scene.export_groups(edits, outputs)
        self.assertEqual(sorted(Path(path).name for path in report.written),
                         ['ingame.group.bin', 'test_statics.group.bin'])
        rebuilt = blender_scene.import_groups([self.out / 'test_statics.group.bin'],
                                              [self.out / 'ingame.group.bin'])
        locations = sorted(item.location for item in rebuilt.meshes
                           if item.resource_hash == iw_hash('crate'))
        self.assertIn((9.0, 9.0, 9.0), locations)
        crate = next(item for item in rebuilt.meshes if item.resource_hash == iw_hash('crate'))
        self.assertEqual(crate.vertices[0], (1.0, 0.0, 0.0))
        rebuilt_child = next(item for item in rebuilt.meshes if item.instance_path == (0,))
        self.assertEqual(rebuilt_child.scale, (2.0, 2.0, 2.0))

    def test_save_to_mod_and_reload_with_its_edits(self):
        client = Path(self.directory.name) / 'client'
        client.mkdir()
        original = self.statics.read_bytes()
        edits = edits_for(self.load())
        crate = next(edit for edit in edits if edit.resource_hash == iw_hash('crate'))
        crate.location = (7.0, 7.0, 7.0)
        report = blender_scene.export_to_mod(edits, client, 'blender_edits')
        mod = client / 'mods' / 'blender_edits'
        self.assertIn('id = "blender_edits"', (mod / 'mod.toml').read_text())
        self.assertEqual([Path(path).name for path in report.written], ['test_statics.group.bin'])
        # Reloading with the mod shows the edit; editing again replaces the mod's own copy.
        editable, references = blender_scene.level_groups(self.statics.parent, mod / 'assets')
        self.assertEqual(editable, [(mod / 'assets' / 'test_statics.group.bin').resolve()])
        reloaded = blender_scene.import_groups(editable, references)
        self.assertIn((7.0, 7.0, 7.0), [item.location for item in reloaded.meshes])
        edits = edits_for(reloaded)
        next(edit for edit in edits if edit.location == (7.0, 7.0, 7.0)).location = (8.0, 8.0, 8.0)
        blender_scene.export_to_mod(edits, client, 'blender_edits')
        again = blender_scene.import_groups(*blender_scene.level_groups(self.statics.parent,
                                                                        mod / 'assets'))
        self.assertIn((8.0, 8.0, 8.0), [item.location for item in again.meshes])
        self.assertEqual(self.statics.read_bytes(), original)  # game files are never written
        with self.assertRaises(ValueError):
            blender_scene.export_to_mod(edits, client, '../escape')

    def test_shared_instances_must_agree(self):
        edits = edits_for(self.load())
        crates = [edit for edit in edits if edit.resource_hash == iw_hash('crate')]
        crates[0].vertices = [(x + 1, y, z) for x, y, z in crates[0].vertices]
        outputs = {path: self.out / Path(path).name
                   for path in {edit.source_group for edit in edits} |
                   {edit.instance_source_group for edit in edits if edit.instance_source_group}}
        with self.assertRaisesRegex(ValueError, 'shared model'):
            blender_scene.export_groups(edits, outputs)

    def test_sources_are_never_overwritten(self):
        edits = edits_for(self.load())
        with self.assertRaises(ValueError):
            blender_scene.export_groups(edits, {str(self.statics): self.statics,
                                                str(self.shared): self.out / 'x.group.bin'})

    def test_single_group_export_rejects_multi_group_scene(self):
        edits = edits_for(self.load())
        with self.assertRaisesRegex(ValueError, 'several groups'):
            blender_scene.export_group(self.statics, self.out / 'x.group.bin', edits)


if __name__ == '__main__':
    unittest.main()
