"""Triangle-mesh payload appended to ``CIsCollisionMeshSpec`` components."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class CollisionMesh:
    """Bullet shape metadata plus editable vertices, indices, and triangle materials."""

    bullet_shape: bytes
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    materials: bytes = b''
    material_names: list[str] = field(default_factory=list)


def decode(data: bytes) -> CollisionMesh:
    """Decode the collision payload while retaining the serialized Bullet shape."""
    if len(data) < 16:
        raise ValueError('truncated collision mesh')
    bullet_size = struct.unpack_from('<I', data)[0]
    p = 4 + bullet_size
    if p + 12 > len(data):
        raise ValueError('invalid Bullet shape size')
    vertex_count, index_count, material_name_count = struct.unpack_from('<III', data, p)
    p += 12
    material_names = []
    for _ in range(material_name_count):
        try:
            end = data.index(b'\0', p)
        except ValueError as exc:
            raise ValueError('unterminated collision material name') from exc
        material_names.append(data[p:end].decode('latin-1'))
        p = end + 1
    if index_count % 3:
        raise ValueError('collision index count is not divisible by three')
    expected = p + vertex_count * 12 + index_count * 4 + index_count // 3
    if expected != len(data):
        raise ValueError('collision mesh counts do not match its size')
    vertices = [struct.unpack_from('<3f', data, p + index * 12)
                for index in range(vertex_count)]
    p += vertex_count * 12
    indices = list(struct.unpack_from(f'<{index_count}I', data, p)) if index_count else []
    p += index_count * 4
    return CollisionMesh(bytes(data[4:4 + bullet_size]), vertices, indices, bytes(data[p:]),
                         material_names)


def encode(mesh: CollisionMesh) -> bytes:
    """Encode a collision mesh and validate all triangle/material relationships."""
    if any(len(vertex) != 3 for vertex in mesh.vertices):
        raise ValueError('collision vertices must be XYZ triples')
    if len(mesh.indices) % 3 or len(mesh.materials) != len(mesh.indices) // 3:
        raise ValueError('collision requires one material byte per triangle')
    if any(not 0 <= index < len(mesh.vertices) for index in mesh.indices):
        raise ValueError('collision index is outside the vertex array')
    names = [name.encode('latin-1') for name in mesh.material_names]
    if any(b'\0' in name for name in names):
        raise ValueError('collision material names cannot contain NULs')
    out = bytearray(struct.pack('<I', len(mesh.bullet_shape))) + mesh.bullet_shape
    out += struct.pack('<III', len(mesh.vertices), len(mesh.indices), len(names))
    out += b''.join(name + b'\0' for name in names)
    out += b''.join(struct.pack('<3f', *vertex) for vertex in mesh.vertices)
    out += b''.join(struct.pack('<I', index) for index in mesh.indices)
    return bytes(out) + mesh.materials
