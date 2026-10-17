"""Effects and projectiles (synthetic): the catalog, the project's effects, bundling into a map."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import effects, group, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

GERSCH, MODEL, SPARK = iw_hash('bh_bomb_projectile'), iw_hash('bh_bomb_model'), iw_hash('spark')


def component(name, props=()):
    return resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash(name),
                               [reflect.Blob(iw_hash(name), list(props))])


def prop(owner, type_name, name, raw):
    return reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), raw)


def projectile_spec(behaviour):
    return resources.encode_entity_spec(resources.EntitySpec([
        component('CProjectileEntity', [prop('CProjectileEntity', 'CParsableEnumManager::ProjectileBehaviourType',
                                             'behaviourType', struct.pack('<I', behaviour))]),
        component('CIsRenderableModel', [prop('CIsRenderableModel', 'unsigned int', 'model',
                                              struct.pack('<I', MODEL))])]))


def effect_spec():
    return resources.encode_entity_spec(resources.EntitySpec([component('CIsTransform'), component('CIsRenderableGFXEmitter', [prop('CIsRenderableGFXEmitter', 'unsigned int', 'emitterSpec', struct.pack('<I', 7))])]))


def make_group(types):
    return group.Group(bytes((0x3D, 0, 0, 0, 0, 0)), [group.Section(group.RESOURCES, b'', types)])


def rtype(class_name, items, names_omitted=1, subclass=None):
    return group.ResourceType(iw_hash(class_name), names_omitted, 1,
                              [group.Resource(subclass, h, body) for h, body in items])


GERSCH_SOUNDS = ('gersch_opens', 'gersch_loop', 'gersch_shuts', 'gersch_teleport')


class Pack:
    """A game pack over in-memory groups."""

    def __init__(self, groups):
        self.groups = groups

    def names(self):
        return list(self.groups)

    def read(self, path):
        return self.groups[path]


def game():
    sounds = [(iw_hash(n), b'pcm ' + n.encode()) for n in GERSCH_SOUNDS]
    groups = {
        'ingame/weapons/weapon_projectiles_ascension.group.bin': make_group([
            rtype('CIsEntitySpec', [(GERSCH, projectile_spec(6))]),
            rtype('CIwModel', [(MODEL, b'model'), (iw_hash('unused_model'), b'other')])]),
        'levels/ascension/ascension_statics.group.bin': make_group([
            rtype('CIwSoundData', sounds, names_omitted=0, subclass=iw_hash('CIwSoundDataADPCM'))]),
        'ingame/effects/visualeffects.group.bin': make_group([rtype('CIsEntitySpec', [(SPARK, effect_spec())])]),
        'ingame/ingame.group.bin': make_group([]),
    }
    return groups, (lambda path: groups[path])


class Catalog(unittest.TestCase):
    def test_effects_and_projectiles(self):
        groups, read = game()
        found = {e.hash: e for e in effects.catalog(read, list(groups), {SPARK: 'spark'})}
        self.assertEqual((found[SPARK].kind, found[SPARK].level, found[SPARK].label), ('effect', '', 'spark'))
        self.assertEqual((found[GERSCH].kind, found[GERSCH].level, found[GERSCH].behaviour),
                         ('projectile', 'ascension', 6))
        self.assertEqual(found[GERSCH].key, f'ascension:0x{GERSCH:08x}')


class Project(unittest.TestCase):
    def test_round_trip_and_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            used = [effects.Used('gersch', 'projectile', 'ascension', GERSCH, 6)]
            effects.save(source, used)
            self.assertEqual(effects.load(source), used)
            self.assertEqual(effects.runtime(used), [{'name': 'gersch', 'hash': GERSCH, 'kind': 'projectile',
                                                      'behaviour': 6, 'triggers': ['open']}])
            with self.assertRaises(effects.EffectError):
                effects.save(source, [effects.Used('Bad Name', 'effect', '', 1)])
            effects.save(source, [])
            self.assertEqual(effects.load(source), [])


class Apply(unittest.TestCase):
    def test_a_projectile_of_another_map_comes_with_what_it_uses(self):
        groups, read = game()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            effects.save(source, [effects.Used('gersch', 'projectile', 'ascension', GERSCH, 6),
                                  effects.Used('spark', 'effect', '', SPARK)])
            target = make_group([])
            level = {'weapon_projectiles_mymap.group.bin': target}
            listed = effects.apply(read, source, level, 'mymap', Pack(groups))
            self.assertEqual([e['name'] for e in listed], ['gersch', 'spark'])
            held = {(t.class_hash, r.in_group_hash) for g in level.values() for t in g.types() for r in t.resources}
            self.assertIn((iw_hash('CIsEntitySpec'), GERSCH), held)
            self.assertIn((iw_hash('CIwModel'), MODEL), held)
            self.assertNotIn((iw_hash('CIwModel'), iw_hash('unused_model')), held)

    def test_a_changed_copy_without_model_and_physics(self):
        groups, read = game()
        spec = resources.encode_entity_spec(resources.EntitySpec([
            component('CProjectileEntity'), component('CIsRigidBody'), component('CIsCollisionSphere'),
            component('CIsRenderableModel'), component('CIsTransform')]))
        groups['ingame/weapons/weapon_projectiles_ascension.group.bin'].types()[0].resources[0].body = spec
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            used = effects.Used('gersch', 'projectile', 'ascension', GERSCH, 6, hidden=True, anchored=True)
            effects.save(source, [used])
            self.assertEqual(effects.load(source), [used])
            target = make_group([])
            listed = effects.apply(read, source, {'weapon_projectiles_mymap.group.bin': target}, 'mymap',
                                   Pack(groups))
            own = iw_hash('boz_effect_gersch')
            self.assertEqual(listed[0]['hash'], own)                   # scripts spawn the copy
            body = next(r.body for t in target.types() for r in t.resources if r.in_group_hash == own)
            kept = [c.type_hash for c in resources.decode_entity_spec(body).components]
            self.assertEqual(kept, [iw_hash('CProjectileEntity'), iw_hash('CIsTransform')])
            group.parse(group.encode(target))


if __name__ == '__main__':
    unittest.main()
