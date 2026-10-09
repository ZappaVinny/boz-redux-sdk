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


# Detour v7 tile data (dtMeshHeader followed by 4-byte aligned sections). dtPolyRef is 32-bit.
_TILE_HEADER = struct.Struct('<5iI9i3f3f3ff')
# BOZ's Detour build widens dtPoly to 40 bytes: firstLink, verts[6], neis[6], u32 flags, an extra
# u32 (zero in shipped data), vertCount, areaAndtype, 2 bytes padding. Stock Detour has 32 bytes
# with u16 flags. Proven by section sizes summing to each shipped tile's length.
_POLY = struct.Struct('<I6H6HIIBBxx')
POLY_SIZE = _POLY.size  # 40
# dtOffMeshConnection is likewise 4 bytes longer than stock (40 instead of 36): pos[6], radius,
# an extra float (0.9 in every shipped link), then poly, flags, side and userId as in stock.
_OFF_MESH = struct.Struct('<6fffHBBI')
OFF_MESH_SIZE = _OFF_MESH.size  # 40


@dataclass
class NavPoly:
    vertices: list[int]
    neighbours: list[int]
    flags: int
    area: int
    kind: int  # 0 ground polygon, 1 off-mesh connection
    extra: int = 0  # BOZ-specific u32 after the flags


@dataclass
class TileData:
    """A decoded Detour tile: everything editors and rebuild checks need."""

    x: int
    y: int
    layer: int
    walkable_height: float
    walkable_radius: float
    walkable_climb: float
    bmin: tuple[float, float, float]
    bmax: tuple[float, float, float]
    vertices: list[tuple[float, float, float]]
    polys: list[NavPoly]
    detail_meshes: list[tuple[int, int, int, int]]  # vert base, tri base, vert count, tri count
    detail_vertices: list[tuple[float, float, float]]
    detail_triangles: list[tuple[int, int, int, int]]
    bv_node_count: int
    off_mesh_count: int
    max_link_count: int
    off_mesh: list[tuple] = field(default_factory=list)  # (start, end, radius, extra, poly, flags, side, user)

    def triangles(self):
        """World triangles (metres, Y-up) of every ground polygon, including detail geometry."""
        for index, poly in enumerate(self.polys):
            if poly.kind != 0:
                continue
            vert_base, tri_base, vert_count, tri_count = self.detail_meshes[index]
            for a, b, c, _ in self.detail_triangles[tri_base:tri_base + tri_count]:
                corners = []
                for value in (a, b, c):
                    if value < len(poly.vertices):
                        corners.append(self.vertices[poly.vertices[value]])
                    else:
                        corners.append(self.detail_vertices[vert_base + value - len(poly.vertices)])
                yield poly, tuple(corners)


def decode_tile(data: bytes) -> TileData:
    if not data.startswith(NAVMESH_MAGIC):
        raise ValueError('Detour tile is missing its DNAV header')
    fields = _TILE_HEADER.unpack_from(data)
    (_, version, x, y, layer, _, poly_count, vert_count, max_links, detail_count,
     detail_vert_count, detail_tri_count, bv_count, off_mesh_count, _) = fields[:15]
    if version != 7:
        raise ValueError(f'unsupported Detour tile version {version}')
    walkable_height, walkable_radius, walkable_climb = fields[15:18]
    bmin, bmax = tuple(fields[18:21]), tuple(fields[21:24])
    p = _TILE_HEADER.size

    def take(count, fmt, size):
        nonlocal p
        values = [struct.unpack_from(fmt, data, p + index * size) for index in range(count)]
        p += (count * size + 3) & ~3
        return values

    vertices = take(vert_count, '<3f', 12)
    polys = []
    for first_link, *rest in take(poly_count, _POLY.format, POLY_SIZE):
        verts, neis = rest[:6], rest[6:12]
        flags, extra, count, area_type = rest[12:16]
        polys.append(NavPoly(list(verts[:count]), list(neis[:count]), flags, area_type & 0x3f,
                             area_type >> 6, extra))
    take(max_links, '<IIBBBB', 12)
    detail_meshes = [value[:4] for value in take(detail_count, '<IIBBxx', 12)]
    detail_vertices = take(detail_vert_count, '<3f', 12)
    detail_triangles = take(detail_tri_count, '<4B', 4)
    p += bv_count * 16
    off_mesh = []
    for values in take(off_mesh_count, _OFF_MESH.format, OFF_MESH_SIZE):
        off_mesh.append((values[0:3], values[3:6], *values[6:]))
    if p != len(data):
        raise ValueError('Detour tile sections do not add up to its size')
    return TileData(x, y, layer, walkable_height, walkable_radius, walkable_climb, bmin, bmax,
                    vertices, polys, detail_meshes, detail_vertices, detail_triangles, bv_count,
                    off_mesh_count, max_links, off_mesh)
