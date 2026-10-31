# Lua mods

A Lua mod changes the game with scripts: new rules, cheats, settings in the pause menu, windows
over the game, or your own code running inside any game function. This page explains how mod
scripts run and walks through the things most mods do, then how a project becomes a mod you can
share, and ends with the reference of everything the client gives Lua. If you have not made a
mod yet, start with [Your first mod](getting-started.md#your-first-mod).

Two other pages go with it:

- [Standard library](standard-library.md): the `boz.*` modules most mods are built from. Start
  there when looking for something.
- [Console reference](console-reference.md): every console variable and command in the game.

## Writing a mod

### How it fits together

| Layer | What it is | You |
| --- | --- | --- |
| **Client** | The program that runs the game: emulator, window, sound, controls, file loading, and the Lua runtime with its low-level functions (`game`, `hook`, `events`, `ui`, ...). | use it |
| **Standard library** (`boz.*`) | Lua modules that turn the game's internals into plain functions: `camera.set_fov(90)`, `pause_settings.add_slider{...}`, `console.set(...)`. | use it |
| **Your mod** | A folder with a manifest, scripts and optional replacement files. | write it |

Two habits keep mods working:

- **Use names, not addresses.** Standard library functions and the game definition's names
  (`"CScoreManager::AddScore"`) keep working when the game definition is updated; raw addresses
  do not.
- **Prefer the standard library.** If something you need is missing, it probably belongs in the
  standard library rather than in your mod.

### The mod folder

An SDK project builds into this folder (see [Projects and packaging](#projects-and-packaging)); you can also
write one by hand in the client's `mods/` folder:

```text
mods/<folder>/
  mod.toml        id, name, version, author, game, description
  scripts/        Lua: main.lua runs; other files load with require
  assets/         replacement files (optional), see "Replace game files"
```

| `mod.toml` key | Meaning |
| --- | --- |
| `id` | Unique, lower-case, no spaces. Used for settings and the load order. Defaults to the folder name. |
| `name`, `version`, `author`, `description` | Shown in the launcher. |
| `game` | The game version the mod is made for (`1.0.11`). The launcher warns about others. |
| `maps` | The levels the mod adds (`["my_arena"]`). The client's launcher offers each of them when you press **PLAY**, alone or as a co-op room. The SDK writes it for map projects. |

A mod that uses the standard library carries its own copy in `scripts/boz`. SDK projects add it
for you; for a hand-made mod, copy the SDK's `lib/boz` folder there.

The launcher's **Mods** tab turns mods on and off and sets their order; when two mods replace
the same file, the later one wins.

### How your script runs

- `main.lua` runs **once, before the game starts**. Use it to register things: event handlers,
  key bindings, hooks, settings rows, file patches. The game is not running yet, so do not read
  game state here.
- After that your code runs only from **events** and **hooks**:

  ```lua
  events.on("frame", function(dt) ... end)          -- every frame, dt in seconds
  events.on("key", function(name, down) ... end)    -- every key press and release
  input.bind("F6", function() ... end)              -- one key press
  ```

- Each mod has its own globals. `mod.id`, `mod.name`, `mod.dir` describe your mod.
- `require("name")` loads `scripts/name.lua` from your mod (`require("ui.tabs")` loads
  `scripts/ui/tabs.lua`), once.
- **Errors** do not crash the game: they are written to `boz-log.txt` as `[lua] <mod>: ...` with a
  traceback, and the handler that failed is switched off. Fix the script and restart.

### Using the standard lib

Require the modules you need:

```lua
local player = require("boz.player")
local console = require("boz.console")
local pause_settings = require("boz.pause_settings")
```

What is in it (everything is in the [standard library reference](standard-library.md)):

| Module | For |
| --- | --- |
| `boz.player` | Health, god mode, position, stance, speeds, perks (give and take), field of view |
| `boz.weapons` | The player's weapons: give, take, Pack-a-Punch, ammo, damage, fire rate, events |
| `boz.zombies` | Zombies, dogs, monkeys and George: spawn, kill, teleport, speed, freeze/burn/explode, ... |
| `boz.rounds` | The round: next round, go to a round, counts, spawning on or off, time |
| `boz.score` | Points: add, spend, set, what actions are worth |
| `boz.pickups` | Power-ups: spawn, give, timers |
| `boz.pieces` | Mystery boxes, perk machines, doors, traps, Pack-a-Punch, ...: use (or use for free), move the box, costs |
| `boz.effects` | The game's effects and projectiles anywhere (black holes, explosions, ...) |
| `boz.hud`, `boz.camera`, `boz.screen`, `boz.audio` | HUD elements and messages; camera shakes; full-screen effects and fog; sounds and music |
| `boz.map`, `boz.spawns`, `boz.stats` | The level (power, map events), spawn points, achievements and stats |
| `boz.input` | Watch, block or send the game's actions (shoot, aim, reload, ...) |
| `boz.fly` | Noclip |
| `boz.console`, `boz.cvars` | Console variables and commands |
| `boz.reflect`, `boz.entities`, `boz.game_events` | Anything else: every reflected field, every entity and component, every game event |
| `boz.pause_settings` | Sliders and checkboxes in the pause menu's Settings page |
| `boz.text` | Your own text for the game's menus |
| `boz.iwui`, `boz.frontend` | Building blocks for menu changes |

Functions that only make sense in a match (perks, zombies, field of view, fly) return `nil` or
`false` outside one, so you can call them any time.

### Recipes

#### Save a setting

```lua
local volume = settings.get("volume", 0.5)   -- the saved value, or the default
settings.set("volume", 0.8)                   -- saved to saves/mods/<id>.cfg
```

Values are strings, numbers or booleans.

#### Add a setting to the pause menu

The pause menu's Settings page gets new rows that look exactly like the game's own. This is a
field of view setting, complete:

```lua
local pause_settings = require("boz.pause_settings")
local camera = require("boz.camera")

local function saved_fov()
    local value = settings.get("fov")
    return type(value) == "number" and value or 50
end

pause_settings.add_slider{
    id = "fov",
    label = "Field of view",
    min = 50, max = 120, step = 1,
    get = saved_fov,
    set = function(value)
        settings.set("fov", value)
        camera.set_fov(value)
    end,
}

camera.set_fov(saved_fov())   -- apply the saved value from the start
```

A checkbox works the same way:

```lua
pause_settings.add_checkbox{
    id = "god_mode",
    label = "God mode",
    get = function() return console.get("UnlimitedHealth") == "true" end,
    set = function(on) console.set("UnlimitedHealth", on) end,
}
```

Call them in `main.lua`. Rows appear in the order mods register them; rows from several mods
stack without overlapping.

#### Use the game's console variables

The game has hundreds of settings and cheats as console variables
([console reference](console-reference.md)):

```lua
local console = require("boz.console")
console.set("WeaponsUnlimitedAmmo", true)
print(console.get("WalkSpeed"))
console.exec("SwitchPowerOn")
```

Many variables exist only during a match (the game creates them when the code using them first
runs); `console.get` returns `nil` until then. Some the game reads but never creates (marked
*lookup only*): create them with `console.register("StartingScore", 5000)`.

#### Show a window or overlay

The client draws windows over the game with Dear ImGui (`ui.*`, in the [Lua API](#client-lua-api)).
Draw them from a `frame` handler, every frame you want them visible:

```lua
local open = false
input.bind("F7", function()
    open = not open
    overlay.capture(open)   -- free the mouse and keyboard for the window
end)

events.on("frame", function()
    if not open then return end
    open = ui.window("My mod", {x = 100, y = 100, w = 400, h = 200, closable = true}, function()
        if ui.button("Give all perks") then
            require("boz.player").give_all_perks()
        end
    end)
    overlay.capture(open)
end)
```

#### Replace game files

Put replacement files in your mod's `assets/` folder; the client uses them instead of the
game's when the game loads them. The game's packs store plain file names, so
`assets/weapons_kino.group.bin` replaces that file wherever the game asks for it. Turn on
**Log every file the game opens** in the launcher's settings to see the names it uses.

Game data files (`.group.bin`) can be read and edited with the
[bozkit command line](sdk-reference.md#bozkit-command-line) (formats: [Asset formats](how-the-game-works.md#asset-formats)), for example
`python3 -m bozkit set weapons_kino.group.bin colt45 m_clipSize 12 --component CPlayerWeapon -o out.group.bin`.

Complete or edited game files are fine in your own projects. Before you share a mod that
contains them, decide whether you may (see
[Projects and packaging](#game-files-in-a-mod)). When a code-only change does the job,
`assets.patch` avoids shipping the file at all:

#### Change a file as it loads

```lua
assets.patch("weapons_kino.group.bin", function(bytes)
    -- return the changed bytes (a Lua string), or nil to leave the file alone
    return bytes
end)
```

The function gets the player's own copy of the file each time the game opens it. Register the
patch in `main.lua`, before the game loads the file. The standard lib uses this for the main
menu (`boz.frontend`).

### Hooks: when the standard lib is not enough

A hook runs your code when a game function is called. You can read and change its arguments,
skip it, or change what it returns. Names come from the game definition
(`gamedef/symbols/boz-1.0.11.toml`); each entry's `notes` describe the arguments.

For example, `CScoreManager::AddScore` is noted as *"AddScore(playerId, delta, countForStats):
adds to the player's score"*. As a method, its first argument is the score manager itself
(`this`), so `delta` is argument 3. To double every point earned:

```lua
hook.add("CScoreManager::AddScore", {before = function(call)
    local delta = call:arg_signed(3)
    if delta > 0 then
        call:set_arg(3, delta * 2)
    end
end})
```

An `after` handler sees the result:

```lua
hook.add("CWaveManager::StartWave", {after = function(call)
    log("a new round started")
end})
```

| In a handler | |
| --- | --- |
| `call:arg(i)`, `call:arg_signed(i)`, `call:arg_float(i)` | Argument `i` (1 = `this` for methods) |
| `call:set_arg(i, v)` (before) | Change an argument |
| `call:skip(value)` (before) | Return `value` at once; the function does not run |
| `call:result()`, `call:set_result(v)` (after) | The return value |

Several mods can hook the same function. A handler that raises an error is switched off and
logged. Hooks only see the game's main thread (game logic, menus, drawing). See the
[Lua API](#client-lua-api) for all of it, and keep hook handlers short: some functions run many
times per frame.

Reading and writing game memory (`game.read`, `game.write`) and calling functions
(`game.call`) are also available. They are powerful and unforgiving: a wrong address crashes the
game. Prefer the standard lib; if you write something reusable this way, it probably belongs in
the standard lib.

### Debugging

- **`boz-log.txt`** (next to `client.ini`) has your `log(...)` and `print(...)` lines, every
  error with a traceback, and what the client loaded (`[mods]`, `[lua]`, `[gamedef]`).
- The **Developer** mod (in the SDK's `mods/developer`) opens the game's console with `` ` ``:
  run commands, watch variables, try cheats. Turn it on in the launcher.
- **Log every file the game opens** (launcher settings) shows file names for `assets/` and
  `assets.patch`.
- For menu work: `iwui.dump(element)` logs a page's widgets; `require("boz.flash").capture_log()`
  logs the main menu's ActionScript `trace()` output and warnings.

### Mods working together

- Every mod has its own globals and its own copy of the standard lib; copies cooperate (pause
  menu rows stack, hooks chain).
- The load order (Mods tab) decides which file wins when two mods replace the same one, and the
  order hooks and settings rows are added.
- `shared` is one table every mod can read and write, for mods that want to talk to each other.

### Sharing your mod

`bozkit package` (or the SDK app) makes a ZIP of the mod with its copy of the standard library.
Players unzip it into their client's `mods/` folder and tick it in the launcher. See
[Projects and packaging](#share-a-mod).

## Projects and packaging

A **project** is the editable source of one mod. It holds your Lua scripts, any replacement game
files, and for a map everything the editor makes. **Building** a project makes the mod folder
the client loads; **packaging** makes the same folder as a ZIP to share.

The SDK app does all of this with buttons (see [The SDK app](getting-started.md#the-sdk-app)).
This section explains what happens underneath, with the matching `bozkit` commands.

### Create a project

```bash
bozkit new my-mod --id my_mod --name "My mod" --author "Your name"
```

- `--kind script` (the default) makes a Lua mod; `--kind map` makes a map for the editor.
- `--template` picks what you start from. Script mods: `blank`, `round` (code at every round
  start), `hotkey` (a key runs a console line) and `settings` (options in the pause menu). Maps:
  `empty`, `debug`, `kino`, `callofthedead`, `ascension` and `tutorial` (see
  [Your first map](getting-started.md#1-create-a-map-project)).

The mod id must start with a lower-case letter and use only `a-z`, `0-9`, `_` and `-`.

### The project folder

```text
my-mod/
  boz-project.toml       the manifest
  scripts/
    main.lua             runs when the game starts
    boz/                 a copy of the standard library
    .luarc.json          tells Lua editors (VS Code with LuaLS) where boz.* is
  assets/                replacement game files (optional)
  build/                 build output, made by the SDK
```

A map project also has `source/`, where the editor keeps the world, weapons, models, sounds,
effects and rules ([Project files](sdk-reference.md#project-files)), and `map.blend`, the
editor's scene.

### The manifest

`boz-project.toml` describes the mod:

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
kind = "script"          # "script" or "map"

[paths]
scripts = "scripts"
assets = "assets"

[build]
include_standard_library = false
```

- A map project also has a `[map]` table: the level's `name` (the mod id with `-` turned into
  `_`; it cannot be one of the game's own level names) and the `template` it started from.
- New projects carry their own copy of the standard library in `scripts/boz`, so your editor can
  autocomplete it; the SDK app refreshes the copy. With `include_standard_library = true` the
  build copies the SDK's current library in instead.
- Schema 1 projects still load; the SDK writes schema 2 when it saves one.

### Build, install, run

```bash
bozkit validate my-mod
bozkit build my-mod
bozkit install my-mod --client path/to/boz-redux
```

- `build` writes the mod to `build/<mod id>/`, with a `boz-build.json` report: the project
  schema, dependencies, warnings and the SHA-256 of every file. A map is compiled first; this
  needs the game's files (the SDK's asset library, or a client given with `--client`).
- `install` builds and copies the mod into the client's `mods/` folder. It refuses to replace an
  existing mod unless you pass `--force`.
- The SDK app's **Run in game** and **Build & Run** install the mod, switch it on and start the
  game; a map starts straight into its level.

### Share a mod

```bash
bozkit package my-mod
```

This writes `build/<mod id>-<version>.zip`. Identical projects always give identical ZIPs: file
order, times and paths are normalised. Players unzip it into their client's `mods/` folder and
tick it in the launcher's **Mods** tab. A map mod then appears in the list **PLAY** opens.

Before you share:

- bump `version` when you change the mod;
- keep `game` set to the game version you tested with;
- run `bozkit validate my-mod --profile distribution` and read its warnings (see below).

### Dependencies

A mod can record the mods it needs:

```toml
[[dependencies]]
id = "another_mod"
version = ">=0.2.0"
```

They go into the build report and the mod's manifest. The client does not check them yet.

### Game files in a mod

A project may contain complete or edited game files (for example an edited
`kino_statics.group.bin` in `assets/`). That is fine for your own use. Whether you may share
them is your decision; the SDK helps you keep track. Mark where a file came from in the
manifest:

```toml
[[provenance]]
path = "assets/kino_statics.group.bin"
kind = "game-derived"
note = "Edited from my installed 1.0.11 data"
```

`kind` is one of `authored`, `game`, `game-derived`, `extracted`, `generated` and `unknown`
(other values are kept as they are). `bozkit validate --profile distribution` warns about
`game`, `game-derived` and `extracted` files. It never fails the build or leaves a file out.

When a small code change does the job, `assets.patch` changes a game file as the game loads it,
so the file never has to be shipped (see
[Making Lua mods](#change-a-file-as-it-loads)).

## Client Lua API

Everything the client itself gives a mod script, in Lua 5.4. The
[standard library](standard-library.md) is built on it and covers most needs in friendlier
form; use these functions directly when it does not. The API grows with each client release;
anything not listed here is not part of it yet.

### Scripts and modules

A mod is a folder in the client's `mods/` folder:

```
mods/my-mod/
  mod.toml          id, name, version, author, game, description
  assets/           replacement game files (see making-mods.md)
  scripts/main.lua  runs when the game starts, if the mod is switched on
```

`main.lua` runs once, just before the game starts, so its hooks and file patches see everything
the game does. It sets things up: registers event handlers, key bindings, hooks and so on; game
state (the console, a match) does not exist yet. The `frame` event starts with the first frame.
The game keeps running between events; a script never blocks.

Every mod has its own globals. The API below is shared, and `mod` describes the running mod:
`mod.id`, `mod.name`, `mod.version`, `mod.dir` (full path of the mod folder).

`require("name")` loads `scripts/name.lua` from the same mod (dots become folders:
`require("ui.tabs")` loads `scripts/ui/tabs.lua`), runs it once and returns what it returns.
`loadscript("name", env)` loads `scripts/name.lua` the same way but does not run it or remember
it: it returns the script as a function whose globals are the table `env`. The standard
library's `boz.prefabs` uses it to run a prefab's script once per object, each with its own
`self` (clients from before October 2026 do not have it).

Available standard libraries: `string`, `table`, `math`, `utf8`, `coroutine`, and `os` limited to
`os.time`, `os.clock`, `os.date` and `os.difftime`. There is no `io`, `dofile` or `loadfile`.

### Script errors

An error in `main.lua` stops that mod's setup and is written to `boz-log.txt` as
`[lua] <mod>: <message>` with a traceback. An error inside an event handler switches that handler
off (other handlers keep running) and is logged the same way. `print` and `log` also write to
`boz-log.txt` as `[lua] <mod>: ...`.

### events module

| Function | Description |
| --- | --- |
| `events.on(name, fn)` | Calls `fn` on every event `name`. |
| `events.off(name, fn)` | Removes a handler added with `events.on`. |

| Event | Arguments | Notes |
| --- | --- | --- |
| `frame` | `dt` (seconds since the last frame) | Once per displayed frame. The only place `ui` functions work. |
| `key` | `name`, `down`, `repeat` | Every key press and release. `name` is the key name used in `client.ini` (SDL names: `A`, `F1`, `` ` ``, `Left Shift`, `Escape`). Return `true` to say the mod used the key. |
| `action` | `name`, `down` | A game action pressed or released during a Zombies match (see `input`), before the game gets it. Return `true` to keep it from the game. |

### input module

| Function | Description |
| --- | --- |
| `input.bind(key, fn)` | Calls `fn()` when `key` is pressed (not on key repeat). One binding per key across all mods; the last one wins. A key a mod binds does not also type its character into the overlay. |
| `input.unbind(key)` | Removes the binding. |
| `input.send(action, down)` | Sends a game action as if its button was pressed (`down` true, the default) or released. Does not raise the `action` event. |
| `input.down(action)` | True while the player holds the action's binding. |
| `input.aiming()` | True while the player is aiming down sights. Approximate: it can miss aiming in some states. |
| `input.native()` | True when the client sends controls straight to the game (actions work). False with the old touchpad controls (`BOZ_TOUCHPAD_CONTROLS`, or a game definition without the input functions). |

The game still sees bound keys unless the overlay is capturing input (see `overlay`).

Actions are the game's own, whatever keys the player bound: `shoot`, `aim` (a toggle in the game), `reload`, `use`, `melee`, `grenade`, `tactical`, `crouch` (tap crouches, hold goes prone), `fire_mode`, `switch_weapon`. During a Zombies match the client turns the player's bindings into these (mouse look and movement go to the game directly). Dead Ops Arcade still uses the touchpad controls and raises no actions. The standard lib's `boz.input` wraps them.

### gamedef module

Names from the game definition the client loaded (`gamedef/`).

| Function | Returns | Description |
| --- | --- | --- |
| `gamedef.cvars()` | array | Every known console variable: `{name, type, default, used_by, lookup_only}`. |
| `gamedef.commands()` | array | Every known console command: `{name, id, owner}`. |

The game's console itself (running lines, reading and setting variables, its output) is not part
of the client: the standard library's `boz.console` provides it (see *Standard library* below).
The [console reference](console-reference.md) lists every variable and command.

### game module

Low-level access to the game. Addresses are numbers (the game is 32-bit); names are looked up in
the game definition (`gamedef/symbols`), so mods keep working when addresses are re-mapped.

| Function | Description |
| --- | --- |
| `game.symbol(name)` | Address of a named function or global, or `nil`. Thumb functions carry bit 0. |
| `game.base()` | Address the game image is loaded at. |
| `game.read(type, address)` | Reads memory. Types: `u8`, `i8`, `u16`, `i16`, `u32`, `i32`, `ptr`, `f32`, `bool`, `string` (third argument: maximum length, default 256). |
| `game.write(type, address, value)` | Writes memory (same types except `string`). |
| `game.call(target, ...)` | Calls a game function by name or address with up to 6 arguments: integers, booleans, `nil` (0) or strings (passed as a pointer to a copy, at most 4 per call, 1 KB each). Returns the result as an integer. Pass floats as `hook.float_bits(x)` (the game passes floats in integer registers). |
| `game.alloc(size)` / `game.free(address)` | Memory the game can read and write (zeroed), for buffers passed to game functions. |

`address` may also be a symbol name. Reading or writing a wrong address crashes the game: these
functions are for mod authors who know the data they touch.

### hook module

Runs Lua when a game function is called. The game's code is never patched; a hook costs nothing
until its function runs. Several hooks (from one or many mods) can share a function; they run in
the order they were added.

| Function | Description |
| --- | --- |
| `hook.add(target, {before = fn, after = fn})` | Hooks a function by gamedef name or address. Returns a handle. Either handler may be left out. |
| `hook.remove(handle)` | Removes a hook. |
| `hook.float_bits(x)` / `hook.bits_float(u)` | Converts between a float and the 32-bit pattern the game passes it as. |

Handlers receive a `call` object, valid only while the handler runs:

| Method | In | Description |
| --- | --- | --- |
| `call:arg(i)`, `call:arg_signed(i)`, `call:arg_float(i)` | before, after | Argument `i` (1-based; `this` is argument 1 for methods). In `after`, the values the function was called with. |
| `call:set_arg(i, v)`, `call:set_arg_float(i, v)` | before | Changes an argument. |
| `call:skip([value])`, `call:skip_float(value)` | before | Returns at once with `value` (default 0); the function does not run, `after` handlers are not called. |
| `call:result()`, `call:result_signed()`, `call:result_float()` | after | The return value. |
| `call:set_result(v)`, `call:set_result_float(v)` | after | Changes the return value. |
| `call:address()` | both | The hooked function's address. |

Hooks fire on the game thread (game logic, menus, rendering); functions run by the game's audio or
network threads are not hooked. An error in a handler switches that handler off.

```lua
-- Halve all damage the player takes (illustrative: check the function and its arguments in gamedef).
hook.add("CHealth::Damage", {before = function(call)
    call:set_arg(2, call:arg(2) // 2)
end})
```

### settings module

Values a mod keeps between sessions, saved per mod in `saves/mods/<mod id>.cfg`.

| Function | Description |
| --- | --- |
| `settings.get(key, [default])` | A saved value (string, number or boolean), or `default`. |
| `settings.set(key, value)` | Saves a value (`nil` removes it). Changes are written at the end of the frame. |

### overlay module

The overlay draws over the game. While it captures input, the game gets no mouse or keyboard
input, the mouse pointer is free and the overlay draws its own cursor.

| Function | Description |
| --- | --- |
| `overlay.capture(on)` | Takes the mouse and keyboard from the game (`true`) or gives them back. |
| `overlay.capturing()` | True while capturing. |

### ui module

Immediate-mode widgets (Dear ImGui), called from a `frame` handler every frame you want them
shown. Widgets that hold others take a function and close themselves even if it raises an error.
Sizes are in 720p units and scale with the window. Labels must be unique within a window; text
after `##` is not shown, so `"Run##SetRound"` shows "Run" with its own identity.

| Function | Returns | Description |
| --- | --- | --- |
| `ui.window(title, [opts], fn)` | open | A window. `opts`: `x`, `y`, `w`, `h` (first use), `closable` (adds a close button; returns false once it was pressed), `focus`, `no_title`, `no_resize`, `no_move`, `no_collapse`, `auto_size`, `no_background`, `no_inputs`, `no_scrollbar`. |
| `ui.child(id, w, h, fn)` | | A scrolling area. `0` fills the space; negative values leave that much room. |
| `ui.tab_bar(id, fn)` / `ui.tab(label, fn)` | / open | Tabs; `fn` runs for the selected tab. |
| `ui.collapsing(label, fn, [open])` | open | A collapsible section; `open` sets its first state. |
| `ui.tree(label, fn)` | open | A tree node. |
| `ui.table(id, columns, fn)` | | A table; call `ui.next_column()` before each cell. |
| `ui.text(s)`, `ui.text_wrapped(s)`, `ui.text_disabled(s)` | | Text. |
| `ui.text_colored(s, r, g, b, [a])` | | Coloured text (components 0 to 1). |
| `ui.button(label, [w, h])` | clicked | A button. |
| `ui.selectable(label, selected)` | clicked | A selectable row. |
| `ui.checkbox(label, value)` | changed, value | A checkbox. |
| `ui.slider(label, value, min, max, [integer])` | changed, value | A slider. |
| `ui.combo(label, index, items)` | changed, index | A drop-down; `index` counts from 1. |
| `ui.input(label, text, [opts])` | changed, text | A text box. `opts`: `hint`, `width` (negative: fill), `focus`, `submit` (returns true only when Enter is pressed), `history` (array of earlier lines for Up/Down). |
| `ui.same_line()`, `ui.spacing()` | | Layout. |
| `ui.separator([text])` | | A line, with a title if given. |
| `ui.tooltip(text)` | | Shows `text` while the previous widget is hovered. |
| `ui.item_width(w)` | | Width of the next widget. |
| `ui.focus_next()` | | Gives keyboard focus to the next widget. |
| `ui.scroll_to_bottom()`, `ui.at_bottom()` | / boolean | Scrolling inside the current window or child. |
| `ui.scale()` | number | The overlay scale (window height / 720). |
| `ui.wants_keyboard()` | boolean | True while a text box has focus. |

### assets module

| Function | Description |
| --- | --- |
| `assets.patch(file, fn)` | Every time the game opens `file` (matched by file name, without case), `fn(bytes)` gets the player's copy as a string and returns the changed bytes, or `nil` to leave it alone. Several mods can patch one file; patches run in load order. Register in `main.lua`, before the game loads the file. |

Replacement files in a mod's `assets/` folder (see [Making Lua mods](#replace-game-files)) are applied
before patches.

### shared module

`shared` is one table every mod sees (each mod's own globals are separate). Code that several
mods carry, like the standard lib, uses it to coordinate; mods can use it to talk to each other.

### Lua API and the standard library

Most mods should use the standard lib (`boz.*`) rather than the functions on this page: it turns
the game's internals into plain functions (`camera.set_fov(90)`,
`pause_settings.add_slider{...}`). See the [standard library](standard-library.md).

### API example

```lua
-- Toggle unlimited ammo with F5 and show its state in a corner.
local console = require("boz.console")
local on = false

input.bind("F5", function()
    on = not on
    console.set("WeaponsUnlimitedAmmo", on)
end)

events.on("frame", function()
    ui.window("ammo", {x = 10, y = 10, auto_size = true, no_title = true, no_inputs = true}, function()
        ui.text(on and "Unlimited ammo: on" or "Unlimited ammo: off")
    end)
end)
```

The Developer mod (`mods/developer`) is the complete reference: a console window, variable
browser, cheats and commands.
