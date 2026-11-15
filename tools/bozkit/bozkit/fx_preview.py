"""A preview of an own effect (bozkit.fx) the way the game runs it (bozkit.gfx; Ghidra: the
emitter's spawn 0x4a0c89fc, update vf23, draw vf18), drawn from the side (x right, y up) into
an RGBA image. Approximate: no camera facing, no world turning; enough to see shape, timing,
colour and size."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path



@dataclass
class Particle:
    emitter: int
    life: float          # ms left
    total: float         # ms it lives
    x: float
    y: float
    z: float
    vx: float            # units per ms
    vy: float
    vz: float
    size: float          # units
    angle: float         # degrees
    spin: float          # degrees per ms


class Simulation:
    """Runs an effect's emitters over time (ms)."""

    def __init__(self, effect: dict, seed: int = 1):
        self.effect = effect
        self.random = random.Random(seed)
        self.particles: list[Particle] = []
        self.time = 0.0
        self.timers = [0.0 for _ in effect.get('emitters', [])]
        self.origin = [0.0, 0.0, 0.0]      # where the effect is (moving: it circles)
        self.travelled = 0.0

    def _between(self, pair) -> float:
        low, high = float(pair[0]), float(pair[1])
        return low + (high - low) * self.random.random() if high > low else low

    def _spawn(self, index: int, emitter: dict) -> None:
        scale = float(self.effect.get('scale', 1.0))
        p = [float(v) for v in emitter.get('position', [0, 0, 0])]
        ps = [float(v) for v in emitter.get('position_spread', [0, 0, 0])]
        v = [float(c) for c in emitter.get('velocity', [0, 0, 0])]
        vs = [float(c) for c in emitter.get('velocity_spread', [0, 0, 0])]
        pos = [self.origin[i] + p[i] + ps[i] * (2 * self.random.random() - 1) for i in range(3)]
        vel = [(v[i] + vs[i] * (2 * self.random.random() - 1)) * scale / 1000 for i in range(3)]
        life = self._between(emitter.get('life', [500, 500]))
        size = self._between(emitter.get('size', [10, 10])) * scale * float(emitter.get('size_scale', 1.0))
        self.particles.append(Particle(index, life, life, *pos, *vel, size,
                                       self._between(emitter.get('angle', [0, 0])),
                                       self._between(emitter.get('spin', [0, 0])) / 1000))

    def step_moving(self, ms: float, radius: float = 150.0, speed: float = 300.0) -> None:
        """A step with the effect moving round a circle (units, units a second): trails show as
        they do behind a projectile."""
        self.travelled += speed * ms / 1000
        angle = self.travelled / radius
        self.origin = [radius * math.cos(angle), 0.0, radius * math.sin(angle)]
        self.step(ms)

    def step(self, ms: float) -> None:
        self.time += ms
        for i, emitter in enumerate(self.effect.get('emitters', [])):
            duration = float(emitter.get('duration', -1))
            if duration >= 0 and self.time > duration:
                continue
            self.timers[i] -= ms
            guard = 0
            while self.timers[i] <= 0 and guard < 200:
                self._spawn(i, emitter)
                self.timers[i] += max(1.0, self._between(emitter.get('spawn_every', [50, 50])))
                guard += 1
        scale = float(self.effect.get('scale', 1.0))
        alive = []
        for particle in self.particles:
            emitter = self.effect['emitters'][particle.emitter]
            g = [float(c) / 1_000_000 for c in emitter.get('gravity', [0, 0, 0])]
            particle.vx += g[0] * ms * scale
            particle.vy += g[1] * ms * scale
            particle.vz += g[2] * ms * scale
            particle.x += particle.vx * ms
            particle.y += particle.vy * ms
            particle.z += particle.vz * ms
            particle.size = max(0.0, particle.size + float(emitter.get('growth', 0)) / 1000 * ms * scale)
            particle.angle += particle.spin * ms
            particle.life -= ms
            if particle.life > 0:
                alive.append(particle)
        self.particles = alive


def alpha_of(particle: Particle, emitter: dict) -> float:
    """The game fades a particle once it has less than its emitter's shortest life left."""
    if 'fade_out' not in emitter.get('flags', []):
        return 1.0
    shortest = float(emitter.get('life', [1, 1])[0]) or 1.0
    return max(0.0, min(1.0, particle.life / shortest))


