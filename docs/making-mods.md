# Making Lua mods

This guide takes you from an empty folder to a mod that changes the game, adds settings to the
pause menu and hooks game functions. It assumes you can edit text files and have the BOZ Redux
client set up with the game. No C, Ghidra or reverse engineering is needed for most mods.

**References** you will use alongside it:

- [standard-library.md](standard-library.md): the standard lib (`boz.*`), the functions most mods
  are built from. Start here when looking for something.
- [lua-api.md](lua-api.md): what the client itself gives Lua (events, input, settings, hooks,
  memory, the overlay UI). Lower level.
- [console-reference.md](console-reference.md): every console variable and command in the game.

## How it fits together

| Layer | What it is | You |
| --- | --- | --- |
| **Client** | The program that runs the game: emulator, window, sound, controls, file loading, and the Lua runtime with its low-level functions (`game`, `hook`, `events`, `ui`, ...). | use it |
| **Standard lib** (`boz.*`) | Lua modules that turn the game's internals into plain functions: `player.set_fov(90)`, `pause_settings.add_slider{...}`, `console.set(...)`. | use it |
| **Your mod** | A folder with a manifest, scripts and optional replacement files. | write it |

Two rules keep mods working and keep official project history clean:

- **Never commit game files to the BOZ Redux repositories.** SDK projects and local packages may
  contain complete, extracted or edited files for development and testing. Mod authors are
  responsible for deciding what they are permitted to distribute. `assets.patch` is useful when a
  code-only change is preferable, but it is not a requirement.
- **Use names, not addresses.** The standard lib and `gamedef` names (`"CScoreManager::AddScore"`)
  keep working when the game definition is updated; raw numbers do not.

## Your first mod

For a quick experiment, create a folder in the client's `mods/` folder (next to `client.ini`):

```
mods/hello/
  mod.toml
  scripts/main.lua
```

`mod.toml` describes the mod:

```toml
id = "hello"
name = "Hello"
version = "0.1.0"
author = "you"
game = "1.0.11"
description = "My first mod: unlimited ammo on F5."
```

`scripts/main.lua` is the code. This one toggles unlimited ammo with F5 and shows a small label
while it is on:

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

It uses the standard lib (`boz.console`), so a hand-made mod needs a copy of the SDK's `lib/boz`
folder at `mods/hello/scripts/boz`. For normal development, create an
[SDK project](sdk-projects.md); its builder adds the library automatically.

Start the launcher. **Mods** lists "Hello"; make sure it is ticked, press **Play**, start a
match and press F5. Open `boz-log.txt` (next to `client.ini`) to see `[lua] hello: Hello from
my first mod`, and any errors.

## The mod folder

```
mods/<folder>/
  mod.toml        id, name, version, author, game, description
  scripts/        Lua: main.lua runs; other files load with require
  assets/         replacement files (optional), see "Replacing game files"
```

| `mod.toml` key | Meaning |
| --- | --- |
| `id` | Unique, lower-case, no spaces. Used for settings and the load order. Defaults to the folder name. |
| `name`, `version`, `author`, `description` | Shown in the launcher. |
| `game` | The game version the mod is made for (`1.0.11`). The launcher warns about others. |

The launcher's **Mods** tab turns mods on and off and sets their order; when two mods replace
the same file, the later one wins.

## How your script runs

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

## Using the standard lib

Require the modules you need:

```lua
local player = require("boz.player")
local console = require("boz.console")
local pause_settings = require("boz.pause_settings")
```

What is in it (full list in [standard-library.md](standard-library.md)):

| Module | For |
| --- | --- |
| `boz.player` | Perks, field of view |
| `boz.input` | Watch, block or send the game's actions (shoot, aim, reload, ...) |
| `boz.fly` | Noclip |
| `boz.rounds` | Next round, spawn or kill zombies, power, time |
| `boz.console` | Console variables and commands |
| `boz.pause_settings` | Sliders and checkboxes in the pause menu's Settings page |
| `boz.text` | Your own text for the game's menus |
| `boz.iwui`, `boz.frontend` | Building blocks for menu changes |

Functions that only make sense in a match (perks, field of view, fly) return `nil` or `false`
outside one, so you can call them any time.

