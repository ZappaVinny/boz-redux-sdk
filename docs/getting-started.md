# Getting started

This page takes you from nothing to a playable map with your own scripted object. Install the
tools, build a small room, play it, then make something in it react to you.

## Installation

You need three things: the BOZ Redux client with the game installed, the SDK, and (for maps)
the editor's Blender.

### 1. The client and the game

The client is the program that runs the game on PC. It also loads mods.

1. Download the client for your system from the
   [BOZ Redux releases](https://github.com/ZappaVinny/boz-redux/releases) and unpack it anywhere.
2. Start `boz-redux` (Linux) or `boz-redux.exe` (Windows).
3. In the launcher's **Game files** tab, choose your own copy of the Android game (APK, version
   1.0.11) and click **Install**. Then click **Download** to fetch the game's data packs, or
   import them from a folder.
4. Click **PLAY** once to check that the game runs.

The folder you unpacked is your **client folder**. It holds `mods/` (installed mods),
`saves/`, `client.ini` (settings) and `boz-log.txt` (the log you will read when something goes
wrong). The SDK asks for this folder the first time it starts.

### 2. The SDK

The SDK needs Python 3.11 or newer and Git.

```bash
git clone --recurse-submodules https://github.com/ZappaVinny/boz-redux-sdk.git
cd boz-redux-sdk
python3 -m pip install -e '.[desktop]'
```

This installs two commands:

