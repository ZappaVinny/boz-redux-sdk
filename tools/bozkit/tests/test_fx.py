"""Own effects (synthetic): the emitter codec and its units, checks, materials, state machine
states for extra clips, the extra clip list, the preview."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import anim, fx, fx_preview, gfx, native, weapon_anim  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402


class Emitters(unittest.TestCase):
    def test_round_trip_and_defaults(self):
        body = gfx.encode({})
        self.assertEqual(len(body), gfx.SIZE)
        spec = gfx.decode(body)
        self.assertEqual(spec['frame_time'], 33)
        self.assertEqual(spec['flags'], 0x3)
        self.assertEqual(gfx.encode(spec), body)
        with self.assertRaises(gfx.GfxError):
            gfx.decode(body[:-4])

    def test_units(self):
        self.assertEqual(gfx.shown('life', [4096 * 500, 4096 * 900]), [500.0, 900.0])
        self.assertEqual(gfx.raw('velocity', [0, 1000, 0]), [0, 4096, 0])     # 1000 units/s
        self.assertEqual(gfx.raw('duration', -1), -gfx.ONE)
        self.assertEqual(gfx.shown('angle', [1024, 2048]), [90.0, 180.0])
        self.assertEqual(gfx.flag_names(0x0b), ['additive', 'flag_1', 'fade_out'])

    def test_own_values_to_raw_and_back(self):
        emitter = fx.new_emitter(life=[250, 750], velocity=[0, 120, 0], flags=['fade_out', 'trail'])
        raw = fx.emitter_raw(emitter, iw_hash('mat'))
        self.assertEqual(raw['material'], iw_hash('mat'))
        self.assertEqual(raw['flags'], 0x08 | 0x04)
        back = fx.emitter_from_raw(gfx.decode(gfx.encode(raw)))
        self.assertEqual(back['life'], [250.0, 750.0])
        self.assertAlmostEqual(back['velocity'][1], 120, delta=0.3)

    def test_beam(self):
        body = gfx.encode_beam({'material': 7, 'shorts': [1, 2, 3, 4]})
        self.assertEqual(gfx.decode_beam(body)['shorts'], [1, 2, 3, 4])


class Checks(unittest.TestCase):
    def test_problems(self):
        good = fx.new_effect('glow')
        good['emitters'][0]['texture'] = 'source/fx/glow.png'
        bad = fx.new_effect('Bad Name')
        bad['emitters'][0].update(blend='mix', frames=2, columns=4, life=[0, 10])
        projectile = fx.new_projectile('bolt', 'bolt')
        projectile['pieces'].update(trail='nope', blast={'damage': [1, 2], 'radius': [50, 10]})
        projectile['script'] = 'scripts/projectiles/gone.lua'
        problems = fx.check({'effects': [good, bad, dict(good)], 'projectiles': [projectile]}, Path('/nowhere'))
        for words in ('"Bad Name"', 'pick a texture', 'blend must be', 'frames (1-64)', 'longer than 0',
                      'two effects', '"nope"', 'inner <= outer', 'gone.lua is missing'):
            self.assertTrue(any(words in p for p in problems), (words, problems))

    def test_file(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            self.assertEqual(fx.load(source), {'effects': [], 'projectiles': []})
            fx.save(source, {'effects': [fx.new_effect('a')], 'projectiles': []})
            self.assertEqual(fx.load(source)['effects'][0]['name'], 'a')
            fx.save(source, {'effects': [], 'projectiles': []})
            self.assertFalse((source / fx.FILE).exists())


class Projectiles(unittest.TestCase):
    def test_blank_by_default_and_presets(self):
        self.assertEqual(fx.new_projectile('a')['pieces'], {})
        self.assertEqual(sorted(fx.new_projectile('b', 'bolt')['pieces']), ['blast', 'ribbon'])
        self.assertIn('lure', fx.new_projectile('c', 'lure')['pieces'])
        hole = {'effects': [], 'projectiles': [fx.new_projectile('d', 'black_hole')]}
        self.assertEqual([u.name for u in fx.needs_game(hole)], ['boz_black_hole'])

    def test_effect_pieces(self):
        effect = fx.new_effect('beacon')
        effect['pieces'] = {'lure': {'seconds': 8.0}}
        data = {'effects': [effect], 'projectiles': []}
        self.assertFalse([p for p in fx.check(data) if 'piece' in p or 'seconds' in p])
        effect['pieces'] = {'trail': 'x', 'lure': {'seconds': 0}}
        problems = fx.check(data)
        self.assertTrue(any('unknown pieces trail' in p for p in problems))
        self.assertTrue(any('lure seconds' in p for p in problems))
        effect['pieces'] = {'black_hole': {'seconds': 5.0}}
        self.assertEqual([u.name for u in fx.needs_game(data)], ['boz_black_hole'])

    def test_old_projectiles_become_pieces(self):
        old = {'name': 'bolt', 'damage': [5, 9], 'radius': [10, 20], 'impact': 'boom', 'trail': '',
               'ribbon': {'width': 40}}
        new = fx.upgrade_projectile(old)
        self.assertEqual(new['pieces']['blast'], {'damage': [5, 9], 'radius': [10, 20]})
        self.assertEqual(new['pieces']['impact'], 'boom')
        self.assertEqual(new['pieces']['ribbon']['width'], 40)
        self.assertNotIn('trail', new['pieces'])
        self.assertEqual(new['lifetime'], 5.0)

    def test_script_stubs(self):
        self.assertIn('boz.Projectile:extend("IceBolt")', fx.script_stub('projectile', 'ice_bolt'))
        self.assertIn('boz.Effect:extend("Frost")', fx.script_stub('effect', 'frost'))
        self.assertEqual(fx.script_path('projectile', 'ice_bolt'), 'scripts/projectiles/ice_bolt.lua')


class Materials(unittest.TestCase):
    def test_flipbook_and_blend(self):
        template = native.encode_material(native.Material(False, 0x2000c, b'\0' * 4, [(255,) * 4] * 4,
                                                          [1, 0, 0, 0], b'\x00\x00\xd8113'))
        body = fx.material_body(template, iw_hash('tex'), 'blend', frames=16, columns=4, cell=(64, 64))
        material = native.decode_material(body)
        self.assertEqual((material.flags >> 16) & 7, 4)
        self.assertEqual(material.textures[0], iw_hash('tex'))
        self.assertEqual(list(material.trailer[:7]), [1, 0, 16, 4, 64, 64, 1])
        self.assertEqual(material.trailer[7:], b'\x00\xd8113')
        plain = native.decode_material(fx.material_body(body, iw_hash('tex'), 'add'))
        self.assertEqual(plain.trailer, b'\x00\x00\xd8113')


def state(name, length, events):
    record = struct.pack('<IIIiihIBB', iw_hash(name), 1, 1, 4096, length, 0, 0, 0, 0)
    record += struct.pack('<I', 0) * 3 + struct.pack('<I', len(events))
    for target in events:
        record += struct.pack('<hhhiBB', target, 0, 0, 1, 0, 1)
    return record


def machine():
    states = [state('idle', 0, []), state('reloading', 0, [0]), state('inspect_end', 900, [0])]
    body = struct.pack('<I', len(states))
    for i, record in enumerate(states):
        record = bytearray(record)
        struct.pack_into('<h', record, 20, i)
        body += record
    return body + struct.pack('<II', 1, iw_hash('shoot')) + struct.pack('<I', 0) + struct.pack('<h', 0)


class ExtraClips(unittest.TestCase):
    def test_append_states(self):
        body = machine()
        new = anim.append_states(body, [(iw_hash('charge'), iw_hash('clip'), 700)])
        states, default = anim.decode_asm(new)
        self.assertEqual([s.name for s in states][-1], iw_hash('charge'))
        self.assertEqual(states[-1].anim, iw_hash('clip'))
        spans, end = anim.asm_state_spans(new)
        self.assertEqual(struct.unpack_from('<h', new, spans[-1][1] + 20)[0], 3)   # its own index
        self.assertEqual(struct.unpack_from('<i', new, spans[-1][1] + 16)[0], 700)
        self.assertEqual(new[end:], body[anim.asm_state_spans(body)[1]:])          # triggers kept
        self.assertEqual(default, 0)

    def test_list(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            state_hash = weapon_anim.add_extra_clip(source, 'staff', 'charge', 45)
            self.assertEqual(state_hash, iw_hash('charge'))
            self.assertEqual(weapon_anim.extra_clips(source, 'staff'), [('charge', 45)])
            with self.assertRaises(weapon_anim.WeaponAnimError):
                weapon_anim.add_extra_clip(source, 'staff', 'charge', 10)
            with self.assertRaises(weapon_anim.WeaponAnimError):
                weapon_anim.add_extra_clip(source, 'staff', 'reloading', 10, taken=[iw_hash('reloading')])
            self.assertEqual(weapon_anim.load_clips(source, 'staff'), {})       # the list is not a clip
            weapon_anim.remove_extra_clip(source, 'staff', 'charge')
            self.assertEqual(weapon_anim.extra_clips(source, 'staff'), [])


class Preview(unittest.TestCase):
    def test_simulation(self):
        effect = fx.new_effect('glow')
        effect['emitters'][0].update(spawn_every=[100, 100], life=[2000, 2000], velocity=[0, 100, 0],
                                     velocity_spread=[0, 0, 0], position_spread=[0, 0, 0])
        sim = fx_preview.Simulation(effect)
        for _ in range(10):
            sim.step(100)
        self.assertEqual(len(sim.particles), 11)                 # at 0 ms, then one each 100 ms
        self.assertTrue(all(p.y >= 0 for p in sim.particles))    # rising
        sim.step(1500)
        self.assertTrue(all(p.life > 0 for p in sim.particles))  # the old ones are gone


if __name__ == '__main__':
    unittest.main()
