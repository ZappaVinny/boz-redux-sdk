"""Recast/Detour navigation resources used by ``CIsNavMesh``.

BOZ stores an 80-byte Recast build configuration followed by the standard
32-bit Detour navmesh-set container. Unknown configuration bytes and complete
tile payloads are retained verbatim.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

NAVMESHSET_MAGIC = b'TESM'  # little-endian bytes of the MSET integer
NAVMESH_MAGIC = b'VAND'     # little-endian bytes of the DNAV integer
CONFIG_SIZE = 80


@dataclass
class RecastConfig:
    cell_size: float
    cell_height: float
    agent_height: float
    agent_radius: float
    agent_max_climb: float
    agent_max_slope: float
    raw: bytes


@dataclass
class NavTile:
    reference: int
    data: bytes


@dataclass
class NavMesh:
    config: RecastConfig
    version: int
    origin: tuple[float, float, float]
    tile_width: float
    tile_height: float
    max_tiles: int
    max_polygons: int
    tiles: list[NavTile] = field(default_factory=list)
    trailer: bytes = b''


@dataclass
class NavMeshConnection:
    """Serialized ``CIsNavMeshConnection``; uncertain fields retain offset names."""

    start: tuple[float, float, float]
    end: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    value_50: int
    value_54: int
    value_48: float
    value_4c: float
    flag_5c: bool
    flag_5d: bool


def decode(body: bytes) -> NavMesh:
    """Decode and structurally validate a BOZ Detour navmesh set."""
    if len(body) < 120 or body[CONFIG_SIZE:CONFIG_SIZE + 4] != NAVMESHSET_MAGIC:
        raise ValueError('CIsNavMesh is missing its MSET header')
    config_values = struct.unpack_from('<6f', body)
    config = RecastConfig(*config_values, bytes(body[:CONFIG_SIZE]))
    version, count = struct.unpack_from('<II', body, 84)
    origin = struct.unpack_from('<3f', body, 92)
    tile_width, tile_height = struct.unpack_from('<2f', body, 104)
    max_tiles, max_polygons = struct.unpack_from('<II', body, 112)
    p = 120
    tiles = []
    for _ in range(count):
        if p + 8 > len(body):
            raise ValueError('truncated CIsNavMesh tile header')
        reference, size = struct.unpack_from('<II', body, p)
        p += 8
        if size <= 0 or p + size > len(body):
            raise ValueError('invalid CIsNavMesh tile size')
        data = bytes(body[p:p + size])
        if not data.startswith(NAVMESH_MAGIC):
            raise ValueError('CIsNavMesh tile is missing its DNAV header')
        tiles.append(NavTile(reference, data))
        p += size
    return NavMesh(config, version, origin, tile_width, tile_height, max_tiles,
                   max_polygons, tiles, bytes(body[p:]))


def encode(mesh: NavMesh) -> bytes:
    """Encode a navmesh set, preserving unknown config bytes and tile payloads."""
    if len(mesh.config.raw) != CONFIG_SIZE:
        raise ValueError('Recast config must retain its 80-byte source')
    config = bytearray(mesh.config.raw)
    struct.pack_into('<6f', config, 0, mesh.config.cell_size, mesh.config.cell_height,
                     mesh.config.agent_height, mesh.config.agent_radius,
                     mesh.config.agent_max_climb, mesh.config.agent_max_slope)
    out = config + bytearray(NAVMESHSET_MAGIC)
    out += struct.pack('<II3f2fII', mesh.version, len(mesh.tiles), *mesh.origin,
                       mesh.tile_width, mesh.tile_height, mesh.max_tiles, mesh.max_polygons)
    for tile in mesh.tiles:
        if not tile.data.startswith(NAVMESH_MAGIC):
            raise ValueError('CIsNavMesh tile is missing its DNAV header')
        out += struct.pack('<II', tile.reference, len(tile.data)) + tile.data
    return bytes(out) + mesh.trailer


def decode_connection(body: bytes) -> NavMeshConnection:
    """Decode the exact 55-byte layout confirmed from the game's serializer."""
    if len(body) != 55:
        raise ValueError('CIsNavMeshConnection must be exactly 55 bytes')
    start = struct.unpack_from('<3f', body, 0)
    end = struct.unpack_from('<3f', body, 12)
    rotation = struct.unpack_from('<4f', body, 24)
    value_50 = body[40]
    value_54 = struct.unpack_from('<I', body, 41)[0]
    value_48 = struct.unpack_from('<f', body, 45)[0]
    value_4c = struct.unpack_from('<f', body, 49)[0]
    return NavMeshConnection(start, end, rotation, value_50, value_54, value_48, value_4c,
                             bool(body[53]), bool(body[54]))


def encode_connection(connection: NavMeshConnection) -> bytes:
    """Encode a navigation connection in the game's unaligned field order."""
    if not 0 <= connection.value_50 <= 255 or not 0 <= connection.value_54 <= 0xffffffff:
        raise ValueError('navigation connection integer is out of range')
    return (struct.pack('<3f3f4fBIff', *connection.start, *connection.end, *connection.rotation,
                        connection.value_50, connection.value_54, connection.value_48,
                        connection.value_4c) + bytes((int(connection.flag_5c),
                                                      int(connection.flag_5d))))
