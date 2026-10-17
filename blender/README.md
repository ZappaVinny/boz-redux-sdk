# Blender: the BOZ Redux editor (code)

`boz_suite/` is the BOZ Redux editor, a Blender 5.2 LTS application template. How to use it is in
the documentation: [The map editor](../docs/map-editor.md) and [Weapons, models, effects and sounds](../docs/weapons-and-assets.md). This file is
a map of the code.

`tools/build_suite.py` assembles the editor with the bozkit modules into `build/suite/` (a Blender
user scripts folder) and generates its `startup.blend` from `boz_suite/tabs.py`; the SDK app
rebuilds it in a checkout when the sources change. Tests: `python3 blender/tests/run_suite_test.py`
(the editor) and `blender -b --factory-startup --python blender/tests/headless_roundtrip.py` (the
shipped-file tools); see [Contributing](../docs/contributing.md#working-on-the-sdk).

## Modules

| Module | What it does |
| --- | --- |
| `__init__.py` | Registers the editor |
| `_bozkit.py` | Imports bozkit: the SDK checkout's, else the copy the build carries |
| `shell.py` | Blender's top bar, menus and Properties editor reshaped for the game |
| `tabs.py` | The tabs (one workspace each) and how the startup file lays them out |
| `link.py` | The link to the project: open and save the world, the logs, Problems, Build & Run |
| `convert.py` | The project's world (`source/world.json`) and the Blender scene, both ways |
| `objects.py` | Models, volumes and prefabs: the Game panel, prefabs, scripts and their properties |
| `shapes.py` | Game-sized building shapes and model import |
| `game.py` | Game models built from the SDK's asset library, cached per model |
| `meshes.py` | Game resources as Blender objects: meshes, game-like materials, markers |
| `palette.py`, `palette_build.py` | The "BOZ Game" asset library in the World tab's asset browser |
| `prefab_library.py` | The "My prefabs" and "My assets" catalogs |
| `preview.py` | The navmesh and collision previews |
| `scene_view.py` | The overlays: show switches, link lines, the Selected panel |
| `game_tab.py` | The Game tab |
| `weapons_tab.py`, `weapon_view.py` | The Weapons and Animation tabs, and the weapon as one armature |
| `assets_tab.py`, `asset_build.py` | The Assets tab, and making a game version in a background Blender |
| `effects_tab.py` | The Effects tab |
| `sounds_tab.py` | The Audio tab |
| `placeholders.py` | Planned features, as panels in their tabs |
| `shipped_maps.py` | The Shipped files tools |

Background Blender cannot split areas or create editors in screens that are not shown, so each
tab's editors are changed the first time the tab is on screen. What Python cannot change in
Blender at all (the case for a fork) is tracked in `docs/internal/blender-walls.md`.

## Shipped-file tools

`boz_suite/shipped_maps.py` edits the game's own group files without a project: the editor's
**Shipped files** sidebar tab imports a group or a level folder, validates, and exports to files
or into a mod. The mesh and material builders they share with the rest of the editor are in
`boz_suite/meshes.py`; the overlays (markers, links, the Selected panel) in
`boz_suite/scene_view.py`.

Import currently creates separate collections for:

- independently movable `CIwModel` instances placed by `CIsEntitySpec` transform/renderable
  components;
- optional unmatched local-space `CIwModel` asset geometry;
- `CIsCollisionMeshSpec` collision geometry;
- `CIsPortal` visibility portals, including front/back sector properties.
- `CIsNavMeshConnection` traversal links as editable two-point edges.

Every object stores schema version, source group, class hash, resource index, and resource hash as
custom properties. Placed models additionally retain their entity-spec identity, allowing object
transforms and shared geometry to be written to the correct separate resources. Export writes a
new group and preserves unsupported and unchanged resources byte-for-byte. Model and collision
topology must remain unchanged in this first slice; transforms and vertex edits are supported.
Portal geometry and sector names are editable.

Coordinates are rotated losslessly from the game's right-handed Y-up basis into Blender's Z-up
basis, then rotated back during export.

Placed and local models resolve every native material triangle list. Raw BGRA8888/RGB565 and
cooked ETC1/DXT1 textures are decoded inside the add-on and packed into the Blender project; no
external texture converter or Pillow installation is required. Each GL primitive's serialized
material-array index is honored directly. Native render-vertex colours are copied to Blender face
corners and retained as `boz_native_colour`. The default editing preview displays the primary
decoded texture directly. It deliberately does not combine the colour stream with only texture
stage zero: shipped materials commonly use a second stage or shader technique, and presenting an
incomplete composition would make valid geometry misleadingly dark.

Never commit extracted game content or `.blend` files made from it.
