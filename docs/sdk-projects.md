# SDK projects

An SDK project is the editable source for one BOZ Redux mod. It can contain Lua, complete or
modified game assets, and files made from scratch. Building it creates the folder the client loads;
packaging it creates the same folder in a reproducible ZIP.

The SDK never silently removes game-derived files. The development profile accepts them. The
distribution profile warns when a file has been marked as game-derived so the author can decide
what they are permitted to share. Game assets and derived files must not be committed to the
official BOZ Redux repositories.

## Install the tools

From the SDK checkout:

```bash
python3 -m pip install -e .
# Include the desktop application:
python3 -m pip install -e '.[desktop]'
```

The installed commands are `bozkit` and `boz-sdk`. Without installing, run the CLI from
`tools/bozkit` as `python3 -m bozkit`.

## Create and build a project

```bash
bozkit new my-mod --id my_mod --name "My mod" --author "Your name"
bozkit inspect my-mod
bozkit validate my-mod
bozkit build my-mod
bozkit install my-mod --client ../boz-redux
bozkit package my-mod
```

`build` writes `build/<mod id>/`. `package` writes
`build/<mod id>-<version>.zip`. Builds contain a `boz-build.json` report with the project schema,
profile, dependencies, provenance entries, warnings, and SHA-256 of every output file. ZIP paths,
timestamps and ordering are normalized so identical inputs produce identical archives.

Installation refuses to replace an existing mod unless `--force` is passed.

## Project layout

```text
my-mod/
  boz-project.toml
  scripts/
    main.lua
    boz/                 a copy of the standard library
    .luarc.json          tells Lua editors (VS Code with LuaLS) where boz.* is
  assets/
  build/                 generated and ignored
```

A new project's manifest (schema 2):

```toml
schema = 2

[mod]
id = "my_mod"
name = "My mod"
version = "0.1.0"
author = "Your name"
game = "1.0.11"
description = ""

[project]
kind = "script"          # "script" (a Lua mod) or "map" (a level made in the editor)

[paths]
scripts = "scripts"
assets = "assets"

[build]
include_standard_library = false
```

A map project also has a `[map]` table with the level's internal `name` (the mod id with `-`
turned into `_`; it cannot be one of the game's own level names) and the `template` it started
from (`empty`, `debug`, `kino`, `callofthedead`, `ascension` or `tutorial`).

### Map worlds

A map project's world is source the compiler reads, in `source/`. The editor writes it on every
save; it can also be edited by hand.

```text
source/
  world.json             base level, meshes, props, instances, entities
  meshes/<name>.json     level geometry: vertices (centimetres, Y up, world space), UVs,
                         triangles, and per triangle which texture it uses
  props/<name>.json      a prop's geometry, in its own space
  textures/<name>.png    textures (power-of-two sides, 4 to 1024); <name>_1.png, ... for a
                         mesh's further textures
```

```json
{
  "format": 2,
  "base": "kino",
  "meshes": [
    {"name": "floor", "file": "meshes/floor.json", "textures": ["textures/floor.png"], "collision": "floor", "double_sided": true}
  ],
  "props": [
    {"name": "crate", "file": "props/crate.json", "textures": ["textures/crate.png"], "collision": "solid", "shape": "box", "double_sided": false}
  ],
  "instances": [
    {"prop": "crate", "position": [300.0, 0.0, 300.0], "yaw": 45.0},
    {"model": "levels/kino/alley_shared.group.bin#0x1a2b3c4d", "collision": "solid", "shape": "box", "position": [0.0, 0.0, 600.0], "yaw": 90.0}
  ],
  "entities": [
    {"source": "spawn_player_1", "position": [-100.0, 5.0, -100.0], "yaw": 0.0},
    {"source": "0x9f1e2d3c", "group": "ingame/ingame.group.bin", "position": [600.0, 0.0, -600.0], "yaw": 180.0}
  ]
}
```

- `base` is the shipped level that provides the rounds, zombie types, sounds, cameras, weapons
  and arms. With `"inherit": true` the map is the **whole base level** (rooms, entities,
  navmesh) plus the world's contents: the original-map templates.
