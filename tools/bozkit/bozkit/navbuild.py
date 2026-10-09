"""Rebuild a level's Detour navmesh from its collision with Recast.

The shipped navmeshes were built from the level's collision mesh (79% of their surfaces lie
within one cell height of it) with the 80-byte build settings stored in each ``CIsNavMesh``.
BOZ modified Detour: polygons are 40 bytes (u32 flags plus a u32 name hash) and off-mesh
connections 40 bytes (an extra float after the radius). The game tags polygons through those
fields: flag 0x2 with a door's name marks floor the door blocks, 0x4000 with a jump area's name
marks jump points, and other bits mark further area types. Off-mesh connections are the zombie
window crossings and climbs, named after their barricade or climb.

The rebuild runs Recast (the ``boz-navmesh`` helper in tools/navmesh) per tile on the tile grid
stored in the navmesh, converts the stock tiles to BOZ's layout, gives every new polygon the tags
of the shipped polygon under its centre, and keeps every off-mesh connection.
"""
from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import navigation

_STOCK_POLY = struct.Struct('<I6H6HHBB')       # 32 bytes
_STOCK_OFF_MESH = struct.Struct('<6ffHBBI')    # 36 bytes
_BOZ_POLY = navigation._POLY                   # 40 bytes
_BOZ_OFF_MESH = navigation._OFF_MESH           # 40 bytes


def helper_path() -> Path:
    """The boz-navmesh executable: $BOZ_NAVMESH, next to this package (Blender add-on), or the
    SDK's tools/navmesh/build."""
    candidates = []
    if os.environ.get('BOZ_NAVMESH'):
        candidates.append(Path(os.environ['BOZ_NAVMESH']))
    here = Path(__file__).resolve().parent
    name = 'boz-navmesh.exe' if os.name == 'nt' else 'boz-navmesh'
    candidates += [here / name, here.parents[1] / 'navmesh' / 'build' / name]
    for candidate in candidates:
        if candidate.is_file():
            if os.name != 'nt' and not os.access(candidate, os.X_OK):
                # Blender's add-on installer unpacks ZIPs without permission bits.
                candidate.chmod(candidate.stat().st_mode | 0o755)
            return candidate
    found = shutil.which('boz-navmesh')
    if found:
        return Path(found)
    raise FileNotFoundError('boz-navmesh is not built; run cmake in tools/navmesh '
                            '(see docs/navmesh.md)')


@dataclass
class Settings:
    """The build settings stored in the first 80 bytes of a CIsNavMesh."""

    cell_size: float
    cell_height: float
    agent_height: float
    agent_radius: float
    agent_max_climb: float
    agent_max_slope: float
    region_min_size: int
    region_merge_size: int
    edge_max_len: float
    edge_max_error: float
    verts_per_poly: int
    detail_sample_dist: float
    detail_sample_max_error: float
    tile_size: int
    bmin: tuple[float, float, float]
    bmax: tuple[float, float, float]

    @classmethod
    def from_raw(cls, raw: bytes) -> Settings:
        values = struct.unpack_from('<6f2i2fi2fi3f3f', raw)
        return cls(*values[:14], tuple(values[14:17]), tuple(values[17:20]))


def _tile_triangles(tile: navigation.TileData):
    for poly, triangle in tile.triangles():
        yield poly, triangle


class _SurfaceIndex:
    """Find the shipped polygon (flags, name hash) under a point, by XZ cell lookup."""

    def __init__(self, tiles: list[navigation.TileData], cell: float = 1.0):
        self.cell = cell
        self.cells: dict[tuple[int, int], list] = {}
        for tile in tiles:
            for poly, (a, b, c) in _tile_triangles(tile):
                xs, zs = (a[0], b[0], c[0]), (a[2], b[2], c[2])
                for gx in range(math.floor(min(xs) / cell), math.floor(max(xs) / cell) + 1):
                    for gz in range(math.floor(min(zs) / cell), math.floor(max(zs) / cell) + 1):
                        self.cells.setdefault((gx, gz), []).append((poly, a, b, c))

    def find(self, point, height_tolerance: float):
        x, y, z = point
        best = None
        for poly, a, b, c in self.cells.get((math.floor(x / self.cell), math.floor(z / self.cell)), ()):
            d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
            if abs(d) < 1e-12:
                continue
            l1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / d
            l2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / d
            l3 = 1 - l1 - l2
            if min(l1, l2, l3) < -1e-4:
                continue
            gap = abs(l1 * a[1] + l2 * b[1] + l3 * c[1] - y)
            if gap <= height_tolerance and (best is None or gap < best[0]):
                best = (gap, poly)
        return best[1] if best else None


