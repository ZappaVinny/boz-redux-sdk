"""Writable map-structure resource bodies."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .hashing import iw_hash


@dataclass
class Portal:
    """A convex visibility portal connecting two named sectors."""

    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0)
    distance: float = 0.0
    front_sector: str = ''
    back_sector: str = ''


def _cstring(body: bytes, offset: int) -> tuple[str, int]:
    end = body.index(b'\0', offset)
    return body[offset:end].decode('latin-1'), end + 1


def decode_portal(body: bytes) -> Portal:
    """Decode a ``CIsPortal`` body and validate its cached sector hashes."""
    if len(body) < 32:
        raise ValueError('truncated CIsPortal')
    count = struct.unpack_from('<I', body)[0]
    p = 4
    fixed_end = p + count * 12 + 12 + 4 + 8
    if count < 3 or fixed_end > len(body):
        raise ValueError('invalid CIsPortal vertex count')
    vertices = [struct.unpack_from('<3f', body, p + index * 12) for index in range(count)]
    p += count * 12
    normal = struct.unpack_from('<3f', body, p)
    p += 12
    distance = struct.unpack_from('<f', body, p)[0]
    p += 4
    front_hash, back_hash = struct.unpack_from('<II', body, p)
    p += 8
    front, p = _cstring(body, p)
    back, p = _cstring(body, p)
    if p != len(body):
        raise ValueError('CIsPortal has trailing bytes')
    if (front_hash, back_hash) != (iw_hash(front), iw_hash(back)):
        raise ValueError('CIsPortal sector hash does not match its name')
    return Portal(vertices, normal, distance, front, back)


def encode_portal(portal: Portal) -> bytes:
    """Encode a portal, regenerating sector hashes from their names."""
    if len(portal.vertices) < 3:
        raise ValueError('portal requires at least three vertices')
    if any(len(value) != 3 for value in portal.vertices) or len(portal.normal) != 3:
        raise ValueError('portal positions and normal must be XYZ triples')
    front = portal.front_sector.encode('latin-1')
    back = portal.back_sector.encode('latin-1')
    if b'\0' in front or b'\0' in back:
        raise ValueError('portal sector names must be single-byte strings without NULs')
    out = bytearray(struct.pack('<I', len(portal.vertices)))
    out += b''.join(struct.pack('<3f', *value) for value in portal.vertices)
    out += struct.pack('<3ffII', *portal.normal, portal.distance,
                       iw_hash(portal.front_sector), iw_hash(portal.back_sector))
    return bytes(out) + front + b'\0' + back + b'\0'
