# Blender: the BOZ Redux editor and the map tools

Two parts live here:

- `boz_suite/`: the **BOZ Redux editor**, a Blender application template. The SDK launcher
  opens map projects in it (**Open in Editor**). `tools/build_suite.py` assembles it with the
  add-on and the bozkit modules into `build/suite/` (a Blender user scripts folder) and
  generates its `startup.blend` from `boz_suite/tabs.py`; the launcher rebuilds it in a checkout
  when the sources change. Test: `python3 blender/tests/run_suite_test.py`.
- `boz_redux/`: the add-on with the existing-map tools (below). In the editor they sit in the
  World tab's sidebar; on their own they install into any Blender 5.2.

## The editor

- **Weapons tab:** the project's weapons: Import from game (this map's or another map's, with
  models and animations), New weapon (a copy), every field with units and help, Pack-a-Punch
  result, Add script. See [docs/weapons.md](../docs/weapons.md).
- **Assets tab:** your own models: Import a high-quality .blend, FBX, glTF or OBJ as a Prop or
  a Weapon, Make game version (reduced to the Stock or PC preset's triangles and textures, the
  normal map baked into the colour), Game checks with fixes, Save edits, Refresh from source,
  Place in map (also Add → My assets and the palette's My assets). See
  [docs/assets.md](../docs/assets.md).
- **Tabs:** Game, World, Weapons, Characters, Assets, Effects, Animation, Scripts, Audio,
  UI / HUD, drawn in the top bar in that order. **Build & Run** (and its ⚙ settings) is at the
  right of the top bar on every tab. The menus are Project, Edit and Help.
- **Properties** shows only Object, Modifiers, Data and Material; stock panels that cannot reach
  the game are hidden. The object tab's **Game** panel shows what the object is and its settings.
- **Log** areas show build output and the game's `boz-log.txt`; the sidebar's **Problems** tab
  lists what would stop a build, with a button that selects the object.
- **Three kinds of object** (`boz_suite/convert.py`; the world format in `docs/sdk-projects.md`).
  Every object's name is its name in the game and in scripts.
  - **Model**: a mesh you see and bump into. A **game model** (from the palette) or **your own
    mesh** (built in Blender, Add → Game shapes, Project → Import model, or **Make editable** on
    a game model). Collision **Walkable / Blocking / None** with **Box / Mesh**; copies made with
    Alt+D share one mesh.
  - **Volume**: an invisible box that sends script events: **Trigger** (enter / exit), **Hit**
    (shot), **Use** (the player presses use; prompt text and cost). Drawn as a see-through box
    (teal, red, green); its size is its scale (100 cm at 1).
  - **Prefab**: one object made of parts. **Make prefab** (Ctrl+G, or Object menu) groups the
    selected models, volumes and prefabs under an Empty; **Ungroup** (Ctrl+Alt+G) takes it apart.
    A part keeps its **part name** inside the prefab (in the game: `<Prefab>.<Part>`); its
    object is named `<Prefab> › <Part>`, so searching the outliner for a prefab shows all of it.
    **Game prefabs** are the game's own: perk machines, Pack-a-Punch, the box, the power switch,
    wall buys, doors, barricades, traps, and the **level markers** (spawns, jump points, sound
    emitters), with their settings (cost, needs power, ...). They can be parts of your prefabs.
- **When the level starts** (models and prefabs): Visible, Collision, and **Blocks the walkable
  area** (the navmesh under it stays shut until a script opens it).
- **Script** (any object): **New** makes `scripts/prefabs/<Name>.lua` from a template and opens
  it in the **Scripts** tab's text editor (saving the map saves edited scripts; the small link
  button opens your own editor instead); **Pick…** uses an existing one. The script's `---@property` lines become fields in the
  panel, with values for each object ([docs/map-scripting.md](../docs/map-scripting.md)).
- **Prefab library:** **Save as new prefab** stores a prefab in `source/prefabs`; it appears in
  the asset browser under **My prefabs** (`boz_suite/prefab_library.py` writes the open project's
  prefabs into the palette folder), and dropping it places a copy. Each copy is independent.
  Project → Prefab library deletes library prefabs.
