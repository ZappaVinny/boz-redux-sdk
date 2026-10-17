"""The game's sounds: formats, the ADPCM codec, the slots a project can replace, the processing
that turns an imported recording into a game sound, and the build step that puts it in.

Formats (Ghidra: CIwSoundData::Serialise, CIwSoundDataADPCM::Serialise, CIwSoundSpec::Serialise,
CSoundSequence::Serialise and its commands):

- CIwSoundData: u32 data bytes, u32 sample count, the data, u32 sample rate, u16 format (2 =
  ADPCM); an ADPCM one adds u32 samples per block and u32 block bytes. The game's are mono
  Microsoft IMA ADPCM: blocks of 512 bytes (1017 samples) at 22050 Hz or 256 bytes (505
  samples) at 11025 Hz, each starting with s16 predictor, u8 step index, u8 0.
- CIwSoundSpec (48 bytes): u16 flags, s16 volume min/max, pan min/max, pitch min/max (4096 =
  1.0), s32 x2, u32 x2, u8, u16 polyphony, u8, u16 priority, u32 sound group, u32, u32 the
  CIwSoundData it plays (in the shared group the spec and its data share one hash).
- CSoundSequence: u8, u32 command count, then per command u32 class hash, u32 0 and its fields:
  Play / PlayAsync u32 sound spec, u32 CSoundVariation (one of the two is 0), u8; Delay s32
  milliseconds. Weapon sound fields (fireSoundSequence, ...) name sequences: a reload plays its
  parts in order with waits between them; a shot plays a variation, one take picked at random.
- CSoundVariation: a reflected resource listing the specs it picks from.

A slot is one CIwSoundData of a group the game loads. Replacing it swaps that data (the spec,
its volume and pitch, and everything that plays it stay as they are).
"""
from __future__ import annotations

import json
import math
import re
import struct
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .hashing import iw_hash

DATA = iw_hash('CIwSoundData')
SPEC = iw_hash('CIwSoundSpec')
SEQUENCE = iw_hash('CSoundSequence')
VARIATION = iw_hash('CSoundVariation')
DELAY = iw_hash('CSoundSequenceCommandDelay')
ADPCM = 2
RATES = (22050, 11025)
BLOCK_BYTES = {22050: 512, 11025: 256}
NAME_RE = re.compile(r'[a-z][a-z0-9_]{0,31}')
SHARED_GROUP = 'ingame/ingame.group.bin'
GROUPS = {'shared': 'Shared', 'map': 'This map', 'characters': 'Characters',
          'interface': 'Interface'}


class SoundError(ValueError):
    pass


# --- Formats ----------------------------------------------------------------------------------

@dataclass
class SoundData:
    rate: int
    count: int              # samples, as stored
    data: bytes
    format: int = ADPCM
    block_samples: int = 0
    block_bytes: int = 0

    @property
    def seconds(self) -> float:
        return self.count / self.rate if self.rate else 0.0


def decode_data(body: bytes) -> SoundData:
    size, count = struct.unpack_from('<II', body, 0)
    if 8 + size + 6 > len(body):
        raise SoundError('sound data shorter than its size')
    data = bytes(body[8:8 + size])
    rate, fmt = struct.unpack_from('<IH', body, 8 + size)
    rest = len(body) - (8 + size + 6)
    if rest == 8:
        block_samples, block_bytes = struct.unpack_from('<II', body, 8 + size + 6)
        return SoundData(rate, count, data, fmt, block_samples, block_bytes)
    if rest:
        raise SoundError(f'sound data has {rest} unknown trailing bytes')
    return SoundData(rate, count, data, fmt)


def encode_data(sound: SoundData) -> bytes:
    body = struct.pack('<II', len(sound.data), sound.count) + sound.data + \
        struct.pack('<IH', sound.rate, sound.format)
    if sound.block_bytes:
        body += struct.pack('<II', sound.block_samples, sound.block_bytes)
    return body


@dataclass
class Spec:
    volume: tuple
    pan: tuple
    pitch: tuple
    polyphony: int
    priority: int
    group: int
    data: int


