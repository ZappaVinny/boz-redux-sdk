"""Sectors (what the game draws), zones (when zombie spawns wake) and portals: the world's map
volumes, lowered and compiled (synthetic data; the game's behaviour is checked in the game)."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import group, links, map_resources, native, reflect, resources, spec_fields  # noqa: E402
from bozkit import world, world_compile  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

TURN = (0.0, 0.70710678, 0.0, 0.70710678)   # 90 degrees about Y


def typed(type_name, name, value, owner):
    prop = reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), b'')
    reflect.set_typed_value(prop, value)
    return prop


def placed_template() -> bytes:
    """An entity spec like the level's placed props: a transform and one model."""
    transform = [typed('CIwFVec3', 'm_localPosition', (5.0, 6.0, 7.0), 'CIsTransform'),
                 typed('CIwFQuat', 'm_localRotation', (0.0, 0.0, 0.0, 1.0), 'CIsTransform')]
    asset = reflect.Blob(iw_hash('CIsRenderableAsset'), [
        typed('unsigned int', 'model', iw_hash('crate'), 'CIsRenderableAsset')])
    assets = reflect.Property(iw_hash('CIsRenderableModel'), iw_hash('asset_list'),
                              iw_hash('assets'), b'', elements=[asset])
    return resources.encode_entity_spec(resources.EntitySpec([
        resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsTransform'),
                            [reflect.Blob(iw_hash('CIsTransform'), transform)]),
        resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsRenderableModel'),
                            [reflect.Blob(iw_hash('CIsRenderableModel'), [assets])])]))


def two_rooms():
    """Rooms A (x < 0) and B (x > 0), 1200 x 300 x 1200 each, a doorway between them."""
    return [world.MapBox('sector', 'RoomA', (-600.0, 150.0, 0.0), (0.0, 0.0, 0.0, 1.0),
                         (1200.0, 300.0, 1200.0)),
            world.MapBox('sector', 'RoomB', (600.0, 150.0, 0.0), (0.0, 0.0, 0.0, 1.0),
                         (1200.0, 300.0, 1200.0)),
            world.MapBox('portal', 'Door', (0.0, 150.0, 0.0), (0.0, 0.0, 0.0, 1.0),
                         (20.0, 300.0, 300.0))]


class MapVolumeTests(unittest.TestCase):
    def test_zone_fields_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            original = world.empty_world()
            original.volumes = [world.Volume('Hall_1', 'zone', size=(500.0, 300.0, 500.0),
                                             zone='Hall', starting=True),
                                world.Volume('Lobby', 'sector'), world.Volume('Gap', 'portal')]
            world.save(original, source)
            self.assertEqual(world.load(source).volumes, original.volumes)

    def test_starting_zone_is_required_once(self):
        empty = world.empty_world()
        empty.volumes = [world.Volume('A', 'zone'), world.Volume('B', 'zone')]
        self.assertIn('one zone must be the starting zone (zone volumes: Starting zone)',
                      world.validate(empty))
        empty.volumes = [world.Volume('A', 'zone', starting=True),
                         world.Volume('B', 'zone', starting=True)]
        self.assertIn('only one zone can be the starting zone, not 2', world.validate(empty))
        # Two boxes of one zone may both say so.
        empty.volumes = [world.Volume('A_1', 'zone', zone='A', starting=True),
                         world.Volume('A_2', 'zone', zone='A', starting=True),
                         world.Volume('B', 'zone')]
        self.assertEqual(world.validate(empty), [])

    def test_zone_name_cannot_be_another_object(self):
        empty = world.empty_world()
        empty.volumes = [world.Volume('Box', 'zone', zone='floor', starting=True)]
        self.assertIn("zone 'floor': another object has this name", world.validate(empty))

    def test_remix_keeps_its_own(self):
        remix = world.World(inherit=True, volumes=[world.Volume('Lobby', 'sector')])
        self.assertIn("'Lobby': sectors, zones and portals are for new maps (a remix keeps the "
                      "base level's own)", world.validate(remix))

    def test_lowered_to_boxes_not_entities(self):
        source = world.empty_world()
        source.prefabs.append(world.Prefab('Wing', position=(1000.0, 0.0, 0.0), parts=[
            world.Volume('Box', 'zone', position=(0.0, 150.0, 0.0), size=(400.0, 300.0, 200.0),
                         zone='East', starting=True)]))
        layout = world.lower(source)
        (box,) = layout.boxes
        self.assertEqual((box.kind, box.name, box.zone), ('zone', 'Wing.Box', 'East'))
        self.assertEqual(box.position, (1000.0, 150.0, 0.0))
        self.assertFalse(any(e.script.get('name') == 'Wing.Box' for e in layout.entities))
        (zone,) = [e for e in world.describe(source) if e['class'] == 'Zone']
        self.assertEqual((zone['name'], zone['starting']), ('East', True))
        self.assertIn('East', world.object_names(source))

    def test_box_contains_turned_points(self):
        box = world.MapBox('zone', 'Z', (0.0, 0.0, 0.0), TURN, (1000.0, 100.0, 100.0))
        self.assertTrue(box.contains((0.0, 0.0, 400.0)))    # its long side now runs along Z
        self.assertFalse(box.contains((400.0, 0.0, 0.0)))