BUILD_OPTIONS = int(os.environ.get('BOZ_NAVMESH_OPTIONS', '0'))  # see tools/navmesh


def _request(settings: Settings, mesh: navigation.NavMesh, vertices, triangles, tiles, links) -> bytes:
    out = bytearray(b'BOZN' + struct.pack('<II', 2, BUILD_OPTIONS))
    out += struct.pack('<6f2i2fi2ff', settings.cell_size, settings.cell_height,
                       settings.agent_height, settings.agent_radius, settings.agent_max_climb,
                       settings.agent_max_slope, settings.region_min_size,
                       settings.region_merge_size, settings.edge_max_len,
                       settings.edge_max_error, settings.verts_per_poly,
                       settings.detail_sample_dist, settings.detail_sample_max_error,
                       mesh.tile_width)
    out += struct.pack('<3f3f3f', *mesh.origin, *settings.bmin, *settings.bmax)
    out += struct.pack('<I', len(vertices)) + b''.join(struct.pack('<3f', *v) for v in vertices)
    out += struct.pack('<I', len(triangles)) + b''.join(struct.pack('<3i', *t) for t in triangles)
    out += struct.pack('<I', len(tiles)) + b''.join(struct.pack('<2i', *t) for t in tiles)
    out += struct.pack('<I', len(links))
    for start, end, radius, bidirectional, user in links:
        out += struct.pack('<3f3ffBI', *start, *end, radius, int(bidirectional), user)
    return bytes(out)


def _read_reply(data: bytes) -> list[tuple[int, int, bytes]]:
    if not data.startswith(b'BOZT'):
        raise ValueError('boz-navmesh wrote no tiles')
    count = struct.unpack_from('<I', data, 4)[0]
    p, tiles = 8, []
    for _ in range(count):
        x, y, size = struct.unpack_from('<iiI', data, p)
        p += 12
        tiles.append((x, y, data[p:p + size]))
        p += size
    return tiles


def _align(value: int) -> int:
    return (value + 3) & ~3


def to_boz_tile(stock: bytes, tag, link_extras) -> bytes:
    """Re-pack a stock Detour tile into BOZ's layout.

    *tag(poly_index, centre)* returns (flags, name hash) for a ground polygon; *link_extras*
    maps an off-mesh userId to the BOZ float stored after the radius.
    """
    header = bytearray(stock[:navigation._TILE_HEADER.size])
    fields = navigation._TILE_HEADER.unpack_from(stock)
    poly_count, vert_count, max_links = fields[6], fields[7], fields[8]
    detail_count, detail_verts, detail_tris = fields[9], fields[10], fields[11]
    bv_count, off_mesh_count = fields[12], fields[13]
    p = len(header)
    verts_size = _align(vert_count * 12)
    vertices = [struct.unpack_from('<3f', stock, p + i * 12) for i in range(vert_count)]
    out = bytearray(header) + stock[p:p + verts_size]
    p += verts_size
    polys = [_STOCK_POLY.unpack_from(stock, p + i * 32) for i in range(poly_count)]
    p += _align(poly_count * 32)
    for index, (first_link, *rest) in enumerate(polys):
        verts, neis = rest[:6], rest[6:12]
        flags, count, area_type = rest[12:15]
        extra = 0
        if area_type >> 6 == 0 and count:
            centre = tuple(sum(vertices[v][axis] for v in verts[:count]) / count for axis in range(3))
            flags, extra = tag(index, centre)
        out += _BOZ_POLY.pack(first_link, *verts, *neis, flags, extra, count, area_type)
    rest_size = (_align(max_links * 12) + _align(detail_count * 12) + _align(detail_verts * 12)
                 + _align(detail_tris * 4) + _align(bv_count * 16))
    out += stock[p:p + rest_size]
    p += rest_size
    for index in range(off_mesh_count):
        values = _STOCK_OFF_MESH.unpack_from(stock, p + index * 36)
        pos, radius, poly, flags, side, user = values[:6], values[6], values[7], values[8], values[9], values[10]
        out += _BOZ_OFF_MESH.pack(*pos, radius, link_extras.get(user, 0.9), poly, flags, side, user)
    return bytes(out)


@dataclass
class RebuildReport:
    tiles: int          # tiles rebuilt
    polys: int          # polygons in rebuilt tiles
    tagged: int         # rebuilt polygons that took a shipped tag
    links: int          # off-mesh links in the level
    links_placed: int   # links inside rebuilt tiles
    reachable: int = 0  # tiles kept as shipped because a rebuild would drop their links


