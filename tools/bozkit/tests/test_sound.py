"""Game sounds (synthetic): formats, the ADPCM codec, processing, project sounds, slots, build."""
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import group, sound  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402


def tone(seconds=0.2, rate=22050, freq=440.0, level=0.5):
    return [int(level * 32767 * math.sin(2 * math.pi * freq * i / rate))
            for i in range(int(seconds * rate))]


def snr(a, b):
    err = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
    sig = sum(x * x for x in a) / len(a)
    return 10 * math.log10(sig / max(err, 1e-9))


def spec_body(data_hash, group_hash=0x1234):
    body = struct.pack('<H6h', 0, 4096, 4096, 0, 0, 4096, 4096) + struct.pack('<iiII', 100, 6144, 1, 0)
    body += bytes([0]) + struct.pack('<H', 3) + bytes([0]) + struct.pack('<H', 100)
    return body + struct.pack('<III', group_hash, 0, data_hash)


def sequence_body(commands):
    out = bytearray(b'\0') + struct.pack('<I', len(commands))
    for kind, value in commands:
        if kind == 'delay':
            out += struct.pack('<IIi', sound.DELAY, 0, value)
        else:
            out += struct.pack('<IIIIB', iw_hash('CSoundSequenceCommandPlayAsync'), 0, value, 0, 0)
    return bytes(out)


def make_group(types):
    return group.Group(bytes((0x3D, 0, 0, 0, 0, 0)), [group.Section(group.RESOURCES, b'', types)])


def rtype(class_hash, items):
    return group.ResourceType(class_hash, 1, 1, [group.Resource(None, h, body) for h, body in items])


class Formats(unittest.TestCase):
    def test_data_round_trip_and_layout(self):
        data = sound.encode_adpcm(tone(), 22050)
        body = sound.encode_data(data)
        self.assertEqual(struct.unpack_from('<II', body, 0), (len(data.data), data.count))
        self.assertEqual(struct.unpack_from('<IHII', body, 8 + len(data.data)), (22050, 2, 1017, 512))
        self.assertEqual(sound.encode_data(sound.decode_data(body)), body)
        self.assertEqual(len(data.data) % 512, 0)
        small = sound.encode_adpcm(tone(rate=11025), 11025)
        self.assertEqual((small.block_samples, small.block_bytes), (505, 256))

    def test_codec_quality(self):
        values = tone()
        back = sound.game_quality(values, 22050)
        self.assertEqual(len(back), len(values))
        self.assertGreater(snr(values, back), 25)
        with self.assertRaises(sound.SoundError):
            sound.encode_adpcm(values, 44100)

    def test_spec_and_sequence(self):
        spec = sound.decode_spec(spec_body(0xabcdef01))
        self.assertEqual((spec.volume, spec.pitch, spec.polyphony, spec.priority, spec.data),
                         ((1.0, 1.0), (1.0, 1.0), 3, 100, 0xabcdef01))
        commands = [('delay', 0), ('play', 7), ('delay', 300), ('play', 9)]
        self.assertEqual(sound.decode_sequence(sequence_body(commands)), commands)