- `boz-sdk` starts [the SDK app](#the-sdk-app): your projects, the asset library and the editor.
- `bozkit` is the [command line](sdk-reference.md#bozkit-command-line): build, install and package projects,
  and read or edit game files.

You can also run the app without installing, from the checkout: `./boz-sdk`. On Linux,
`boz-sdk --add-to-menu` adds it, with its icon, to your desktop's application menu. Leave out
`[desktop]` if you only want the command line.

### 3. The map editor (maps only)

The map editor is Blender 5.2 LTS with the SDK's editor add-on. Install Blender 5.2 LTS from
[blender.org](https://www.blender.org/download/lts/), or put it in the SDK's `blender/` folder.
The SDK app finds it there or on your `PATH`; **Settings** in the app can point at another
Blender. The app prepares the editor itself the first time you open a map.

#### The navmesh helper

When you change a map's walls or floors, the SDK rebuilds where players and zombies can walk
with a small native helper. Build it once (needs CMake and a C++ compiler):

```bash
git submodule update --init tools/navmesh/third_party/recast
cmake -S tools/navmesh -B tools/navmesh/build -DCMAKE_BUILD_TYPE=Release
cmake --build tools/navmesh/build -j
```

Without it everything still works, but edits that change collision keep the old walkable area
(the editor tells you so when you save). See [Navigation meshes](map-internals.md#navigation-meshes).

### Check that it works

1. Run `boz-sdk`, and choose your client folder when it asks.
2. The **Client** page should say the game data is installed.
3. The **Library** page builds the asset library from your game files the first time (about
   half a minute). When it shows previews of the game's models, you are ready.

## Your first map

You need the tools above, and the asset library built once (the **Library** page in the SDK app).

### 1. Make a new map

In the SDK app, click **New project**, choose **Map**, pick **New map** and name it `my_arena`. The
name becomes the level's name, so it can't be one of the game's own maps.

Click **Open in Editor**. The editor opens on the **World** tab. You start with a floor and four
player spawns, and players start with the Colt. On the left is the asset browser.

### 2. Add a wall, a perk and some zombies

1. Click **Shapes** in the World header and add a **Wall**. Move it to the edge of the floor with
   G. Shapes are ready to use: a wall blocks walking and stops bullets.
2. In the asset browser, open **Game prefabs → Machines** and drag **Juggernog** onto the floor.
3. From the same group, drag in the **Power switch**. Perk machines wait for the power.
4. From **Level markers → Spawns**, drag a **Zombie spawn** onto the floor and set its **Type** to
   **Ground**.

Select the perk machine. Its **Settings** box in the **Game** panel shows its **Cost**. Set it to
1000.

Move objects with G, turn them with R. One Blender unit is one game centimetre.

### 3. Build & Run

Click **Build & Run** at the right of the top bar. The editor saves the map, builds it into a mod,
and starts the game straight into your map. Turn on the power, buy the perk, and shoot some
zombies.

If something stops the build, the **Problems** panel in the sidebar lists it, with a button that
selects the object at fault.

### 4. Your first script

Now make something of your own: a skull that pays out when you shoot it.

1. Drag a small model from **Models** onto the floor.
2. From **Volumes**, drag a **Hit** volume over it and scale it to cover the model.
3. Select both and press **Ctrl+G**. They're now a prefab. Name it `Skull`.
4. In the **Script** box of the **Game** panel, click **New**, choose **Basic prefab** and click OK.
   The **Scripts** tab opens.
5. Replace what is there with this:

```lua
local Skull = boz.Prefab:extend("Skull")

function Skull:on_hit(player)
    self:hide()
    player:give_points(500)
    player:message("Skull found")
end

return Skull
```

Click **Build & Run** and shoot the skull. It vanishes, and you get 500 points.

That's the whole idea: **a prefab is parts plus a script, and hooks like `on_hit` say what it does
when things happen.** Everything else builds on this.

### 5. Play it from the client

Your map is now a mod in the client. In the client's launcher, press **PLAY** and it's in the list.
**PLAY SOLO** starts it. **CO-OP ROOM** joins a friend's room on the same map, or hosts one
(everyone needs the map's mod).

### Where next

- [How a map works](how-a-map-works.md): the model behind all of this, in one page.
- [Prefabs](prefabs.md): everything a prefab can do, with recipes to copy.
- [Game prefabs](game-prefabs.md): change perk machines, doors and the rest.

## Your first mod

A script mod changes the game without a map. This one gives you points with a key.

In the SDK app, click **New project**, choose **Script-only mod** and the **Blank** template, and
name it `hello`. Click **Open folder** and replace `scripts/main.lua` with:

```lua
local boz = require("boz")

log("Hello from my first mod")

input.bind("F5", function()
    boz.player():give_points(1000)
end)

boz.on("round_started", function(data)
    boz.player():message("Round " .. data.round)
end)
```

Click **Run in game**, start a match and press F5.

Everything your mod logs goes to `boz-log.txt` in the client folder, and errors show there too,
with the line they happened on:

```text
[lua] hello: Hello from my first mod
```

An error never crashes the game: the part that failed is switched off until you restart.

More in [Script mods](script-mods.md).

## The SDK app

The SDK app (`boz-sdk`) is where your work lives: it keeps your projects, opens maps in the
editor, builds and installs mods into the client, and browses every asset in the game. It uses
the same compiler as the `bozkit` command line, so both always give the same result.

The first time it starts, it asks for your BOZ Redux client folder and checks that the game data
is installed. Without game data, script mods still work, but maps cannot be built.

### Projects

The project list, with search and sorting. A **project** is the source of one mod (see
[Projects and packaging](script-mods.md#projects-and-packaging)).

- **New project** makes a map or a script mod from a template. Projects go in `~/BOZ Projects`
  unless you choose another folder in **Settings**.
- **Open**, **Duplicate**, **Rename**, **Delete** (to the trash), **Show in file manager** and
  **Remove from list** work on the selected project.

### A project's page

- Edit the mod's details: name, version, author, description.
- **Open folder** opens the project in VS Code if you have it, else in the file manager.
- **Run in game** (script mods) installs the mod and the Developer mod into the client, then
  starts the game.
- **Build & Run** (maps) builds the map, installs it into the client last in the load order, and
  starts the game straight into the map once the main menu is up.
- **Open in Editor** (maps) opens the map in [the editor](editor.md), which has its
  own Build & Run with start options (unlimited health or points, starting points).
- The game's log, filtered to your mod and to errors.

### Client

Your client folder, whether the game data is installed, and the installed mods, which you can
switch on and off. **Open client launcher** starts the client's own launcher.

### Library

Every Zombies asset in the game, with previews: props, weapons, models, textures, materials,
effects, sounds and animations. Search by name, description or `0x` hash, filter by kind and
map, and copy an asset's name or hash for your scripts.

The app builds the library from your own game files the first time it sees them (about half a
minute, in the background), and again when the game files change. Nothing in it is shipped. The
editor's palettes use the same library.

The game stores most assets by a hash of their name only, so many have no name. The library
labels them by what uses them (for example *Model of Juggernog perk*) or shows the hash. The same
name can hold different contents in different files (each map's loading screen, for example);
the library lists each one as a separate *variant*.

### Learn

The guides and references, and the Developer mod as an example to read.

### Settings

Your client folder, where new projects go, the default author, the editor's Blender (by default
the SDK's own, else `blender` on your `PATH`) and **Rebuild library**.

### Where the app keeps its data

Settings, the project list and the asset library live in the SDK data folder:
`~/.local/share/boz-redux-sdk` on Linux, `%APPDATA%\BOZ Redux SDK` on Windows. Set
`BOZ_SDK_HOME` to use another folder.

| Path | What it is |
| --- | --- |
| `library/1.0.11/groups/` | Untouched copies of every Zombies group file; map templates start from these |
| `library/1.0.11/index.sqlite` | One row per asset: kind, hash, variant, name, label, description, groups, maps, size, triangles, thumbnail |
| `library/1.0.11/thumbs/` | 128-pixel previews |
| `library/1.0.11/names.txt` | Names recovered from the game's strings, for hash lookups |
| `library/1.0.11/stamp.json` | The game files and library version the library was built from |

Tools can read the library with `bozkit.library.Library`.