class ZoneTests(unittest.TestCase):
    def test_spawns_join_the_zone_holding_them(self):
        zones = world_compile.map_zones([
            world.MapBox('zone', 'A', (-600.0, 150.0, 0.0), (0, 0, 0, 1), (1200.0, 300.0, 1200.0),
                         zone='A', starting=True),
            world.MapBox('zone', 'B', (600.0, 150.0, 0.0), (0, 0, 0, 1), (1200.0, 300.0, 1200.0),
                         zone='B')])
        members = world_compile.zone_spawns(zones, [1, 2, 3], {1: (-300.0, 0.0, 0.0),
                                                              2: (300.0, 0.0, 0.0),
                                                              3: (5000.0, 0.0, 0.0)})
        self.assertEqual(members, {'A': [1, 3], 'B': [2]})   # outside every box: the starting zone

    def test_door_opens_a_zone_by_any_of_its_boxes(self):
        door = resources.EntitySpec([resources.Component(
            iw_hash('CIsComponentSpec'), 0, iw_hash('CDoor'), [reflect.Blob(iw_hash('CDoor'), [])])])
        resource = group.Resource(None, iw_hash('Gate'), resources.encode_entity_spec(door))
        level = world_compile._Level.__new__(world_compile._Level)
        level.name = 'mymap'
        level.named = {'gate': (iw_hash('Gate'), ['CDoor'], 'door', 'Gate')}
        level.link_requests = [(resource, world.Placement(
            'Gate', (0.0, 0.0, 0.0), piece='door', script={'name': 'Gate'},
            links={'zones': ['Hall_1', 'Hall_2']}))]
        level.barricade_spawns, level.added, level.moved, level.runtime = {}, [resource], [], {}
        level.zone_boxes = {'hall_1': 'Hall', 'hall_2': 'Hall'}
        level.area_names = {iw_hash('mymap_zone_hall'): 'Hall'}
        level.apply_links()
        blob = spec_fields.component_blob(resources.decode_entity_spec(resource.body), 'CDoor')
        raw = spec_fields.prop(blob, 'm_AreasUnlock').raw
        self.assertEqual(struct.unpack('<II', raw), (1, iw_hash('mymap_zone_hall')))
        level.runtime_links()
        self.assertEqual(level.runtime['links'], {'Gate': {'zones': ['Hall']}})

    def test_zone_link_needs_a_zone(self):
        self.assertTrue(links.can_target(links.BY_NAME['zones'],
                                         links.kinds_of(role='volume', volume='zone')))
        self.assertFalse(links.can_target(links.BY_NAME['zones'],
                                          links.kinds_of(role='volume', volume='trigger')))
        self.assertIn('zones', [k.name for k in links.kinds_for(
            links.kinds_of(role='prefab', piece='debris'))])


