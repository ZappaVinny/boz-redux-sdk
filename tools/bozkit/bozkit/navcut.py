"""Tag areas of a shipped navmesh by cutting its polygons, without rebuilding anything.

A blocking object (a wall a script opens) needs the floor under it tagged with its name, so
NavMesh_SetTagOpen can shut and open it. Rebuilding the tile with Recast does that but loses
floor the designers made from other input than the level's collision (Kino's stairs are a ramp
under the steps; a rebuilt tile lost a quarter of them and players got stuck). Cutting instead
keeps every tile as shipped and only splits the polygons under each area along its outline:

- the pieces inside the outline take the area's tag (flags | DOOR_FLAG, the name hash);
- every new corner also goes into the neighbouring polygons whose edges it lies on, so shared
  edges still match exactly (Detour links polygons by shared edges);
- polygons over 6 corners are split into fans, heights come from the shipped detail surface,
  and the BV tree is rebuilt the way Detour builds it.
"""
from __future__ import annotations

import math
import struct

from . import navigation

DOOR_FLAG = 2
EPS = 1e-4          # metres: points closer than this in XZ are one point
MAX_VERTS = 6


# BV tree (Detour's dtNavMeshBuilder createBVTree)

def _longest_axis(x: int, y: int, z: int) -> int:
    axis, best = 0, x
    if y > best:
        axis, best = 1, y
    if z > best:
        axis = 2
    return axis


def bv_tree(tile: navigation.TileData, quant: float) -> list[tuple]:
    """BV tree nodes (bmin3, bmax3, index) over the tile's ground polygons, built as Detour's
    createBVTree does (median split along the longest axis). Boxes are in *quant* units from
    the tile's minimum, rounded outwards (polygon corners and detail heights), so every query
    Detour makes finds the polygons it should."""
    items = []
    for index, poly in enumerate(tile.polys):
        if poly.kind != 0 or not poly.vertices:
            continue
        points = [tile.vertices[v] for v in poly.vertices]
        vert_base, _tri_base, vert_count, _tri_count = tile.detail_meshes[index]
        points += tile.detail_vertices[vert_base:vert_base + vert_count]
        lo = [max(0, min(0xffff, math.floor((min(p[a] for p in points) - tile.bmin[a]) * quant)))
              for a in range(3)]
        hi = [max(0, min(0xffff, math.ceil((max(p[a] for p in points) - tile.bmin[a]) * quant)))
              for a in range(3)]
        items.append([lo, hi, index])
    nodes: list[list] = []

    def subdivide(lo_index: int, hi_index: int) -> None:
        count = hi_index - lo_index
        current = len(nodes)
        node = [None, None, 0]
        nodes.append(node)
        if count == 1:
            item = items[lo_index]
            node[0], node[1], node[2] = tuple(item[0]), tuple(item[1]), item[2]
            return
        part = items[lo_index:hi_index]
        bmin = tuple(min(it[0][a] for it in part) for a in range(3))
        bmax = tuple(max(it[1][a] for it in part) for a in range(3))
        node[0], node[1] = bmin, bmax
        axis = _longest_axis(bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2])
        part.sort(key=lambda it: it[0][axis])
        items[lo_index:hi_index] = part
        split = lo_index + count // 2
        subdivide(lo_index, split)
        subdivide(split, hi_index)
        node[2] = -(len(nodes) - current)

    if items:
        subdivide(0, len(items))
    return [tuple(node) for node in nodes]


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _area(points) -> float:
    """Signed area in XZ: positive when the points run counter-clockwise (x right, z up)."""
    return sum(points[i - 1][0] * points[i][1] - points[i][0] * points[i - 1][1]
               for i in range(len(points))) / 2


