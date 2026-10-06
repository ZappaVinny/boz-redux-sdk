"""Writable native Marmalade resources used by BOZ 1.0.11.

The editors in this module deliberately retain the source body.  Known fields are
patched in place and every unknown byte remains untouched.  Constructors produce
small synthetic resources for tests and newly-authored content.
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from PIL import Image

from .hashing import iw_hash

_TEXTURE_SCAN = range(4, 40)
_TEXTURE_FORMATS = {0x05: (2, 'RGB565'), 0x0E: (4, 'BGRA8888')}
_VERTS = iw_hash('CIwModelBlockVerts')
_UVS = iw_hash('CIwModelBlockGLUVs')
_TRIS = iw_hash('CIwModelBlockGLTriList')


@dataclass(frozen=True)
class TextureLayout:
    header_offset: int
    texel_offset: int
    pixel_format: int
    width: int
    height: int
    pitch: int
    bytes_per_pixel: int


def texture_layout(body: bytes) -> TextureLayout:
    """Locate the dimensions and texel tail of a serialized ``CIwTexture``."""
    for off in _TEXTURE_SCAN:
        if off + 9 > len(body):
            break
        width, height, pitch = struct.unpack_from('<HHH', body, off + 3)
        if not width or not height or pitch % width:
            continue
        bpp = pitch // width
        texel_offset = len(body) - pitch * height
        pixel_format = body[off]
        known = _TEXTURE_FORMATS.get(pixel_format)
        if known is not None and known[0] == bpp and 12 <= texel_offset <= 40:
            return TextureLayout(off, texel_offset, pixel_format, width, height, pitch, bpp)
    raise ValueError('unsupported CIwTexture layout')


def decode_texture(body: bytes) -> Image.Image:
    """Decode the writable raw texture layouts used by BOZ."""
    layout = texture_layout(body)
    raw = body[layout.texel_offset:]
    if layout.pixel_format == 0x05:
        return Image.frombytes('RGB', (layout.width, layout.height), raw, 'raw', 'BGR;16',
                               layout.pitch, 1)
    if layout.pixel_format == 0x0E:
        return Image.frombytes('RGBA', (layout.width, layout.height), raw, 'raw', 'BGRA',
                               layout.pitch, 1)
    raise ValueError(f'unsupported CIwImage pixel format {layout.pixel_format:#04x}')


def _rgb565(image: Image.Image) -> bytes:
    out = bytearray()
    raw = image.convert('RGB').tobytes()
    for index in range(0, len(raw), 3):
        red, green, blue = raw[index:index + 3]
        value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        out += struct.pack('<H', value)
    return bytes(out)


def encode_texture(image: Image.Image, source: bytes | None = None,
                   bytes_per_pixel: int | None = None) -> bytes:
    """Encode an image, optionally retaining an existing texture's unknown header bytes.

    When *source* is supplied its pixel format is retained unless *bytes_per_pixel* is
    explicit.  Dimensions, pitch, and the texel tail are updated; all other header
    fields remain byte-identical.
    """
    layout = texture_layout(source) if source is not None else None
    bpp = bytes_per_pixel or (layout.bytes_per_pixel if layout else 4)
    if bpp not in (2, 4):
        raise ValueError('texture bytes_per_pixel must be 2 (RGB565) or 4 (BGRA8888)')
    width, height = image.size
    if not 0 < width <= 8192 or not 0 < height <= 8192:
        raise ValueError('texture dimensions must be between 1 and 8192')
    if bpp == 2:
        texels = _rgb565(image)
    else:
        texels = image.convert('RGBA').tobytes('raw', 'BGRA')
    if source is None:
        header = bytearray(16)
        off = 4
    else:
        header = bytearray(source[:layout.texel_offset])
        off = layout.header_offset
    header[off] = 0x05 if bpp == 2 else 0x0E
    struct.pack_into('<HHH', header, off + 3, width, height, width * bpp)
    return bytes(header) + texels


def encode_texture_png(png: str | Path | bytes, source: bytes | None = None,
                       bytes_per_pixel: int | None = None) -> bytes:
    """Import a PNG file or PNG bytes into a ``CIwTexture`` body."""
    if isinstance(png, (str, Path)):
        with Image.open(png) as image:
            return encode_texture(image, source, bytes_per_pixel)
    with Image.open(io.BytesIO(png)) as image:
        return encode_texture(image, source, bytes_per_pixel)


@dataclass
class Material:
    same_as_default: bool
    flags: int
    unknown: bytes = b'\0\0\0\0'
    colours: list[tuple[int, int, int, int]] = field(default_factory=list)
    textures: list[int] = field(default_factory=list)
    trailer: bytes = b''


def decode_material(body: bytes) -> Material:
    """Decode a material while retaining unrecognized header and trailer bytes."""
    if len(body) < 5:
        raise ValueError('truncated CIwMaterial')
    same = bool(body[0])
    flags = struct.unpack_from('<I', body, 1)[0]
    if same:
        return Material(same, flags, trailer=bytes(body[5:]))
    if len(body) < 29:
        raise ValueError('truncated CIwMaterial')
    unknown = bytes(body[5:9])
    colours = [tuple(body[p:p + 4]) for p in range(9, 25, 4)]
    count = struct.unpack_from('<I', body, 25)[0]
    end = 29 + count * 4
    if end > len(body):
        raise ValueError('truncated CIwMaterial texture list')
    textures = list(struct.unpack_from(f'<{count}I', body, 29)) if count else []
    return Material(False, flags, unknown, colours, textures, bytes(body[end:]))


def encode_material(material: Material) -> bytes:
    """Encode a material including all retained unknown data."""
    out = bytearray([int(material.same_as_default)])
    out += struct.pack('<I', material.flags)
    if material.same_as_default:
        return bytes(out) + material.trailer
    if len(material.unknown) != 4 or len(material.colours) != 4:
        raise ValueError('material requires four unknown header bytes and four RGBA colours')
    out += material.unknown
    for colour in material.colours:
        if len(colour) != 4 or any(not 0 <= channel <= 255 for channel in colour):
            raise ValueError('material colours must be four 8-bit RGBA tuples')
        out += bytes(colour)
    out += struct.pack('<I', len(material.textures))
    out += b''.join(struct.pack('<I', value) for value in material.textures)
    return bytes(out) + material.trailer


@dataclass
class Model:
    vertices: list[tuple[int, int, int]]
    triangles: list[tuple[int, int, int]]
    uvs: list[tuple[float, float]] = field(default_factory=list)
    raw_triangles: list[tuple[int, int, int]] = field(default_factory=list, repr=False,
                                                               compare=False)


def _block(body: bytes, block_hash: int) -> int:
    signature = struct.pack('<I', block_hash)
    offset = body.find(signature)
    if offset < 0:
        raise ValueError(f'model is missing block {block_hash:#010x}')
    # Shipped models wrap each serialized block with an outer type hash, so the
    # same hash occurs twice. The inner hash begins the layout described below.
    # Synthetic/new blocks may contain only the inner form.
    if body[offset + 4:offset + 8] == signature:
        offset += 4
    return offset


def decode_model(body: bytes) -> Model:
    """Decode positions, UVs, and triangle indices from a ``CIwModel``."""
    verts = _block(body, _VERTS)
    tris = _block(body, _TRIS)
    render_count = struct.unpack_from('<H', body, verts + 6)[0]
    unique_count = struct.unpack_from('<H', body, verts + 10)[0]
    centre = struct.unpack_from('<h', body, verts + 12)[0]
    component_offset = verts + 14
    components = [struct.unpack_from(f'<{unique_count}h', body,
                                     component_offset + axis * unique_count * 2)
                  for axis in range(3)]
    unique = [tuple(components[axis][index] + centre for axis in range(3))
              for index in range(unique_count)]

    # CIwModelBlockVerts stores each position once, followed by one u16
    # source-position index for every duplicated render vertex.  The
    # normal, UV, colour, and triangle blocks address the expanded render array.
    remap_offset = component_offset + unique_count * 6
    duplicate_count = render_count - unique_count
    if duplicate_count < 0:
        raise ValueError('model render vertex count is smaller than its position count')
    if duplicate_count:
        remap = struct.unpack_from(f'<{duplicate_count}H', body, remap_offset)
        if any(index >= unique_count for index in remap):
            raise ValueError('model position remap is outside the unique-position array')
        vertices = unique + [unique[index] for index in remap]
    else:
        vertices = unique
    try:
        uv_offset = _block(body, _UVS)
    except ValueError:
        uv_offset = -1
    uvs = []
    if uv_offset >= 0:
        uv_count = struct.unpack_from('<H', body, uv_offset + 6)[0]
        if uv_count == render_count:
            uvs = [(u / 4096.0, v / 4096.0) for u, v in
                   (struct.unpack_from('<hh', body, uv_offset + 10 + index * 4)
                    for index in range(render_count))]
    index_count = struct.unpack_from('<H', body, tris + 6)[0]
    indices = [struct.unpack_from('<H', body, tris + 14 + index * 2)[0]
               for index in range(index_count - index_count % 3)]
    raw_triangles = [tuple(indices[index:index + 3]) for index in range(0, len(indices), 3)]
    triangles = [triangle for triangle in raw_triangles
                 if len(set(triangle)) == 3 and all(value < render_count for value in triangle)]
    return Model(vertices, triangles, uvs, raw_triangles)


def encode_model(model: Model, source: bytes | None = None) -> bytes:
    """Encode a model or patch same-sized geometry into a source body losslessly."""
    if any(len(vertex) != 3 or any(not -32768 <= value <= 32767 for value in vertex)
           for vertex in model.vertices):
        raise ValueError('model vertices must be signed 16-bit XYZ triples')
    if any(len(triangle) != 3 or any(not 0 <= value <= 65535 for value in triangle)
           for triangle in model.triangles):
        raise ValueError('model triangle indices must be unsigned 16-bit triples')
    if source is None and any(value >= len(model.vertices)
                              for triangle in model.triangles for value in triangle):
        raise ValueError('model triangle index is outside the vertex array')
    if model.uvs and len(model.uvs) != len(model.vertices):
        raise ValueError('model UV count must match its vertex count')
    if source is None:
        count = len(model.vertices)
        centre = 0
        planar = b''.join(struct.pack(f'<{count}h', *(vertex[axis] - centre
                                                     for vertex in model.vertices))
                          for axis in range(3))
        verts = (struct.pack('<IHHHHh', _VERTS, 14 + len(planar), count, 0, count, centre) +
                 planar)
        uvs = b''
        if model.uvs:
            raw_uvs = [(round(u * 4096), round(v * 4096)) for u, v in model.uvs]
            uv_data = b''.join(struct.pack('<hh', *value) for value in raw_uvs)
            uvs = struct.pack('<IHHH', _UVS, 10 + len(uv_data), len(raw_uvs), 0) + uv_data
        indices = [value for triangle in model.triangles for value in triangle]
        tri = bytearray(struct.pack('<IHHHI', _TRIS, 14 + len(indices) * 2, len(indices), 0, 0))
        tri += b''.join(struct.pack('<H', value) for value in indices)
        return verts + uvs + bytes(tri)
    old = decode_model(source)
    if (len(old.vertices), len(old.triangles), bool(old.uvs)) != \
            (len(model.vertices), len(model.triangles), bool(model.uvs)):
        raise ValueError('lossless source patch requires unchanged vertex, triangle, and UV counts')
    out = bytearray(source)
    verts = _block(source, _VERTS)
    render_count = struct.unpack_from('<H', source, verts + 6)[0]
    unique_count = struct.unpack_from('<H', source, verts + 10)[0]
    centre = struct.unpack_from('<h', source, verts + 12)[0]
    remap_offset = verts + 14 + unique_count * 6
    remap = list(range(unique_count))
    if render_count > unique_count:
        remap.extend(struct.unpack_from(f'<{render_count - unique_count}H', source, remap_offset))
    unique_values = list(model.vertices[:unique_count])
    for render_index, unique_index in enumerate(remap):
        if model.vertices[render_index] != unique_values[unique_index]:
            raise ValueError('duplicated render vertices must retain one shared position')
    for axis in range(3):
        for index, value in enumerate(unique_values):
            delta = value[axis] - centre
            if not -32768 <= delta <= 32767:
                raise ValueError('model position exceeds the source block encoding range')
            struct.pack_into('<h', out, verts + 14 + axis * unique_count * 2 + index * 2, delta)
    uv_offset = _block(source, _UVS) if model.uvs else -1
    for index, (u, v) in enumerate(model.uvs):
        struct.pack_into('<hh', out, uv_offset + 10 + index * 4, round(u * 4096), round(v * 4096))
    tris = _block(source, _TRIS)
    slots = [index for index, triangle in enumerate(old.raw_triangles)
             if len(set(triangle)) == 3 and all(value < len(old.vertices) for value in triangle)]
    for slot, triangle in zip(slots, model.triangles, strict=True):
        struct.pack_into('<HHH', out, tris + 14 + slot * 6, *triangle)
    return bytes(out)
