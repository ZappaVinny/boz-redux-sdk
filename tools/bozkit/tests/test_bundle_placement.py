"""Where bundled resources go (synthetic): each group gets what it uses where it can see it while
it loads, and a clash rename never points a use at another class's resource."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import bundle, group, levels, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

MODEL, SKEL, SKIN = iw_hash('CIwModel'), iw_hash('CIwAnimSkel'), iw_hash('CIwAnimSkin')
SPEC, ANIM = iw_hash('CIsEntitySpec'), iw_hash('CIwAnim')
ASM = iw_hash('CIsAnimStateMachine')
DYNAMICS = 'levels/moon/moon_dynamics.group.bin'


def rtype(cls, items):
    return group.ResourceType(cls, 1, 1, [group.Resource(None, h, body) for h, body in items])


def word(name):
    return struct.pack('<I', iw_hash(name))


def board_spec():
    """A barricade: its "Boards" (a model, and a state machine that differs per map) and its
    power switch link (the field name hashes as the entity name: iw_hash ignores case)."""
    def prop(name, value):
        return reflect.Property(iw_hash('CBoard'), iw_hash('unsigned int'), iw_hash(name), struct.pack('<I', value))
    component = resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CBoard'), [reflect.Blob(
        iw_hash('CBoard'), [prop('ASM', iw_hash('Boards')), prop('powerSwitch', iw_hash('PowerSwitch'))])])
    return resources.encode_entity_spec(resources.EntitySpec([component]))


class Game:
    """Another map's skinned machine: a skeleton, a skin using it and the model "PAP", plus a
    spec also named "PAP" (as Ascension's Pack-a-Punch); the base level's dynamics group."""

    def __init__(self):
        self.files = {
            'ingame/ingame.group.bin': levels.make_group('ingame', flags=1),
            'shared/shared.group.bin': levels.make_group('shared', flags=1),
            'ingame/effects/visualeffects.group.bin': levels.make_group('visualeffects'),
            DYNAMICS: levels.make_group('moon_dynamics', types=[rtype(SKEL, [(iw_hash('base_skel'), b'base skeleton')])]),
            'levels/moon/moon_statics.group.bin': levels.make_group('moon_statics', types=[
                rtype(MODEL, [(iw_hash('PAP'), b'pap model'), (iw_hash('Boards'), b'boards model')]),
                rtype(SKEL, [(iw_hash('pap_skel'), b'pap skeleton')]),
                rtype(SKIN, [(iw_hash('pap_skin'), b'skin' + word('PAP') + word('pap_skel'))]),
                rtype(ANIM, [(iw_hash('pap_anim'), b'anim' + word('base_skel'))]),
                rtype(SPEC, [(iw_hash('PAP'), b'not a reflected spec'),
                             (iw_hash('board'), board_spec())]),
                rtype(ASM, [(iw_hash('Boards'), b'moon boards machine')])]),
        }
        self.paths = list(self.files)

    def read(self, path):
        return group.encode(self.files[path])


def map_groups(weapons=(), projectiles=()):
    """A generated map's groups as the game loads them (weapons with their projectiles child,
    the level with the base dynamics and its statics)."""
    return {
        'weapons_mymap.group.bin': levels.make_group(
            'weapons_mymap', [levels.Child('ingame/weapons//weapon_projectiles_mymap.group', 'weapon_projectiles_mymap')],
            list(weapons)),
        'weapon_projectiles_mymap.group.bin': levels.make_group('weapon_projectiles_mymap', types=list(projectiles)),
        'arms_mymap.group.bin': levels.make_group('arms_mymap'),
        'mymap.group.bin': levels.make_group('mymap', [
            levels.Child('levels/moon//moon_dynamics.group', 'moon_dynamics'),
            levels.Child('levels/mymap//mymap_statics.group', 'mymap_statics')]),
        'mymap_statics.group.bin': levels.make_group('mymap_statics'),
    }


def held(target):
    return {(t.class_hash, r.in_group_hash): r.body for t in target.types() for r in t.resources}


def bundle_for(groups):
    game = Game()
    reg = bundle.Registry(game.read, game.paths)
    reg.runtime = {}
    return bundle.Bundle(reg, groups, 'mymap')


class Placement(unittest.TestCase):
    def test_load_order(self):
        b = bundle_for(map_groups())
        order = b.load_order()
        self.assertLess(order['weapon_projectiles_mymap.group.bin'][0], order['weapons_mymap.group.bin'][0])
        self.assertLess(order['weapons_mymap.group.bin'][0], order['mymap_statics.group.bin'][0])
        self.assertLess(order[DYNAMICS][0], order['mymap_statics.group.bin'][0])
        self.assertTrue(order['ingame/ingame.group.bin'][2])                 # shared
        self.assertTrue(b.visible('ingame/ingame.group.bin', 'weapons_mymap.group.bin'))
        self.assertTrue(b.visible(DYNAMICS, 'mymap_statics.group.bin'))      # loaded with the level
        self.assertFalse(b.visible(DYNAMICS, 'weapons_mymap.group.bin'))     # loads later
        self.assertFalse(b.visible('weapons_mymap.group.bin', 'mymap_statics.group.bin'))
        self.assertFalse(b.visible('weapon_projectiles_mymap.group.bin', 'weapons_mymap.group.bin'))

    def test_a_skeleton_another_group_holds_is_copied_again(self):
        # The weapons group already has the skeleton (a box weapon brought it); a skin in the
        # statics cannot see it while it loads, so the statics get their own copy.
        groups = map_groups(weapons=[rtype(SKEL, [(iw_hash('pap_skel'), b'pap skeleton')])])
        b = bundle_for(groups)
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin')
        statics = held(groups['mymap_statics.group.bin'])
        self.assertIn((SKIN, iw_hash('pap_skin')), statics)
        self.assertEqual(statics[(SKEL, iw_hash('pap_skel'))], b'pap skeleton')
        self.assertIn((MODEL, iw_hash('PAP')), statics)

    def test_a_group_reuses_what_it_can_see(self):
        groups = map_groups()
        b = bundle_for(groups)
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin')
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin')
        statics = held(groups['mymap_statics.group.bin'])
        self.assertEqual(len([k for k in statics if k[0] == SKEL]), 1)       # once
        # The base dynamics load before the statics: their skeleton is not copied.
        b.add([iw_hash('pap_anim')], prefer='levels/moon/moon_statics.group.bin')
        self.assertNotIn((SKEL, iw_hash('base_skel')), held(groups['mymap_statics.group.bin']))

    def test_the_same_resource_in_two_groups_that_need_it(self):
        groups = map_groups()
        b = bundle_for(groups)
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin')
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin',
              target='weapon_projectiles_mymap.group.bin')
        projectiles = held(groups['weapon_projectiles_mymap.group.bin'])
        self.assertIn((SKIN, iw_hash('pap_skin')), projectiles)
        self.assertIn((SKEL, iw_hash('pap_skel')), projectiles)
        self.assertIn((MODEL, iw_hash('PAP')), projectiles)
        for target in groups.values():
            group.parse(group.encode(target))

    def test_a_rename_stays_in_its_class(self):
        # The map already has a different spec called PAP: the skin's PAP is the model, which
        # does not clash, so the skin keeps pointing at it.
        groups = map_groups(projectiles=[rtype(SPEC, [(iw_hash('PAP'), b'my own spec')])])
        b = bundle_for(groups)
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin')
        statics = held(groups['mymap_statics.group.bin'])
        skin = statics[(SKIN, iw_hash('pap_skin'))]
        self.assertIn(word('PAP'), skin)
        self.assertEqual(statics[(MODEL, iw_hash('PAP'))], b'pap model')
        everything = {}
        for target in groups.values():
            everything.update(held(target))
        self.assertNotIn((SPEC, iw_hash('boz_moon_statics_%08x' % iw_hash('PAP'))), everything)

    def test_a_renamed_model_is_pointed_at(self):
        # A different model called PAP is already in the statics: the copy gets a name of its
        # own, and the skin uses that name.
        groups = map_groups()
        groups['mymap_statics.group.bin'].sections[-1].types.append(rtype(MODEL, [(iw_hash('PAP'), b'my own model')]))
        b = bundle_for(groups)
        b.add([iw_hash('pap_skin')], prefer='levels/moon/moon_statics.group.bin')
        statics = held(groups['mymap_statics.group.bin'])
        new = iw_hash('boz_moon_statics_%08x' % iw_hash('PAP'))
        self.assertEqual(statics[(MODEL, new)], b'pap model')
        skin = statics[(SKIN, iw_hash('pap_skin'))]
        self.assertIn(struct.pack('<I', new), skin)
        self.assertNotIn(word('PAP'), skin)

    def test_a_name_renamed_for_one_class_is_renamed_for_all(self):
        # The map's own "Boards" state machine is another one: the barricade's copy is renamed,
        # its model (no clash) is copied under that name too, and the spec points at the name.
        groups = map_groups()
        groups['mymap_statics.group.bin'].sections[-1].types.append(rtype(ASM, [(iw_hash('Boards'), b'my boards machine')]))
        b = bundle_for(groups)
        b.add([iw_hash('board')], prefer='levels/moon/moon_statics.group.bin')
        projectiles = held(groups['weapon_projectiles_mymap.group.bin'])
        new = iw_hash('boz_moon_statics_%08x' % iw_hash('Boards'))
        self.assertEqual(projectiles[(ASM, new)], b'moon boards machine')
        self.assertEqual(projectiles[(MODEL, new)], b'boards model')
        board = projectiles[(SPEC, iw_hash('board'))]
        self.assertIn(struct.pack('<I', new), board)
        self.assertNotIn(word('Boards'), board)

    def test_links_and_field_names_are_never_renamed(self):
        # A different PowerSwitch spec is in the map: the barricade's power switch link (and its
        # field name, the same hash) stay as they are, and no PowerSwitch template comes along.
        groups = map_groups(projectiles=[rtype(SPEC, [(iw_hash('PowerSwitch'), b'my switch')])])
        game = Game()
        game.files['levels/moon/moon_statics.group.bin'].sections[-1].types.append(
            rtype(SPEC, [(iw_hash('PowerSwitch'), b'moon switch')]))
        reg = bundle.Registry(game.read, game.paths)
        reg.runtime = {}
        b = bundle.Bundle(reg, groups, 'mymap')
        b.add([iw_hash('board')], prefer='levels/moon/moon_statics.group.bin')
        board = held(groups['weapon_projectiles_mymap.group.bin'])[(SPEC, iw_hash('board'))]
        self.assertEqual(board.count(word('PowerSwitch')), 2)               # field name and value
        spec = resources.decode_entity_spec(board)
        self.assertEqual([p.name_hash for p in spec.components[0].blob.properties],
                         [iw_hash('ASM'), iw_hash('powerSwitch')])
        everything = {}
        for target in groups.values():
            everything.update(held(target))
        self.assertNotIn((SPEC, iw_hash('boz_moon_statics_%08x' % iw_hash('PowerSwitch'))), everything)


if __name__ == '__main__':
    unittest.main()