class _Cutter:
    """One tile: points are ids into self.points, each with its XZ, height and origin, so
    points on one original edge are shared by every polygon along that edge."""

    def __init__(self, tile: navigation.TileData):
        self.tile = tile
        self.points: list[tuple] = []     # (x, y, z)
        self.keys: dict = {}              # origin key -> point id
        self.on_edge: dict[int, tuple] = {}   # point id -> (i, j, t) along original edge i<j
        for index, vertex in enumerate(tile.vertices):
            self.points.append(tuple(vertex))
            self.keys[('v', index)] = index

    def xz(self, point_id):
        x, _y, z = self.points[point_id]
        return (x, z)

    def edges_of(self, point_id, poly_vertices) -> set:
        """Original edges (i, j), i < j, a point lies on (within the polygon it came from)."""
        if point_id < len(self.tile.vertices):
            n = len(poly_vertices)
            if point_id in poly_vertices:
                k = poly_vertices.index(point_id)
                return {tuple(sorted((point_id, poly_vertices[k - 1]))),
                        tuple(sorted((point_id, poly_vertices[(k + 1) % n])))}
            return set()
        edge = self.on_edge.get(point_id)
        return {edge[:2]} if edge else set()

    def edge_point(self, i: int, j: int, t: float) -> int:
        if i > j:
            i, j, t = j, i, 1 - t
        if t <= 1e-6:
            return i
        if t >= 1 - 1e-6:
            return j
        key = ('e', i, j, round(t, 6))
        if key not in self.keys:
            a, b = self.points[i], self.points[j]
            self.points.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
            self.keys[key] = len(self.points) - 1
            self.on_edge[len(self.points) - 1] = (i, j, t)
        return self.keys[key]

    def interior_point(self, poly_index: int, x: float, z: float) -> int:
        key = ('i', poly_index, round(x / EPS), round(z / EPS))
        if key not in self.keys:
            self.points.append((x, self.height(poly_index, x, z), z))
            self.keys[key] = len(self.points) - 1
        return self.keys[key]

    def height(self, poly_index: int, x: float, z: float) -> float:
        """Height of the shipped surface of a polygon at XZ (its detail triangles)."""
        tile = self.tile
        poly = tile.polys[poly_index]
        vert_base, tri_base, vert_count, tri_count = tile.detail_meshes[poly_index]
        best = None
        for tri in tile.detail_triangles[tri_base:tri_base + tri_count]:
            corners = [tile.vertices[poly.vertices[v]] if v < len(poly.vertices)
                       else tile.detail_vertices[vert_base + v - len(poly.vertices)] for v in tri[:3]]
            (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = corners
            d = (z2 - z3) * (x1 - x3) + (x3 - x2) * (z1 - z3)
            if abs(d) < 1e-12:
                continue
            l1 = ((z2 - z3) * (x - x3) + (x3 - x2) * (z - z3)) / d
            l2 = ((z3 - z1) * (x - x3) + (x1 - x3) * (z - z3)) / d
            l3 = 1 - l1 - l2
            outside = -min(l1, l2, l3)
            if best is None or outside < best[0]:
                best = (outside, l1 * y1 + l2 * y2 + l3 * y3)
        if best is None:
            ys = [tile.vertices[v][1] for v in poly.vertices]
            return sum(ys) / len(ys)
        return best[1]

    def clip(self, poly_index, loop, a, b, keep_inside):
        """Sutherland-Hodgman: the part of a convex loop (point ids) on one side of a->b."""
        original = self.tile.polys[poly_index].vertices
        out = []
        for k in range(len(loop)):
            p, q = loop[k - 1], loop[k]
            sp = _cross(a, b, self.xz(p))
            sq = _cross(a, b, self.xz(q))
            p_in = sp >= -1e-9 if keep_inside else sp <= 1e-9
            q_in = sq >= -1e-9 if keep_inside else sq <= 1e-9
            if q_in:
                if not p_in:
                    out.append(self.cross_point(poly_index, original, p, q, sp, sq))
                out.append(q)
            elif p_in:
                out.append(self.cross_point(poly_index, original, p, q, sp, sq))
        cleaned = []
        for point in out:
            if not cleaned or point != cleaned[-1]:
                cleaned.append(point)
        if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
            cleaned.pop()
        return cleaned

    def cross_point(self, poly_index, original, p, q, sp, sq) -> int:
        t = sp / (sp - sq) if sp != sq else 0.0
        if t <= 1e-9:
            return p
        if t >= 1 - 1e-9:
            return q
        shared = self.edges_of(p, original) & self.edges_of(q, original)
        if shared:
            i, j = next(iter(shared))
            ti = self.param(p, i, j)
            tj = self.param(q, i, j)
            return self.edge_point(i, j, ti + (tj - ti) * t)
        (px, pz), (qx, qz) = self.xz(p), self.xz(q)
        return self.interior_point(poly_index, px + (qx - px) * t, pz + (qz - pz) * t)

    def param(self, point_id, i, j) -> float:
        if point_id == i:
            return 0.0
        if point_id == j:
            return 1.0
        return self.on_edge[point_id][2]


def _fans(loop, xz):
    """Split a convex loop into convex loops of at most MAX_VERTS points: halve it along a
    diagonal whose two sides both have area (a diagonal along a straight run of points would
    leave a sliver), and repeat."""
    if len(loop) <= MAX_VERTS:
        return [loop]
    n = len(loop)
    best = None
    for i in range(n):
        for step in range(n // 2, 1, -1):
            j = (i + step) % n
            a = [loop[(i + k) % n] for k in range((j - i) % n + 1)]
            b = [loop[(j + k) % n] for k in range((i - j) % n + 1)]
            area_a, area_b = abs(_area([xz(v) for v in a])), abs(_area([xz(v) for v in b]))
            if min(area_a, area_b) < 1e-4:
                continue
            score = (max(len(a), len(b)), -min(area_a, area_b))
            if best is None or score < best[0]:
                best = (score, a, b)
            break
    if best is None:
        return [loop]
    return _fans(best[1], xz) + _fans(best[2], xz)


def cut_tile(data: bytes, areas, max_polygons: int) -> tuple[bytes, set]:
    """The tile with every area cut out of its polygons and tagged; returns (data, tagged name
    hashes). *areas*: (name hash, convex XZ outline in metres, min y, max y)."""
    tile = navigation.decode_tile(data)
    cutter = _Cutter(tile)
    ground = [i for i, p in enumerate(tile.polys) if p.kind == 0 and p.vertices]
    loops = {i: list(tile.polys[i].vertices) for i in ground}
    tags = {i: (tile.polys[i].flags, tile.polys[i].extra) for i in ground}
    source = {i: i for i in ground}
    changed = set()
    tagged = set()
    next_id = len(tile.polys)
    for name_hash, outline, low, high in areas:
        hull = list(outline)
        if _area(hull) < 0:
            hull.reverse()
        if len(hull) < 3:
            continue
        hx = [p[0] for p in hull]
        hz = [p[1] for p in hull]
        for poly_id in list(loops):
            loop = loops[poly_id]
            pts = [cutter.points[v] for v in loop]
            ys = [p[1] for p in pts]
            if max(ys) < low - 1.0 or min(ys) > high + 0.5:
                continue
            if (max(p[0] for p in pts) < min(hx) or min(p[0] for p in pts) > max(hx) or
                    max(p[2] for p in pts) < min(hz) or min(p[2] for p in pts) > max(hz)):
                continue
            original = source[poly_id]
            inside = loop
            for k in range(len(hull)):
                inside = cutter.clip(original, inside, hull[k - 1], hull[k], True)
                if len(inside) < 3:
                    break
            if len(inside) < 3 or abs(_area([cutter.xz(v) for v in inside])) < 1e-4:
                continue
            pieces, rest = [], loop
            for k in range(len(hull)):
                piece = cutter.clip(original, rest, hull[k - 1], hull[k], False)
                if len(piece) >= 3 and abs(_area([cutter.xz(v) for v in piece])) >= 1e-4:
                    pieces.append(piece)
                rest = cutter.clip(original, rest, hull[k - 1], hull[k], True)
            flags, extra = tags[poly_id]
            del loops[poly_id]
            loops[poly_id] = inside
            tags[poly_id] = (flags | DOOR_FLAG, name_hash)
            changed.add(poly_id)
            tagged.add(name_hash)
            for piece in pieces:
                loops[next_id] = piece
                tags[next_id] = (flags, extra)
                source[next_id] = original
                changed.add(next_id)
                next_id += 1
    if not changed:
        return data, set()
    # Every new point goes into every polygon edge it lies on, at the same height: edges along
    # an original edge and edges along the outline inside a cut polygon alike (no T-junctions;
    # Detour links two polygons only through an edge both have).
    new_points = range(len(tile.vertices), len(cutter.points))
    for poly_id, loop in list(loops.items()):
        out = []
        for k in range(len(loop)):
            u, v = loop[k], loop[(k + 1) % len(loop)]
            out.append(u)
            a, b = cutter.points[u], cutter.points[v]
            dx, dz = b[0] - a[0], b[2] - a[2]
            length2 = dx * dx + dz * dz
            if length2 < EPS * EPS:
                continue
            between = []
            for w in new_points:
                if w in (u, v) or w in loop:
                    continue
                c = cutter.points[w]
                t = ((c[0] - a[0]) * dx + (c[2] - a[2]) * dz) / length2
                if not 1e-6 < t < 1 - 1e-6:
                    continue
                off = abs((c[0] - a[0]) * dz - (c[2] - a[2]) * dx) / math.sqrt(length2)
                if off < EPS * 10 and abs(c[1] - (a[1] + (b[1] - a[1]) * t)) < 0.3:
                    between.append((t, w))
            for _t, w in sorted(between):
                out.append(w)
                changed.add(poly_id)
        loops[poly_id] = out
    # Final polygons: unchanged ones keep their index order first, then the rest.
    order = [i for i in ground] + sorted(k for k in loops if k not in ground)
    final = []      # (loop, flags, extra, source, changed)
    for poly_id in order:
        if poly_id not in loops:
            continue
        for piece in (_fans(loops[poly_id], cutter.xz) if poly_id in changed else [loops[poly_id]]):
            final.append((piece, *tags[poly_id], source[poly_id], poly_id in changed))
    off_mesh_polys = [p for p in tile.polys if p.kind == 1]
    if len(final) + len(off_mesh_polys) > max_polygons:
        raise ValueError(f'tile ({tile.x}, {tile.y}) would have more polygons than the level allows')
    # Neighbours: shared edges inside the tile; border portals and walls from the original edge.
    by_edge: dict[tuple, list] = {}
    for index, (loop, *_rest) in enumerate(final):
        for k in range(len(loop)):
            by_edge.setdefault(tuple(sorted((loop[k], loop[(k + 1) % len(loop)]))), []).append(index)
    original_nei = {}
    for i in ground:
        poly = tile.polys[i]
        for k in range(len(poly.vertices)):
            original_nei[tuple(sorted((poly.vertices[k], poly.vertices[(k + 1) % len(poly.vertices)])))] = poly.neighbours[k]
    polys, meshes, detail_vertices, detail_triangles = [], [], [], []
    for index, (loop, flags, extra, src, was_changed) in enumerate(final):
        neis = []
        for k in range(len(loop)):
            u, v = loop[k], loop[(k + 1) % len(loop)]
            others = [o for o in by_edge[tuple(sorted((u, v)))] if o != index]
            if others:
                neis.append(others[0] + 1)
                continue
            edge = None
            for i, j in cutter.edges_of(u, tile.polys[src].vertices) & cutter.edges_of(v, tile.polys[src].vertices):
                edge = (i, j)
            if u < len(tile.vertices) and v < len(tile.vertices):
                edge = tuple(sorted((u, v)))
            nei = original_nei.get(edge, 0) if edge else 0
            neis.append(nei if nei & 0x8000 else 0)
        src_poly = tile.polys[src]
        polys.append(navigation.NavPoly(list(loop), neis, flags, src_poly.area, 0, extra))
        if not was_changed:
            vert_base, tri_base, vert_count, tri_count = tile.detail_meshes[src]
            meshes.append((len(detail_vertices), len(detail_triangles), vert_count, tri_count))
            detail_vertices += tile.detail_vertices[vert_base:vert_base + vert_count]
            detail_triangles += tile.detail_triangles[tri_base:tri_base + tri_count]
        else:
            n = len(loop)
            tris = []
            for k in range(1, n - 1):
                edge_flags = (1 if k == 1 else 0) | (1 << 2) | ((1 if k + 1 == n - 1 else 0) << 4)
                tris.append((0, k, k + 1, edge_flags))
            meshes.append((len(detail_vertices), len(detail_triangles), 0, len(tris)))
            detail_triangles += tris
    # Off-mesh connections follow the ground polygons; their polygon index moves with them.
    ground_count = len(polys)
    off_mesh = []
    for k, poly in enumerate(off_mesh_polys):
        polys.append(poly)
        meshes.append((0, 0, 0, 0))
    for start, end, radius, extra_f, _poly, flags, side, user in tile.off_mesh:
        off_mesh.append((start, end, radius, extra_f, ground_count + len(off_mesh), flags, side, user))
    edges = sum(len(p.vertices) for p in polys[:ground_count])
    portals = sum(1 for p in polys[:ground_count] for n in p.neighbours if n & 0x8000)
    max_links = max(tile.max_link_count, edges + portals * 2 + len(off_mesh) * 4)
    out_tile = navigation.TileData(
        tile.x, tile.y, tile.layer, tile.walkable_height, tile.walkable_radius,
        tile.walkable_climb, tile.bmin, tile.bmax, list(cutter.points), polys, meshes,
        detail_vertices, detail_triangles, 0, len(off_mesh), max_links, off_mesh)
    _shipped_nodes, quant = navigation.decode_bv_nodes(data)
    nodes = bv_tree(out_tile, quant) if tile.bv_node_count else []
    if nodes:
        # Shipped tiles allocate two nodes per polygon; the unused ones are zero.
        nodes += [((0, 0, 0), (0, 0, 0), 0)] * (ground_count * 2 - len(nodes))
    user_id = struct.unpack_from('<I', data, 20)[0]
    return navigation.encode_tile(out_tile, user_id, nodes, quant), tagged


def cut_areas(body: bytes, areas) -> tuple[bytes, set]:
    """The navmesh with every area cut into the tiles it covers and tagged; returns (body,
    tagged name hashes). Tiles no area touches stay byte-identical."""
    if not areas:
        return body, set()
    mesh = navigation.decode(body)
    tagged = set()
    for tile in mesh.tiles:
        decoded = navigation.decode_tile(tile.data)
        touching = []
        for area in areas:
            _name, outline, low, high = area
            xs = [p[0] for p in outline]
            zs = [p[1] for p in outline]
            if (max(xs) < decoded.bmin[0] or min(xs) > decoded.bmax[0] or
                    max(zs) < decoded.bmin[2] or min(zs) > decoded.bmax[2]):
                continue
            touching.append(area)
        if touching:
            try:
                tile.data, names = cut_tile(tile.data, touching, mesh.max_polygons)
            except ValueError:
                continue    # over the level's polygon limit: the tile stays as shipped, untagged
            tagged |= names
    return navigation.encode(mesh), tagged
