"""Minimal PNG reading and writing without Pillow (Blender's Python has no Pillow).

Reads 8-bit greyscale, grey + alpha, RGB, RGBA and palette images (non-interlaced, 1/2/4/8-bit
palette and greyscale), which covers what image editors save for game textures. Writes RGBA.
"""
from __future__ import annotations

import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'


class PngError(ValueError):
    pass


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def write_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """A PNG of *rgba* (rows top to bottom)."""
    if len(rgba) != width * height * 4:
        raise PngError('RGBA data does not match the size')
    stride = width * 4
    raw = b''.join(b'\0' + rgba[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (SIGNATURE + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(raw, 9))
            + _chunk(b'IEND', b''))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_rgba(data: bytes) -> tuple[int, int, bytes]:
    """(width, height, RGBA rows top to bottom) of a PNG."""
    if not data.startswith(SIGNATURE):
        raise PngError('not a PNG file')
    p, header, palette, alpha, idat = 8, None, b'', b'', bytearray()
    while p < len(data):
        (length,) = struct.unpack_from('>I', data, p)
        kind = data[p + 4:p + 8]
        body = data[p + 8:p + 8 + length]
        p += 12 + length
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            palette = body
        elif kind == b'tRNS':
            alpha = body
        elif kind == b'IDAT':
            idat += body
        elif kind == b'IEND':
            break
    if header is None:
        raise PngError('PNG has no header')
    width, height, depth, colour, _compression, _filter, interlace = header
    if interlace:
        raise PngError('interlaced PNGs are not supported; save without interlacing')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None or depth not in ((1, 2, 4, 8) if colour in (0, 3) else (8,)):
        raise PngError(f'PNG colour type {colour} at {depth} bits is not supported; save as 8-bit RGBA')
    raw = zlib.decompress(bytes(idat))
    bits = channels * depth
    stride = (width * bits + 7) // 8
    step = max(1, bits // 8)
    rows, previous, q = [], bytearray(stride), 0
    for _ in range(height):
        kind, line = raw[q], bytearray(raw[q + 1:q + 1 + stride])
        q += 1 + stride
        for i in range(stride):
            left = line[i - step] if i >= step else 0
            up = previous[i]
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 255
            elif kind == 4:
                line[i] = (line[i] + _paeth(left, up, previous[i - step] if i >= step else 0)) & 255
            elif kind != 0:
                raise PngError('bad PNG filter')
        rows.append(line)
        previous = line
    out = bytearray()
    for line in rows:
        if depth < 8:
            per_byte = 8 // depth
            values = [(line[x // per_byte] >> (8 - depth * (x % per_byte + 1))) & ((1 << depth) - 1)
                      for x in range(width)]
        else:
            values = None
        for x in range(width):
            if colour == 6:
                out += line[x * 4:x * 4 + 4]
            elif colour == 2:
                out += line[x * 3:x * 3 + 3] + b'\xff'
            elif colour == 4:
                grey, a = line[x * 2], line[x * 2 + 1]
                out += bytes((grey, grey, grey, a))
            elif colour == 0:
                grey = values[x] * 255 // ((1 << depth) - 1) if values else line[x]
                out += bytes((grey, grey, grey, 255))
            else:
                index = values[x] if values else line[x]
                out += palette[index * 3:index * 3 + 3] + bytes((alpha[index] if index < len(alpha)
                                                                 else 255,))
    return width, height, bytes(out)
