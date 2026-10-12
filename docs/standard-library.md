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
- **Other**: [boz.levels](#bozlevels), [boz.objects](#bozobjects), [boz.prefabs](#bozprefabs), [boz.weapons](#bozweapons), [boz.world](#bozworld)

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
| `components.each(table_name)` | Iterates the components in a table (its gamedef name, or its address): for component, id in components.each(name) do ... end |

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
| `levels.autostart()` | Starts the level a tool asked for, once: reads and clears the mod's "autostart_level" setting (the SDK's Build & Run writes it), and its "autostart_vars" ("Name=value;..."), console variables set just before the level starts (e.g. UnlimitedHealth=true). Returns the level name or nil. |

### boz.objects

The map's objects by name: show and hide them, switch their collision, open and

close the walkable area under them, and react when players walk into them, use them or shoot them. The building blocks for triggers and easter eggs.

```lua
local objects = require("boz.objects")
local skull = objects.get("Skull_1")
skull:on("use", function(object) object:hide() end)
objects.on("Secret_Room_Trigger", "enter", function(object, who)
    if who.player then objects.get("Secret_Wall"):hide():set_collision(false):open_navmesh() end
end)
```

Names are the script names the editor shows for each object (Properties → Object → Game → Scripts): turn on "Scripts can change it" there. Shipped entities use their own names.

<details><summary>How it works</summary>

- CIsEntityDB::FindEntity(name hash) gives the entity (a pointer; its id is at +4). A

</details>

```lua
component's entity pointer is at component +0xc; children hang off CIsHierarchy +0x24.
```

- Visibility: CIsRenderableModel::SetVisible (doors hide this way after opening). - Collision: CIsCollisionObject::Enable / Disable on the entity's collision box, sphere,

```lua
capsule or mesh (what SUBJECT_ENABLE/DISABLE_COLLISION do).
```

