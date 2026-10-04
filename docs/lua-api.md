# Lua API

Code mods for the BOZ Redux client are written in Lua 5.4. This page lists everything the client
itself gives a mod script. The standard lib built on it is in
[standard-library.md](standard-library.md), and [making-mods.md](making-mods.md) is the guide.
The API grows with each client release; anything not listed here is not part of it yet.

## Where scripts live

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

Available standard libraries: `string`, `table`, `math`, `utf8`, `coroutine`, and `os` limited to
`os.time`, `os.clock`, `os.date` and `os.difftime`. There is no `io`, `dofile` or `loadfile`.

## Errors

An error in `main.lua` stops that mod's setup and is written to `boz-log.txt` as
`[lua] <mod>: <message>` with a traceback. An error inside an event handler switches that handler
off (other handlers keep running) and is logged the same way. `print` and `log` also write to
`boz-log.txt` as `[lua] <mod>: ...`.

## events

| Function | Description |
| --- | --- |
| `events.on(name, fn)` | Calls `fn` on every event `name`. |
| `events.off(name, fn)` | Removes a handler added with `events.on`. |

| Event | Arguments | Notes |
| --- | --- | --- |
| `frame` | `dt` (seconds since the last frame) | Once per displayed frame. The only place `ui` functions work. |
| `key` | `name`, `down`, `repeat` | Every key press and release. `name` is the key name used in `client.ini` (SDL names: `A`, `F1`, `` ` ``, `Left Shift`, `Escape`). Return `true` to say the mod used the key. |
| `action` | `name`, `down` | A game action pressed or released during a Zombies match (see `input`), before the game gets it. Return `true` to keep it from the game. |

## input

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

## gamedef

Names from the game definition the client loaded (`gamedef/`).

| Function | Returns | Description |
| --- | --- | --- |
| `gamedef.symbol(name)` | address or `nil` | Same as `game.symbol`. |
| `gamedef.cvars()` | array | Every known console variable: `{name, type, default, used_by, lookup_only}`. |
| `gamedef.commands()` | array | Every known console command: `{name, id, owner}`. |

The game's console itself (running lines, reading and setting variables, its output) is not part
of the client: the standard library's `boz.console` provides it (see *Standard library* below).
[console-reference.md](console-reference.md) lists every variable and command.

## game

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

## hook

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

## settings

Values a mod keeps between sessions, saved per mod in `saves/mods/<mod id>.cfg`.

| Function | Description |
| --- | --- |
| `settings.get(key, [default])` | A saved value (string, number or boolean), or `default`. |
| `settings.set(key, value)` | Saves a value (`nil` removes it). Changes are written at the end of the frame. |

## overlay

The overlay draws over the game. While it captures input, the game gets no mouse or keyboard
input, the mouse pointer is free and the overlay draws its own cursor.

| Function | Description |
| --- | --- |
| `overlay.capture(on)` | Takes the mouse and keyboard from the game (`true`) or gives them back. |
| `overlay.capturing()` | True while capturing. |

## ui

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

## assets

| Function | Description |
| --- | --- |
| `assets.patch(file, fn)` | Every time the game opens `file` (matched by file name, without case), `fn(bytes)` gets the player's copy as a string and returns the changed bytes, or `nil` to leave it alone. Several mods can patch one file; patches run in load order. Register in `main.lua`, before the game loads the file. |

Replacement files in a mod's `assets/` folder (see [making-mods.md](making-mods.md)) are applied
before patches.

## shared

`shared` is one table every mod sees (each mod's own globals are separate). Code that several
mods carry, like the standard lib, uses it to coordinate; mods can use it to talk to each other.

## Standard library

Most mods should use the standard lib (`boz.*`) rather than the functions on this page: it turns
the game's internals into plain functions (`player.set_fov(90)`,
`pause_settings.add_slider{...}`). See [standard-library.md](standard-library.md).

## Example

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