class Processing(unittest.TestCase):
    def test_mixdown_trim_resample_normalize_fade(self):
        rate = 44100
        left = [0.25 * math.sin(i / 10) for i in range(rate)]
        right = [-v for v in left]
        settings = sound.Settings(rate=11025, trim_start=0.25, trim_end=0.25, normalize=True)
        out = sound.process([left, [0.5 * v for v in left]], rate, settings)
        self.assertAlmostEqual(len(out), 11025 // 2, delta=2)
        self.assertAlmostEqual(max(abs(v) for v in out) / 32767, 10 ** (-1 / 20), delta=0.02)
        silent = sound.process([left, right], rate, sound.Settings(normalize=False))
        self.assertEqual(max(abs(v) for v in silent), 0)       # opposite channels cancel
        faded = sound.process([left], rate, sound.Settings(fade_in=0.1, fade_out=0.1))
        self.assertEqual(faded[0], 0)
        self.assertLess(abs(faded[-1]), 50)
        with self.assertRaises(sound.SoundError):
            sound.process([left], rate, sound.Settings(trim_start=0.6, trim_end=0.6))


    def test_resampling_without_numpy_matches(self):
        values = [math.sin(i / 3) for i in range(2000)]
        fast = sound._resample(values, 44100, 11025)
        saved = sys.modules.get('numpy')
        sys.modules['numpy'] = None             # import numpy now fails
        try:
            slow = sound._resample(values, 44100, 11025)
        finally:
            if saved is None:
                del sys.modules['numpy']
            else:
                sys.modules['numpy'] = saved
        self.assertEqual(len(fast), len(slow))
        self.assertLess(max(abs(a - b) for a, b in zip(fast, slow)), 1e-6)


class Project(unittest.TestCase):
    def test_sounds_and_slots(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            channels = [[0.5 * math.sin(i / 7) for i in range(22050)]]
            values = sound.save(source, sound.SoundDef('roar', 'roar.ogg', sound.Settings(rate=11025)),
                                channels, 22050)
            self.assertAlmostEqual(len(values), 11025, delta=2)
            loaded = sound.list_defs(source)
            self.assertEqual([(d.name, d.original, d.settings.rate) for d in loaded], [('roar', 'roar.ogg', 11025)])
            back, rate = sound.read_wav(sound.game_wav(source, 'roar'))
            self.assertEqual((rate, len(back)), (11025, 1))
            key = sound.slot_key(sound.SHARED_GROUP, 0x10)
            sound.save_slots(source, {key: 'roar'})
            self.assertEqual(sound.check(source), [])
            sound.save_slots(source, {key: 'missing'})
            self.assertTrue(sound.check(source))
            sound.save_slots(source, {key: 'roar'})
            sound.delete(source, 'roar')
            self.assertEqual((sound.list_defs(source), sound.load_slots(source)), ([], {}))
            with self.assertRaises(sound.SoundError):
                sound.check_name('Bad Name')


class Slots(unittest.TestCase):
    def game(self):
        data_a = sound.encode_data(sound.encode_adpcm(tone(0.1), 22050))
        data_b = sound.encode_data(sound.encode_adpcm(tone(0.3, 11025), 11025))
        shared = make_group([
            rtype(sound.DATA, [(0xa, data_a), (0xb, data_b)]),
            rtype(sound.SPEC, [(0x1a, spec_body(0xa)), (0x1b, spec_body(0xb))]),
            rtype(sound.SEQUENCE, [(0x50, sequence_body([('delay', 0), ('play', 0x1a), ('delay', 100),
                                                         ('play', 0x1b)]))]),
        ])
        statics = make_group([rtype(sound.DATA, [(0xc, data_a)])])
        groups = {sound.SHARED_GROUP: shared, 'levels/kino/kino_statics.group.bin': statics}
        return groups, (lambda path: groups[path])

    def test_catalog_labels(self):
        groups, read = self.game()

        class Weapon:
            label, values = 'Ray Gun', {'fireSoundSequence': 0x50}
        slots = sound.catalog(read, list(groups), 'kino', [Weapon()], {})
        by_data = {s.data: s for s in slots}
        self.assertEqual(by_data[0xa].label, 'Ray Gun: Fire part 1 of 2')
        self.assertEqual(by_data[0xb].label, 'Ray Gun: Fire part 2 of 2')
        self.assertEqual((by_data[0xb].rate, round(by_data[0xb].seconds, 1)), (11025, 0.3))
        self.assertEqual(by_data[0xc].category, 'map')
        values, rate = sound.original_samples(read, by_data[0xa].key)
        self.assertEqual((rate, len(values)), (22050, 2205))

    def test_build_patches_level_and_game_groups(self):
        groups, read = self.game()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            sound.save(source, sound.SoundDef('beep'), [[0.3 * math.sin(i / 5) for i in range(4410)]], 22050)
            sound.save_slots(source, {sound.slot_key(sound.SHARED_GROUP, 0xa): 'beep',
                                      sound.slot_key('levels/kino/kino_statics.group.bin', 0xc): 'beep'})
            level = {'mymap_statics.group.bin': make_group([rtype(sound.DATA, [(0xc, b'old')])])}
            patched = sound.apply(source, read, level, 'kino', 'mymap')
            self.assertEqual(patched, ['ingame.group.bin', 'mymap_statics.group.bin'])
            body = sound._resources(level['ingame.group.bin'], sound.DATA)[0xa]
            self.assertEqual(sound.decode_data(body).count, 4410)
            self.assertEqual(sound._resources(level['mymap_statics.group.bin'], sound.DATA)[0xc], body)
            self.assertNotEqual(sound._resources(level['ingame.group.bin'], sound.DATA)[0xb], body)
            sound.save_slots(source, {sound.slot_key(sound.SHARED_GROUP, 0x99): 'beep'})
            with self.assertRaises(sound.SoundError):
                sound.apply(source, read, {}, 'kino', 'mymap')


class WeaponSounds(unittest.TestCase):
    def test_direct_weapon_fields_use_specs_not_sequences(self):
        data = sound.encode_data(sound.encode_adpcm(tone(0.1), 22050))
        original = spec_body(0xa, group_hash=0x777)
        shared = make_group([rtype(sound.SPEC, [(0x1a, original)])])
        weapons_group = make_group([])
        for key in ('buySound', 'playerBuySound', 'fireEmptySound'):
            value = sound.add_weapon_sound(weapons_group, shared, 'idgun', key, 0x1a, data)
            self.assertEqual(value, iw_hash(f'idgun_{key}'))
            self.assertNotIn(value, sound._resources(weapons_group, sound.SEQUENCE))
            new_spec = sound._resources(weapons_group, sound.SPEC)[value]
            self.assertEqual(new_spec[:44], original[:44])
            self.assertEqual(sound.decode_spec(new_spec).data, value)
        self.assertEqual(sound._resources(weapons_group, sound.SEQUENCE), {})

    def test_a_weapon_gets_its_own_sequence(self):
        data = sound.encode_data(sound.encode_adpcm(tone(0.1), 22050))
        shared = make_group([
            rtype(sound.DATA, [(0xa, data)]),
            rtype(sound.SPEC, [(0x1a, spec_body(0xa, group_hash=0x777))]),
            rtype(sound.SEQUENCE, [(0x50, sequence_body([('delay', 100), ('play', 0x1a)]))]),
        ])
        weapons_group = make_group([rtype(iw_hash('CIwModel'), [(0x1, b'model')])])
        mine = sound.encode_data(sound.encode_adpcm(tone(0.5), 11025))
        sequence = sound.add_weapon_sound(weapons_group, shared, 'idgun', 'reloadSoundSequence', 0x50, mine)
        self.assertEqual(sequence, iw_hash('idgun_reloadSoundSequence_seq'))
        own = iw_hash('idgun_reloadSoundSequence')
        self.assertEqual(sound.decode_sequence(sound._resources(weapons_group, sound.SEQUENCE)[sequence]),
                         [('play', own)])
        spec = sound.decode_spec(sound._resources(weapons_group, sound.SPEC)[own])
        self.assertEqual((spec.data, spec.group), (own, 0x777))     # the original's settings
        self.assertEqual(sound._resources(weapons_group, sound.DATA)[own], mine)
        data_type = next(t for t in weapons_group.types() if t.class_hash == sound.DATA)
        self.assertEqual((data_type.names_omitted, data_type.resources[0].name_hash), (0, sound.DATA_ADPCM))
        self.assertEqual(sound._resources(shared, sound.SEQUENCE)[0x50][:5], b'\0\2\0\0\0')   # untouched
        back = group.parse(group.encode(weapons_group))
        self.assertEqual(sound._resources(back, sound.SPEC)[own][-4:], struct.pack('<I', own))


if __name__ == '__main__':
    unittest.main()