def _key(point):
    return tuple(round(value, 3) for value in point)


def reachable_polys(tiles: list[navigation.TileData], seeds, links, *, horizontal=1.0,
                    vertical=1.0) -> list[set[int]]:
    """Per tile, the ground polygons reachable from *seeds* through shared edges and off-mesh
    links. Unreached polygons are what the original tool left out (rooftops, closed spaces)."""
    nodes = [(t, p) for t, tile in enumerate(tiles) for p, poly in enumerate(tile.polys)
             if poly.kind == 0]
    number = {node: i for i, node in enumerate(nodes)}
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    edges = {}
    for t, p in nodes:
        tile = tiles[t]
        verts = tile.polys[p].vertices
        for k in range(len(verts)):
            edge = tuple(sorted((_key(tile.vertices[verts[k]]),
                                 _key(tile.vertices[verts[(k + 1) % len(verts)]]))))
            other = edges.setdefault(edge, number[(t, p)])
            if other != number[(t, p)]:
                union(other, number[(t, p)])
    surfaces = _SurfaceIndex(tiles)
    owner = {id(tiles[t].polys[p]): number[(t, p)] for t, p in nodes}

    def nearest(point):
        for radius in (0.0, horizontal):
            for dx, dz in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius)):
                found = surfaces.find((point[0] + dx, point[1], point[2] + dz), vertical)
                if found is not None:
                    return owner[id(found)]
        return None

    for start, end in links:
        a, b = nearest(start), nearest(end)
        if a is not None and b is not None:
            union(a, b)
    roots = {find(i) for i in (nearest(seed) for seed in seeds) if i is not None}
    result = [set() for _ in tiles]
    for (t, p), i in number.items():
        if find(i) in roots:
            result[t].add(p)
    return result


def _set_poly_flags(data: bytes, flags_by_poly: dict[int, int]) -> bytes:
    """Patch BOZ polygon flags in place (u32 at +28 of each 40-byte polygon)."""
    out = bytearray(data)
    vert_count = struct.unpack_from('<i', data, 28)[0]
    base = navigation._TILE_HEADER.size + _align(vert_count * 12)
    for index, flags in flags_by_poly.items():
        struct.pack_into('<I', out, base + index * POLY_STRIDE + 28, flags)
    return bytes(out)


POLY_STRIDE = 40


def _inside(point, boxes, margin=0.0) -> bool:
    return any(box[0] - margin <= point[0] <= box[2] + margin and
               box[1] - margin <= point[2] <= box[3] + margin for box in boxes)