def decode_spec(body: bytes) -> Spec:
    if len(body) < 48:
        raise SoundError('sound spec too short')
    v = struct.unpack_from('<H6h', body, 0)
    polyphony, = struct.unpack_from('<H', body, 31)
    priority, = struct.unpack_from('<H', body, 34)
    group, _unknown, data = struct.unpack_from('<III', body, 36)
    return Spec((v[1] / 4096, v[2] / 4096), (v[3] / 4096, v[4] / 4096),
                (v[5] / 4096, v[6] / 4096), polyphony, priority, group, data)


def decode_sequence(body: bytes) -> list[tuple]:
    """[("play", sound spec or variation hash) | ("delay", ms)] of a CSoundSequence."""
    count, = struct.unpack_from('<I', body, 1)
    p, out = 5, []
    for _ in range(count):
        cls, = struct.unpack_from('<I', body, p)
        p += 8
        if cls == DELAY:
            out.append(('delay', struct.unpack_from('<i', body, p)[0]))
            p += 4
        else:
            spec, variation = struct.unpack_from('<II', body, p)
            out.append(('play', spec or variation))
            p += 9
    if p != len(body):
        raise SoundError('sound sequence: unexpected layout')
    return out


def variation_specs(body: bytes, specs) -> list[int]:
    """The specs a CSoundVariation picks from (its words that name one of *specs*)."""
    words = struct.unpack_from(f'<{len(body) // 4}I', body, 0) if len(body) >= 4 else ()
    found = [w for w in words if w in specs]
    shifted = [struct.unpack_from('<I', body, o)[0] for o in range(1, len(body) - 3)]
    return list(dict.fromkeys(found + [w for w in shifted if w in specs]))


# --- The codec (Microsoft IMA ADPCM, mono) -----------------------------------------------------

STEPS = (7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55,
         60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337,
         371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552,
         1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894,
         6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350,
         22385, 24623, 27086, 29794, 32767)
INDEX = (-1, -1, -1, -1, 2, 4, 6, 8) * 2


def _step(pred: int, index: int, nibble: int) -> tuple[int, int]:
    step = STEPS[index]
    diff = step >> 3
    if nibble & 4:
        diff += step
    if nibble & 2:
        diff += step >> 1
    if nibble & 1:
        diff += step >> 2
    pred = pred - diff if nibble & 8 else pred + diff
    return max(-32768, min(32767, pred)), max(0, min(88, index + INDEX[nibble]))


def samples(sound: SoundData) -> list[int]:
    """The 16-bit samples of a sound (ADPCM, or 16/8-bit PCM)."""
    if sound.format != ADPCM:
        if sound.count and len(sound.data) >= sound.count * 2:
            return list(struct.unpack_from(f'<{sound.count}h', sound.data, 0))
        return [(b - 128) << 8 for b in sound.data[:sound.count]]
    out = []
    size = sound.block_bytes or len(sound.data)
    for offset in range(0, len(sound.data), size):
        block = sound.data[offset:offset + size]
        if len(block) < 4:
            break
        pred, index = struct.unpack_from('<hB', block, 0)
        index = min(88, index)
        out.append(pred)
        for byte in block[4:]:
            for nibble in (byte & 15, byte >> 4):
                pred, index = _step(pred, index, nibble)
                out.append(pred)
    return out[:sound.count]


def _encode_nibble(sample: int, pred: int, index: int) -> int:
    step = STEPS[index]
    diff = sample - pred
    nibble = 0
    if diff < 0:
        nibble, diff = 8, -diff
    if diff >= step:
        nibble |= 4
        diff -= step
    if diff >= step >> 1:
        nibble |= 2
        diff -= step >> 1
    if diff >= step >> 2:
        nibble |= 1
    return nibble


def encode_adpcm(values: list[int], rate: int) -> SoundData:
    """Game sound data for 16-bit mono *values* at *rate* (22050 or 11025)."""
    if rate not in BLOCK_BYTES:
        raise SoundError(f'sample rate {rate}: the game plays {RATES[0]} or {RATES[1]} Hz')
    block_bytes = BLOCK_BYTES[rate]
    block_samples = (block_bytes - 4) * 2 + 1
    values = [max(-32768, min(32767, int(v))) for v in values] or [0]
    padded = values + [0] * (-len(values) % block_samples)
    out = bytearray()
    index = 0
    for start in range(0, len(padded), block_samples):
        block = padded[start:start + block_samples]
        pred = block[0]
        out += struct.pack('<hBB', pred, index, 0)
        nibbles = []
        for sample in block[1:]:
            nibble = _encode_nibble(sample, pred, index)
            pred, index = _step(pred, index, nibble)
            nibbles.append(nibble)
        out += bytes(nibbles[i] | (nibbles[i + 1] << 4) for i in range(0, len(nibbles), 2))
    return SoundData(rate, len(values), bytes(out), ADPCM, block_samples, block_bytes)


