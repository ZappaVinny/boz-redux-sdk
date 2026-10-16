"""Map-agnostic assets (synthetic): the registry, closures, clashing names, where things go."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import bundle, group, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

SPEC, SOUND = iw_hash('CIsEntitySpec'), iw_hash('CIwSoundSpec')


def component(name, props=()):
    return resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash(name),
                               [reflect.Blob(iw_hash(name), list(props))])


def hash_prop(owner, name, value):
    return reflect.Property(iw_hash(owner), iw_hash('unsigned int'), iw_hash(name), struct.pack('<I', value))


def spec(*components):
    return resources.encode_entity_spec(resources.EntitySpec(list(components)))


def make_group(types, children=()):
    sections = [group.Section(group.RESOURCES, b'', types)]
    return group.Group(bytes((0x3D, 0, 0, 0, 0, 0)), sections)


def rtype(cls, items):
    return group.ResourceType(iw_hash(cls), 1, 1, [group.Resource(None, h, body) for h, body in items])


class Game:
    """Two maps: the device (a projectile using a sound by data, and one its class plays by name)
    and a model named "Base" in both maps with different bodies."""

    def __init__(self):
        device = spec(component('CProjectileEntity'), component('CThing', [hash_prop('CThing', 'snd', iw_hash('hum'))]))
        prop_a = spec(component('CThing', [hash_prop('CThing', 'model', iw_hash('Base'))]))
        self.files = {
            'ingame/ingame.group.bin': make_group([rtype('CIwSoundSpec', [(iw_hash('click'), b'shared click')])]),
            'shared/shared.group.bin': make_group([]),
            'ingame/effects/visualeffects.group.bin': make_group([]),
            'ingame/weapons/weapon_projectiles_moon.group.bin': make_group([rtype('CIsEntitySpec', [(iw_hash('device'), device)])]),
            'levels/moon/moon_statics.group.bin': make_group([
                rtype('CIwSoundSpec', [(iw_hash('hum'), b'hum data'), (iw_hash('boom'), b'boom data')]),
                rtype('CIwModel', [(iw_hash('Base'), b'moon base model')]),
                rtype('CIsEntitySpec', [(iw_hash('moon_prop'), prop_a)])]),
        }
        self.paths = list(self.files)

    def read(self, path):
        return group.encode(self.files[path])


def registry(game):
    reg = bundle.Registry(game.read, game.paths)
    reg.runtime = {iw_hash('CProjectileEntity'): [iw_hash('boom'), iw_hash('click')]}
    return reg


def map_groups():
    return {'mymap_statics.group.bin': make_group([rtype('CIwModel', [(iw_hash('Base'), b'my own base')])]),
            'weapon_projectiles_mymap.group.bin': make_group([]),
            'weapons_mymap.group.bin': make_group([])}


def held(target):
    return {(t.class_hash, r.in_group_hash): r.body for t in target.types() for r in t.resources}


class Bundles(unittest.TestCase):
    def test_a_projectile_brings_its_data_and_runtime_names(self):
        game = Game()
        groups = map_groups()
        b = bundle.Bundle(registry(game), groups, 'mymap')
        count = b.add([iw_hash('device')])
        projectiles = held(groups['weapon_projectiles_mymap.group.bin'])
        self.assertIn((SPEC, iw_hash('device')), projectiles)            # specs: never the statics
        self.assertIn((SOUND, iw_hash('hum')), projectiles)              # by data
        self.assertIn((SOUND, iw_hash('boom')), projectiles)             # its class plays it by name
        self.assertNotIn((SOUND, iw_hash('click')), projectiles)         # every map has it already
        self.assertEqual(count, 3)
        self.assertEqual(b.add([iw_hash('device')]), 0)                  # already there

    def test_already_in_the_map_still_brings_what_it_uses(self):
        game = Game()
        groups = map_groups()
        device = game.files['ingame/weapons/weapon_projectiles_moon.group.bin'].types()[0].resources[0]
        groups['weapon_projectiles_mymap.group.bin'].sections[0].types.append(
            group.ResourceType(SPEC, 1, 1, [group.Resource(None, device.in_group_hash, device.body)]))
        b = bundle.Bundle(registry(game), groups, 'mymap')
        b.add([iw_hash('device')])               # another step copied the spec alone
        projectiles = held(groups['weapon_projectiles_mymap.group.bin'])
        self.assertIn((SOUND, iw_hash('boom')), projectiles)
        self.assertIn((SOUND, iw_hash('hum')), projectiles)

    def test_a_clashing_name_gets_its_own(self):
        game = Game()
        groups = map_groups()
        b = bundle.Bundle(registry(game), groups, 'mymap')
        b.add([iw_hash('moon_prop')], prefer='levels/moon/moon_statics.group.bin')
        statics = held(groups['mymap_statics.group.bin'])
        new = iw_hash('boz_moon_statics_%08x' % iw_hash('Base'))
        self.assertEqual(statics[(iw_hash('CIwModel'), iw_hash('Base'))], b'my own base')   # untouched
        everything = {}
        for target in groups.values():
            everything.update(held(target))
        self.assertEqual(everything[(iw_hash('CIwModel'), new)], b'moon base model')
        copied = held(groups['weapon_projectiles_mymap.group.bin'])[(SPEC, iw_hash('moon_prop'))]
        self.assertIn(struct.pack('<I', new), copied)                    # the prop uses the renamed one
        self.assertNotIn(struct.pack('<I', iw_hash('Base')), copied)
        for target in groups.values():
            group.parse(group.encode(target))

    def test_script_names(self):
        import tempfile
        game = Game()
        reg = registry(game)
        with tempfile.TemporaryDirectory() as temp:
            scripts = Path(temp)
            (scripts / 'main.lua').write_text('effects.projectile("device", p)\n'
                                              f'effects.spawn("0x{iw_hash("moon_prop"):08x}", p)\nlog("hello")\n')
            (scripts / 'boz').mkdir()
            (scripts / 'boz' / 'x.lua').write_text('"device_never"')
            self.assertEqual(bundle.script_names(scripts, reg), [iw_hash('device'), iw_hash('moon_prop')])

    def test_library_calls(self):
        import tempfile
        from unittest import mock
        reg = registry(Game())
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(bundle.LIBRARY_CALLS, {'spawn_prop': ['moon_prop']}):
            scripts = Path(temp)
            (scripts / 'main.lua').write_text('zombies.spawn_prop(p)\n')
            self.assertEqual(bundle.script_names(scripts, reg), [iw_hash('moon_prop')])


if __name__ == '__main__':
    unittest.main()