def frame_of(particle: Particle, emitter: dict, time: float) -> int:
    frames = int(emitter.get('frames', 1))
    if frames <= 1:
        return 0
    mode = int(emitter.get('frame_mode', 2))
    if mode == 1:                               # over the particle's life
        return min(frames - 1, int((1 - particle.life / particle.total) * frames))
    if mode == 0:                               # over the emitter's duration
        duration = float(emitter.get('duration', -1))
        return min(frames - 1, int(time / duration * frames)) if duration > 0 else 0
    return int(time / max(1, int(emitter.get('frame_time', 33)))) % frames


def render(sim: Simulation, sprites: list, size: int = 256, span: float = 300.0):
    """The particles as an RGBA uint8 image (numpy) of size x size showing span units across.
    *sprites*: per emitter, a list of frame images (PIL RGBA, tinted)."""
    import numpy
    canvas = numpy.zeros((size, size, 3), dtype=numpy.float32)
    alpha_canvas = numpy.zeros((size, size), dtype=numpy.float32)
    per_unit = size / span
    for particle in sorted(sim.particles, key=lambda p: p.z):
        emitter = sim.effect['emitters'][particle.emitter]
        frames = sprites[particle.emitter] if particle.emitter < len(sprites) else []
        if not frames:
            continue
        side = max(1, int(particle.size * 2 * per_unit))
        if side > size * 2:
            continue
        sprite = frames[frame_of(particle, emitter, sim.time) % len(frames)].resize((side, side))
        if particle.angle:
            sprite = sprite.rotate(-particle.angle)
        pixels = numpy.asarray(sprite, dtype=numpy.float32) / 255.0
        cx = int(size / 2 + particle.x * per_unit)
        cy = int(size * 0.75 - particle.y * per_unit)
        x0, y0 = cx - side // 2, cy - side // 2
        x1, y1 = max(0, x0), max(0, y0)
        x2, y2 = min(size, x0 + side), min(size, y0 + side)
        if x1 >= x2 or y1 >= y2:
            continue
        part = pixels[y1 - y0:y2 - y0, x1 - x0:x2 - x0]
        a = part[..., 3:4] * alpha_of(particle, emitter)
        if emitter.get('blend', 'add') == 'add':
            canvas[y1:y2, x1:x2] += part[..., :3] * a
        else:
            canvas[y1:y2, x1:x2] = canvas[y1:y2, x1:x2] * (1 - a) + part[..., :3] * a
        alpha_canvas[y1:y2, x1:x2] = numpy.maximum(alpha_canvas[y1:y2, x1:x2], a[..., 0])
    out = numpy.zeros((size, size, 4), dtype=numpy.uint8)
    out[..., :3] = (numpy.clip(canvas, 0, 1) * 255).astype(numpy.uint8)
    out[..., 3] = 255
    return out


def sprites_for(effect: dict, project_root: Path) -> list:
    """Per emitter: its texture's frames (PIL RGBA), tinted; [] when its texture is missing."""
    from PIL import Image
    out = []
    for emitter in effect.get('emitters', []):
        path = Path(project_root) / emitter.get('texture', '') if emitter.get('texture') else None
        if path is None or not path.is_file():
            out.append([])
            continue
        with Image.open(path) as image:
            image = image.convert('RGBA')
        tint = emitter.get('tint', [255, 255, 255])
        if tuple(tint[:3]) != (255, 255, 255):
            r, g, b, a = image.split()
            image = Image.merge('RGBA', (r.point(lambda v: v * tint[0] // 255),
                                         g.point(lambda v: v * tint[1] // 255),
                                         b.point(lambda v: v * tint[2] // 255), a))
        frames, columns = int(emitter.get('frames', 1)), int(emitter.get('columns', 1))
        rows = max(1, -(-frames // max(1, columns)))
        w, h = image.size[0] // max(1, columns), image.size[1] // rows
        out.append([image.crop(((i % columns) * w, (i // columns) * h, (i % columns + 1) * w,
                                (i // columns + 1) * h)) for i in range(frames)] if frames > 1 else [image])
    return out
