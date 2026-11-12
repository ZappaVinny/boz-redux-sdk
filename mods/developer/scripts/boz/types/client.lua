---@meta
-- What the BOZ Redux client gives every mod's scripts, for editors that complete Lua (the Lua
-- language server in VS Code reads this; the game never runs it). The standard library itself
-- (require("boz")) is plain Lua next to this folder.

---@class ClientInfo
---@field version string the client's version ("0.4.0")
---@field api integer the Lua API number (a mod.toml's [sdk] client_api)
---@field arch "x86"|"x64"|"arm64"
---@field platform "windows"|"linux"|"android"
---@field touch boolean true on phones: a mod can pick a layout for fingers
client = {}

---@class ModInfo
---@field id string
---@field name string
---@field version string
---@field folder string
mod = {}

--- Writes a line to boz-log.txt as "[lua] <mod>: ...".
---@param ... any
function log(...) end

--- One table every mod sees (each mod's own globals are separate).
---@type table
shared = {}

events = {}
--- Calls fn on every event name: "frame" (dt), "key" (name, down, repeat), "action" (name, down).
--- Return true from "key" or "action" to say the mod used it.
---@param name "frame"|"key"|"action"|string
---@param fn function
function events.on(name, fn) end
--- Removes a handler added with events.on.
---@param name string
---@param fn function
function events.off(name, fn) end

input = {}
--- Calls fn() when the key is pressed ("F5", "`", "Left Shift"); one binding per key.
---@param key string
---@param fn fun()
function input.bind(key, fn) end
---@param key string
function input.unbind(key) end
--- Sends a game action ("shoot", "reload", "use", ...) as if pressed (down, the default) or released.
---@param action string
---@param down? boolean
function input.send(action, down) end
--- True while the player holds the action's binding.
---@param action string
---@return boolean
function input.down(action) end
---@return boolean
function input.aiming() end
--- True when the client sends controls straight to the game.
---@return boolean
function input.native() end

gamedef = {}
--- Every known console variable: {name, type, default, used_by, lookup_only}.
---@return table[]
function gamedef.cvars() end
--- Every known console command: {name, id, owner}.
---@return table[]
function gamedef.commands() end

settings = {}
--- A saved value of this mod (string, number or boolean), or default.
---@param key string
---@param default? any
---@return any
function settings.get(key, default) end
--- Saves a value (nil removes it).
---@param key string
---@param value any
function settings.set(key, value) end

assets = {}
--- Every time the game opens file (by file name), fn(bytes) returns the changed bytes or nil.
---@param file string
---@param fn fun(bytes: string): string?
function assets.patch(file, fn) end

network = {}
--- The online server Play Online uses, or "" when it is off.
---@return string
function network.server() end
--- Sends Play Online to host ("" or nil: off). Needs mod.toml [network] connects = ["host"] or "*".
---@param host? string
function network.set_server(host) end
--- Tries to reach a server (TCP 3074 by default); fn(ok, message) runs on a later frame.
---@param host string
---@param port_or_fn integer|fun(ok: boolean, message: string)
---@param fn? fun(ok: boolean, message: string)
function network.check(host, port_or_fn, fn) end

game = {}
--- Address of a named function or global (gamedef), or nil. Thumb functions carry bit 0.
---@param name string
---@return integer?
function game.symbol(name) end
--- Where the game image is loaded.
---@return integer
function game.base() end
--- Reads memory: "u8", "i8", "u16", "i16", "u32", "i32", "ptr", "f32", "bool", "string".
---@param type string
---@param address integer|string
---@param max_length? integer
---@return any
function game.read(type, address, max_length) end
--- Writes memory (the same types except "string").
---@param type string
---@param address integer|string
---@param value any
function game.write(type, address, value) end
--- Calls a game function by name or address with up to 6 arguments; the result as an integer.
---@param target integer|string
---@return integer
function game.call(target, ...) end
--- Zeroed memory the game can read and write.
---@param size integer
---@return integer
function game.alloc(size) end
---@param address integer
function game.free(address) end

---@class HookCall
local HookCall = {}
--- Argument i (1-based; this is 1 for methods).
---@param i integer
---@return integer
function HookCall:arg(i) end
---@param i integer
---@return integer
function HookCall:arg_signed(i) end
---@param i integer
---@return number
function HookCall:arg_float(i) end
---@param i integer
---@param value integer
function HookCall:set_arg(i, value) end
---@param i integer
---@param value number
function HookCall:set_arg_float(i, value) end
--- Returns at once with value (default 0): the function does not run.
---@param value? integer
function HookCall:skip(value) end
---@param value number
function HookCall:skip_float(value) end
---@return integer
function HookCall:result() end
---@return integer
function HookCall:result_signed() end
---@return number
function HookCall:result_float() end
---@param value integer
function HookCall:set_result(value) end
---@param value number
function HookCall:set_result_float(value) end
---@return integer
function HookCall:address() end

hook = {}
--- Runs Lua when a game function (gamedef name or address) is called. Returns a handle.
---@param target integer|string
---@param handlers {before?: fun(call: HookCall), after?: fun(call: HookCall)}
---@return integer
function hook.add(target, handlers) end
---@param handle integer
function hook.remove(handle) end
---@param x number
---@return integer
function hook.float_bits(x) end
---@param bits integer
---@return number
function hook.bits_float(bits) end

overlay = {}
--- Takes the mouse and keyboard from the game (true) or gives them back.
---@param on boolean
function overlay.capture(on) end
---@return boolean
function overlay.capturing() end

--- Windows and controls; only inside an events.on("frame") handler.
ui = {}
--- A window. opts: x, y, w, h (first use, 720p units), closable, focus, no_title, no_resize,
--- no_move, no_collapse, auto_size, no_background, no_inputs, no_scrollbar, clickable (takes
--- clicks while nothing captures input), pivot_x, pivot_y (pinned to x, y of a 1280x720 screen).
---@param title string
---@param opts_or_fn table|fun()
---@param fn? fun()
---@return boolean open
function ui.window(title, opts_or_fn, fn) end
---@param id string
---@param w number
---@param h number
---@param fn fun()
function ui.child(id, w, h, fn) end
---@param label string
---@param fn fun()
---@param open? boolean
---@return boolean
function ui.collapsing(label, fn, open) end
---@param label string
---@param fn fun()
---@return boolean
function ui.tree(label, fn) end
---@param id string
---@param fn fun()
function ui.tab_bar(id, fn) end
---@param label string
---@param fn fun()
---@return boolean
function ui.tab(label, fn) end
---@param id string
---@param columns integer
---@param fn fun()
function ui.table(id, columns, fn) end
function ui.next_column() end
---@param text string
function ui.text(text) end
---@param text string
function ui.text_wrapped(text) end
---@param text string
function ui.text_disabled(text) end
---@param text string
---@param r number
---@param g number
---@param b number
---@param a? number
function ui.text_colored(text, r, g, b, a) end
---@param label string
---@param w? number
---@param h? number
---@return boolean clicked
function ui.button(label, w, h) end
---@param label string
---@param selected boolean
---@return boolean clicked
function ui.selectable(label, selected) end
---@param label string
---@param value boolean
---@return boolean changed, boolean value
function ui.checkbox(label, value) end
---@param label string
---@param value number
---@param min number
---@param max number
---@param integer? boolean
---@return boolean changed, number value
function ui.slider(label, value, min, max, integer) end
---@param label string
---@param index integer
---@param items string[]
---@return boolean changed, integer index
function ui.combo(label, index, items) end
--- A text box. opts: hint, width, focus, submit (true only on Enter), history.
---@param label string
---@param text string
---@param opts? table
---@return boolean changed, string text
function ui.input(label, text, opts) end
function ui.same_line() end
---@param text? string
function ui.separator(text) end
function ui.spacing() end
---@param text string
function ui.tooltip(text) end
function ui.scroll_to_bottom() end
---@return boolean
function ui.at_bottom() end
function ui.focus_next() end
---@param w number
function ui.item_width(w) end
---@return number
function ui.scale() end
---@return boolean
function ui.wants_keyboard() end

--- BOZ Test (tests/*.lua run by bozkit test); the harness adds test.step, test.expect, ...
test = {}
--- A step: fn runs; a failed expect inside marks the step failed (later steps still run).
---@param name string
---@param fn fun()
function test.step(name, fn) end
---@param ok any
---@param message? string
function test.expect(ok, message) end
---@param message string
function test.fail(message) end
--- Waits seconds of game time.
---@param seconds number
function test.wait(seconds) end
---@param count integer
function test.frames(count) end
--- Waits until fn() returns something true (returns it), or fails after seconds.
---@param fn fun(): any
---@param seconds number
---@param what? string
---@return any
function test.wait_until(fn, seconds, what) end
---@return boolean
function test.in_match() end
--- Starts a map (a level name) once the game is up; vars: console variables to set first.
---@param name string
---@param vars? table<string, any>
function test.start_map(name, vars) end
--- Opens the map's co-op room (two clients: --! players: 2).
---@param name string
---@param vars? table<string, any>
function test.coop_map(name, vars) end
--- A finger (touch screens): action "down", "move" or "up"; x, y from 0 to 1.
---@param id integer
---@param action "down"|"move"|"up"
---@param x number
---@param y number
function test.touch(id, action, x, y) end
---@param x number
---@param y number
function test.tap(x, y) end
---@param x1 number
---@param y1 number
---@param x2 number
---@param y2 number
---@param seconds? number
---@param hold? boolean
function test.drag(x1, y1, x2, y2, seconds, hold) end
--- Saves the screen into the report as name.png.
---@param name string
function test.screenshot(name) end
--- Lua errors in mods so far.
---@return integer
function test.errors() end
---@return number
function test.time() end
---@type "solo"|"host"|"guest"
test.role = "solo"