## Recipes

### Save a setting

```lua
local volume = settings.get("volume", 0.5)   -- the saved value, or the default
settings.set("volume", 0.8)                   -- saved to saves/mods/<id>.cfg
```

Values are strings, numbers or booleans.

### Add a setting to the pause menu

The pause menu's Settings page gets new rows that look exactly like the game's own. This is
the Redux mod's field of view setting, complete:

```lua
local pause_settings = require("boz.pause_settings")
local player = require("boz.player")

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
        player.set_fov(value)
    end,
}

player.set_fov(saved_fov())   -- apply the saved value from the start
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

### Use the game's console variables

The game has hundreds of settings and cheats as console variables
([console-reference.md](console-reference.md)):

```lua
local console = require("boz.console")
console.set("WeaponsUnlimitedAmmo", true)
print(console.get("WalkSpeed"))
console.exec("SwitchPowerOn")
```

Many variables exist only during a match (the game creates them when the code using them first
runs); `console.get` returns `nil` until then. Some the game reads but never creates (marked
*lookup only*): create them with `console.register("StartingScore", 5000)`.

### Show a window or overlay

The client draws windows over the game with Dear ImGui (`ui.*`, in [lua-api.md](lua-api.md)).
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

### Replace game files

Put replacement files in your mod's `assets/` folder; the client uses them instead of the
game's when the game loads them. The game's packs store plain file names, so
`assets/weapons_kino.group.bin` replaces that file wherever the game asks for it. Turn on
**Log every file the game opens** in the launcher's settings to see the names it uses.

Game data files (`.group.bin`) can be read and edited with the SDK's bozkit
([asset-formats.md](asset-formats.md)): for example
`python3 -m bozkit set weapons_kino.group.bin colt45 m_clipSize 12 --component CPlayerWeapon -o out.group.bin`.

The SDK deliberately supports complete and edited game files in local projects and packages. Mark
their provenance in `boz-project.toml` to receive a distribution warning, then make your own
decision about sharing them. When a code-only change is useful, use `assets.patch`:

### Change a file as it loads

```lua
assets.patch("weapons_kino.group.bin", function(bytes)
    -- return the changed bytes (a Lua string), or nil to leave the file alone
    return bytes
end)
```

The function gets the player's own copy of the file each time the game opens it. Register the
patch in `main.lua`, before the game loads the file. The standard lib uses this for the main
menu (`boz.frontend`).

## Hooks: when the standard lib is not enough

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
logged. Hooks only see the game's main thread (game logic, menus, drawing). See
[lua-api.md](lua-api.md) for all of it, and keep hook handlers short: some functions run many
times per frame.

Reading and writing game memory (`game.read`, `game.write`) and calling functions
(`game.call`) are also available. They are powerful and unforgiving: a wrong address crashes the
game. Prefer the standard lib; if you write something reusable this way, it probably belongs in
the standard lib.

## Debugging

- **`boz-log.txt`** (next to `client.ini`) has your `log(...)` and `print(...)` lines, every
  error with a traceback, and what the client loaded (`[mods]`, `[lua]`, `[gamedef]`).
- The **Developer** mod (in the SDK's `mods/developer`) opens the game's console with `` ` ``:
  run commands, watch variables, try cheats. Turn it on in the launcher.
- **Log every file the game opens** (launcher settings) shows file names for `assets/` and
  `assets.patch`.
- For menu work: `iwui.dump(element)` logs a page's widgets; `require("boz.flash").capture_log()`
  logs the main menu's ActionScript `trace()` output and warnings.

## Mods working together

- Every mod has its own globals and its own copy of the standard lib; copies cooperate (pause
  menu rows stack, hooks chain).
- The load order (Mods tab) decides which file wins when two mods replace the same one, and the
  order hooks and settings rows are added.
- `shared` is one table every mod can read and write, for mods that want to talk to each other.

## Sharing your mod

Use `bozkit package` to create a deterministic ZIP containing the mod and its standard-library
copy. Players unzip it into their `mods/` folder and tick it in the launcher. Bump `version` when
you change it, keep `game` set to the tested version, and review the distribution-profile warnings
for any game-derived content you chose to include.