def rebuild(body: bytes, vertices_m, triangles, *, dirty=None, helper: Path | None = None
            ) -> tuple[bytes, RebuildReport]:
    """Rebuild the tiles of a CIsNavMesh that edits touched.

    *vertices_m*/*triangles* are the level's navmesh input (collision, metres, the game's Y-up
    axes, the game's winding; reversed here for Recast). *dirty* lists XZ boxes (min x, min z,
    max x, max z in metres) around changed geometry, old and new positions; ``None`` rebuilds
    every tile (used to validate the pipeline against shipped data).

    Untouched tiles stay byte-identical. In a rebuilt tile a polygon is kept where the shipped
    navmesh had walkable floor (so exclusions the designers painted survive) or inside a dirty
    box (where edits can create floor); other polygons get flags 0, which the game's query
    filter skips. Polygons take the flags and name hash of the shipped polygon under them. A tile
    whose rebuild would drop one of its off-mesh links (window crossings, climbs) keeps its
    shipped data.
    """
    triangles = [(a, c, b) for a, b, c in triangles]
    mesh = navigation.decode(body)
    settings = Settings.from_raw(mesh.config.raw)
    old_by_xy = {}
    for tile in mesh.tiles:
        decoded = navigation.decode_tile(tile.data)
        old_by_xy[(decoded.x, decoded.y)] = (tile, decoded)
    old_tiles = [decoded for _, decoded in old_by_xy.values()]
    surfaces = _SurfaceIndex(old_tiles)
    links, link_extras = [], {}
    for tile in old_tiles:
        for start, end, radius, extra_float, poly, flags, side, user in tile.off_mesh:
            links.append((start, end, radius, bool(flags & 1), user))
            link_extras[user] = extra_float
    columns = math.ceil((settings.bmax[0] - mesh.origin[0]) / mesh.tile_width)
    rows = math.ceil((settings.bmax[2] - mesh.origin[2]) / mesh.tile_width)
    margin = settings.agent_radius + settings.cell_size * 4
    if dirty is None:
        grid = [(x, y) for y in range(rows) for x in range(columns)]
    else:
        grid = []
        for y in range(rows):
            for x in range(columns):
                x0 = mesh.origin[0] + x * mesh.tile_width
                z0 = mesh.origin[2] + y * mesh.tile_width
                if any(box[0] - margin <= x0 + mesh.tile_width and box[2] + margin >= x0 and
                       box[1] - margin <= z0 + mesh.tile_width and box[3] + margin >= z0
                       for box in dirty):
                    grid.append((x, y))
    if not grid:
        return body, RebuildReport(len(mesh.tiles), 0, 0, len(links), len(links))
    # Shipped floor outside the edits is extra walkable input: some shipped floor has no geometry
    # under it (the original tool had more input than the current collision), and keeping it
    # keeps rebuilt tiles faithful away from the edit and anchors window crossings and climbs.
    vertices_m, triangles = list(vertices_m), list(triangles)
    wanted = {(x + dx, y + dy) for x, y in grid for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    for (x, y), (_, decoded) in old_by_xy.items():
        if (x, y) not in wanted:
            continue
        for poly, (a, b, c) in decoded.triangles():
            centre = tuple((a[i] + b[i] + c[i]) / 3 for i in range(3))
            if not poly.flags or _inside(centre, dirty or [], margin):
                continue
            # Shipped floor is already eroded by the agent radius; inflate it so Recast's erosion
            # brings it back to its shipped extent instead of shrinking it twice.
            grown = []
            for corner in (a, b, c):
                dx, dz = corner[0] - centre[0], corner[2] - centre[2]
                length = math.hypot(dx, dz) or 1.0
                grow = (settings.agent_radius + settings.cell_size) * 2.0
                grown.append((corner[0] + dx / length * grow, corner[1], corner[2] + dz / length * grow))
            a, b, c = grown
            base = len(vertices_m)
            vertices_m += [a, b, c]
            up = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
            triangles.append((base, base + 1, base + 2) if up > 0 else (base, base + 2, base + 1))
    request = _request(settings, mesh, vertices_m, triangles, grid, links)
    with tempfile.TemporaryDirectory(prefix='boz-navmesh-') as directory:
        request_path = Path(directory) / 'request.bin'
        reply_path = Path(directory) / 'tiles.bin'
        request_path.write_bytes(request)
        subprocess.run([str(helper or helper_path()), str(request_path), str(reply_path)],
                       check=True, capture_output=True)
        built = {(x, y): data for x, y, data in _read_reply(reply_path.read_bytes())}
    tolerance = settings.agent_max_climb
    boxes = dirty or []
    report = RebuildReport(0, 0, 0, len(links), 0)

    def tag(index, centre):
        old = surfaces.find(centre, tolerance)
        if old is None:
            return (1, 0) if _inside(centre, boxes, settings.agent_radius) else (0, 0)
        if old.flags != 1 or old.extra:
            report.tagged += 1
        return old.flags, old.extra

    tile_bits = max(1, math.ceil(math.log2(mesh.max_tiles)))
    poly_bits = max(1, math.ceil(math.log2(mesh.max_polygons)))
    tiles = {xy: tile for xy, (tile, _) in old_by_xy.items()}
    used = {(tile.reference >> poly_bits) & ((1 << tile_bits) - 1) for tile in mesh.tiles}
    kept_for_links = 0
    for xy in grid:
        old = old_by_xy.get(xy)
        stock = built.get(xy)
        data = to_boz_tile(stock, tag, link_extras) if stock is not None else None
        decoded = navigation.decode_tile(data) if data is not None else None
        old_links = old[1].off_mesh_count if old else 0
        if old_links and (decoded is None or decoded.off_mesh_count < old_links):
            kept_for_links += 1
            continue
        if decoded is not None and len(decoded.polys) > mesh.max_polygons:
            raise ValueError(f'tile {xy} has more polygons than the level allows')
        if decoded is None or not any(poly.flags for poly in decoded.polys):
            tiles.pop(xy, None)
            continue
        if old is not None:
            reference = old[0].reference
        else:
            free = next(index for index in range(mesh.max_tiles) if index not in used)
            used.add(free)
            reference = (1 << (tile_bits + poly_bits)) | (free << poly_bits)
        tiles[xy] = navigation.NavTile(reference, data)
        report.polys += len(decoded.polys)
        report.links_placed += decoded.off_mesh_count
    if len(tiles) > mesh.max_tiles:
        raise ValueError(f'navmesh needs {len(tiles)} tiles; the level allows {mesh.max_tiles}')
    order = {tile.reference: index for index, tile in enumerate(mesh.tiles)}
    mesh.tiles = sorted(tiles.values(), key=lambda tile: order.get(tile.reference, len(order)
                                                                    + tile.reference))
    report.tiles = len(grid) - kept_for_links
    report.reachable = kept_for_links
    return navigation.encode(mesh), report


def build(body: bytes, vertices_m, triangles, *, helper: Path | None = None) -> bytes:
    """A new navmesh for new geometry, on *body*'s settings and tile grid (a shipped navmesh as
    template). Every tile the geometry touches is built; all floor is plain walkable (flags 1, no
    name) and there are no off-mesh links. Input as for :func:`rebuild`."""
    triangles = [(a, c, b) for a, b, c in triangles]
    mesh = navigation.decode(body)
    settings = Settings.from_raw(mesh.config.raw)
    if not vertices_m:
        raise ValueError('a navmesh needs walkable geometry')
    columns = math.ceil((settings.bmax[0] - mesh.origin[0]) / mesh.tile_width)
    rows = math.ceil((settings.bmax[2] - mesh.origin[2]) / mesh.tile_width)
    xs = [v[0] for v in vertices_m]
    zs = [v[2] for v in vertices_m]
    if min(xs) < settings.bmin[0] or max(xs) > settings.bmax[0] or \
            min(zs) < settings.bmin[2] or max(zs) > settings.bmax[2]:
        raise ValueError('geometry lies outside the navmesh bounds of the template')
    first_x = max(0, math.floor((min(xs) - mesh.origin[0]) / mesh.tile_width) - 1)
    last_x = min(columns - 1, math.floor((max(xs) - mesh.origin[0]) / mesh.tile_width) + 1)
    first_y = max(0, math.floor((min(zs) - mesh.origin[2]) / mesh.tile_width) - 1)
    last_y = min(rows - 1, math.floor((max(zs) - mesh.origin[2]) / mesh.tile_width) + 1)
    grid = [(x, y) for y in range(first_y, last_y + 1) for x in range(first_x, last_x + 1)]
    request = _request(settings, mesh, vertices_m, triangles, grid, [])
    with tempfile.TemporaryDirectory(prefix='boz-navmesh-') as directory:
        request_path = Path(directory) / 'request.bin'
        reply_path = Path(directory) / 'tiles.bin'
        request_path.write_bytes(request)
        subprocess.run([str(helper or helper_path()), str(request_path), str(reply_path)],
                       check=True, capture_output=True)
        built = _read_reply(reply_path.read_bytes())
    tile_bits = max(1, math.ceil(math.log2(mesh.max_tiles)))
    poly_bits = max(1, math.ceil(math.log2(mesh.max_polygons)))
    tiles = []
    for x, y, stock in sorted(built, key=lambda item: (item[1], item[0])):
        data = to_boz_tile(stock, lambda index, centre: (1, 0), {})
        decoded = navigation.decode_tile(data)
        if not decoded.polys:
            continue
        if len(decoded.polys) > mesh.max_polygons:
            raise ValueError(f'tile {(x, y)} has more polygons than the level allows')
        if len(tiles) >= mesh.max_tiles:
            raise ValueError(f'the navmesh needs more than {mesh.max_tiles} tiles')
        tiles.append(navigation.NavTile((1 << (tile_bits + poly_bits)) | (len(tiles) << poly_bits),
                                        data))
    if not tiles:
        raise ValueError('Recast found no walkable floor in the geometry')
    mesh.tiles = tiles
    return navigation.encode(mesh)


def coverage(a_tiles, b_tiles, tolerance: float = 0.3) -> float:
    """Fraction of walkable area of *a* (by triangle centres) that *b* also covers."""
    index = _SurfaceIndex(b_tiles)
    total = covered = 0.0
    for tile in a_tiles:
        for _, (p, q, r) in _tile_triangles(tile):
            area = abs((q[0] - p[0]) * (r[2] - p[2]) - (q[2] - p[2]) * (r[0] - p[0])) / 2
            centre = tuple((p[i] + q[i] + r[i]) / 3 for i in range(3))
            total += area
            if index.find(centre, tolerance) is not None:
                covered += area
    return covered / total if total else 1.0
