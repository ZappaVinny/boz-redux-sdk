"""Placed game prefabs' links to each other (bozkit.links, world_compile.rewire_links and
apply_links, set_level_boxes)."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import group, links, reflect, resources, spec_fields, toolkit, world, world_compile  # noqa: E402,E501
from bozkit.hashing import iw_hash  # noqa: E402

KINO = 'levels/kino/kino_statics.group.bin'
ASCENSION = 'levels/ascension/ascension_statics.group.bin'
POWER = iw_hash('PowerSwitch')


def prop(owner, type_name, name, raw):
    return reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), raw)


def component(name, props=()):
    return resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash(name),
                               [reflect.Blob(iw_hash(name), list(props))])


def u32(owner, name, value):
    return prop(owner, 'unsigned int', name, struct.pack('<I', value))


def names(owner, name, values):
    return prop(owner, 'std::list<unsigned int>', name, toolkit.encode_hash_list(values))


def value(spec, class_name, field_name):
    raw = spec_fields.prop(spec_fields.component_blob(spec, class_name), field_name).raw
    if (class_name, field_name) in world_compile.LIST_LINKS:
        return toolkit.hash_list(raw)
    return struct.unpack('<I', raw)[0]


class RewireTests(unittest.TestCase):
    def test_power_link_goes_to_the_map_switch(self):
        # A Kino perk links to Kino's PowerSwitch; the map's switch is PowerSwitch too.
        perk = resources.EntitySpec([component('CPerk', [u32('CPerk', 'powerSwitch', POWER)])])
        self.assertFalse(world_compile.rewire_links(perk, KINO, {}, {POWER}, POWER))
        # A switch under another name in its level: the link follows the map's switch.
        perk = resources.EntitySpec([component('CPerk', [u32('CPerk', 'powerSwitch',
                                                             iw_hash('Power_Main'))])])
        self.assertTrue(world_compile.rewire_links(perk, ASCENSION, {}, {POWER}, POWER))
        self.assertEqual(value(perk, 'CPerk', 'powerSwitch'), POWER)

    def test_no_power_and_unpowered_stay(self):
        no_power = iw_hash(toolkit.NO_POWER)
        for link in (0, no_power):
            perk = resources.EntitySpec([component('CPerk', [u32('CPerk', 'powerSwitch', link)])])
            self.assertFalse(world_compile.rewire_links(perk, KINO, {}, {POWER}, POWER))
            self.assertEqual(value(perk, 'CPerk', 'powerSwitch'), link)
        # No power switch in the map: the link is left alone (it never powers on).
        door = resources.EntitySpec([component('CDoor', [u32('CDoor', 'powerSwitch', POWER)])])
        self.assertFalse(world_compile.rewire_links(door, KINO, {}, set(), 0))

    def test_trap_list_follows_renamed_trap(self):
        firepit, renamed = iw_hash('Traps_Firepit'), iw_hash('Firepit')
        switch = resources.EntitySpec([component('CTrapSwitch', [
            u32('CTrapSwitch', 'powerSwitch', POWER),
            names('CTrapSwitch', 'traps', [firepit, iw_hash('Traps_Elsewhere')])])])
        renames = {(KINO, firepit): renamed}
        self.assertTrue(world_compile.rewire_links(switch, KINO, renames, {POWER, renamed}, POWER))
        # The placed trap's new name; a trap the map does not have is dropped.
        self.assertEqual(value(switch, 'CTrapSwitch', 'traps'), [renamed])

    def test_renames_only_within_the_home_group(self):
        firepit = iw_hash('Traps_Firepit')
        switch = resources.EntitySpec([component('CTrapSwitch', [
            names('CTrapSwitch', 'traps', [firepit])])])
        renames = {(KINO, firepit): iw_hash('Firepit')}
        world_compile.rewire_links(switch, ASCENSION, renames, set(), 0)
        self.assertEqual(value(switch, 'CTrapSwitch', 'traps'), [])

    def test_present_target_wins(self):
        # A remix keeps links to the base level's own entities, even with a placed copy renamed.
        top, bottom = iw_hash('Balcony_To_Bar_Top'), iw_hash('Balcony_To_Bar_Bottom')
        door = resources.EntitySpec([component('CDoor', [names('CDoor', 'm_Siblings', [top])])])
        renames = {(KINO, top): iw_hash('Copy_Top')}
        self.assertFalse(world_compile.rewire_links(door, KINO, renames, {top, bottom}, 0))
        self.assertEqual(value(door, 'CDoor', 'm_Siblings'), [top])


def placed(name, spec, piece='', set_links=None):
    """(resource, placement) of an entity placed under the world name *name*."""
    resource = group.Resource(None, iw_hash(name), resources.encode_entity_spec(spec))
    return resource, world.Placement(name, (0.0, 0.0, 0.0), piece=piece,
                                     script={'name': name}, links=set_links or {})


def level_with(*items):
    """A bare _Level holding *items* ((resource, placement)), as entity() leaves it."""
    from bozkit.blender_scene import component_names

    level = world_compile._Level.__new__(world_compile._Level)
    level.named, level.link_requests, level.barricade_spawns = {}, [], {}
    level.added, level.moved, level.runtime = [], [], {}
    for resource, placement in items:
        spec = resources.decode_entity_spec(resource.body)
        level.named[placement.script['name'].lower()] = (
            resource.in_group_hash, component_names(spec), placement.piece,
            placement.script['name'])
        level.added.append(resource)
        if placement.links:
            level.link_requests.append((resource, placement))
    return level


def decoded(resource):
    return resources.decode_entity_spec(resource.body)


class SetLinkTests(unittest.TestCase):
    def test_table(self):
        kinds = [kind.name for kind in links.kinds_for(['CIsTransform', 'CTrapSwitch'])]
        self.assertEqual(kinds, ['power', 'traps'])
        self.assertEqual([k.name for k in links.kinds_for(['CBarricade'])], ['spawns'])
        self.assertTrue(links.can_target(links.BY_NAME['traps'], ['CTrap']))
        self.assertFalse(links.can_target(links.BY_NAME['spawns'], ['CSpawnPoint'], 'zombie_ground'))
        self.assertEqual(links.clean({'power': ['A', 'B'], 'traps': 'T', 'nope': ['x']}),
                         {'power': ['A'], 'traps': ['T']})
        self.assertEqual(links.renamed({'traps': ['A', 'B']}, 'A', 'C'), {'traps': ['C', 'B']})

    def test_world_json_round_trip(self):
        prefab = world.Prefab('Switch', source='Traps_Switch', links={'traps': ['Firepit']})
        again = world.object_from_json(world.object_json(prefab))
        self.assertEqual(again.links, {'traps': ['Firepit']})
        self.assertNotIn('links', world.object_json(world.Prefab('Perk', source='perk')))

    def test_set_links_are_written_by_map_name(self):
        switch = placed('Electro', resources.EntitySpec([component('CTrapSwitch', [
            u32('CTrapSwitch', 'powerSwitch', POWER),
            names('CTrapSwitch', 'traps', [iw_hash('Traps_Electro')])])]),
            set_links={'traps': ['Firepit', 'Zapper'], 'power': ['Power']})
        firepit = placed('Firepit', resources.EntitySpec([component('CTrap')]))
        zapper = placed('Zapper', resources.EntitySpec([component('CTrap')]))
        power = placed('Power', resources.EntitySpec([component('CPowerSwitch')]))
        power[0].in_group_hash = POWER   # a new map's switch is always called PowerSwitch
        level = level_with(switch, firepit, zapper, power)
        level.apply_links()
        spec = decoded(switch[0])
        self.assertEqual(value(spec, 'CTrapSwitch', 'traps'), [iw_hash('Firepit'), iw_hash('Zapper')])
        self.assertEqual(value(spec, 'CTrapSwitch', 'powerSwitch'), POWER)
        self.assertNotIn('warnings', level.runtime)
        level.runtime_links()
        self.assertEqual(level.runtime['links']['Electro'],
                         {'power': ['Power'], 'traps': ['Firepit', 'Zapper']})

    def test_missing_or_wrong_target_is_an_error(self):
        switch = placed('Electro', resources.EntitySpec([component('CTrapSwitch')]),
                        set_links={'traps': ['Gone']})
        with self.assertRaisesRegex(world_compile.WorldError, 'Gone, which is not in the map'):
            level_with(switch).apply_links()
        door = placed('Door', resources.EntitySpec([component('CDoor')]))
        switch = placed('Electro', resources.EntitySpec([component('CTrapSwitch')]),
                        set_links={'traps': ['Door']})
        with self.assertRaisesRegex(world_compile.WorldError, 'cannot be one'):
            level_with(switch, door).apply_links()

    def test_switch_without_traps_warns(self):
        switch = placed('Electro', resources.EntitySpec([component('CTrapSwitch', [
            names('CTrapSwitch', 'traps', [])])]))
        level = level_with(switch)
        level.apply_links()
        self.assertEqual(level.runtime['warnings'],
                         ['trap switch Electro runs no trap: set its Traps link'])

    def test_barricade_spawns_link_has_no_game_field(self):
        barricade = placed('Window', resources.EntitySpec([component('CBarricade')]),
                           set_links={'spawns': ['Window_Spawn']})
        spawn = placed('Window_Spawn', resources.EntitySpec([component('CSpawnPoint')]),
                       piece='zombie_window')
        level = level_with(barricade, spawn)
        before = barricade[0].body
        level.apply_links()
        self.assertEqual(barricade[0].body, before)
        self.assertEqual(level.barricade_spawns, {'Window': ['Window_Spawn']})
        level.runtime_links()
        self.assertEqual(level.runtime['links'], {'Window': {'spawns': ['Window_Spawn']}})


class CollisionKindTests(unittest.TestCase):
    """What a model's kind feeds: the navmesh (walking, players and zombies alike) and the
    collision mesh (bullets), each on or off."""

    def level(self):
        level = world_compile._Level.__new__(world_compile._Level)
        level.solid, level.single, level.blocking, level.feeds = [], [], [], []
        level.script_collision, level.dirty = {}, []
        return level

    def test_each_kind_feeds_what_it_says(self):
        triangle = [(0, 0, 0), (100, 0, 0), (0, 0, 100)]
        self.assertEqual(world.collision_kind('block', False), 'block')
        for kind, (nav, shot, blocks) in {'floor': (1, 1, 0), 'walk': (1, 0, 0),
                                           'solid': (1, 1, 1), 'block': (1, 0, 1),
                                           'bullets': (0, 1, 0), 'none': (0, 0, 0)}.items():
            level = self.level()
            level.collide(triangle, [(0, 1, 2)], kind, 'mesh')
            self.assertEqual(len(level.triangles(world_compile.NAV)), nav, kind)
            self.assertEqual(len(level.triangles(world_compile.BULLETS)), shot, kind)
            self.assertEqual(level.nav_blocking(), [blocks] * nav, kind)

    def test_hidden_object_stops_and_blocks_nothing_until_shown(self):
        level = self.level()
        level.runtime = {'hidden': [], 'no_collision': [], 'blocked': []}
        level.blockers, level.blocker_points, level.player_radius = [], {}, 0.4
        item = world.Placement('wall', (0.0, 0.0, 0.0), script={
            'name': 'Wall', 'visible': False, 'collision': True, 'blocks': True, 'dynamic': True})
        level.script(item, [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 0.0, 100.0)])
        self.assertEqual(level.runtime['hidden'], ['Wall'])
        self.assertEqual(level.runtime['no_collision'], ['Wall'])
        self.assertEqual(level.runtime['blocked'], [])            # open while hidden
        self.assertEqual(level.runtime['solid'], ['Wall'])        # what show() brings back
        self.assertEqual(level.runtime['blocking'], ['Wall'])
        self.assertEqual(len(level.blockers), 1)                  # its tagged area exists


class LevelBoxTests(unittest.TestCase):
    def level(self, *props):
        return reflect.Blob(iw_hash('CLevel'), list(props))

    def test_box_start_and_avoid(self):
        lobby, mine = iw_hash('MysteryBox_Lobby'), iw_hash('Box')
        blob = self.level(u32('CLevel', 'MysteryBoxAvoid', lobby))
        world_compile.set_level_boxes(blob, [mine, iw_hash('Box2')])
        self.assertEqual(struct.unpack('<I', spec_fields.prop(blob, 'MysteryBoxAvoid').raw)[0], 0)
        self.assertEqual(struct.unpack('<I', spec_fields.prop(blob, 'MysteryBoxStart').raw)[0], mine)
        # Round trip through the reflected format.
        again = resources.decode_reflected(resources.encode_reflected(blob))
        self.assertEqual(struct.unpack('<I', spec_fields.prop(again, 'MysteryBoxStart').raw)[0],
                         mine)

    def test_no_boxes_clears_start(self):
        blob = self.level(u32('CLevel', 'MysteryBoxStart', iw_hash('MysteryBox_PowerRoom')))
        world_compile.set_level_boxes(blob, [])
        self.assertEqual(struct.unpack('<I', spec_fields.prop(blob, 'MysteryBoxStart').raw)[0], 0)
        self.assertIsNone(spec_fields.prop(blob, 'MysteryBoxAvoid'))


if __name__ == '__main__':
    unittest.main()


class BoxPoolTests(unittest.TestCase):
    """weapons.limit_box_pools: the boxes roll the map's weapons."""

    def pool_after(self, pool, index, stock=()):
        from bozkit import group, weapons
        spec = resources.EntitySpec([component('CMysteryBox', [names('CMysteryBox', 'm_Weapons',
                                                                     [iw_hash(n) for n in pool])])])
        box = group.Resource(None, iw_hash('Box'), resources.encode_entity_spec(spec))
        boxes = group.ResourceType(resources.ENTITY_SPEC, 0, 0, [box])
        target = type('Statics', (), {'types': lambda self: [boxes]})()
        weapons.limit_box_pools({'statics': target}, index, 'colt45',
                                {frozenset(iw_hash(n) for n in s) for s in stock})
        spec = resources.decode_entity_spec(box.body)
        return toolkit.hash_list(spec_fields.prop(spec_fields.component_blob(spec, 'CMysteryBox'),
                                                  'm_Weapons').raw)

    def test_stock_pool_becomes_the_map_list(self):
        self.assertEqual(self.pool_after(['raygun', 'AUG'], ['colt45', 'humangun', 'raygun'],
                                         stock=[['raygun', 'AUG']]),
                         [iw_hash('humangun'), iw_hash('raygun')])

    def test_own_pool_keeps_its_weapons_in_the_list(self):
        self.assertEqual(self.pool_after(['raygun', 'AUG'], ['colt45', 'humangun', 'raygun']),
                         [iw_hash('raygun')])

    def test_no_list_keeps_the_pool(self):
        self.assertEqual(self.pool_after(['raygun', 'AUG'], []),
                         [iw_hash('raygun'), iw_hash('AUG')])
