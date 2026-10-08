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
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from PIL import Image

from .hashing import iw_hash

_TEXTURE_SCAN = range(4, 40)
_TEXTURE_FORMATS = {0x05: (2, 'RGB565'), 0x0E: (4, 'BGRA8888')}
_VERTS = iw_hash('CIwModelBlockVerts')
_UVS = iw_hash('CIwModelBlockGLUVs')
_TRIS = iw_hash('CIwModelBlockGLTriList')
_COLS = iw_hash('CIwModelBlockCols')


@dataclass(frozen=True)
class TextureLayout:
    header_offset: int
    texel_offset: int
    pixel_format: int
    width: int
    height: int
    pitch: int
    bytes_per_pixel: int


@dataclass(frozen=True)
class DecodedTexture:
    width: int
    height: int
    rgba: bytes
    format: str


def _unpack_rgb565(value):
    return ((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63,
            (value & 31) * 255 // 31)


def _decode_dxt1(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    p = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            c0, c1, bits = struct.unpack_from('<HHI', data, p)
            p += 8
            a, b = _unpack_rgb565(c0), _unpack_rgb565(c1)
            if c0 > c1:
                palette = [a, b, tuple((2 * a[i] + b[i]) // 3 for i in range(3)),
                           tuple((a[i] + 2 * b[i]) // 3 for i in range(3))]
                alpha = [255] * 4
            else:
                palette = [a, b, tuple((a[i] + b[i]) // 2 for i in range(3)), (0, 0, 0)]
                alpha = [255, 255, 255, 0]
            for y in range(4):
                for x in range(4):
                    if bx + x >= width or by + y >= height:
                        continue
                    index = (bits >> (2 * (y * 4 + x))) & 3
                    target = ((by + y) * width + bx + x) * 4
                    out[target:target + 4] = bytes((*palette[index], alpha[index]))
    return bytes(out)


_ETC_MODIFIERS = ((2, 8, -2, -8), (5, 17, -5, -17), (9, 29, -9, -29),
                  (13, 42, -13, -42), (18, 60, -18, -60), (24, 80, -24, -80),
                  (33, 106, -33, -106), (47, 183, -47, -183))


def _expand4(value):
    return value * 17


def _expand5(value):
    return (value << 3) | (value >> 2)


def _signed3(value):
    return value - 8 if value & 4 else value


def _decode_etc1(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    p = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            block = int.from_bytes(data[p:p + 8], 'big')
            p += 8
            high, low = block >> 32, block & 0xffffffff
            if high & 2:
                r1, g1, b1 = (high >> 27) & 31, (high >> 19) & 31, (high >> 11) & 31
                r2 = max(0, min(31, r1 + _signed3((high >> 24) & 7)))
                g2 = max(0, min(31, g1 + _signed3((high >> 16) & 7)))
                b2 = max(0, min(31, b1 + _signed3((high >> 8) & 7)))
                colours = ((_expand5(r1), _expand5(g1), _expand5(b1)),
                           (_expand5(r2), _expand5(g2), _expand5(b2)))
            else:
                colours = (((_expand4((high >> 28) & 15)), _expand4((high >> 20) & 15),
                            _expand4((high >> 12) & 15)),
                           (_expand4((high >> 24) & 15), _expand4((high >> 16) & 15),
                            _expand4((high >> 8) & 15)))
            tables = ((high >> 5) & 7, (high >> 2) & 7)
            flip = high & 1
            for y in range(4):
                for x in range(4):
                    if bx + x >= width or by + y >= height:
                        continue
                    sub = int(y >= 2) if flip else int(x >= 2)
                    bit = x * 4 + y
                    index = ((low >> bit) & 1) | (((low >> (bit + 16)) & 1) << 1)
                    modifier = _ETC_MODIFIERS[tables[sub]][index]
                    rgb = tuple(max(0, min(255, channel + modifier)) for channel in colours[sub])
                    target = ((by + y) * width + bx + x) * 4
                    out[target:target + 4] = bytes((*rgb, 255))
    return bytes(out)


def decode_texture_rgba(body: bytes) -> DecodedTexture:
    """Decode raw, DXT1, or ETC1 texture data without a third-party image library."""
    try:
        layout = texture_layout(body)
    except ValueError:
        layout = None
    if layout is not None:
        raw = body[layout.texel_offset:layout.texel_offset + layout.pitch * layout.height]
        if layout.pixel_format == 0x0e:
            rgba = bytearray()
            for blue, green, red, alpha in struct.iter_unpack('4B', raw):
                rgba += bytes((red, green, blue, alpha))
            return DecodedTexture(layout.width, layout.height, bytes(rgba), 'BGRA8888')
        rgba = bytearray()
        for (value,) in struct.iter_unpack('<H', raw):
            rgba += bytes((*_unpack_rgb565(value), 255))
        return DecodedTexture(layout.width, layout.height, bytes(rgba), 'RGB565')
    if len(body) < 95:
        raise ValueError('unsupported CIwTexture layout')
    mip_count, width, height = struct.unpack_from('<III', body, 35)
    # Native constructor 0x4a24c7b4 allocates a fixed 0x48-byte platform
    # header, with twelve size slots at +0x18 and data at +0x48.
    # That header starts at body+23, so blocks start at 95, not 79.
    if not 1 <= mip_count <= 12:
        raise ValueError('invalid cooked CIwTexture mip table')
    mip_sizes = struct.unpack_from(f'<{mip_count}I', body, 47)
    size = ((width + 3) // 4) * ((height + 3) // 4) * 8
    data_offset = 23 + 0x48
    if (not width or not height or mip_sizes[0] != size
            or data_offset + sum(mip_sizes) > len(body)):
        raise ValueError('invalid cooked CIwTexture dimensions')
    payload = body[data_offset:data_offset + size]
    if body[23] == 0x34:
        return DecodedTexture(width, height, _decode_dxt1(payload, width, height), 'DXT1')
    if body[23] == 0x27:
        return DecodedTexture(width, height, _decode_etc1(payload, width, height), 'ETC1')
    raise ValueError('unsupported cooked CIwTexture platform')


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
    from PIL import Image

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
    from PIL import Image

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
        if len(body) < 9:
            raise ValueError('truncated compact CIwMaterial texture reference')
        # Serialise initializes its reference destination to this+0x2c (texture 0).
        # Only the full-record branch changes it to this+0x54 (shader technique).
        return Material(same, flags, textures=[struct.unpack_from('<I', body, 5)[0]],
                        trailer=bytes(body[9:]))
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
        if len(material.textures) != 1:
            raise ValueError('compact material requires exactly one texture reference')
        return bytes(out) + struct.pack('<I', material.textures[0]) + material.trailer
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
    position_remap: list[int] = field(default_factory=list, repr=False, compare=False)
    face_materials: list[int] = field(default_factory=list, compare=False)
    vertex_colours: list[tuple[int, int, int, int]] = field(default_factory=list,
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


def _blocks(body: bytes, block_hash: int) -> list[int]:
    signature = struct.pack('<I', block_hash)
    result, start = [], 0
    while (offset := body.find(signature, start)) >= 0:
        if body[offset + 4:offset + 8] == signature:
            result.append(offset + 4)
            start = offset + 8
        else:
            result.append(offset)
            start = offset + 4
    return result


def decode_model(body: bytes) -> Model:
    """Decode positions, UVs, and triangle indices from a ``CIwModel``."""
    verts = _block(body, _VERTS)
    tri_blocks = _blocks(body, _TRIS)
    if not tri_blocks:
        raise ValueError(f'model is missing block {_TRIS:#010x}')
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
    remap = list(range(unique_count))
    if duplicate_count:
        duplicate_remap = struct.unpack_from(f'<{duplicate_count}H', body, remap_offset)
        if any(index >= unique_count for index in duplicate_remap):
            raise ValueError('model position remap is outside the unique-position array')
        remap.extend(duplicate_remap)
        vertices = [unique[index] for index in remap]
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
    colours = []
    colour_blocks = _blocks(body, _COLS)
    if colour_blocks:
        colours_offset = colour_blocks[0]
        colour_count = struct.unpack_from('<H', body, colours_offset + 6)[0]
        if colour_count == render_count:
            # The block's 28 bytes of non-colour data are split between an 11-byte inner
            # header and a 13-byte trailer (plus the 4-byte outer type wrapper).
            grayscale = bool(body[colours_offset + 10])
            stored_count = colour_count if grayscale else colour_count * 4
            raw_colours = body[colours_offset + 11:colours_offset + 11 + stored_count]
            if len(raw_colours) == stored_count:
                if grayscale:
                    # CIwModelBlockCols::Serialise writes only the first byte when every colour
                    # is opaque grayscale, then expands it to RGB with alpha 255 on load.
                    colours = [(value, value, value, 255) for value in raw_colours]
                else:
                    # IwSerialiseStructArray descriptor 0x0104 stores four byte components as
                    # separate planes rather than interleaved RGBA.
                    colours = [tuple(raw_colours[axis * colour_count + index]
                                     for axis in range(4))
                               for index in range(colour_count)]
    raw_triangles, triangles, face_materials = [], [], []
    for tris in tri_blocks:
        index_count = struct.unpack_from('<H', body, tris + 6)[0]
        # CIwModelBlockGLPrimBase::Serialise stores the index into CIwModel's
        # material-reference array immediately before the index data.  Blocks
        # are commonly ordered by material in shipped files, but that ordering
        # is not part of the format and repeated/out-of-order indices are valid.
        material_index = struct.unpack_from('<I', body, tris + 10)[0]
        indices = [struct.unpack_from('<H', body, tris + 14 + index * 2)[0]
                   for index in range(index_count - index_count % 3)]
        block_triangles = [tuple(indices[index:index + 3])
                           for index in range(0, len(indices), 3)]
        raw_triangles.extend(block_triangles)
        valid = [triangle for triangle in block_triangles
                 if len(set(triangle)) == 3 and all(value < render_count for value in triangle)]
        triangles.extend(valid)
        face_materials.extend([material_index] * len(valid))
    return Model(vertices, triangles, uvs, raw_triangles=raw_triangles,
                 position_remap=remap, face_materials=face_materials,
                 vertex_colours=colours)


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
    if model.face_materials and model.face_materials != old.face_materials:
        raise ValueError('model material reassignment is not supported yet')
    triangle_index = 0
    for tris in _blocks(source, _TRIS):
        index_count = struct.unpack_from('<H', source, tris + 6)[0]
        raw = [struct.unpack_from('<HHH', source, tris + 14 + slot * 6)
               for slot in range(index_count // 3)]
        slots = [slot for slot, triangle in enumerate(raw)
                 if len(set(triangle)) == 3 and all(value < len(old.vertices) for value in triangle)]
        for slot in slots:
            struct.pack_into('<HHH', out, tris + 14 + slot * 6,
                             *model.triangles[triangle_index])
            triangle_index += 1
    return bytes(out)
