"""Synthetic game data the tests share."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import bullet  # noqa: E402


def synthetic_triangle_mesh(vertices, indices) -> bytes:
    """A minimal triangle-mesh file for tests. It has no DNA catalogue, so the game cannot load it."""
    shape = bytearray(bullet._SHAPE_SIZE)
    struct.pack_into('<i', shape, 4, bullet.TRIANGLE_MESH_SHAPE)
    struct.pack_into('<I4fi', shape, bullet._SHAPE_PARTS, 2, 1.0, 1.0, 1.0, 0.0, 1)
    struct.pack_into('<I', shape, bullet._SHAPE_BVH, 5)
    part = struct.pack('<8I', 4, 0, 3, 0, 0, 0, len(indices) // 3, len(vertices))
    return bullet.encode([
        bullet.Chunk(b'SHAP', 1, 0, 1, bytes(shape)),
        bullet.Chunk(b'ARAY', 2, 0, 1, part),
        bullet.Chunk(b'ARAY', 3, 0, len(indices), struct.pack(f'<{len(indices)}i', *indices)),
        bullet.Chunk(b'ARAY', 4, 0, len(vertices),
              b''.join(struct.pack('<4f', *vertex, 0.0) for vertex in vertices)),
        bullet.Chunk(b'QBVH', 5, 0, 1, bytes(84)),
    ])
