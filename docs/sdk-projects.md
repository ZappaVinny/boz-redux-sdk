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

A map project keeps what the editor makes under `source/`: the world, weapons
(`source/weapons/`, [weapons.md](weapons.md)), assets (`source/assets/`, with their high-quality
sources in `assets/<name>/`, which the build never ships, [assets.md](assets.md)) and sounds
(`source/sounds/`, [sounds.md](sounds.md)), the effects it uses (`source/effects.json`,
[effects.md](effects.md)) and its rules (`source/game.json`, [game.md](game.md)).

### Map worlds

A map project's world is source the compiler reads, in `source/`. The editor writes it on every
save; it can also be edited by hand.

```text
source/
  world.json             base level, models, volumes, prefabs
  meshes/<name>.json     a mesh of the world's own: vertices (centimetres, Y up, the model's
                         own space), UVs, triangles, and per triangle which texture it uses
  textures/<name>.png    textures (power-of-two sides, 4 to 1024); <name>_1.png, ... for a
                         mesh's further textures
  prefabs/<Name>.json    the prefab library (with <Name>/meshes and <Name>/textures)
  weapons/index.json     the project's weapon list (Weapons tab; see weapons.md)
  weapons/<name>.json    a changed, new or imported weapon
  weapons/anims/<weapon>/<state>.json  your animations of a weapon (Animation tab)
  assets/<name>.json     an asset's settings (Assets tab; see assets.md)
  assets/<name>/         its game version: model.json, textures/N.png, stats.json
assets/<name>/<file>     the high-quality source the asset was made from (a copy)
```

A model can also be an asset (`{"name": "Gun", "asset": "idgun", ...}`): the build uses the
asset's game version, stored in tenths of a centimetre and placed at 0.1 scale.

```json
{
  "format": 3,
  "base": "kino",
  "meshes": [
    {"name": "wall", "file": "meshes/wall.json", "textures": ["textures/wall.png"], "double_sided": false}
  ],
  "models": [
    {"name": "Wall_1", "mesh": "wall", "collision": "solid", "shape": "mesh", "position": [0.0, 0.0, 300.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
    {"name": "Rock", "game": "levels/kino/alley_shared.group.bin#0x1a2b3c4d", "collision": "solid", "shape": "box", "position": [0.0, 0.0, 600.0], "rotation": [0.0, 0.0, 0.0, 1.0], "start": {"visible": false}}
  ],
  "volumes": [
    {"name": "Room", "volume": "trigger", "position": [0.0, 100.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "size": [400.0, 200.0, 400.0], "who": "players"}
  ],
  "prefabs": [
    {"name": "Vault_1", "script": "prefabs/Vault.lua", "properties": {"delay": 2.0}, "position": [500.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0],
     "parts": [{"name": "Door", "mesh": "wall", "collision": "solid", "shape": "mesh", "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "start": {"blocks": true}},
               {"name": "Skull", "volume": "hit", "position": [0.0, 150.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "size": [40.0, 40.0, 40.0], "who": "players", "once": true}]},
    {"name": "Juggernog", "source": "Juggernog", "piece": "juggernog", "settings": {"CPerk.m_perkSinglePCost": 2000}, "position": [-100.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
    {"name": "spawn_player_1", "source": "spawn_player_1", "piece": "player_spawn", "position": [-100.0, 5.0, -100.0], "rotation": [0.0, 0.0, 0.0, 1.0]}
  ]
}
```

- `base` is the shipped level that provides the rounds, zombie types, sounds, cameras, weapons
  and arms. With `"inherit": true` the map is the **whole base level** (rooms, entities,
  navmesh) plus the world's contents: the original-map templates.
- Every object has a `name` (letters, digits and `_`): its name in the game (`CIsNamed`) and in
  scripts. A prefab's parts are named `<Prefab>.<Part>` in the game. Positions are centimetres;
  `rotation` is an x, y, z, w quaternion in the game's axes, `scale` optional.
- **Models** draw one mesh: one of the world's `meshes` (`mesh`) or a game model (`game`:
  `<group path>#0x<hash>`, copied into the level with its materials and textures). Triangles use
  the game's winding; a mesh's `double_sided` also draws their backs. `collision` is `floor`
  (walkable: players stand on it and the navmesh is built on its top), `solid` (blocking: it cuts
  the navmesh) or `none`; `shape` is `box` (its bounds) or `mesh` (its triangles). The editor
  calls these Walkable, Blocking and None. Models sharing a mesh share one game model.
- **Volumes** are invisible boxes that send events to scripts: `trigger` (a ghost box made from
  Call of the Dead's snow trigger: enter / exit), `hit` (a musical easter egg skull with a song
  of its own, a sphere of the box's largest side: shot) and `use` (a point of interest without a
  game prompt: the player pressed use; `prompt` and `cost`). `who` is `players`, `zombies` or
  `anyone`; `once` fires the first time only. `size` is in centimetres.
- **Prefabs** are either yours (`parts`, in the prefab's space: models, volumes and prefabs) or
  **game prefabs**: one of the game's entities (`source`: name or `0x` hash, from the base level
  or from any `group`), with the toolkit `piece` it came from, its `settings` as the editor shows
  them and the `fields` they write (`"CPerk.m_perkSinglePCost": 2000`; names and the power link
  as names, `0` for none). A game prefab can draw one of the world's meshes (`mesh`) or a game
  model (`game`) instead of its own model, keeping its behaviour. Templates without a transform
  (in `ingame`) get one; zombie spawn points become the starting area's spawns in a generated map.
- In an inherited map, a game prefab with `"base": true` is one of the base level's own entities
  (by its `0x` hash), moved and edited; further copies of it are ordinary game prefabs.
  `removed` lists base-level entities taken out; the navmesh around them is rebuilt.
- `start` sets how an object starts: `visible`, `collision`, `blocks` (the navmesh under it is
  tagged with its name and shut until a script opens it). An object a script may change (it has
  a script, a start state, or is part of a prefab with a script) gets its own collision entity
  (`<name>_collision`) so `boz.objects` can switch it.
- `script` is a Lua file in the project's `scripts/` folder, `properties` the values of the
  `---@property` lines it declares ([map-scripting.md](map-scripting.md)).
- Format 1 and 2 files (meshes, props, instances, entities) still load and are converted.
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
  `boz/world.lua`, `boz/prefabs.lua`, `boz/objects.lua` and the map's generated
  `boz/world_data.lua` (start state, scripted objects, volumes). `boz.world` powers perk machines
  whose power switch is `boz_no_power` (the editor's "Needs power" off), as the game powers Quick
  Revive in solo (Pack-a-Punch gets `m_HasPower`; doors and trap switches without a power switch
  need none), applies the start state when each level starts, and starts the scripts.
- The compiler (`bozkit.world.compile_world`) lowers the world into a flat layout (prefabs
  flattened into their parts) and writes the level's groups into the mod's assets.
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