def game_quality(values: list[int], rate: int) -> list[int]:
    """*values* as the game will play them: through its ADPCM and back."""
    return samples(encode_adpcm(values, rate))


# --- WAV and processing ------------------------------------------------------------------------

def read_wav(path: Path) -> tuple[list[list[float]], int]:
    """(channels of samples in -1..1, rate) of a PCM WAV file."""
    with wave.open(str(path), 'rb') as w:
        channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), \
            w.getnframes()
        raw = w.readframes(frames)
    if width == 2:
        flat = [v / 32768 for v in struct.unpack(f'<{len(raw) // 2}h', raw)]
    elif width == 1:
        flat = [(b - 128) / 128 for b in raw]
    elif width == 4:
        flat = [v / 2147483648 for v in struct.unpack(f'<{len(raw) // 4}i', raw)]
    elif width == 3:
        flat = [int.from_bytes(raw[i:i + 3], 'little', signed=True) / 8388608
                for i in range(0, len(raw), 3)]
    else:
        raise SoundError(f'{path.name}: {width * 8}-bit WAV is not supported')
    return [flat[c::channels] for c in range(channels)], rate


def write_wav(path: Path, values: list[int], rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f'<{len(values)}h', *values))


@dataclass
class Settings:
    rate: int = 22050
    trim_start: float = 0.0       # seconds cut from the start
    trim_end: float = 0.0         # seconds cut from the end
    gain_db: float = 0.0
    normalize: bool = True        # peak to -1 dB before the gain
    fade_in: float = 0.0          # seconds
    fade_out: float = 0.0


def _resample(values: list[float], source: int, target: int) -> list[float]:
    if source == target or not values:
        return list(values)
    try:
        import numpy
    except ImportError:
        numpy = None
    if numpy is not None:          # the same filter and interpolation, fast (Blender has numpy)
        return _resample_numpy(numpy, values, source, target)
    ratio = target / source
    if ratio < 1:                 # low-pass first (windowed sinc), so nothing folds back
        kernel = _kernel(ratio)
        taps = len(kernel)
        half = taps // 2
        n = len(values)
        values = [sum(kernel[j] * values[i + j - half] for j in range(taps)
                      if 0 <= i + j - half < n) for i in range(n)]
    count = max(1, int(len(values) * ratio))
    out = []
    last = len(values) - 1
    for i in range(count):
        position = i / ratio
        left = min(int(position), last)
        frac = position - left
        right = min(left + 1, last)
        out.append(values[left] * (1 - frac) + values[right] * frac)
    return out


def _kernel(ratio: float) -> list[float]:
    cutoff = 0.45 * ratio
    taps = 31
    half = taps // 2
    kernel = []
    for i in range(taps):
        x = i - half
        sinc = 2 * cutoff if x == 0 else math.sin(2 * math.pi * cutoff * x) / (math.pi * x)
        kernel.append(sinc * (0.54 - 0.46 * math.cos(2 * math.pi * i / (taps - 1))))
    total = sum(kernel)
    return [k / total for k in kernel]


def _resample_numpy(numpy, values, source: int, target: int) -> list[float]:
    array = numpy.asarray(values, dtype=numpy.float64)
    ratio = target / source
    if ratio < 1:
        array = numpy.convolve(array, numpy.asarray(_kernel(ratio)), mode='same')
    count = max(1, int(len(array) * ratio))
    positions = numpy.arange(count) / ratio
    return numpy.interp(positions, numpy.arange(len(array)), array).tolist()


