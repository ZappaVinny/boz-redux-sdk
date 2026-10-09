# Standard library

The standard lib (`boz.*`) is the friendly layer for writing mods: plain functions for the
player, menus, the console and more, with the game's addresses, offsets and events hidden
inside. Mods should use it instead of the client's low-level `game`/`hook` functions
([lua-api.md](lua-api.md)) wherever it covers what they need.

This page is generated from the comments in `lib/boz/*.lua` (`tools/stdlib_doc.py`); see
[making-mods.md](making-mods.md) for how to use it in a mod.

Using it in a mod: copy `lib/boz` into the mod as `scripts/boz` (or link it while developing),
then `local player = require("boz.player")`. Each mod carries its own copy; copies in
different mods work together. The SDK will add it to mods automatically once it builds them.

Functions that need a Zombies match return `nil` (or `false`) outside one instead of failing.

## Contents

- **Gameplay**: [boz.player](#bozplayer), [boz.fly](#bozfly), [boz.rounds](#bozrounds)
- **Controls**: [boz.input](#bozinput)
- **Console**: [boz.console](#bozconsole)
- **Menus and text**: [boz.pause_settings](#bozpausesettings), [boz.text](#boztext)
- **Game UI building blocks**: [boz.iwui](#boziwui), [boz.frontend](#bozfrontend), [boz.flash](#bozflash)
- **Low-level helpers**: [boz.components](#bozcomponents), [boz.hash](#bozhash), [boz.swf](#bozswf), [boz.avm1](#bozavm1)
- **Other**: [boz.levels](#bozlevels)

## Gameplay

### boz.player

The local player in a Zombies match: perks and field of view.

```lua
local player = require("boz.player")
player.give_all_perks()
player.set_fov(90)                  -- kept across matches; aiming down sights still zooms
```

| Function | Description |
| --- | --- |
| `player.in_match()` | True while a Zombies match with a local player is running. |
| `player.PERKS` | The perk names, in the game's order. |
| `player.perks()` | The perks the player owns, by name ({["Juggernog"] = true, ...}), or nil outside a match. |
| `player.give_perk(name)` | Gives a perk by name (with its effects, e.g. Juggernog's health). False if not possible. |
| `player.give_all_perks()` | Gives every perk the player is missing. Returns the names given, or nil outside a match. |
| `player.fov()` | The field of view in degrees and the map's default, or nil outside a match. |
| `player.set_fov(degrees)` | Sets the field of view in degrees (aiming down sights still zooms); nil restores the map's default. The value is kept across matches. Returns false outside a match (it still applies when the next match starts). |

### boz.fly

Noclip, using the game's developer fly mode.

```lua
local fly = require("boz.fly")
fly.set(true)                       -- fly through walls; movement keys fly where you look
fly.move_vertical(1, dt)            -- call each frame while an "up" key is held
```

<details><summary>How it works</summary>

CPlayerFreeFly toggles on SUBJECT_PLAYER_FREE_MODE (sent to CInputManager's subject); while flying, movement moves the player along the view at FreeFlySpeed and SUBJECT_PLAYER_ASCEND raises it by FreeFlySpeed (sent here with the speed scaled and signed).

</details>

| Function | Description |
| --- | --- |
| `fly.available()` | True if fly mode can be used now (a Zombies match whose player has the fly component). |
| `fly.active()` | True while flying. |
| `fly.set(on)` | Turns fly mode on or off (nil toggles). Returns the new state, or nil if unavailable. |
| `fly.speed()` | Fly speed (FreeFlySpeed): distance per frame at full speed. |
| `fly.set_speed(speed)` | Sets the fly speed (FreeFlySpeed). |
| `fly.move_vertical(direction, dt)` | Moves up (direction 1) or down (-1) for dt seconds at fly speed. Call it every frame while a key is held. |

### boz.rounds

Rounds and the match (Zombies mode).

```lua
rounds.start_next()   rounds.spawn_zombie()   rounds.kill_all()
```

<details><summary>How it works</summary>

these run the game's developer commands (StartWave, SpawnZombie, ...) through boz.console.

</details>

| Function | Description |
| --- | --- |
| `rounds.start_next()` | Starts the next round now. |
| `rounds.spawn_zombie()` | Spawns one zombie. |
| `rounds.kill_all()` | Kills every zombie. |
| `rounds.power_on()` | Turns the map's power on. |
| `rounds.toggle_pause()` | Pauses or resumes game time. |
| `rounds.set_time_scale(factor)` | Game speed multiplier (1 = normal). |

## Controls

### boz.input

The player's controls during a Zombies match: watch, change or send the game's actions.

```lua
local input = require("boz.input")
input.on_action("melee", function(down)
    log("knife " .. (down and "pressed" or "released"))
end)
input.send("reload")
```

Actions: shoot, aim, reload, use, melee, grenade, tactical, crouch, fire_mode, switch_weapon. They are the game's own actions, whatever keys the player bound to them.

<details><summary>How it works</summary>

the client sends the player's key presses straight to the game's input (native controls) and raises the "action" event first; a handler that returns true keeps the action from the game. Dead Ops Arcade still uses the touchpad path and raises no actions.

</details>

| Function | Description |
| --- | --- |
| `M.ACTIONS` | The action names. |
| `M.on_action(name, fn)` | Calls fn(down) when the player presses (true) or releases (false) the action. If fn returns true the game does not get it. Several handlers may watch one action; any one returning true keeps it from the game. |
| `M.send(name, down)` | Sends an action to the game as if its button was pressed (down = true, the default) or released. Handlers from on_action do not see it. |
| `M.held(name)` | True while the player holds the action's key or button. |
| `M.aiming()` | True while the player is aiming down sights (approximate: it can miss aiming in some states). |
| `M.native()` | True when the client sends controls straight to the game (actions work); false with the old touchpad controls. |

## Console

### boz.console

The game's developer console.

```lua
local console = require("boz.console")
console.set("WeaponsUnlimitedAmmo", true)
print(console.exec("listVars Unlimited"))
```

Runs console lines, reads and sets console variables (cvars), registers new ones, and passes on everything the console prints. Every variable and command is listed in console-reference.md.

<details><summary>How it works</summary>

the release build kept the console (CIwConsole, g_console) but no display, so Console_Print has nowhere to send text. This module hooks Console_Print and wraps the console's own functions (Console_Execute, Console_FindVar, Cvar_Register*).

</details>

| Function | Description |
| --- | --- |
| `console.ready()` | True once the game created its console (from the first frame on, in practice). |
| `console.on_output(fn)` | Calls fn(text) for every line the console prints. |
| `console.exec(line)` | Runs a console line as if typed. Returns what it printed, or nil and an error. |
| `console.get(name)` | A console variable's value as text, or nil when the game has not registered it. |
| `console.set(name, value)` | Sets a registered variable from text (numbers and booleans are converted). Returns the value the game kept, or nil and an error. |
| `console.register(name, value, kind)` | Registers a variable with the game (if it does not exist yet) and sets it. kind: bool, int, float or string; guessed from the value when omitted. Makes values the game only reads, like StartingScore, take effect. Returns the value and the kind used. |
| `console.vars()` | Every known variable: {name, type, default, used_by, lookup_only}. |
| `console.commands()` | Every known command: {name, id, owner}. |

## Menus and text

### boz.pause_settings

Settings in the game's pause menu (Settings page, CIngameStateOptions).

```lua
local pause_settings = require("boz.pause_settings")
pause_settings.add_slider{id = "fov", label = "Field of view", min = 50, max = 120, step = 1,
                          get = function() return value end, set = function(v) ... end}
pause_settings.add_checkbox{id = "aim_toggle", label = "Toggle aim",
                            get = function() return on end, set = function(on) ... end}
```

Call these when the mod's script starts. Each time the page opens, the rows are added in the order they were registered, stacked in the free column right of the game's sliders, styled exactly like the game's own (they are copies of its widgets).

<details><summary>How it works</summary>

the page is one flat IwUI panel. A slider row is copied from the detail level row (bar image, slider, title label), a checkbox row from the auto aim row (label, box, cross, button). Copies keep the original's slot (OnLODChanged, OnAutoAim); hooks on those slots take the events that come from a copy and leave the game's own alone. Labels show a string id registered with boz.text.

</details>

| Function | Description |
| --- | --- |
| `pause_settings.add_slider(spec)` | Adds a slider. spec: id, label, min, max, step (optional), get() -> number, set(number). |
| `pause_settings.add_checkbox(spec)` | Adds a checkbox. spec: id, label, get() -> boolean, set(boolean). |

### boz.text

Adding text to the game's string table.

```lua
text.add("S_MYMOD_TITLE", "My setting")
iwui.set_text_id(label, "S_MYMOD_TITLE")
```

The game shows text by string id (like S_MENU_MUSIC) in the current language. text.add registers an id of the mod's own; use it wherever the game takes a string id.

<details><summary>How it works</summary>

menus and labels hash the id and ask Localise_GetString for the text; a hook answers for the mod's ids.

</details>

| Function | Description |
| --- | --- |
| `text.add(id, value)` | Adds (or replaces) the text for a string id. Returns the id's hash. |

## Game UI building blocks

### boz.iwui

The in-game menus (Marmalade IwUI pages, e.g. the pause menu).

```lua
local slider = iwui.find("musicSlider")
local copy = iwui.clone(slider)
iwui.add_child(iwui.parent(slider), copy)
iwui.set_position(copy, 800, 300)
```

Find elements by name, walk and dump a page, copy and place widgets, set labels, slider values and visibility. boz.pause_settings is built on it; use that for settings rows.

<details><summary>How it works</summary>

pages are trees of elements shown by CUIPageManager. Element layout: +4 name hash, +0x18 parent, +0x1c children (data, +0x20 count), +0x34 event handlers, +0x48/+0x4c slots, +0x5c position, +0x64 size, +0x8c layout, +0xa0 properties. Widgets call named slots on their page's event handler (a slider's OnSliderChanged calls e.g. CIngameStateOptions::OnMusicChanged with itself as the element).

</details>

| Function | Description |
| --- | --- |
| `iwui.find(name)` | The element with this name on the current page, or nil. |
| `iwui.parent(element)` | The element's parent, or nil. |
| `iwui.children(element)` | The element's children (list of addresses). |
| `iwui.class_name(element)` | The element's C++ class (from its RTTI), e.g. "CIwUISlider". |
| `iwui.name_hash(element)` | The hash of the element's name (compare with boz.hash.name). |
| `iwui.rect(element)` | Position and size in the parent (pixels): +0x5c/+0x60 position, +0x64/+0x68 size. |
| `iwui.set_position(element, x, y)` | Moves an element within its parent. |
| `iwui.is_named(element, name)` | True if the element's name is name. |
| `iwui.clone(element)` | A deep copy of an element (not yet on any page; add it with add_child). |
| `iwui.add_child(parent, child)` | Adds an element to a parent (and to the parent's layout, if it has one). |
| `iwui.set_name(element, name)` | Renames an element (CIwManaged::SetName, vtable slot 9) so FindElement finds it. |
| `iwui.set_visible(element, visible)` | Shows or hides an element. |
| `iwui.set_caption(label, text)` | Sets a label's text. SetCaption only stores the "caption" property and skips the redraw in some states, so the label is also told the property changed (vtable +0xb8). |
| `iwui.set_text_id(label, id)` | Points a label at a string id (boz.text.add, or one of the game's like S_MENU_MUSIC). The game's labels show their localiseCaption string id rather than their caption. Changes only the label's own property (not one shared through its style). Returns false if it has none. |
| `iwui.set_value(slider, value)` | Sets a slider's value (0..4096 on the game's sliders); calls its OnSliderChanged slot. |
| `iwui.find_in(element, test, depth)` | The first descendant (depth first) for which test(element) is true. |
| `iwui.dump(element, names, depth)` | Logs the element tree under element (class, name, children); names resolves known names. |

### boz.frontend

Changing the main menu (front end), one Flash movie played by gameswf.

Building blocks for mods that change main-menu screens; higher-level helpers (adding widgets to a screen) will grow here. frontend.patch_screen adds ActionScript (built with boz.avm1) to a screen; frontend.call runs one of the movie's ActionScript functions.

<details><summary>How it works</summary>

ActionScript talks to the game with _root.sendMsg(name, a, b), which the native IsSendMessage turns into the active CFlashMenuState's OnEvent(IwHashString(name), a, b) (numbers arrive as integers); screens pass events they do not know to CFlashMenuState::OnEvent, so hooks can add new ones. The game calls ActionScript with CFlashMenuState::CallActionScript(state, function, format, ...) (gameswf format: "%d", "%f", "%s", comma separated). The movie is patched as it loads (assets.patch), so no game file is changed or shipped.

</details>

| Function | Description |
| --- | --- |
| `frontend.patch_screen(names, build)` | Adds a frame script to the screen (sprite) whose scripts use all of names (e.g. {"initialise", "SUBJECT_OPTIONS_VOLUME"} is the Options screen). build(b) fills an avm1 builder; the script runs after the screen's own first-frame script. Call while the mod's script starts (before the menu loads). |
| `frontend.call(state, fn, format, ...)` | Calls an ActionScript function on a Flash menu state (CFlashMenuState) with gameswf's format, e.g. frontend.call(state, "setMusicVol", "%d", 50). |

### boz.flash

Debugging the game's Flash menus (gameswf).

flash.capture_log() makes ActionScript trace() output and gameswf's own warnings appear in boz-log.txt as "[flash] ...".

<details><summary>How it works</summary>

the release build sets no gameswf log handler, so nothing is formatted. A hook on gameswf_LogMsg formats each message with the game's vsnprintf.

</details>

| Function | Description |
| --- | --- |
| `flash.capture_log()` | Shows ActionScript trace() output and gameswf warnings in boz-log.txt as "[flash] ...". |

## Low-level helpers

### boz.components

Finding the game's entity components (helper for the other modules).

Most mods use boz.player and friends instead. components.local_player() gives the local player's entity; components.on_player(table) or components.each(table) find components by the gamedef name of their table (e.g. "CPerkManager::s_table").

<details><summary>How it works</summary>

component tables (T::s_table) keep components in a red-black tree keyed by entity id: header node pointer at table +4 (header +8 = first node), nodes link parent +4, left +8, right +0xc, key +0x10, component +0x14.

</details>

| Function | Description |
| --- | --- |
| `components.local_player()` | The local player's entity (CLevelManager +0x1a0) and its id, or nil outside a Zombies match. |
| `components.find(table_name, id)` | The component of an entity id in a table (by gamedef name, e.g. "CPerkManager::s_table"). |
| `components.on_player(table_name)` | The component on the local player's entity, or nil. |
| `components.each(table_name)` | Iterates the components in a table: for component, id in components.each(name) do ... end |

### boz.hash

The game's name hash.

Event ids (SUBJECT_*), element names, resource names, string ids and console names are all hashed this way: hash.name("musicSlider").

<details><summary>How it works</summary>

IwHashString is djb2 (h = h * 33 + c from 5381) over the name with A-Z lower-cased.

</details>

| Function | Description |
| --- | --- |
| `hash.name(text)` | The game's hash of a name (IwHashString). |

### boz.swf

Reading and changing Flash movies (SWF), for patching the game's menus.

Most mods use boz.frontend instead. swf.parse(bytes) gives a movie whose sprites can be found by the names their scripts use and given extra frame scripts; movie:serialize() writes it back.

<details><summary>How it works</summary>

works on the uncompressed movies the game ships (FWS). Tags keep their original bytes unless changed, so an untouched movie serializes back byte for byte.

</details>

| Function | Description |
| --- | --- |
| `Sprite:actions()` | The frame scripts (DoAction bodies) of the sprite's tags, in order. |
| `Sprite:uses(text)` | True if any frame script of the sprite contains text (a name used in its code). |
| `Sprite:add_first_frame_action(action_bytes)` | Adds a frame script to the sprite's first frame, after the scripts already there. |
| `Sprite:serialize()` | The sprite's tag bytes (used by Movie:serialize). |
| `swf.parse(bytes)` | Parses a movie. Returns the movie, or nil and an error. |
| `Movie:sprites()` | Every sprite (DefineSprite) in the movie, parsed. |
| `Movie:sprite(id)` | The sprite with this character id, or nil. |
| `Movie:find_sprite_using(...)` | The first sprite whose frame scripts use all the given names, or nil. |
| `Movie:serialize()` | The movie as bytes, with changed sprites rebuilt. |

### boz.avm1

Building ActionScript 2 bytecode (AVM1) for the game's Flash menus.

```lua
local b = avm1.builder()
b:push("hello from a mod"):op("Trace")
local bytes = b:bytes()   -- a frame script for boz.swf / boz.frontend.patch_screen
```

A builder collects actions. Values are pushed with :push(...) (strings, numbers, booleans, avm1.NULL, avm1.UNDEFINED); :get("a.b.c") pushes a path; functions are built with :func(name, params, body_fn); jumps use labels. Used by boz.frontend.

| Function | Description |
| --- | --- |
| `Builder:push(...)` | Pushes values onto the stack (one Push action). |
| `Builder:op(name)` | Emits a simple action by name (GetVariable, SetMember, CallMethod, ...). |
| `Builder:label(name)` | Marks a jump target. |
| `Builder:if_true(name)` | Jumps to a label if the value on the stack is true. |
| `Builder:jump(name)` | Jumps to a label. |
| `Builder:func(name, params, body)` | Defines a function: name ("" for an anonymous one, left on the stack), parameter names, and body(b) which fills a builder for the function body. |
| `Builder:bytes(inner)` | The finished bytecode; frame scripts end with an End action unless inner is set. |
| `Builder:get(path)` | Pushes the value of a dotted path, e.g. b:get("_root.Options.settings"). |
| `Builder:call_method(push_obj, method, ...)` | Calls obj.method(args...) where obj is pushed by push_obj(b); leaves the result on the stack. |
| `Builder:trace(text, path)` | trace(text .. value-of-path): writes a line to the Flash log (see boz.flash.capture_log). |

## Other

### boz.levels

Start levels (Zombies maps) without going through the menus.

```lua
levels.start("kino")      levels.autostart()
```

<details><summary>How it works</summary>

the front end's StartLevel console command starts a single-player match on a level by name (it sends the game's own start-game event). The command only works once the front end is running, so levels.start waits for the Flash menu's first ActionScript call and a short settling time. levels.autostart reads a one-shot request from the mod's settings: the Blender add-on's Build & Run writes it to start the level just saved.

</details>

| Function | Description |
| --- | --- |
| `levels.start(name)` | Starts a single-player match on the level (e.g. "kino") once the front end is up. Call it while the mod's script starts; the match starts after the main menu appears. |
| `levels.autostart()` | Starts the level a tool asked for, once: reads and clears the mod's "autostart_level" setting (the Blender add-on's Build & Run writes it). Returns the level name or nil. |
