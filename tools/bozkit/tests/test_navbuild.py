"""Incremental navmesh rebuild on synthetic geometry (needs tools/navmesh built)."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import blender_scene, navbuild, navigation  # noqa: E402

try:
    HELPER = navbuild.helper_path()
except FileNotFoundError:
    HELPER = None

TILE = 6.4


def empty_navmesh() -> bytes:
    """A CIsNavMesh with the tutorial's settings, a 2 x 1 tile grid and no tiles."""
    bmin, bmax = (0.0, -1.0, 0.0), (2 * TILE, 3.0, TILE)
    config = struct.pack('<6f2i2fi2fi3f3f', 0.3, 0.2, 1.5, 0.4, 0.4, 45.0, 8, 20, 12.0, 1.3, 6,
                         6.0, 1.0, 32, *bmin, *bmax)
    mesh = navigation.NavMesh(navigation.RecastConfig(0.3, 0.2, 1.5, 0.4, 0.4, 45.0, config), 1,
                              bmin, TILE, TILE, 256, 16384, [])
    return navigation.encode(mesh)


def floor():
    """A flat floor across both tiles, in the game's winding (clockwise seen from above)."""
    vertices = [(0.0, 0.0, 0.0), (2 * TILE, 0.0, 0.0), (2 * TILE, 0.0, TILE), (0.0, 0.0, TILE)]
    return vertices, [(0, 1, 2), (0, 2, 3)]


def add_box(vertices, triangles, centre, half):
    base = len(vertices)
    for corner in range(8):
        vertices.append(tuple(centre[i] + (half[i] if corner >> i & 1 else -half[i])
                              for i in range(3)))
    triangles += [(base + a, base + c, base + b) for a, b, c in blender_scene._BOX_FACES]


def walkable(body, point):
    tiles = [navigation.decode_tile(tile.data) for tile in navigation.decode(body).tiles]
    found = navbuild._SurfaceIndex(tiles).find(point, 0.5)
    return found is not None and found.flags != 0


@unittest.skipIf(HELPER is None, 'tools/navmesh is not built')
class NavRebuildTests(unittest.TestCase):
    def setUp(self):
        vertices, triangles = floor()
        everywhere = [(0.0, 0.0, 2 * TILE, TILE)]
        self.shipped, report = navbuild.rebuild(empty_navmesh(), vertices, triangles,
                                                dirty=everywhere)
        self.assertEqual(report.tiles, 2)

    def test_fresh_build_for_new_geometry(self):
        vertices, triangles = floor()
        built = navbuild.build(empty_navmesh(), vertices, triangles)
        mesh = navigation.decode(built)
        self.assertEqual(len(mesh.tiles), 2)
        self.assertEqual(len({tile.reference for tile in mesh.tiles}), 2)
        for tile in mesh.tiles:
            decoded = navigation.decode_tile(tile.data)
            self.assertTrue(all((poly.flags, poly.extra) == (1, 0) for poly in decoded.polys))
            self.assertEqual(decoded.off_mesh_count, 0)
        self.assertTrue(walkable(built, (3.2, 0.0, 3.2)))
        with self.assertRaises(ValueError):
            navbuild.build(empty_navmesh(), [(v[0] + 50, v[1], v[2]) for v in vertices],
                           triangles)

    def test_layout_and_walkable_floor(self):
        mesh = navigation.decode(self.shipped)
        self.assertEqual(len(mesh.tiles), 2)
        for tile in mesh.tiles:
            decoded = navigation.decode_tile(tile.data)  # validates the 40-byte BOZ layout
            self.assertTrue(decoded.polys and all(poly.flags == 1 for poly in decoded.polys))
        self.assertTrue(walkable(self.shipped, (3.2, 0.0, 3.2)))
        self.assertTrue(walkable(self.shipped, (9.6, 0.0, 3.2)))

    def test_obstacle_rebuilds_only_its_tile(self):
        vertices, triangles = floor()
        add_box(vertices, triangles, (3.2, 1.0, 3.2), (1.0, 1.0, 1.0))
        rebuilt, report = navbuild.rebuild(self.shipped, vertices, triangles,
                                           dirty=[(2.2, 2.2, 4.2, 4.2)])
        self.assertEqual(report.tiles, 1)
        before = {tile.reference: tile.data for tile in navigation.decode(self.shipped).tiles}
        after = {tile.reference: tile.data for tile in navigation.decode(rebuilt).tiles}
        self.assertEqual(set(before), set(after))
        changed = [reference for reference in before if before[reference] != after[reference]]
        self.assertEqual(len(changed), 1)
        self.assertFalse(walkable(rebuilt, (3.2, 0.0, 3.2)))      # under the box
        self.assertTrue(walkable(rebuilt, (1.2, 0.0, 1.2)))       # same tile, open floor
        self.assertTrue(walkable(rebuilt, (9.6, 0.0, 3.2)))       # untouched tile

    def test_floor_outside_edits_keeps_shipped_extent(self):
        # A rebuilt tile keeps only floor the shipped navmesh had, or floor inside the edit.
        vertices, triangles = floor()
        vertices.append((20.0, 0.0, 20.0))  # unrelated geometry does not matter
        rebuilt, _ = navbuild.rebuild(self.shipped, vertices, triangles,
                                      dirty=[(0.0, 0.0, 1.0, 1.0)])
        self.assertTrue(walkable(rebuilt, (3.2, 0.0, 3.2)))

    def test_untouched_rebuild_is_identical(self):
        vertices, triangles = floor()
        rebuilt, report = navbuild.rebuild(self.shipped, vertices, triangles, dirty=[])
        self.assertEqual(rebuilt, self.shipped)


if __name__ == '__main__':
    unittest.main()
