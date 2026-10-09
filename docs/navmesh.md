# Navigation meshes

Players and zombies walk on the level's Detour navmesh, not on its collision:
`CPlayerController::FixedStep` moves the player through `Player_MoveOnNavMesh`
(`Nav_FindNearestPoly`, `Nav_MoveAlongSurface`, `Nav_GetPolyHeight`). Collision decides what
bullets hit; the navmesh decides where anyone can go. When map edits change collision, the SDK
rebuilds the navmesh tiles around them.

## Build the helper

The rebuild runs Recast through a small native program, `boz-navmesh`, built from
`tools/navmesh` against the `tools/recast` submodule (recastnavigation 1.6.0, zlib licence):

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
git submodule update --init tools/recast
cmake -S tools/navmesh -B tools/navmesh/build -DCMAKE_BUILD_TYPE=Release
cmake --build tools/navmesh/build -j
python3 tools/build_blender_addon.py   # bundles the helper into the add-on
```

Without the helper, saving still works and reports that the navmesh was not rebuilt.

## How BOZ stores navmeshes

A `CIsNavMesh` resource holds the build settings and a tiled Detour v7 navmesh (see
[asset formats](asset-formats.md#navigation-meshes-cisnavmesh)). The 80-byte settings block is
RecastDemo's: cell size and height, agent height, radius, climb and slope, region minimum and
merge sizes, edge length and error, vertices per polygon, detail sampling distance and error,
tile size, and the build bounds. Tiles are `tile size × cell height` wide (32 × 0.15 = 4.8 m in
Kino; the original tool multiplied by the wrong cell dimension), and positions are metres, the
game's units divided by 100.

BOZ modified Detour. A polygon is 40 bytes instead of 32: `firstLink`, six vertices, six
neighbours, **32-bit flags**, a **32-bit name hash**, the vertex count, the area and type, and two
bytes of padding. An off-mesh connection is 40 bytes instead of 36: an extra float (0.9 in every
shipped link) follows the radius. Polygon flags and name hashes carry gameplay:

| Flag | Name hash | Meaning |
| --- | --- | --- |
| `0x1` | | walkable |
| `0x2` | a door's name | floor the door blocks until it opens |
| `0x4000` | a jump area (`CPlayerJumpPoint`) | jump point |
| `0x8` | | water (Call of the Dead) |
| `0x40`, `0x80`, `0x100`, `0x200`, `0x1000`, `0x8000` | | further area types, not yet identified |

Off-mesh connections are the zombie window crossings (one per barricade, named after the
barricade's plank entity), climbs (`TheatreLeft_Climb_1`) and drops from balconies. They are
one-way.

## How the rebuild works

The shipped navmeshes were built from the level's collision (79% of their surfaces lie within one
cell height of it), with triangles wound the opposite way to Recast's convention. Collision
boxes on entities count as obstacles; doors do not, because the navmesh runs under doors and
their tags gate it.

On save, the SDK builds this input from the game's original files and from the current level;
triangles that differ mark dirty areas, and only the tiles overlapping them are rebuilt from the
game's original navmesh with the stored settings. Because the comparison is always against the
game, repeated saves give the same result. **Rebuild navmesh** in the sidebar runs it even when
nothing else changed (it repairs mods saved by older add-on versions).

- Every other tile stays byte-identical. An untouched level keeps its navmesh exactly.
- In a rebuilt tile, polygons are kept where the shipped navmesh had floor or inside the edited
  areas. The original designers also cut areas away (for example the street outside Kino) that
  nothing in the level data describes; this keeps those cuts. Other polygons get flags 0, which
  the game's query filter skips.
- Outside the edited areas the shipped floor itself is extra walkable input (inflated by the
  agent radius, which Recast erodes again). Some shipped floor has no geometry under it at all,
  such as the drop-off point on Kino's lobby balcony, so this keeps rebuilt tiles faithful and
  keeps window crossings and climbs anchored.
- New polygons take the flags and name hash of the shipped polygon under them, so door gating,
  jump areas and water carry over.
- A tile whose rebuild would drop one of its window crossings or climbs keeps its shipped data.

Rebuilding every Kino tile at once (the worst case) reproduces 94% of the shipped walkable area,
96% of the rebuilt area lies on shipped floor, and 44 of the 48 window crossings and climbs are
rebuilt (the other four tiles keep their shipped data). In normal use only the tiles around an
edit are rebuilt.

## Limits

- Tags stay where they were: moving a door does not move the floor it gates.
- New window crossings and climbs cannot be added yet.
- Windows builds of the helper are not produced yet.