def process(channels: list[list[float]], rate: int, settings: Settings) -> list[int]:
    """16-bit mono samples at settings.rate from imported channels at *rate*."""
    if settings.rate not in BLOCK_BYTES:
        raise SoundError(f'sample rate {settings.rate}: use {RATES[0]} or {RATES[1]} Hz')
    if not channels or not channels[0]:
        raise SoundError('the recording is empty')
    count = min(len(c) for c in channels)
    mono = [sum(c[i] for c in channels) / len(channels) for i in range(count)]
    start = int(max(0.0, settings.trim_start) * rate)
    end = count - int(max(0.0, settings.trim_end) * rate)
    mono = mono[start:max(start, end)]
    if not mono:
        raise SoundError('the trim leaves nothing')
    mono = _resample(mono, rate, settings.rate)
    if settings.normalize:
        peak = max(abs(v) for v in mono)
        if peak > 0:
            target = 10 ** (-1 / 20)
            mono = [v * target / peak for v in mono]
    gain = 10 ** (settings.gain_db / 20)
    fade_in = int(max(0.0, settings.fade_in) * settings.rate)
    fade_out = int(max(0.0, settings.fade_out) * settings.rate)
    n = len(mono)
    out = []
    for i, v in enumerate(mono):
        v *= gain
        if fade_in and i < fade_in:
            v *= i / fade_in
        if fade_out and i >= n - fade_out:
            v *= (n - 1 - i) / fade_out
        out.append(max(-32768, min(32767, int(round(v * 32767)))))
    return out


# --- Project sounds ----------------------------------------------------------------------------
# source/sounds/<name>.json   {"format": 1, "name", "original", "settings": Settings}
# source/sounds/<name>/source.wav   the imported recording (as Blender read it)
# source/sounds/<name>/game.wav     the processed sound (mono, 16-bit, the game's rate)
# source/sounds/slots.json    {slot key: sound name}: the replaced game sounds

@dataclass
class SoundDef:
    name: str
    original: str = ''
    settings: Settings = field(default_factory=Settings)


def sounds_dir(source: Path) -> Path:
    return Path(source) / 'sounds'


def def_path(source: Path, name: str) -> Path:
    return sounds_dir(source) / f'{name}.json'


def source_wav(source: Path, name: str) -> Path:
    return sounds_dir(source) / name / 'source.wav'


def game_wav(source: Path, name: str) -> Path:
    return sounds_dir(source) / name / 'game.wav'


def check_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise SoundError(f'sound name {name!r}: use a-z, 0-9 and _ (at most 32, starting with a '
                         'letter)')


def list_defs(source: Path) -> list[SoundDef]:
    folder = sounds_dir(source)
    if not folder.is_dir():
        return []
    return [load_def(source, p.stem) for p in sorted(folder.glob('*.json')) if p.stem != 'slots']


def load_def(source: Path, name: str) -> SoundDef:
    try:
        data = json.loads(def_path(source, name).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise SoundError(f'sound {name}: {exc}') from None
    known = {f for f in Settings.__dataclass_fields__}
    settings = Settings(**{k: v for k, v in dict(data.get('settings', {})).items() if k in known})
    return SoundDef(str(data.get('name', name)), str(data.get('original', '')), settings)


def save_def(source: Path, sound: SoundDef) -> None:
    check_name(sound.name)
    sounds_dir(source).mkdir(parents=True, exist_ok=True)
    def_path(source, sound.name).write_text(json.dumps(
        {'format': 1, 'name': sound.name, 'original': sound.original,
         'settings': asdict(sound.settings)}, indent=2) + '\n', encoding='utf-8', newline='\n')


def import_recording(source: Path, sound: SoundDef, channels: list[list[float]], rate: int) -> None:
    """Bring a recording in (not usable yet: save() makes its game version)."""
    check_name(sound.name)
    _write_channels(source_wav(source, sound.name), channels, rate)
    game_wav(source, sound.name).unlink(missing_ok=True)
    save_def(source, sound)


def is_saved(source: Path, name: str) -> bool:
    return game_wav(source, name).is_file()


def preview(source: Path, name: str, settings: Settings) -> tuple[list[int], int]:
    """(samples, rate) of a recording with *settings*, as the game will play it."""
    channels, rate = read_wav(source_wav(source, name))
    return game_quality(process(channels, rate, settings), settings.rate), settings.rate


def save(source: Path, sound: SoundDef, channels: list[list[float]] | None = None,
         rate: int = 0) -> list[int]:
    """Save a sound: its settings and its processed game version (from the recording, given
    here or imported before). Returns the processed samples."""
    check_name(sound.name)
    if channels is not None:
        _write_channels(source_wav(source, sound.name), channels, rate)
    channels, rate = read_wav(source_wav(source, sound.name))
    values = process(channels, rate, sound.settings)
    write_wav(game_wav(source, sound.name), values, sound.settings.rate)
    save_def(source, sound)
    return values


def _write_channels(path: Path, channels: list[list[float]], rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = min(len(c) for c in channels)
    frames = bytearray()
    for i in range(count):
        for c in channels:
            frames += struct.pack('<h', max(-32768, min(32767, int(round(c[i] * 32767)))))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def delete(source: Path, name: str) -> None:
    import shutil
    def_path(source, name).unlink(missing_ok=True)
    shutil.rmtree(sounds_dir(source) / name, ignore_errors=True)
    slots = load_slots(source)
    save_slots(source, {k: v for k, v in slots.items() if v != name})


def load_slots(source: Path) -> dict:
    path = sounds_dir(source) / 'slots.json'
    try:
        return dict(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return {}


def save_slots(source: Path, slots: dict) -> None:
    path = sounds_dir(source) / 'slots.json'
    if not slots:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(slots.items())), indent=2) + '\n', encoding='utf-8',
                    newline='\n')