- Walkable area: navmesh polygons carry a tag (a name hash); NavMesh_SetTagOpen(navmesh, tag,

```lua
open) opens or closes them, as doors do with their own name. The editor tags the polygons
under objects set to block the walkable area with the object's name.
```

- "enter"/"exit": CIsCollisionObject::OnCollisionEnter/OnCollisionExit (this, other) run

```lua
when two collision objects start or stop touching; ghost volumes (triggers) get them too.
```

- "use": Poi_SendUse runs when the player presses use at the point of interest in reach

```lua
(entity at CLevelManager +0x214).
```

- "damage": CHealth::Damage(health, amount, attacker) on objects with health. - "hit": CEasterEgg::OnEvent runs when a weapon hits a skull (Hit volumes are made from the

```lua
musical easter egg's skulls); for objects with "hit" handlers the game's handling is skipped,
so they stay out of the level's own easter egg.
```

- Positions: the entity's CIsTransform keeps its world matrix at +0x38, the position at

```lua
+0x5c/+0x60/+0x64 (game centimetres, y up); CIsTransform::UpdateWorld refreshes it when the
transform moved.
```

| Function | Description |
| --- | --- |
| `objects.level()` | A key that changes when another level loads (0 outside a match). |
| `objects.get(name)` | The object called `name` (a handle: it finds the entity when used, so it can be made before the level loads). Names are not case-sensitive. |
| `objects.find(name)` | The object called `name` if it exists in the running level, else nil. |
| `Object:entity_pointer()` | The entity pointer, or 0 when the object is not in the running level. |
| `Object:exists()` | True when the object is in the running level. |
| `Object:set_visible(visible)` | Shows or hides the object's models (its collision and behaviour stay). Returns the object. |
| `Object:show()` | Shows the object. Returns the object. |
| `Object:hide()` | Hides the object. Returns the object. |
| `Object:set_collision(enabled)` | Switches the object's collision on or off (players and bullets pass through it when off). Returns the object. |
| `objects.set_navmesh(tag, open)` | Opens (true) or closes (false) the walkable area tagged `tag` (a name: an object set to block the walkable area, or a door). Returns true when the level has a navmesh. |
| `Object:set_navmesh(open)` | Opens or closes the walkable area under the object (it must be set to block the walkable area in the editor). Returns the object. |
| `Object:open_navmesh()` | Lets zombies and players walk where the object blocked them. Returns the object. |
| `Object:close_navmesh()` | Blocks the walkable area under the object again. Returns the object. |
| `objects.transform_position(transform)` | The world position of a CIsTransform component: {x, y, z} in game centimetres (y is up). |
| `objects.position_of(entity)` | The world position of an entity (pointer), or nil when it has no transform. |
| `objects.distance(a, b)` | The distance in centimetres between two positions or objects (anything with :position()), or nil when either has no position. |
| `Object:position()` | The object's world position {x, y, z} (game centimetres, y is up), or nil when it is not in the running level. |
| `Object:near(target, distance)` | True when the object is within `distance` centimetres of `target` (a position such as zombie_killed's data.position, or another object). |
| `Object:on(event, fn)` | Calls `fn(object, info)` on the object's `event`: "enter" / "exit" (something starts or stops touching it; info.player, info.zombie, info.entity), "use" (the player pressed use at it), "hit" (a weapon hit it: Hit volumes), "damage" (it was hurt; info.amount, info.attacker). Returns the object. |
| `objects.on(name, event, fn)` | objects.on(name, event, fn): the same as objects.get(name):on(event, fn). |

### boz.prefabs

Scripts for the map's prefabs, models and volumes, and the event bus between them.

A script is attached to an object in the editor (Properties → Object → Game → Script). It is just the handlers; `self` is the object it is attached to:

```lua
function on_hit(volume, info)              -- a Hit volume of this prefab was shot
    self:part("Door"):hide():set_collision(false):open_navmesh()
    boz.send("vault_open", {by = self.name})
end
```

The script runs once per object using it, each with its own `self` and its own top-level variables (a `local hits = 0` at the top counts per object). `boz` is this module.

Saved with the game: a script's global variables (`hits = 0`, not `local hits = 0`) and boz.globals (one table every script of the map shares) are written when the game saves and come back when the player continues that save, before start() runs. Numbers, strings, booleans and tables of those are saved; functions and handles are not.

Timers: boz.after(seconds, fn) and boz.every(seconds, fn) run on game time (they wait while the game is paused) and return a timer with :cancel().

On `self`: self.name, self.properties (the values set in the editor for the script's ---@property lines), self:part(name) and self:parts() for a prefab's parts, and show/hide, set_collision, open_navmesh/close_navmesh for the whole object.

Handlers a script may define (all optional):

```lua
start()                      the level started
on_enter(volume, who), on_exit(volume, who)   a Trigger volume (who.player, who.zombie)
on_hit(volume, info)         a Hit volume was shot
on_use(volume, who)          the player pressed use at a Use volume (its cost already paid)
on_event(name, data)         boz.send(name, data) from any script, and game events:
                             "round_started" {round = n}, "power_on",
                             "perk_bought" {perk = "Juggernog", player = true},
                             "door_opened" {door = name, hash = n},
                             "zombie_killed" {position = {x, y, z}, entity = e,
                                              by_player = true, headshot = true},
                             "player_downed", "player_revived",
                             "weapon_given", "weapon_equipped", "weapon_reloaded"
                             {weapon = "mp40"} ("weapon_fired" only reaches boz.on)
```

Weapon scripts (Weapons tab → Add script): self is the weapon (self.name, and the boz.weapons handle's methods on the live weapon: self:clip(), self:set_damage(...), ...). Handlers: on_given(), on_equip(), on_fire(data), on_reload(), on_event(name, data). volume is the volume's name inside the prefab (its own name for a volume with a script); only volumes send these, and only volumes of the object (or its parts) the script is attached to. Other functions a script defines can be called by other scripts: boz.find("Vault_1"):open(). Every volume event also goes to boz.on listeners as "<volume name>.<event>" ("Vault_1.Skull.hit"); on_event does not get it (the script's own handler did). Trigger volumes: on_enter when something comes in, on_exit once it has left (the game's own enter/exit flicker while standing in it is smoothed out).

print shows in the Developer console as well as the log.

<details><summary>How it works</summary>

the client's loadscript(name, env) loads the script with a fresh environment for each object (self and boz in it, the mod's globals behind it; print also goes through the game's Console_Print, which boz.console passes to the Developer console). Volumes are boz.objects events (enter/exit on ghost boxes, hit on easter egg skulls, use at points of interest). Use prompts: when a Use volume becomes the point of interest in reach (SUBJECT_POI_TRIGGER, handled by CIngameStatePlaying::UpdatePoiPrompt), its prompt is shown with Poi_ShowPrompt; its cost is paid with CScoreManager::AddScore. Rounds: CWaveManager::StartWave (round number at +0x78). Power: a power switch's on flag (CPowerSwitch +0x88). Perks: CPerkManager::GainPerk(manager, perk, apply) for a perk not yet owned (bits at +0x58). Doors: a CDoor whose m_DoorState (+0x9c) became 2 (open), checked each frame. Hooks here are before hooks where they can be: an after hook swaps the return address for the client's trap, and on a busy function that crashed the game. Zombies: CAIControllerZombie::State_Dead entering (state event 1): its transform at +0xc4, killer entity at +0x138, hit location at +0x124 (0 head), kill kind at +0x22c (0/1 knife, 2 grenade). Downed: the local CPlayerController's stance (+0x1f4) is 8 (last stand) while its state machine (state at +0x1d4) is not 0x14/0x15 (dead). Game time: frames in which CPlayerController::FixedStep ran. Saving: CSaveManager::SaveGame (autosave at each round start, pause); continuing a save: CLevelManager +0x298 set at level start, then CSaveManager::NotifyLoad sends SUBJECT_LOAD from the resume-loading state. The values go in the map mod's settings (globals.<level>.<n>, Lua table text in chunks).

</details>

| Function | Description |
| --- | --- |
| `Instance:part(name)` | The boz.objects handle of a part of this prefab (by its name in the prefab). |
| `Instance:parts()` | {name, object} of every part of this prefab. |
| `Instance:set_visible(visible)` | Shows or hides the object (every part of a prefab). Returns self. |
| `Instance:set_collision(enabled)` | Switches the collision of the object (every part of a prefab). Returns self. |
| `Instance:set_navmesh(open)` | Opens or closes the walkable area under the object (and its parts that block it). Returns self. |
| `Instance:position()` | The object's world position {x, y, z} (game centimetres, y is up): a prefab's is the middle of its parts. nil when it is not in the running level. |
| `Instance:near(target, distance)` | True when the object (any part of a prefab) is within `distance` centimetres of `target` (a position such as zombie_killed's data.position, or another object). |
| `Instance:send(name, data)` | boz.send from this object. |
| `prefabs.find(name)` | The scripted object called *name* (its script instance), else its boz.objects handle when it exists in the level, else nil. |
| `prefabs.send(name, data)` | Sends an event on the bus: every boz.on(name) listener and every script's on_event. |
| `prefabs.on(name, fn)` | Calls fn(data, name) on every boz.send(name, ...). Returns fn. |
| `Timer:cancel()` | Stops the timer. |
| `prefabs.after(seconds, fn)` | Runs fn() once, `seconds` of game time from now (paused time does not count). Returns a timer with :cancel(). |
| `prefabs.every(seconds, fn)` | Runs fn() every `seconds` of game time until the timer is cancelled. Returns the timer. |
| `prefabs.save()` | Writes the map's saved globals now (the game's saves call this). |
| `prefabs.start(list, all_names, weapon_list)` | Starts the level's objects (boz.world calls this when a level has started, with the map's world_data objects, the names of all its objects and its weapons). |

### boz.weapons

The local player's weapons during a match: the one in hand, ammo, live stats,

giving weapons, and events when weapons are equipped, given, fired and reloaded.

```lua
local weapons = require("boz.weapons")
local gun = weapons.current()               -- nil outside a match
if gun then gun:set_ammo(gun:clip_size(), 999) end
weapons.give("thundergun")
weapons.listen(function(event, name) print(event .. " " .. name) end)
```

Weapons are named as in the editor's Weapons tab ("mp40", or "0x..." for an unnamed one). Changes made here last for the match; the Weapons tab changes the weapons for good.

<details><summary>How it works</summary>

the player's CWeaponManager sits on a child of the player entity (+0x48 = the player); its weapons are CPlayerWeapon components found by name hash (WeaponManager_FindWeapon, map at +0x1d4), the one in hand at +0x1e0. CWeaponManager::GiveWeapon(manager, hash, slot, refill) equips one; EquipWeapon sends SUBJECT_WEAPON_EQUIPPED; CPlayerController::FireWeapon fires; CWeaponManager::SetReloading starts a reload. A CPlayerWeapon keeps its rounds at +0x2c (clip) and +0x30 (reserve), its clip size at +0x80, reserve size at +0x84, fire rate at +0x200 (rounds per minute) and CWeaponDamage at +0x20c (head +4, torso +8, limbs +0xc).

</details>

| Function | Description |
| --- | --- |
| `weapons.know(list)` | Tell boz.weapons the names of weapons (the map's world data does this for its weapons). |
| `weapons.manager()` | The local player's weapon manager, or nil outside a match. |
| `Weapon:clip() return game.read("u32", self.pointer + CLIP)` | Rounds in the clip. |
| `Weapon:reserve() return game.read("u32", self.pointer + RESERVE)` | Spare rounds. |
| `Weapon:clip_size() return game.read("u32", self.pointer + CLIP_SIZE)` | Clip size. |
| `Weapon:reserve_size() return game.read("u32", self.pointer + RESERVE_SIZE)` | Reserve size. |
| `Weapon:set_ammo(clip, reserve)` | Sets the rounds in the clip and in reserve (nil keeps one). Returns the weapon. |
| `Weapon:fire_rate() return game.read("u32", self.pointer + FIRE_RATE)` | Fire rate in rounds per minute (automatic fire modes). |
| `Weapon:set_fire_rate(rounds_per_minute)` | Sets the fire rate for this match. Returns the weapon. |
| `Weapon:damage()` | Damage per hit: head, torso, limbs. |
| `Weapon:set_damage(head, torso, limbs)` | Sets the damage per hit for this match (nil keeps one). Returns the weapon. |
| `Weapon:in_hand()` | True while this is the weapon in hand. |
| `weapons.current()` | The weapon in the player's hands, or nil. |
| `weapons.get(name)` | The player's weapon called *name* (every weapon of the map is there, owned or not), or nil. |
| `weapons.give(name)` | Gives the player *name* and puts it in hand, with full ammo. Returns false outside a match or when the map has no such weapon. |
| `weapons.listen(fn)` | Calls fn(event, weapon name, data) on "equipped", "given", "fired" and "reloaded" of the local player's weapons. Returns fn. |

### boz.world

Game behaviour a map project's world asks for that the game's data cannot express.

```lua
require("boz.world").start()   (map projects call this from main.lua; the SDK adds it)
```

The map's objects: the editor writes each map's start state and scripted objects into boz/world_data.lua (hidden objects, objects without collision, walkable areas that start blocked, scripts and their property values); as soon as each level has started this applies the start state with boz.objects and starts the scripts with boz.prefabs.

Perk machines that work without power: the editor's "Needs power" off writes the power switch name "boz_no_power". The game only powers a machine when its power switch is turned on (Quick Revive in solo is the exception), so when such a machine starts this powers it the same way (CPerk +0x7c powered, +0x7d lit, and the machine's own "power_switch_on" event for its lights and jingle).

| Function | Description |
| --- | --- |
| `world.start()` | Turns on what map projects need from the standard library (call once, from main.lua). |
