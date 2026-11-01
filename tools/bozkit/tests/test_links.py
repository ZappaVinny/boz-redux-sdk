"""Placed game prefabs' links to each other (world_compile.rewire_links, set_level_boxes)."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import reflect, resources, spec_fields, toolkit, world_compile  # noqa: E402
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