# --- Slots -------------------------------------------------------------------------------------

@dataclass
class Slot:
    key: str                  # "<group path>#<data hash>"
    group: str                # the game group it lives in
    data: int
    category: str             # GROUPS key
    label: str
    seconds: float = 0.0
    rate: int = 0
    users: list = field(default_factory=list)   # what plays it ("Thundergun: Fire", ...)


def slot_key(group_path: str, data_hash: int) -> str:
    return f'{group_path}#0x{data_hash:08x}'


def parse_key(key: str) -> tuple[str, int]:
    path, _, value = key.partition('#')
    return path, int(value, 16)


def sound_groups(names, level: str) -> list[tuple[str, str]]:
    """(group path, category) of the groups holding the sounds a level plays."""
    out = [(SHARED_GROUP, 'shared'), (f'levels/{level}/{level}_statics.group.bin', 'map')]
    out += [(n, 'characters') for n in sorted(names)
            if n.startswith('ingame/sound/snd_player_') and n.endswith('.group.bin')]
    out += [(n, 'interface') for n in ('fixed/fixed.group.bin', 'shared/shared.group.bin')]
    return [(path, category) for path, category in out if path in set(names)]


def _resources(parsed, class_hash: int) -> dict:
    return {r.in_group_hash: r.body for t in parsed.types() if t.class_hash == class_hash
            for r in t.resources}


def _pretty(name: str) -> str:
    return name.replace('_', ' ').strip().capitalize()


