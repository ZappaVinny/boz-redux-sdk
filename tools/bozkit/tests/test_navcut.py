"""Cutting tagged areas into a navmesh tile (synthetic tiles only)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import navcut, navigation  # noqa: E402


def two_squares(height=1.0):
    """A 4 x 2 m tile made of two 2 x 2 m squares sharing an edge; the outer edges on the tile's
    left and right borders are portals."""
    vertices = [(0.0, height, 0.0), (2.0, height, 0.0), (4.0, height, 0.0),
                (0.0, height, 2.0), (2.0, height, 2.0), (4.0, height, 2.0)]
    polys = [navigation.NavPoly([0, 3, 4, 1], [0x8004, 0, 2, 0], 1, 0, 0),
             navigation.NavPoly([1, 4, 5, 2], [1, 0, 0x8000, 0], 1, 0, 0)]
    meshes = [(0, 0, 0, 2), (0, 2, 0, 2)]
    tris = [(0, 1, 2, 1 | 4), (0, 2, 3, 4 | 16)] * 2
    tile = navigation.TileData(3, 4, 0, 1.5, 0.4, 0.4, (0.0, 0.0, 0.0), (4.0, 3.0, 2.0),
                               vertices, polys, meshes, [], tris, 0, 0, 16, [])
    quant = 1 / 0.15
    nodes = navcut.bv_tree(tile, quant)
    return navigation.encode_tile(tile, 7, nodes, quant)


def polygon_area(tile, poly):
    v = [tile.vertices[i] for i in poly.vertices]
    return abs(sum(v[i - 1][0] * v[i][2] - v[i][0] * v[i - 1][2] for i in range(len(v)))) / 2


class NavCutTests(unittest.TestCase):
    def test_encode_round_trip(self):
        data = two_squares()
        tile = navigation.decode_tile(data)
        nodes, quant = navigation.decode_bv_nodes(data)
        self.assertEqual(navigation.encode_tile(tile, 7, nodes, quant), data)
        self.assertEqual(sorted(n[2] for n in nodes if n[2] >= 0), [0, 1])

    def test_cut_across_the_shared_edge(self):
        data = two_squares()
        area = (0xabc, [(1.5, 0.5), (2.5, 0.5), (2.5, 1.5), (1.5, 1.5)], 0.5, 2.0)
        cut, tagged = navcut.cut_tile(data, [area], 64)
        self.assertEqual(tagged, {0xabc})
        tile = navigation.decode_tile(cut)
        total = sum(polygon_area(tile, p) for p in tile.polys)
        inside = sum(polygon_area(tile, p) for p in tile.polys if p.extra == 0xabc)
        self.assertAlmostEqual(total, 8.0, places=4)
        self.assertAlmostEqual(inside, 1.0, places=4)
        self.assertTrue(all(p.flags == 1 | navcut.DOOR_FLAG for p in tile.polys if p.extra == 0xabc))
        self.assertTrue(all(len(p.vertices) <= 6 for p in tile.polys))
        # Links go both ways, through edges both polygons have.
        for index, poly in enumerate(tile.polys):
            for k, nei in enumerate(poly.neighbours):
                if nei and not nei & 0x8000:
                    other = tile.polys[nei - 1]
                    edge = {poly.vertices[k], poly.vertices[(k + 1) % len(poly.vertices)]}
                    back = [other.neighbours[m] for m in range(len(other.vertices))
                            if {other.vertices[m], other.vertices[(m + 1) % len(other.vertices)]} == edge]
                    self.assertEqual(back, [index + 1])
        # No point lies inside another polygon's edge (Detour cannot link across those).
        for poly in tile.polys:
            for k in range(len(poly.vertices)):
                a = tile.vertices[poly.vertices[k]]
                b = tile.vertices[poly.vertices[(k + 1) % len(poly.vertices)]]
                for c_index, c in enumerate(tile.vertices):
                    if c_index in (poly.vertices[k], poly.vertices[(k + 1) % len(poly.vertices)]):
                        continue
                    if not any(c_index in q.vertices for q in tile.polys):
                        continue
                    cross = (b[0] - a[0]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[0] - a[0])
                    length2 = (b[0] - a[0]) ** 2 + (b[2] - a[2]) ** 2
                    t = ((c[0] - a[0]) * (b[0] - a[0]) + (c[2] - a[2]) * (b[2] - a[2])) / length2
                    self.assertFalse(abs(cross) < 1e-6 and 1e-6 < t < 1 - 1e-6,
                                     f'T-junction at {c} on {a}-{b}')
        # Border portals keep their side, over their whole length.
        portals = {}
        for poly in tile.polys:
            for k, nei in enumerate(poly.neighbours):
                if nei & 0x8000:
                    a = tile.vertices[poly.vertices[k]]
                    b = tile.vertices[poly.vertices[(k + 1) % len(poly.vertices)]]
                    portals[nei] = portals.get(nei, 0) + abs(a[2] - b[2])
        self.assertEqual({k: round(v, 4) for k, v in portals.items()}, {0x8004: 2.0, 0x8000: 2.0})
        nodes, _quant = navigation.decode_bv_nodes(cut)
        self.assertEqual(sorted(n[2] for n in nodes if n[2] >= 0 and n[1] != (0, 0, 0)),
                         list(range(len(tile.polys))))

    def test_areas_elsewhere_change_nothing(self):
        data = two_squares()
        far = (0x1, [(10.0, 10.0), (11.0, 10.0), (11.0, 11.0)], 0.5, 2.0)
        above = (0x2, [(1.5, 0.5), (2.5, 0.5), (2.5, 1.5), (1.5, 1.5)], 8.0, 9.0)
        cut, tagged = navcut.cut_tile(data, [far, above], 64)
        self.assertEqual((cut, tagged), (data, set()))

    def test_too_many_polygons(self):
        area = (0xabc, [(1.5, 0.5), (2.5, 0.5), (2.5, 1.5), (1.5, 1.5)], 0.5, 2.0)
        with self.assertRaises(ValueError):
            navcut.cut_tile(two_squares(), [area], 3)


if __name__ == '__main__':
    unittest.main()
