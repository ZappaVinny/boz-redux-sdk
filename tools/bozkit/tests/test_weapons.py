"""Project weapons: fields, project files, new and imported weapons (synthetic groups only)."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import group, reflect, resources, weapons  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

ASM = iw_hash('CIsAnimStateMachine')
ANIM = iw_hash('CIwAnim')
MODEL = iw_hash('CIwModel')


def prop(type_name, name, value=None, raw=None, nested=None):
    p = reflect.Property(iw_hash('CPlayerWeapon'), iw_hash(type_name), iw_hash(name), raw or b'',
                         nested=nested)
    if value is not None:
        reflect.set_typed_value(p, value)
    return p


def weapon_body(name, clip=8, behaviour=1, upgrade='', model=''):
    damage = reflect.Blob(iw_hash('CWeaponDamage'), [
        reflect.Property(iw_hash('CWeaponDamage'), iw_hash('unsigned int'), iw_hash('m_headDamage'),
                         struct.pack('<I', 70))])
    props = [prop('unsigned int', 'm_name', iw_hash(name)),
             prop('CParsableEnumManager::WeaponBehaviourType', 'behaviour',
                  raw=struct.pack('<I', behaviour)),
             prop('unsigned int', 'm_clipSize', clip),
             prop('std::string', 'm_weaponAsm', name),
             prop('CWeaponDamage', 'm_damage', nested=damage)]
    if upgrade:
        props.append(prop('unsigned int', 'Upgrade', iw_hash(upgrade)))
    if model:
        props.append(prop('unsigned int', 'skel', iw_hash(model)))
    component = resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CPlayerWeapon'),
                                    [reflect.Blob(iw_hash('CPlayerWeapon'), props)])
    return resources.encode_entity_spec(resources.EntitySpec([component]))


def make_group(types):
    return group.Group(bytes((0x3D, 0, 0, 0, 0, 0)), [group.Section(group.RESOURCES, b'', types)])


def rtype(class_hash, items):
    return group.ResourceType(class_hash, 1, 1,
                              [group.Resource(None, iw_hash(name), body) for name, body in items])


def kino_groups():
    return {
        'weapons': make_group([
            rtype(weapons.ENTITY_SPEC, [('colt45', weapon_body('colt45', upgrade='0xdeadbeef')),
                                        ('mp40', weapon_body('mp40', 32, 2))]),
            rtype(ASM, [('mp40', b'asm' + struct.pack('<I', iw_hash('mp40_fire')))]),
            rtype(ANIM, [('mp40_fire', b'anim')])]),
        'projectiles': make_group([rtype(weapons.ENTITY_SPEC, [])]),
        'arms': make_group([rtype(ASM, [])]),
    }


class FakeGame:
    """Call of the Dead's groups: the V-R11 (state machine -> animation -> model) and an unrelated
    weapon that must not come along."""

    def __init__(self):
        asm = b'asm' + struct.pack('<I', iw_hash('humangun_fire'))
        anim = b'anim' + struct.pack('<I', iw_hash('humangun_mdl'))
        self.files = {
            'ingame/weapons/weapons_callofthedead.group.bin': make_group([
                rtype(weapons.ENTITY_SPEC, [('humangun', weapon_body('humangun', 3, 16)),
                                            ('unrelated', weapon_body('unrelated'))]),
                rtype(ASM, [('humangun', asm), ('unrelated', b'asm')]),
                rtype(ANIM, [('humangun_fire', anim), ('unrelated_fire', b'x')]),
                rtype(MODEL, [('humangun_mdl', b'model')])]),
            'ingame/weapons/weapon_projectiles_callofthedead.group.bin': make_group([]),
            'ingame/characters/arms/arms_callofthedead.group.bin': make_group([]),
        }

    def read(self, path):
        return group.encode(self.files[path])


def names_in(parsed):
    return {r.in_group_hash for t in parsed.types() for r in t.resources}


class WeaponTests(unittest.TestCase):
    def test_values_and_defaults(self):
        spec = resources.decode_entity_spec(weapon_body('mp40', 32, 2))
        blob = weapons.weapon_blob(spec)
        self.assertEqual(weapons.get_value(blob, 'm_clipSize'), 32)
        self.assertEqual(weapons.get_value(blob, 'behaviour'), 2)
        self.assertEqual(weapons.get_value(blob, 'm_damage.m_headDamage'), 70)
        self.assertIsNone(weapons.get_value(blob, 'autoROF'))
        self.assertEqual(weapons.value_or_default(blob, 'm_accuracy.m_spreadMax'), 1.0)
        weapons.set_value(blob, 'autoROF', 900)
        weapons.set_value(blob, 'm_damage.m_torsoDamage', 150)
        weapons.set_value(blob, 'm_falloff.m_startDistance', 300)    # a struct it did not have
        weapons.set_value(blob, 'recoil', 3)
        again = weapons.weapon_blob(resources.decode_entity_spec(resources.encode_entity_spec(spec)))
        self.assertEqual([weapons.get_value(again, k) for k in (
            'autoROF', 'm_damage.m_headDamage', 'm_damage.m_torsoDamage',
            'm_falloff.m_startDistance', 'recoil')], [900, 70, 150, 300, 3])
        with self.assertRaises(weapons.WeaponError):
            weapons.set_value(blob, 'm_projectileName', 1)

    def test_fields_are_documented(self):
        for spec in weapons.FIELDS:
            self.assertTrue(spec.label and spec.description, spec.key)
            if spec.kind == 'enum':
                self.assertTrue(spec.options, spec.key)

    def test_project_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            self.assertIsNone(weapons.load_index(source))
            weapons.save_index(source, ['colt45', 'mp40_heavy', 'colt45'])
            self.assertEqual(weapons.load_index(source), ['colt45', 'mp40_heavy'])
            weapons.save_def(source, weapons.WeaponDef('mp40_heavy', 'mp40', '', {'m_clipSize': 50}))
            defs = weapons.load_defs(source)
            self.assertEqual([(d.name, d.source, d.fields) for d in defs],
                             [('mp40_heavy', 'mp40', {'m_clipSize': 50})])
            with self.assertRaises(weapons.WeaponError):
                weapons.save_def(source, weapons.WeaponDef('bad', fields={'nope': 1}))
            self.assertEqual(weapons.validate(defs, {'mp40'}), [])
            self.assertTrue(weapons.validate(defs, {'colt45'}))
            self.assertEqual(weapons.load_start(source), ('colt45', 40))
            weapons.save_start(source, 'mp40', 120)
            self.assertEqual(weapons.load_start(source), ('mp40', 120))
            self.assertEqual(weapons.load_index(source), ['colt45', 'mp40_heavy'])   # kept
            weapons.save_index(source, ['mp40'])
            self.assertEqual(weapons.load_start(source), ('mp40', 120))              # kept
            weapons.delete_def(source, 'mp40_heavy')
            self.assertEqual(weapons.load_defs(source), [])

    def test_read_group_and_index(self):
        listed = weapons.read_group(kino_groups()['weapons'], 'kino')
        self.assertEqual({w.name for w in listed}, {'colt45', 'mp40'})
        mp40 = next(w for w in listed if w.name == 'mp40')
        self.assertEqual((mp40.values['m_clipSize'], mp40.values['autoROF']), (32, 0))
        self.assertEqual(weapons.default_index(listed, 'empty'), ['colt45'])
        self.assertEqual(sorted(weapons.default_index(listed, 'kino')), ['colt45', 'mp40'])

    def test_new_weapon_and_changes(self):
        groups = kino_groups()
        result = weapons.apply(FakeGame(), groups, 'kino', [
            weapons.WeaponDef('mp40_heavy', 'mp40', '', {'m_clipSize': 50, 'Upgrade': 'colt45'}),
            weapons.WeaponDef('colt45', '', '', {'m_damage.m_headDamage': 99})])
        self.assertEqual(result['aliases'], {iw_hash('mp40_heavy'): iw_hash('mp40')})
        listed = {w.name: w for w in weapons.read_group(groups['weapons'], extra_names=['mp40_heavy'])}
        self.assertEqual(listed['mp40_heavy'].values['m_clipSize'], 50)
        self.assertEqual(listed['mp40_heavy'].values['behaviour'], 2)
        self.assertEqual(listed['mp40_heavy'].values['Upgrade'], 'colt45')
        self.assertEqual(listed['mp40'].values['m_clipSize'], 32)
        self.assertEqual(listed['colt45'].values['m_damage.m_headDamage'], 99)
        with self.assertRaises(weapons.WeaponError):
            weapons.apply(FakeGame(), kino_groups(), 'kino', [weapons.WeaponDef('x', 'missing')])

    def test_import_brings_what_it_uses(self):
        from bozkit import bundle
        groups = kino_groups()
        game = FakeGame()
        files = {'weapons_mymap.group.bin': groups['weapons'],
                 'weapon_projectiles_mymap.group.bin': groups['projectiles'],
                 'arms_mymap.group.bin': groups['arms']}
        carrier = bundle.Bundle(bundle.Registry(game.read, list(game.files)), files, 'mymap')
        weapons.apply(game, groups, 'kino',
                      [weapons.WeaponDef('humangun', '', 'callofthedead', {'m_clipSize': 5})], bundle=carrier)
        present = names_in(groups['weapons'])
        for name in ('humangun', 'humangun_fire', 'humangun_mdl'):
            self.assertIn(iw_hash(name), present, name)
        for name in ('unrelated', 'unrelated_fire'):
            self.assertNotIn(iw_hash(name), present, name)
        humangun = next(w for w in weapons.read_group(groups['weapons']) if w.name_hash == iw_hash('humangun'))
        self.assertEqual((humangun.values['behaviour'], humangun.values['m_clipSize']), (16, 5))
        # The state machine of the same name came too (resources repeat names across classes).
        asm = [r for t in groups['weapons'].types() if t.class_hash == ASM for r in t.resources]
        self.assertIn(iw_hash('humangun'), {r.in_group_hash for r in asm})

    def test_box_pool_setting(self):
        from bozkit import toolkit
        setting = next(x for x in toolkit.piece('mystery_box').settings if x.kind == 'weapons')
        self.assertEqual(toolkit.fields_for(setting, 'mp40, raygun,'),
                         {'CMysteryBox.m_Weapons': ['mp40', 'raygun']})
        self.assertEqual(toolkit.fields_for(setting, ''), {})
        raw = toolkit.encode_hash_list([iw_hash('mp40'), iw_hash('raygun')])
        self.assertEqual(toolkit.hash_list(raw), [iw_hash('mp40'), iw_hash('raygun')])
        self.assertEqual(toolkit.hash_list(b'\x05\x00\x00\x00'), [])

    def test_runtime(self):
        defs = [weapons.WeaponDef('mp40_heavy', 'mp40', script='weapons/Heavy.lua')]
        self.assertEqual(weapons.runtime(defs, ['colt45']),
                         [{'name': 'colt45', 'script': ''},
                          {'name': 'mp40_heavy', 'script': 'weapons.Heavy'}])

    def test_in_game_name(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            weapons.save_def(source, weapons.WeaponDef('idgun', 'thundergun', display='Apothicon'))
            defs = weapons.load_defs(source)
            self.assertEqual(defs[0].display, 'Apothicon')
            defs[0].sounds = {'reloadSoundSequence': 'my_reload'}
            weapons.save_def(source, defs[0])
            self.assertEqual(weapons.load_defs(source)[0].sounds, {'reloadSoundSequence': 'my_reload'})
            with self.assertRaises(weapons.WeaponError):        # not saved in the Audio tab
                weapons.attach_models(weapons.load_defs(source), source)
            self.assertEqual(weapons.runtime(defs, []),
                             [{'name': 'idgun', 'script': '', 'display': 'Apothicon'}])


if __name__ == '__main__':
    unittest.main()