def catalog(read, names, level: str, weapons=(), known_names: dict | None = None) -> list[Slot]:
    """Every sound a level plays, labelled by what plays it. *read(path)* gives a group's bytes
    (or a parsed group); *weapons* are bozkit.weapons.GameWeapon-likes (label, values)."""
    from . import group as group_module
    from . import weapons as weapons_module
    known = dict(weapons_module.known_names() if known_names is None else known_names)
    sound_fields = [(f.key, f.label) for f in weapons_module.FIELDS
                    if f.kind == 'sound']
    slots = []
    for path, category in sound_groups(names, level):
        parsed = group_module.read_parsed(read, path)
        data = _resources(parsed, DATA)
        if not data:
            continue
        specs = {h: decode_spec(b) for h, b in _resources(parsed, SPEC).items() if len(b) >= 48}
        variations = {h: variation_specs(b, specs) for h, b in _resources(parsed, VARIATION).items()}

        def datas_of(sound_hash: int) -> list[int]:
            if sound_hash in specs:
                return [specs[sound_hash].data]
            if sound_hash in variations:
                return [specs[s].data for s in variations[sound_hash]]
            return [sound_hash] if sound_hash in data else []

        users = {h: [] for h in data}
        part = {}                       # data -> " part 2 of 4" / " take 1 of 3" (first user)

        def add(label: str, plays: list[list[int]]) -> None:
            """*plays*: per sound played in order, its takes (a variation picks one)."""
            for place, takes in enumerate(plays, 1):
                for take, d in enumerate(takes, 1):
                    if d in users and label not in users[d]:
                        if not users[d]:
                            words = []
                            if len(plays) > 1:
                                words.append(f'part {place} of {len(plays)}')
                            if len(takes) > 1:
                                words.append(f'take {take} of {len(takes)}')
                            part[d] = (' ' + ', '.join(words)) if words else ''
                        users[d].append(label)

        by_field = {}
        for weapon in weapons:
            for key, field_label in sound_fields:
                value = weapon.values.get(key)
                if value:
                    by_field.setdefault(value, []).append(f'{weapon.label}: {field_label}')
        for value, labels in by_field.items():  # one sound for many weapons: the first and a count
            weapons_using = list(dict.fromkeys(label.split(': ', 1)[0] for label in labels))
            if len(weapons_using) > 2:
                fields = list(dict.fromkeys(label.split(': ', 1)[1] for label in labels))
                head = f'{weapons_using[0]} +{len(weapons_using) - 1}'
                by_field[value] = [f'{head}: {f}' for f in fields] + labels
        for h, body in _resources(parsed, SEQUENCE).items():
            try:
                commands = decode_sequence(body)
            except (SoundError, struct.error):
                continue
            plays = [datas_of(value) for kind, value in commands if kind == 'play']
            plays = [takes for takes in plays if takes]
            for label in by_field.get(h, []) + ([_pretty(known[h])] if h in known else []):
                add(label, plays)
        for value, labels in by_field.items():      # fields naming a spec or variation directly
            for label in labels:
                add(label, [datas_of(value)])
        character = path.rsplit('snd_player_', 1)[-1].split('.')[0] if category == 'characters' \
            else ''
        for h, body in data.items():
            try:
                decoded = decode_data(body)
            except (SoundError, struct.error):
                continue
            spec_names = [known[s] for s, spec in specs.items() if spec.data == h and s in known]
            if users[h]:
                label = users[h][0] + part.get(h, '')
            elif h in known or spec_names:
                label = _pretty(known.get(h) or spec_names[0])
            else:
                label = f'0x{h:08x}' if character else f'{GROUPS[category]} 0x{h:08x}'
            if character:
                label = f'{character.capitalize()}: {label}'
            slots.append(Slot(slot_key(path, h), path, h, category, label, decoded.seconds,
                              decoded.rate, users[h]))
    order = list(GROUPS)
    slots.sort(key=lambda s: (order.index(s.category), s.label.lower(), s.key))
    seen = {}
    for slot in slots:                  # two sounds with one label: numbered
        seen[slot.label] = seen.get(slot.label, 0) + 1
        if seen[slot.label] > 1:
            slot.label += f' ({seen[slot.label]})'
    return slots


def original_samples(read, key: str) -> tuple[list[int], int]:
    """(samples, rate) of a slot's original sound."""
    from . import group as group_module
    path, data_hash = parse_key(key)
    parsed = group_module.read_parsed(read, path)
    body = _resources(parsed, DATA).get(data_hash)
    if body is None:
        raise SoundError(f'{path} has no sound 0x{data_hash:08x}')
    decoded = decode_data(body)
    return samples(decoded), decoded.rate


# --- Building ----------------------------------------------------------------------------------

DATA_ADPCM = iw_hash('CIwSoundDataADPCM')
SPEC_SOUND = iw_hash('CIwSoundSpecSound')
PLAY_ASYNC = iw_hash('CSoundSequenceCommandPlayAsync')


def add_resource(parsed, class_hash: int, value: int, body: bytes, subclass: int | None = None) -> None:
    """Put a sound resource in a group the way the game's groups hold them: data and specs name
    their class per resource (CIwSoundDataADPCM, CIwSoundSpecSound), sequences do not."""
    from . import group as group_module
    for resource_type in parsed.types():
        if resource_type.class_hash == class_hash:
            for resource in resource_type.resources:
                if resource.in_group_hash == value:
                    resource.body = body
                    return
            resource_type.resources.append(group_module.Resource(
                subclass if not resource_type.names_omitted else None, value, body))
            return
    for section in parsed.sections:
        if section.types is not None:
            section.types.append(group_module.ResourceType(
                class_hash, 0 if subclass else 1, 1, [group_module.Resource(subclass, value, body)]))
            return
    raise SoundError('the group has no resource section')