class SectorTests(unittest.TestCase):
    def test_portal_finds_the_sector_on_each_side(self):
        boxes = two_rooms()
        sectors = [b for b in boxes if b.kind == 'sector']
        self.assertEqual(world_compile.portal_sectors(boxes[2], sectors), ('RoomB', 'RoomA'))
        quad, normal = world_compile.portal_quad(boxes[2])
        self.assertEqual(normal, (1.0, 0.0, 0.0))
        self.assertEqual(sorted(quad), [(0.0, 0.0, -150.0), (0.0, 0.0, 150.0),
                                        (0.0, 300.0, -150.0), (0.0, 300.0, 150.0)])

    def test_portal_needs_two_sectors(self):
        boxes = two_rooms()
        with self.assertRaisesRegex(world.WorldError, 'portal Door: no sector on its front'):
            world_compile.portal_sectors(boxes[2], [boxes[0]])
        lonely = world.MapBox('portal', 'Gap', (-600.0, 150.0, 0.0), (0, 0, 0, 1), (20.0, 300.0, 300.0))
        with self.assertRaisesRegex(world.WorldError, 'both its sides are in sector RoomA'):
            world_compile.portal_sectors(lonely, boxes[:2])

    def test_sector_groups(self):
        files, runtime = world_compile.sector_groups('mymap', two_rooms(), placed_template())
        self.assertEqual(sorted(files), ['mymap_sector_rooma.group.bin', 'mymap_sector_roomb.group.bin',
                                         'mymap_sectors.group.bin'])
        from bozkit import levels
        children = [path for path, _h, _f in levels.children(files['mymap_sectors.group.bin'])]
        self.assertEqual(children, ['levels/mymap//mymap_sector_rooma.group',
                                    'levels/mymap//mymap_sector_roomb.group'])
        room = files['mymap_sector_roomb.group.bin']
        self.assertEqual(room.name, 'mymap_sector_roomb')
        types = {t.class_hash: t for t in room.types()}
        shell = iw_hash('mymap_sector_roomb_shell')
        (model,) = types[iw_hash('CIwModel')].resources
        self.assertEqual(model.in_group_hash, shell)
        self.assertEqual(struct.unpack_from('<I', model.body)[0], world_compile.SHELL_FLAGS)
        decoded = native.decode_model(model.body)
        self.assertEqual((len(decoded.vertices), decoded.triangles), (8, []))
        self.assertEqual(max(v[0] for v in decoded.vertices), 600)
        (spec,) = types[iw_hash('CIsEntitySpec')].resources
        spec = resources.decode_entity_spec(spec.body)
        self.assertEqual(spec_fields.model_reference(spec), shell)
        self.assertEqual(spec_fields.local_transform(spec)[0], (600.0, 150.0, 0.0))
        (portal,) = types[iw_hash('CIsPortal')].resources   # in the sector its front faces
        portal = map_resources.decode_portal(portal.body)
        self.assertEqual((portal.front_sector, portal.back_sector),
                         ('mymap_sector_roomb', 'mymap_sector_rooma'))
        self.assertNotIn(iw_hash('CIsPortal'), {t.class_hash for t in
                                                files['mymap_sector_rooma.group.bin'].types()})
        self.assertEqual(runtime['RoomA']['group'], 'mymap_sector_rooma')
        self.assertEqual(runtime['RoomA']['size'], [1200.0, 300.0, 1200.0])

    def test_turned_sector_bakes_its_turn(self):
        box = world.MapBox('sector', 'Long', (0.0, 0.0, 0.0), TURN, (1000.0, 100.0, 100.0))
        files, _runtime = world_compile.sector_groups('m', [box], placed_template())
        model = next(r for t in files['m_sector_long.group.bin'].types()
                     if t.class_hash == iw_hash('CIwModel') for r in t.resources)
        vertices = native.decode_model(model.body).vertices
        self.assertEqual(max(abs(v[2]) for v in vertices), 500)   # the shell is unturned
        self.assertEqual(max(abs(v[0]) for v in vertices), 50)

    def test_no_sectors_no_groups(self):
        self.assertEqual(world_compile.sector_groups('m', [], placed_template()), ({}, {}))
        with self.assertRaisesRegex(world.WorldError, 'the map has no sectors to join'):
            world_compile.sector_groups('m', two_rooms()[2:], placed_template())


if __name__ == '__main__':
    unittest.main()
