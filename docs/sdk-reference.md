# SDK reference

Reference for the SDK's own tools and formats: every `bozkit` command, the files of a map
project, and which versions of the game, client and formats work together.

## bozkit command line

`bozkit` is the SDK's command-line tool. It builds and packages projects, and reads and edits the
game's data files. The SDK app and the editor use the same code, so the command line always
gives the same result. Install it with the SDK ([Installation](getting-started.md#installation));
without installing, run `python3 -m bozkit` from `tools/bozkit`.

Every command that edits a file writes a new file (`-o`) and never changes its input. Parts of a
file bozkit does not understand are kept byte for byte.

### All commands

| Command | What it does |
| --- | --- |
| **Projects** | |
| `new` | Create a project: `bozkit new my-mod --id my_mod --name "My mod" --author you [--kind map] [--template ...]` |
| `inspect` | Show a project and its validation result |
| `validate` | Check a project (`--profile distribution` warns about game files) |
| `build` | Build a project into `build/<mod id>/` |
| `install` | Build and install a project into a client: `--client path/to/boz-redux [--force]` |
| `package` | Build a project into a reproducible ZIP |
| **Game data** | |
| `extract` | Extract a `.dz` pack or a `.group.bin` (with `dade`; the source is never deleted) |
| `dump` | A group file as JSON (`--class CIsEntitySpec` limits it to one class) |
| `set` | Change one reflected field: `bozkit set weapons_kino.group.bin colt45 m_clipSize 12 --component CPlayerWeapon -o out.group.bin` |
| `names` | Add the names found in the given files to the local name dictionary (`~/.cache/bozkit`), so hashes show as names |
| `corpus` | Check that bozkit reads and writes every file in a folder byte for byte |
| **Saves** | |
| `save` | A game save (`.i3d`) as JSON |
| `settings` | Show or change `save_settings.i3d` (`--set name=value`) |
| **Resources** | |
| `model-export`, `model-import` | A model to glTF and back |
| `material-dump`, `material-set` | Show a material; change its flags or textures |
| `texture-export`, `texture` | A texture to PNG; replace a texture with a PNG |
| `collision-export`, `collision-import` | A collision mesh to glTF and back |
| `nav` | Show or change a navmesh's build settings |
| `nav-connection` | Show or move a navigation connection (window and barricade climbs) |
| `portal` | Show or change a visibility portal |

`bozkit <command> --help` lists each command's options. Projects are explained in
[Projects and packaging](lua-mods.md#projects-and-packaging); the file formats in
[Asset formats](how-the-game-works.md#asset-formats).

### Getting the game's files

The game's data is in `.dz` packs in your client's `original/obb/` folder. Extract one to a
folder of its own (keep extracted files out of any repository):

```bash
bozkit extract path/to/boz-redux/original/obb/blackops_etc.dz ~/boz-etc --kind dz
```

The examples below use `~/boz-etc` and write their results to `~/boz-edits`. To change a map in
the editor instead, see [Editing shipped map files](map-editor.md#editing-shipped-map-files).

### Models and glTF

Export the named Colt M1911 model and open the resulting glTF in Blender:

```bash
bozkit model-export \
  ~/boz-etc/ingame/weapons/weapons_kino.group.bin colt45 ~/boz-edits/colt45.gltf
```

The exporter decodes center-offset component-planar positions, the unique-to-render vertex remap,
UVs, and GL triangle lists. Model bodies and unknown blocks still round-trip byte-identically.
Source-backed geometry edits require unchanged topology. Models using other primitive block types
or multiple primitive groups are rejected or remain preservation-only rather than being guessed.

### Material commands

Inspect a material and change its flags or a texture hash by zero-based slot:

```bash
bozkit material-dump \
  ~/boz-etc/ingame/ingame.group.bin 0x61ec0f93 -o ~/boz-edits/material.json
bozkit material-set \
  ~/boz-etc/ingame/ingame.group.bin 0x61ec0f93 \
  --texture 0=0x12345678 -o ~/boz-edits/ingame-material-test.group.bin
```

The material writer retains unknown header and trailer bytes.

### Navigation commands

Inspect the tutorial map's Recast settings and create a copy with a different agent radius:

```bash
bozkit nav \
  ~/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x021eeaf7
bozkit nav \
  ~/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x021eeaf7 \
  --set agent_radius=0.5 -o ~/boz-edits/tutorial-nav-test.group.bin
```

The editable settings are `cell_size`, `cell_height`, `agent_height`, `agent_radius`,
`agent_max_climb`, and `agent_max_slope`. Detour tiles remain byte-identical.

Inspect or translate a navigation connection from the shared in-game group:

```bash
bozkit nav-connection \
  ~/boz-etc/ingame/ingame.group.bin 0x67b09c42
bozkit nav-connection \
  ~/boz-etc/ingame/ingame.group.bin 0x67b09c42 \
  --translate 0 0 10 -o ~/boz-edits/ingame-nav-connection-test.group.bin
```

Fields whose behavior is not yet proven retain offset-based names in output and `--set`; this keeps
the format writable without presenting guesses as stable semantics.

### Portal commands

Inspect a tutorial visibility portal or translate it while retaining its sector relationship:

```bash
bozkit portal \
  ~/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x332aca12
bozkit portal \
  ~/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x332aca12 \
  --translate 0 0 10 -o ~/boz-edits/tutorial-portal-test.group.bin
```

`--front` and `--back` change the connected sector names and regenerate their cached hashes.

### Collision commands

Export and losslessly re-import the tutorial map's collision triangles:

```bash
bozkit collision-export \
  ~/boz-etc/levels/tutorial/tutorial_statics.group.bin 0xebf33ad1 \
  ~/boz-edits/tutorial-collision.gltf
bozkit collision-import \
  ~/boz-etc/levels/tutorial/tutorial_statics.group.bin 0xebf33ad1 \
  ~/boz-edits/tutorial-collision.gltf -o ~/boz-edits/tutorial-collision-test.group.bin
```

The default import requires unchanged vertex and index counts and keeps the material names and
per-triangle material bytes. `--rebuild-mesh` allows topology changes; new triangles receive
material byte zero when the old material array no longer fits. Either way, the embedded Bullet
physics shape is updated to the same triangles, and its stale BVH is dropped so the game rebuilds
it at load (see [collision meshes](how-the-game-works.md#collision-meshes)).

### Texture commands

Export the recognizable red main-menu logo:

```bash
bozkit texture-export \
  ~/boz-etc/frontend/frontend.group.bin main_menu_logo ~/boz-edits/main_menu_logo.png
```

Row-major ABGR_4444 (`0x05`) and ABGR_8888 (`0x0e`, bytes R, G, B, A) textures can be exported and replaced. PNG import
preserves a source texture's unknown header fields and native pixel format. Cooked ETC1 and DXT1
textures, which make up most map textures, decode for previews (Blender) but cannot be written yet.
Other layouts fail rather than producing a plausible-looking corrupt image.

Edited groups go in a project's `assets/` folder, and the build puts them in the mod (see
[Projects and packaging](lua-mods.md#game-files-in-a-mod)).

## Project files

The formats of a map project's `source/` folder. The editor writes these files every time you
save, and the build reads them; you can also read or edit them by hand, or generate them with
your own tools. Positions are in game centimetres with Y up; rotations are `x, y, z, w`
quaternions in the game's axes.

### The source folder

```text
source/
  world.json                 the world: base level, meshes, models, volumes, prefabs
  meshes/<name>.json         a mesh of the world's own
  textures/<name>.png        its textures (<name>_1.png, ... for further textures)
  prefabs/<Name>.json        the prefab library (with <Name>/meshes and <Name>/textures)
  chalk/<file>.png           wall-buy chalk drawings of your own
  weapons/index.json         the project's weapon list
  weapons/<name>.json        a changed, new or imported weapon
  weapons/anims/<weapon>/<state>.json   your animations of a weapon
  assets/<name>.json         one of your models: its settings
  assets/<name>/             its game version: model.json, textures/N.png, stats.json
  sounds/<name>.json         one of your sounds: its settings
  sounds/<name>/             source.wav (as imported) and game.wav (saved)
  sounds/slots.json          which game sounds you replaced
  effects.json               the effects and projectiles the map names
  game.json                  the map's rules
assets/<name>/<file>         the original file a model was imported from (never shipped)
scripts/                     Lua: main.lua, prefab scripts, weapon scripts, hooks
```

The other files are described with their tools: [Weapons](weapons-and-assets.md#weapon-project-files),
[Your own models](weapons-and-assets.md#model-project-files), [Sounds](weapons-and-assets.md#sound-project-files),
[Effects and projectiles](weapons-and-assets.md#effects-and-projectiles) and [Game rules](map-editor.md#game-rules).

### world.json

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

#### The level

- `format` is 3. Other versions are refused.
- `base` is the shipped level that provides the rounds, zombie types, sounds, cameras, weapons
  and arms.
- `"inherit": true` makes the map the **whole base level** (rooms, entities, navmesh) plus the
  world's contents. The original-map templates use it.

#### Names, positions and start state

- Every object has a `name` (letters, digits and `_`). It is the object's name in the game and
  in scripts. A prefab's parts are named `<Prefab>.<Part>` in the game.
- `position` is in centimetres, `rotation` an `x, y, z, w` quaternion, `scale` optional.
- `start` sets how an object starts: `visible`, `collision`, and `blocks` (the navmesh under it
  is shut until a script opens it). An object a script may change gets its own collision entity
  (`<name>_collision`) so `boz.objects` can switch it.
- `script` is a Lua file in the project's `scripts/` folder, and `properties` the values of the
  `---@property` lines it declares ([Map scripting](map-editor.md#map-scripting)).

#### Meshes and models

- A **mesh** file holds vertices (centimetres, the model's own space), UVs, triangles, and for
  each triangle the texture it uses. Textures are PNGs with power-of-two sides from 4 to 1024.
  `double_sided` also draws the backs of triangles.
- A **model** draws one mesh: one of the world's `meshes` (`mesh`), a game model (`game`:
  `<group path>#0x<hash>`, copied into the level with its materials and textures), or one of
  your models (`asset`, stored in tenths of a centimetre and placed at 0.1 scale).
- `collision` is `floor` (walkable: the navmesh is built on its top), `solid` (blocking: it cuts
  the navmesh) or `none`. The editor calls these Walkable, Blocking and None. `shape` is `box`
  (its bounds) or `mesh` (its triangles).
- Models that share a mesh share one game model.

#### Volumes

Invisible boxes that send events to scripts. `size` is in centimetres.

| `volume` | Event | Made from |
| --- | --- | --- |
| `trigger` | enter / exit | Call of the Dead's snow trigger (a ghost box) |
| `hit` | shot | Kino's musical easter-egg skull, with a song of its own; a sphere of the box's largest side |
| `use` | the player pressed use | a point of interest without a game prompt; `prompt` and `cost` add one |

`who` is `players`, `zombies` or `anyone`; `once` fires the first time only.

#### Prefabs

- **Your prefabs** have `parts`: models, volumes and prefabs, placed in the prefab's space.
- **Game prefabs** are one of the game's entities: `source` (a name or `0x` hash, from the base
  level or from any `group`), the editor `piece` it came from, its `settings` as the editor
  shows them, and the `fields` they write (`"CPerk.m_perkSinglePCost": 2000`; names and the power
  link as names, `0` for none). A game prefab can draw one of the world's meshes (`mesh`) or a
  game model (`game`) instead of its own model, keeping its behaviour.
- In an inherited map, a game prefab with `"base": true` is one of the base level's own entities
  (by its `0x` hash), moved and edited; further copies of it are ordinary game prefabs. `removed`
  lists base-level entities taken out.
- In a wall buy's `fields`, `"boz.weapon"` picks its weapon; in its `settings`, `"boz.chalk"` is
  `""` (automatic), `"none"` or an image in `source/chalk/`.

### What the build does with it

- **Compiling:** `bozkit.world_compile.compile_world` flattens prefabs into their parts and
  writes the level's groups into the mod's `assets/`. A generated map gets a collision mesh and a
  navmesh built from its floor and solid geometry (entities with a model get a box). An inherited
  map adds its own collision entity and rebuilds only the navmesh tiles near what changed.
- **Bringing things in from other maps:** an entity or model from another map brings what it
  uses (models, materials, textures, skins, skeletons, animations, state machines, sounds),
  found by name hash in that map's groups and the shared `ingame` group, unless the level
  already loads it. A wall buy sells a weapon of the level's own weapons group.
- **Chalk:** a shipped wall buy's chalk drawing is a separate decal next to it. Each placed wall
  buy gets one at the same offset: the weapon's own chalk when the game has one, else an outline
  drawn from the weapon model's side.
- **Doors:** the floor under a door's collision box is cut out as its own navmesh polygons,
  tagged with the door's name, so players and zombies pass only once the door is bought. Copies
  get names of their own; doors in generated maps unlock no areas.
- **Scripts:** the build adds `require("boz.world").start()` to `main.lua`, the standard
  library, and a generated `boz/world_data.lua` (start state, scripted objects, volumes).
  `boz.world` applies the start state when the level starts, starts the scripts, powers perk
  machines whose power switch is `boz_no_power` (the editor's **Needs power** off), and starts
  the map when the launcher or Build & Run asks for it.
- **The manifest:** the mod's `mod.toml` gets `maps = ["<level name>"]`, which is how the
  client's launcher knows to offer the map.

## Compatibility

Which versions of the game, the client and the SDK's formats work together. BOZ Redux is in
development: there is no public SDK release yet, and formats can still change. When one of the
formats below changes, its version number goes up and these notes say what to do.

| Component | Current version | Notes |
| --- | --- | --- |
| Game | Android 1.0.11 (versionCode 1045111) | The only supported version. A mod's `game` must be `1.0.11`. |
| Client | v0.1.1 development line | Reads game definition schema 1, mod folders with `mod.toml`, and the `maps` list. |
| Game definition | Schema 1, target `boz-1.0.11` | `gamedef/gamedef.toml`; the client and the SDK check it before loading. |
| Projects | Schema 2 (`boz-project.toml`) | Schema 1 projects still load and are saved as schema 2. |
| Map worlds | Format 3 (`source/world.json`) | Older formats are refused. |
| Lua | 5.4 | The client's [Lua API](lua-mods.md#client-lua-api) and the [standard library](standard-library.md). |
| Editor | Blender 5.2 LTS | |
| Python | 3.11 or newer | For `bozkit`, the SDK app and the symbol tools. |