- **Original maps:** the base level's own entities (perks, doors, wall buys, spawns, triggers,
  traps, ...) are game prefabs from the original map: move, rotate, scale, delete (X) or copy
  (Shift+D) them, change their settings, start them hidden. Only what changed is written; **Put
  back as the level has it** undoes the edits. Rooms stay read only.
- **Building:** Add → **Game shapes** (also the World header's **Shapes** button) adds blocks,
  walls, floors, ramps, stairs and pillars at game size with a tiling default texture and the
  right Collision. Blender's own Add → Mesh shapes are 2 cm big here (one unit is a centimetre);
  the Problems panel flags anything that small. Project → **Import model…** brings in FBX, glTF
  and OBJ files, scaled from metres.
- **Markers:** game prefabs that draw no model are small cubes coloured by type.
- **Show** (World viewport header, and the sidebar's BOZ tab): Markers, Triggers (entity volumes),
  Links, and **Walkable** / **Collision**, which compile the map and show its navmesh (blue, orange
  where a door blocks it) and collision mesh. **Refresh** compiles again after edits.
- **Palettes:** the World tab's asset browser shows the "BOZ Game" library: **Game prefabs**
  (Machines, Buying, Doors, Barricades, Defence), **Level markers** (Spawns, Jump points, Sound),
  **Volumes** (Trigger, Hit, Use), and **Models** and **Textures** from every map. A dropped game
  prefab resolves to a working entity of the map's base level (else another map's, repacked,
  else the shared `ingame` template). `palette_build.py` builds it in a background Blender from
  the SDK's asset library (about 30 s, the first time and after the library changes);
  `palette.py` turns a dropped stand-in into the real thing, where it was dropped.
- **Edit its model** on a game prefab gives it an editable copy of its mesh: it keeps its
  behaviour (a Pack-a-Punch still upgrades weapons) and the game draws your mesh. **Use the
  game's model** goes back.
- **Wall buy** is one game prefab: **Choose…** picks any weapon of the level; the editor shows the
  weapon and its chalk (the weapon's own, one drawn from its model, your image, or none). **Doors**
  and **barricades** come in every design the game's maps have.
- **Textures** (Properties → Material): every slot's texture with its preview, **Replace…** from
  an image file, **From game…** (any game texture, with game shading) and **✕** (back to the
  default grid texture). Game models' textures need **Make editable** first. Dropping a texture from
  the palette gives the same game-shaded material.
- **Shading** matches the game: game models use the shipped-map tools' materials (vertex colours,
  lightmaps, blend modes), project materials are unlit, and the viewport is in material preview
  with the Standard view transform.
- **Placeholders:** every planned feature is a panel in its tab (`boz_suite/placeholders.py`).
- **Project link:** the launcher passes the project in `BOZ_PROJECT`. The first open builds the
  scene from `source/world.json` and saves `map.blend`; every save writes `source/` back (one
  Blender unit is one game centimetre). Scenes from older editors are converted when they open
  (level meshes and props become models, entities game prefabs).
- Background Blender cannot split areas or create editors in screens that are not shown, so
  each tab's editors are changed the first time the tab is on screen.

What Python cannot change in Blender (the case for a fork) is tracked in
`docs/internal/blender-walls.md`.

## Existing-map tools (add-on)

The add-on targets Blender 5.2 LTS and delegates all native parsing and writing to the bundled
`bozkit` modules. Build the installable ZIP from the repository root:

```bash
python3 tools/build_blender_addon.py
```

In Blender, open **Edit > Preferences > Add-ons**, install
`build/blender/boz-redux-blender.zip`, and enable **BOZ Redux Map Tools**. The **BOZ Redux** tab in
the 3D View sidebar provides import, validation, and export.

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

Do not save extracted game content inside this repository. Blender projects may contain it for
local development, but official BOZ repositories must not track those `.blend` files or exports.
