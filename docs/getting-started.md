# Getting started

This page takes you from nothing to a working mod and a playable map. First you install the
client, the SDK and the editor, then you meet the SDK app, and then you make a small script mod
and a small map, step by step.

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

Download the SDK from the [SDK releases](https://github.com/ZappaVinny/boz-redux-sdk/releases)
and unzip it anywhere.

- **Windows:** run `boz-sdk.exe`.
- **Linux:** the SDK needs Python 3.11 or newer. In the unzipped folder run
  `python3 -m pip install -e '.[desktop]'` once, then start it with `./boz-sdk` (or `boz-sdk`).
  `boz-sdk --add-to-menu` adds it, with its icon, to your desktop's application menu.

The release already contains the map editor and the navmesh helper (which rebuilds where
players and zombies can walk after you change a map's walls or floors).

The `bozkit` [command line](sdk-reference.md#bozkit-command-line) comes with a Python install
(`pip install -e .` in the SDK folder): build, install and package projects, and read or edit
game files.

### 3. Blender (maps only)

The map editor runs in Blender 5.2 LTS: install it from
[blender.org](https://www.blender.org/download/lts/). The SDK app finds it on your system;
**Settings** in the app can point at another Blender.

### From source

To work on the SDK itself, clone it with its submodules, install it with
`python3 -m pip install -e '.[desktop]'` and build the navmesh helper with CMake
(`tools/navmesh`); see [Contributing](contributing.md#working-on-the-sdk).

### Check that it works

1. Run `boz-sdk.exe` (Linux: `./boz-sdk`), and choose your client folder when it asks.
2. The **Client** page should say the game data is installed.
3. The **Library** page builds the asset library from your game files the first time (about
   half a minute). When it shows previews of the game's models, you are ready.

## The SDK app

The SDK app (`boz-sdk`) is where your work lives: it keeps your projects, opens maps in the
editor, builds and installs mods into the client, and browses every asset in the game. It uses
the same compiler as the `bozkit` command line, so both always give the same result.

The first time it starts, it asks for your BOZ Redux client folder and checks that the game data
is installed. Without game data, script mods still work, but maps cannot be built.

### Projects

The project list, with search and sorting. A **project** is the source of one mod (see
[Projects and packaging](lua-mods.md#projects-and-packaging)).

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
- **Open in Editor** (maps) opens the map in [the map editor](map-editor.md), which has its
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

## Your first mod

In ten minutes you will make a mod that switches unlimited ammo on and off with F5 and shows a
label while it is on. It needs no reverse engineering, only a text editor.

### 1. Create the project

In the SDK app, click **New project**, choose **Script-only mod** and the **Hotkey** template, and
name it `hello`. Or from a terminal:

```bash
bozkit new hello --id hello --name Hello --author you --template hotkey
```

You get a folder like this:

```text
hello/
  boz-project.toml     the mod's name, version and author
  scripts/
    main.lua           your code
    boz/               the standard library, a copy the mod carries
```

### 2. Write the script

Open `scripts/main.lua` (**Open folder** in the app opens it in VS Code) and replace what is
there with:

```lua
local console = require("boz.console")

log("Hello from my first mod")

local ammo = false

input.bind("F5", function()
    ammo = not ammo
    console.set("WeaponsUnlimitedAmmo", ammo)
end)

events.on("frame", function()
    if ammo then
        ui.window("hello", {x = 20, y = 20, auto_size = true, no_title = true, no_inputs = true}, function()
            ui.text("Unlimited ammo")
        end)
    end
end)
```

What it does:

- `require("boz.console")` loads the standard library's console module. `WeaponsUnlimitedAmmo`
  is one of the game's own console variables; the
  [console reference](console-reference.md) lists all of them.
- `input.bind` runs a function when a key is pressed.
- `events.on("frame", ...)` runs every frame. `ui.window` draws a small window over the game
  for as long as you keep calling it.

### 3. Run it

Click **Run in game** on the project's page in the SDK app. It installs the mod into the client
and starts the game. From a terminal, the same is:

```bash
bozkit install hello --client path/to/boz-redux --force
```

then start the game from the client's launcher. Start a match and press F5.

### 4. Read the log

Everything your mod prints goes to `boz-log.txt` in the client folder:

```text
[lua] hello: Hello from my first mod
```

Errors show up there too, with the line they happened on. An error never crashes the game: the
part of the mod that failed is switched off until you restart.

Next, [Lua mods](lua-mods.md) explains how scripts run and has recipes for settings,
pause-menu options, overlays and hooks; the [standard library](standard-library.md) lists
everything `boz.*` can do.

## Your first map

This walk-through makes a small playable map: the debug arena with a perk machine and a wall buy
you place yourself. You will use the SDK app, the map editor and the client.

You need Blender set up ([Installation](#3-the-map-editor-maps-only)), and the SDK app's asset
library built once (the **Library** page).

### 1. Create a map project

In the SDK app, click **New project**, choose **Map**, and pick a template:

| Template | What you start with |
| --- | --- |
| **Empty** | A 6 m floor and the four player spawns. No zombies; the Colt is the only weapon. |
| **Debug arena** | A walled 24 m square with zombie spawns, Juggernog and the power switch. The quickest way to test. |
| **Kino der Toten**, **Call of the Dead**, **Ascension**, **Tutorial** | The whole original map, to change and add to. |

Pick **Debug arena** and name the map `my_arena`. The name becomes the level's name in the game,
so it cannot be one of the game's own maps.

### 2. Open it in the editor

Click **Open in Editor**. The editor opens on the **World** tab with the arena in the viewport.
On the left is the asset browser with the game's objects, grouped as **Game prefabs** (perk
machines, wall buys, doors, ...), **Level markers** (spawns, jump points), **Volumes** and
**Models**.

### 3. Add things

1. In the asset browser, open **Game prefabs → Machines** and drag **Speed Cola** into the
   arena.
2. A wall buy sells one of the map's weapons, and the debug arena starts with the Colt alone.
   Switch to the **Weapons** tab, click **Import from game** and pick the MP40. Then go back to
   the **World** tab.
3. Open **Game prefabs → Buying** and drag a **Wall buy** onto one of the walls. In the
   Properties editor's **Game** panel, click **Choose…** and pick the MP40.
4. Select the perk machine. Its **Game** panel shows its settings: set **Cost** to 1000.

Move objects with G, turn them with R, as anywhere in Blender. One Blender unit is one game
centimetre.

### 4. Build & Run

Click **Build & Run** at the right of the top bar. The editor saves the map, builds it into a mod
in your client, and starts the game. Once the main menu is up, the game goes straight into your
map. Buy the perk, buy the MP40, and play a few rounds.

If something stops the build, the **Problems** tab in the sidebar lists it, with a button that
selects the object at fault. The build output and the game's log are in the editor's **Log**
areas.

### 5. Play it from the client

Your map is now a mod in the client, and the client knows it is a map. In the client's launcher,
the list next to **PLAY** offers **Main menu** and every map from your enabled mods. Pick
**my_arena** (it shows your mod's name) and press **PLAY**: the game starts straight into it.
Pick **Main menu** to start the game normally. No scripting is needed for this; every map built
by the SDK can be started this way.

Next, [The map editor](map-editor.md) explains every tab and tool, and
[Weapons, models, effects and sounds](weapons-and-assets.md) covers your own guns, models and
audio.