- **Meshes** are level geometry, each a model with its textures and materials. Triangles use the
  game's winding; `double_sided` also draws their backs. `collision` is `floor` (walkable:
  players stand on it and the navmesh is built on its top), `solid` (blocking: nobody passes
  through or walks on it; it cuts the navmesh) or `none` (decoration). The editor calls these
  Walkable, Blocking and None.
- **Props** are models of the project's own, in their own space, placed any number of times by
  **instances**. An instance can also place a **game model** (`<group path>#0x<hash>`); the
  compiler copies the model, its materials and its textures into the level. A prop or model's
  `shape` is `box` (its bounds) or `mesh` (its triangles) for collision.
- **Entities** are copies of the game's entities (perks, spawns, the power switch, ...), by name
  or `0x` hash, from the base level or from any `group`. Templates without a transform (in
  `ingame`) get one. Placing the same entity again makes a renamed copy; in an inherited map the
  first placement of a base-level entity (by its `0x` hash, without `piece` or `group`) moves and
  edits the original, and later ones are copies. `removed` lists base-level entities (`0x`
  hashes) taken out of an inherited map; the navmesh around them is rebuilt. `piece` names the toolkit piece it
  came from, `fields` sets its settings (`"CPerk.m_perkSinglePCost": 2000`; names and the power
  link as names, `0` for none) and `prop` draws a project prop instead of its own model, keeping
  its behaviour. Zombie spawn points become the starting area's spawns in a generated map.
- Instances and entities have a `position`, a `rotation` (x, y, z, w quaternion in the game's
  axes; older files have a `yaw` in degrees) and an optional `scale`. An entity's scale
  multiplies its own (wall buys and weapons are drawn at 1/64).
- **Repacking:** an entity or model from another map brings what it uses (models, materials,
  textures, animation skins, skeletons, animations, state machines, sounds), found by name hash in
  that map's groups and `ingame` and copied into the level unless the level already loads it.
  Weapons are not repacked: a wall buy sells a weapon of the level's own weapons group.
- `"boz.weapon"` in a wall buy's `fields` picks its weapon: its "model" child's asset name,
  skeleton, model and skin are set from a shipped wall buy of that weapon, else from the weapon.
- **Chalk:** a shipped wall buy's chalk drawing is a separate decal (a quad with a 128 x 64
  texture) next to it. Each placed wall buy gets one at the same offset (`bozkit.chalk`): the
  weapon's own chalk when the game has one, else an outline drawn from the weapon model's side
  silhouette. `"boz.chalk"` in its `settings` is `""` (automatic), `"none"`, or an image in
  `source/chalk/`.
- **Doors** gate the navmesh as in the shipped maps: the floor under a door's collision box is
  cut out as its own polygons, flagged as door floor (flags | 2) with the door's name, so players
  and zombies pass only once the door is bought. Copies get names of their own; doors in
  generated maps unlock no areas.
- Map projects get `require("boz.world").start()` in `main.lua` at build time, with the SDK's
  `boz/world.lua`: it powers perk machines whose power switch is `boz_no_power` (the editor's
  "Needs power" off), as the game powers Quick Revive in solo. Pack-a-Punch gets
  `m_HasPower`; doors and trap switches without a power switch need none.
- The compiler (`bozkit.world.compile_world`) writes the level's groups into the mod's assets.
  A generated map gets a collision mesh and a navmesh built from its floor and solid geometry
  (entities with a model get a box). An inherited map adds its own collision entity and rebuilds
  only the navmesh tiles near what changed.

Templates: **Empty** is a 6 m floor and the four player spawns (no zombie spawns; the Colt is
the only weapon). **Debug arena** is a walled 24 m square with the base level's starting-area
zombie spawns, Juggernog and the power switch. **Kino der Toten, Call of the Dead, Ascension and
the Tutorial** inherit the whole original map. All but Empty need the asset library.

Building a map needs the game's groups: `bozkit build` reads the SDK's asset library, or the
client pack given with `--client`.

New projects carry their own copy of the standard library in `scripts/boz`, so editors can
autocomplete it; the launcher refreshes the copy. With `include_standard_library = true` the
compiler copies the SDK's current `lib/boz` into `scripts/boz` at build time instead. Schema 1
projects still load; the SDK writes schema 2 when it saves one.

`bozkit new` takes `--kind script|map` and `--template`. Script templates: `blank`, `round` (code
at every round start), `hotkey` (a key runs a console line) and `settings` (pause-menu settings).