def sequence_body(spec_hash: int) -> bytes:
    """A CSoundSequence that plays one sound spec."""
    return b'\0' + struct.pack('<IIIIIB', 1, PLAY_ASYNC, 0, spec_hash, 0, 0)


def first_spec(shared, sequence_hash: int) -> bytes | None:
    """The spec body a sequence of the shared group plays first (its volume, pitch, group)."""
    specs = _resources(shared, SPEC)
    body = _resources(shared, SEQUENCE).get(sequence_hash)
    if body is not None:
        variations = _resources(shared, VARIATION)
        for kind, value in decode_sequence(body):
            if kind != 'play':
                continue
            if value in specs:
                return specs[value]
            if value in variations:
                found = variation_specs(variations[value], specs)
                if found:
                    return specs[found[0]]
    return None


def add_weapon_sound(parsed, shared, weapon: str, field_key: str, original: int,
                     data_body: bytes) -> int:
    """Give a weapon a sound of its own for one field: the sound's data, a spec copied from the
    one its original sequence plays first (else any of the shared group's), and a sequence that
    plays it, all in *parsed* (the map's weapons group). Returns the sequence's hash for the
    field."""
    template = first_spec(shared, original) or next(iter(_resources(shared, SPEC).values()), None)
    if template is None or len(template) < 48:
        raise SoundError('the game has no sound spec to copy')
    base = f'{weapon}_{field_key}'
    sound_hash, sequence_hash = iw_hash(base), iw_hash(f'{base}_seq')
    add_resource(parsed, DATA, sound_hash, data_body, DATA_ADPCM)
    add_resource(parsed, SPEC, sound_hash, template[:44] + struct.pack('<I', sound_hash), SPEC_SOUND)
    add_resource(parsed, SEQUENCE, sequence_hash, sequence_body(sound_hash))
    return sequence_hash


def encoded(source: Path, name: str) -> bytes:
    """A saved sound as game sound data."""
    if not is_saved(source, name):
        raise SoundError(f'sound {name}: not saved yet (Audio tab → Save)')
    channels, rate = read_wav(game_wav(source, name))
    return encode_data(encode_adpcm([int(round(v * 32767)) for v in channels[0]], rate))

def check(source: Path) -> list[str]:
    """Problems that stop a build: slots naming sounds the project does not have."""
    problems = []
    names = {d.name for d in list_defs(source)}
    for key, name in load_slots(source).items():
        if name not in names:
            problems.append(f'sound slot {key}: no sound {name!r} (Sounds tab)')
        elif not game_wav(source, name).is_file():
            problems.append(f'sound {name}: not saved yet (Sounds tab → Save)')
    return problems


def apply(source: Path, read, groups: dict, level: str, map_name: str) -> list[str]:
    """Put the project's replaced sounds in: into the level's own groups (*groups*: file name ->
    parsed group, written into the mod) where they hold the sound, else into a patched copy of
    the game group (added to *groups* by its file name, which the client serves from the mod).
    Returns the file names it patched."""
    from . import group as group_module
    slots = load_slots(source)
    if not slots:
        return []
    problems = check(source)
    if problems:
        raise SoundError('; '.join(problems))
    made = {}
    patched = set()
    renamed = {f'{level}_statics.group.bin': f'{map_name}_statics.group.bin'}
    for key, name in sorted(slots.items()):
        path, data_hash = parse_key(key)
        if name not in made:
            made[name] = encoded(source, name)
        file_name = path.rsplit('/', 1)[-1]
        target = None
        for candidate in (renamed.get(file_name, file_name), file_name):
            found = groups.get(candidate)
            if found is not None and data_hash in _resources(found, DATA):
                target = candidate
                break
        if target is None:
            parsed = group_module.read_parsed(read, path)
            if data_hash not in _resources(parsed, DATA):
                raise SoundError(f'sound slot {key}: the game has no such sound')
            groups[file_name] = parsed
            target = file_name
        for t in groups[target].types():
            if t.class_hash == DATA:
                for r in t.resources:
                    if r.in_group_hash == data_hash:
                        r.body = made[name]
        patched.add(target)
    return sorted(patched)
