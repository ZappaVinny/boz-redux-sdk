"""Particle emitters (CIwGFXEmitterSpec): decode, encode and what every field means.

An effect is an entity spec whose CIsRenderableGFXEmitter names an emitter spec (its
``emitterSpec`` hash) and scales it (``effectScale``). The emitter specs are their own resources
(the shared ingame group holds 159, Dead Ops' 45). Ghidra: CIwGFXSpec::Serialise (0x4a0ca30e),
CIwGFXEmitterSpec::Serialise (0x4a0c7876), constructor defaults (0x4a0c8cb4); the emitter
(CIwGFXEmitter) spawns particles (0x4a0c89fc) on a timer (vf21) or along the path it moves
(vf22, the "trail" flag), moves them (vf23) and draws them (vf18).

The body is 35 little-endian words in serialise order. Positions are plain units; times
are 20.12 fixed-point milliseconds (4096 = 1 ms); velocities are units per ms in 20.12; angles are
the engine's (4096 = a full turn). Values are
kept raw so a decode/encode round trip is exact; FIELDS says how to show each one.

How a particle lives:
- spawned every "spawn every" ms (a random time between min and max), or, with the trail flag,
  one per "spawn every" units the emitter moved; for "duration" ms (-1: for as long as the
  effect lives);
- at the position (+ a random offset up to the spread on each axis) with the velocity (+ spread),
  both times the effect's scale, in the emitter's space (world: turned with the emitter);
- lives a random time between life min and max; moves by its velocity, which gravity changes;
  spins by its spin speed from its start angle; grows by "growth" per ms;
- with "fade out", fades as it ages; drawn as a camera-facing sprite (or a cross or a streak
  along its velocity) with the material's texture; the texture's frames step by the emitter's
  age, the particle's age or a fixed frame time.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .hashing import iw_hash

EMITTER_SPEC = iw_hash('CIwGFXEmitterSpec')
WORDS = 35
SIZE = WORDS * 4
ONE = 4096                    # 20.12 fixed point
TURN = 4096                   # engine angle units in a full turn


class GfxError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    name: str
    word: int          # first word in the body
    count: int         # words (3 for a vector, 2 for a min/max pair)
    kind: str          # 'int', 'uint', 'fixed', 'float', 'hash', 'flags', 'enum'
    label: str
    unit: str
    help: str
    scale: float = 1.0           # raw -> shown (shown = raw * scale)


SPACES = {0: 'World (turns with the effect)', 1: 'Camera', 2: 'Untransformed'}
SHAPES = {0: 'Sprite (camera-facing quad)', 1: 'Cross', 2: 'Streak (along its velocity)'}
FRAME_MODES = {0: "Over the emitter's duration", 1: "Over the particle's life", 2: 'Fixed frame time'}
# Flag bits (+0x20): the constructor sets 0x3.
FLAGS = {
    0x01: ('additive', 'Its own blending state (the material decides; on in the game\'s effects)'),
    0x02: ('flag_1', 'Set by default; not read by the emitter'),
    0x04: ('trail', 'Spawn along the path the effect moves (one per "spawn every" units) instead '
                    'of on a timer'),
    0x08: ('fade_out', 'Fade particles out as they age (by their life)'),
    0x10: ('face_camera', 'Turn sprites to face the camera (else they lie in the emitter\'s plane)'),
    0x20: ('upright', 'Sprites stand in the vertical plane (with face camera off)'),
    0x40: ('prewarm', 'Start each particle slightly back along its path (gravity included)'),
}

FIELDS = [
    Field('space', 0, 1, 'enum', 'Space', '', 'Where particles live: world space (spawned turned and '
          'moved with the effect), camera space, or untransformed'),
    Field('order', 1, 1, 'int', 'Order', '', 'Kept as the game has it (not read by the emitter)'),
    Field('material', 2, 1, 'hash', 'Material', 'material name', 'The CIwMaterial (texture, blend) '
          'particles are drawn with'),
    Field('flags', 3, 1, 'flags', 'Flags', '', 'See FLAGS'),
    Field('shape', 4, 1, 'enum', 'Shape', '', 'How a particle is drawn'),
    Field('duration', 5, 1, 'fixed', 'Duration', 'ms', 'How long the emitter spawns (-1: as long as '
          'the effect lives)', 1 / ONE),
    Field('size_scale', 6, 1, 'fixed', 'Size x', 'x', 'Every sprite\'s size times this', 1 / ONE),
    Field('position', 7, 3, 'fixed', 'Position', 'units', 'Where particles start (from the effect)'),
    Field('position_spread', 10, 3, 'fixed', 'Position spread', 'units', 'Up to this much further on '
          'each axis, at random'),
    Field('velocity', 13, 3, 'fixed', 'Velocity', 'units/s', 'How fast particles start moving',
          1000 / ONE),
    Field('velocity_spread', 16, 3, 'fixed', 'Velocity spread', 'units/s', 'Up to this much more on '
          'each axis, at random', 1000 / ONE),
    Field('gravity', 19, 3, 'fixed', 'Gravity', 'units/s²', 'Changes the velocity every moment '
          '(negative z falls)', 1_000_000 / (ONE * ONE)),
    Field('life', 22, 2, 'fixed', 'Life', 'ms', 'How long a particle lives (min, max)', 1 / ONE),
    Field('size', 24, 2, 'float', 'Size', 'units', 'A particle\'s size when spawned (min, max)'),
    Field('spin', 26, 2, 'fixed', 'Spin', '°/s', 'How fast it turns (min, max)',
          360 * 1000 / (ONE * TURN)),
    Field('angle', 28, 2, 'fixed', 'Start angle', '°', 'Its angle when spawned (min, max)',
          360 / TURN),
    Field('spawn_every', 30, 2, 'fixed', 'Spawn every', 'ms (trail: units)', 'Time between '
          'particles (min, max); with trail, the distance', 1 / ONE),
    Field('growth', 32, 1, 'fixed', 'Growth', 'units/s', 'How fast a particle grows', 1000 / ONE),
    Field('frame_mode', 33, 1, 'enum', 'Texture frames', '', 'How an animated texture steps'),
    Field('frame_time', 34, 1, 'uint', 'Frame time', 'ms', 'Each frame\'s time (fixed frame time)'),
]
FIELD = {f.name: f for f in FIELDS}
ENUMS = {'space': SPACES, 'shape': SHAPES, 'frame_mode': FRAME_MODES}

# CIwGFXEmitterSpec::CIwGFXEmitterSpec: what an unset field is.
DEFAULTS = {'space': 1, 'order': 0, 'material': 0, 'flags': 0x3, 'shape': 0, 'duration': 0,
            'size_scale': ONE, 'position': [0, 0, 0], 'position_spread': [0, 0, 0],
            'velocity': [0, 0, 0], 'velocity_spread': [0, 0, 0], 'gravity': [0, 0, 0],
            'life': [0, 0], 'size': [0.0, 0.0], 'spin': [0, 0], 'angle': [0, 0],
            'spawn_every': [0, 0], 'growth': 0, 'frame_mode': 2, 'frame_time': 33}


def decode(body: bytes) -> dict:
    """An emitter spec body as {field: raw value} (vectors and pairs as lists)."""
    if len(body) != SIZE:
        raise GfxError(f'an emitter spec is {SIZE} bytes, not {len(body)}')
    out = {}
    for f in FIELDS:
        if f.kind == 'float':
            values = list(struct.unpack_from(f'<{f.count}f', body, f.word * 4))
        else:
            code = 'I' if f.kind in ('uint', 'hash', 'flags') else 'i'
            values = list(struct.unpack_from(f'<{f.count}{code}', body, f.word * 4))
        out[f.name] = values if f.count > 1 else values[0]
    return out


def encode(spec: dict) -> bytes:
    """The body of an emitter spec (missing fields take the game's defaults)."""
    words = bytearray(SIZE)
    for f in FIELDS:
        value = spec.get(f.name, DEFAULTS[f.name])
        values = list(value) if f.count > 1 else [value]
        if len(values) != f.count:
            raise GfxError(f'{f.name} needs {f.count} values')
        if f.kind == 'float':
            struct.pack_into(f'<{f.count}f', words, f.word * 4, *map(float, values))
        else:
            code = 'I' if f.kind in ('uint', 'hash', 'flags') else 'i'
            mask = 0xffffffff
            values = [int(v) & mask if code == 'I' else _signed(int(v)) for v in values]
            struct.pack_into(f'<{f.count}{code}', words, f.word * 4, *values)
    return bytes(words)


def _signed(value: int) -> int:
    value &= 0xffffffff
    return value - (1 << 32) if value >= 1 << 31 else value


def shown(name: str, raw):
    """A raw value in the field's unit (lists stay lists)."""
    f = FIELD[name]
    if f.kind in ('fixed',):
        if isinstance(raw, list):
            return [round(v * f.scale, 4) for v in raw]
        return -1 if (name == 'duration' and raw < 0) else round(raw * f.scale, 4)
    return raw


def raw(name: str, value):
    """A value in the field's unit back to raw."""
    f = FIELD[name]
    if f.kind == 'fixed':
        if isinstance(value, (list, tuple)):
            return [int(round(v / f.scale)) for v in value]
        if name == 'duration' and value < 0:
            return -ONE
        return int(round(value / f.scale))
    if f.kind == 'float':
        return [float(v) for v in value] if isinstance(value, (list, tuple)) else float(value)
    return value


def flag_names(flags: int) -> list[str]:
    return [name for bit, (name, _help) in FLAGS.items() if flags & bit]


def describe(spec: dict) -> dict:
    """The spec in its fields' units, with enums and flags named (for people and the editor)."""
    out = {}
    for f in FIELDS:
        value = spec[f.name]
        if f.kind == 'enum':
            out[f.name] = ENUMS[f.name].get(value, f'unknown ({value})')
        elif f.kind == 'flags':
            out[f.name] = flag_names(value)
        else:
            out[f.name] = shown(f.name, value)
    return out


# Beams (CIwGFXBeamSpec, Serialise 0x4a0c7100): the engine has them, no shipped effect uses one
# and no component draws one from an entity spec, so they are here for use from code only:
# the CIwGFXSpec words (space, order, material, flags), then an int and four 16-bit values.
BEAM_SPEC = iw_hash('CIwGFXBeamSpec')
BEAM_SIZE = 28


def decode_beam(body: bytes) -> dict:
    if len(body) != BEAM_SIZE:
        raise GfxError(f'a beam spec is {BEAM_SIZE} bytes, not {len(body)}')
    space, order, material, flags, value = struct.unpack_from('<iiIIi', body, 0)
    shorts = list(struct.unpack_from('<4h', body, 20))
    return {'space': space, 'order': order, 'material': material, 'flags': flags, 'value': value,
            'shorts': shorts}


def encode_beam(spec: dict) -> bytes:
    return struct.pack('<iiIIi4h', int(spec.get('space', 1)), int(spec.get('order', 0)),
                       int(spec.get('material', 0)) & 0xffffffff, int(spec.get('flags', 3)) & 0xffffffff,
                       int(spec.get('value', 0)), *[int(v) for v in (list(spec.get('shorts', [])) + [0] * 4)[:4]])
