"""Serialized Bullet 2.78 triangle-mesh shapes embedded in ``CIsCollisionMeshSpec``.

``CIsCollisionMeshSpec::Serialise`` (0x4a0527ec) hands this payload to
``btBulletWorldImporter`` and keeps collision shape 0 as the entity's physics shape. It also
builds its own BIH ray-cast tree (0x4a05184c) from the separate vertex/index arrays that
follow the payload. Both copies hold identical geometry in every shipped map, so an edit must
change both.

The shipped files are 32-bit little-endian float files (``BULLETf_v278``)::

    char magic[12]
    repeat: char code[4], u32 length, u32 old_pointer, u32 dna_index, u32 count, data[length]

with one ``SHAP`` chunk (``btTriangleMeshShapeData``), one ``btMeshPartData`` array, a
``btIntIndexData`` index array, a ``btVector3FloatData`` vertex array, the ``QBVH`` optimized
BVH with its node arrays, and the ``DNA1`` type catalogue. Pointers are the writer's old
addresses; chunks are matched by them.

When geometry changes, the vertex and index chunks are rewritten and the shape's
``m_quantizedFloatBvh`` pointer is cleared. The game's ``createBvhTriangleMeshShape``
(``btBulletWorldImporter`` vslot 16, 0x4a02020e) then builds a fresh BVH at load instead of
using the stale serialized one. The orphaned BVH chunks are retained untouched.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b'BULLETf_v278'
TRIANGLE_MESH_SHAPE = 21
_CHUNK = struct.Struct('<4sIIII')
_SHAPE_SIZE = 60     # btTriangleMeshShapeData, 32-bit pointers
_PART_SIZE = 32      # btMeshPartData, 32-bit pointers
_SHAPE_PARTS = 12    # m_meshInterface.m_meshPartsPtr
_SHAPE_PART_COUNT = 32
_SHAPE_BVH = 40      # m_quantizedFloatBvh


@dataclass
class Chunk:
    code: bytes
    old_pointer: int
    dna_index: int
    count: int
    data: bytes


def parse(payload: bytes) -> list[Chunk]:
    """Split a Bullet file into chunks; raises for any layout bozkit cannot rewrite safely."""
    if not payload.startswith(MAGIC):
        raise ValueError('collision shape is not a 32-bit little-endian Bullet 2.78 file')
    chunks, p = [], len(MAGIC)
    while p < len(payload):
        if p + _CHUNK.size > len(payload):
            raise ValueError('truncated Bullet chunk header')
        code, length, old, dna, count = _CHUNK.unpack_from(payload, p)
        p += _CHUNK.size
        if p + length > len(payload):
            raise ValueError('truncated Bullet chunk')
        chunks.append(Chunk(code, old, dna, count, bytes(payload[p:p + length])))
        p += length
        if code == b'ENDB':
            break
    if p != len(payload):
        raise ValueError('Bullet file has trailing bytes')
    return chunks


def encode(chunks: list[Chunk]) -> bytes:
    out = bytearray(MAGIC)
    for chunk in chunks:
        out += _CHUNK.pack(chunk.code, len(chunk.data), chunk.old_pointer, chunk.dna_index,
                           chunk.count) + chunk.data
    return bytes(out)


def _triangle_mesh(chunks: list[Chunk]):
    shapes = [chunk for chunk in chunks if chunk.code == b'SHAP']
    if len(shapes) != 1 or len(shapes[0].data) != _SHAPE_SIZE:
        raise ValueError('Bullet file must contain exactly one triangle-mesh shape')
    shape = shapes[0]
    if struct.unpack_from('<i', shape.data, 4)[0] != TRIANGLE_MESH_SHAPE:
        raise ValueError('Bullet shape is not a btBvhTriangleMeshShape')
    parts_pointer = struct.unpack_from('<I', shape.data, _SHAPE_PARTS)[0]
    if struct.unpack_from('<i', shape.data, _SHAPE_PART_COUNT)[0] != 1:
        raise ValueError('only single-part Bullet triangle meshes are supported')
    by_pointer = {chunk.old_pointer: chunk for chunk in chunks if chunk.old_pointer}
    part = by_pointer.get(parts_pointer)
    if part is None or part.count != 1 or len(part.data) != _PART_SIZE:
        raise ValueError('Bullet triangle mesh part is missing')
    vertices3f, vertices3d, indices32, indices16_3 = struct.unpack_from('<4I', part.data, 0)
    vertex_chunk, index_chunk = by_pointer.get(vertices3f), by_pointer.get(indices32)
    if vertices3d or indices16_3 or vertex_chunk is None or index_chunk is None:
        raise ValueError('Bullet triangle mesh must use float vertices and 32-bit indices')
    return shape, part, vertex_chunk, index_chunk


def triangle_mesh(payload: bytes) -> tuple[list[tuple[float, float, float]], list[int]]:
    """The vertices and flat triangle indices Bullet will load."""
    _, _, vertex_chunk, index_chunk = _triangle_mesh(parse(payload))
    vertices = [struct.unpack_from('<3f', vertex_chunk.data, index * 16)
                for index in range(vertex_chunk.count)]
    indices = list(struct.unpack_from(f'<{index_chunk.count}i', index_chunk.data))
    return vertices, indices


def sync_triangle_mesh(payload: bytes, vertices, indices) -> bytes:
    """Return *payload* with its geometry replaced; unchanged geometry keeps every byte."""
    chunks = parse(payload)
    shape, part, vertex_chunk, index_chunk = _triangle_mesh(chunks)
    vertex_data = b''.join(struct.pack('<4f', *vertex, 0.0) for vertex in vertices)
    index_data = struct.pack(f'<{len(indices)}i', *indices)
    old_vertices = [struct.unpack_from('<3f', vertex_chunk.data, index * 16)
                    for index in range(vertex_chunk.count)]
    packed = [struct.unpack('<3f', struct.pack('<3f', *vertex)) for vertex in vertices]
    if old_vertices == packed and index_chunk.data == index_data:
        return payload
    if len(indices) % 3:
        raise ValueError('Bullet triangle indices must be a multiple of three')
    vertex_chunk.data, vertex_chunk.count = vertex_data, len(vertices)
    index_chunk.data, index_chunk.count = index_data, len(indices)
    part_data = bytearray(part.data)
    struct.pack_into('<ii', part_data, 24, len(indices) // 3, len(vertices))
    part.data = bytes(part_data)
    shape_data = bytearray(shape.data)
    struct.pack_into('<I', shape_data, _SHAPE_BVH, 0)
    shape.data = bytes(shape_data)
    return encode(chunks)


def synthetic_triangle_mesh(vertices, indices) -> bytes:
    """A minimal triangle-mesh file for tests. It has no DNA catalogue, so the game cannot load it."""
    shape = bytearray(_SHAPE_SIZE)
    struct.pack_into('<i', shape, 4, TRIANGLE_MESH_SHAPE)
    struct.pack_into('<I4fi', shape, _SHAPE_PARTS, 2, 1.0, 1.0, 1.0, 0.0, 1)
    struct.pack_into('<I', shape, _SHAPE_BVH, 5)
    part = struct.pack('<8I', 4, 0, 3, 0, 0, 0, len(indices) // 3, len(vertices))
    return encode([
        Chunk(b'SHAP', 1, 0, 1, bytes(shape)),
        Chunk(b'ARAY', 2, 0, 1, part),
        Chunk(b'ARAY', 3, 0, len(indices), struct.pack(f'<{len(indices)}i', *indices)),
        Chunk(b'ARAY', 4, 0, len(vertices),
              b''.join(struct.pack('<4f', *vertex, 0.0) for vertex in vertices)),
        Chunk(b'QBVH', 5, 0, 1, bytes(84)),
    ])