Dependencies are recorded in the build report and generated manifest:

```toml
[[dependencies]]
id = "another_mod"
version = ">=0.2.0"
```

The current client does not enforce dependency versions yet. Recording them now makes projects
forward-compatible with that client capability.

## Asset provenance and validation

Provenance is optional and informational:

```toml
[[provenance]]
path = "assets/kino_statics.group.bin"
kind = "game-derived"
note = "Edited from the user's installed 1.0.11 data"
```

Supported conventions are `authored`, `game`, `game-derived`, `extracted`, `generated`, and
`unknown`; custom values are retained. Distribution validation warns for `game`, `game-derived`
and `extracted`. It does not fail the build or omit the file.

```bash
bozkit validate my-mod --profile development
bozkit validate my-mod --profile distribution
```

## Extract installed assets

The extraction command delegates to `dade` and always passes `--no-delete` for DZ archives:

```bash
bozkit extract blackops_etc.dz extracted/
bozkit extract kino_statics.group.bin kino_statics/ --kind group
```

The original source archive remains in place.

## Desktop application (the SDK launcher)

Run `boz-sdk` (or `./boz-sdk` in the SDK checkout without installing). On the first run it asks
for the BOZ Redux client folder and checks that the game data is installed; without it, maps
can't be built, but script-only projects still work.

- **Projects:** the project list, with search and sorting. **New project** makes a map or a
  script-only mod from a template; projects go in `~/BOZ Projects` by default. Open, Duplicate,
  Rename, Delete (to the trash), Show in file manager and Remove from list work on the selected
  project.
- **Project page:** edit the details, **Open folder** (VS Code if installed, else the file
  manager), **Run in game** for script mods (installs the mod and the Developer mod into the
  client, then starts the game), and the game log filtered to the mod and errors. For maps,
  **Build & Run** compiles the world, installs the mod last in the load order with the Developer
  mod, and the Developer mod starts the level once the main menu is up. **Open in Editor**
  opens a map in the BOZ Redux editor (Blender with the SDK's app template; see
  `blender/README.md`), which has its own Build & Run with start options (unlimited health or
  points, starting points).
- **Client:** the client folder, its game data, and the installed mods, which can be switched on
  and off; **Open client launcher** starts the client's own launcher.
- **Library:** every Zombies asset in the game with previews (see *Asset library* below).
  Search by name, description or `0x` hash, filter by kind and map, and copy an asset's name or
  hash for scripts.
- **Learn:** the guides and references, and the Developer and Redux mods as examples.
- **Settings:** client folder, where new projects go, default author, the editor's Blender
  (automatic: the SDK's own, else `blender` on PATH), and **Rebuild library**.

Settings and the project list live in the SDK data folder (`~/.local/share/boz-redux-sdk` on
Linux, `%APPDATA%\BOZ Redux SDK` on Windows; `BOZ_SDK_HOME` overrides it). The launcher uses the
same compiler as `bozkit` and never writes game formats itself.

## Asset library

The launcher builds the asset library from the user's own game files the first time it sees
installed game data, in the background (about 30 seconds), and again whenever the game files or
the library format change. Nothing in it is shipped or committed. It lives in the SDK data folder
under `library/1.0.11/`:

| Path | What it is |
|------|------------|
| `groups/` | Pristine copies of every Zombies group from `blackops_etc.dz`; map templates start from these |
| `index.sqlite` | One row per asset: kind, hash, variant, name, label, description, groups, maps, size, triangles, thumbnail |
| `thumbs/` | 128-pixel previews: textures, models (flat-shaded with their materials' colours), map loading screens |
| `names.txt` | Names recovered from the game's strings, for hash lookups |
| `stamp.json` | The pack's size and time and the library version it was built from |

The game stores most resources by name hash only, so many assets have no name: the library labels
them from what uses them (for example *Model of Juggernog perk*) or shows the hash. The same name
can hold different contents in different groups (each map's loading screen, sounds, waves); each
distinct body is a separate *variant*, and references resolve in the referring group first, then
in the same map.

Kinds: props (entities with behaviour or a model, from the levels and `ingame`), weapons, models,
textures, materials, effects, sounds and animations. `bozkit.library.Library` reads the index for
other tools (the editor's palettes use the same index).
