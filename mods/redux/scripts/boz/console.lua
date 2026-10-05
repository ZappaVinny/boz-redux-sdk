-- boz.console: the game's developer console.
--
--   local console = require("boz.console")
--   console.set("WeaponsUnlimitedAmmo", true)
--   print(console.exec("listVars Unlimited"))
--
-- Runs console lines, reads and sets console variables (cvars), registers new ones, and passes
-- on everything the console prints. Every variable and command is listed in
-- console-reference.md.
--
-- How it works: the release build kept the console (CIwConsole, g_console) but no display, so
-- Console_Print has nowhere to send text. This module hooks Console_Print and wraps the console's
-- own functions (Console_Execute, Console_FindVar, Cvar_Register*).

local console = {}

local listeners = {}
local capture = nil
local value_buffer = game.alloc(2048)
local VAR_TO_STRING = 0x10   -- CIwConsoleVar vtable: ToString(var, buffer, size)

hook.add("Console_Print", {before = function(call)
    local text = game.read("string", call:arg(2), 2048)
    if capture then
        capture[#capture + 1] = text
    end
    for _, listener in ipairs(listeners) do
        local ok, err = pcall(listener, text)
        if not ok then
            log("console listener: " .. tostring(err))
        end
    end
end})

local function object()
    return game.read("ptr", "g_console")
end

--- True once the game created its console (from the first frame on, in practice).
function console.ready()
    return object() ~= 0
end

--- Calls fn(text) for every line the console prints.
function console.on_output(fn)
    listeners[#listeners + 1] = fn
end

--- Runs a console line as if typed. Returns what it printed, or nil and an error.
function console.exec(line)
    local con = object()
    if con == 0 then
        return nil, "the game console is not ready yet"
    end
    local outer = capture
    capture = {}
    game.call("Console_Execute", con, line)
    local output = table.concat(capture, "\n")
    capture = outer
    return output
end

--- A console variable's value as text, or nil when the game has not registered it.
function console.get(name)
    local con = object()
    if con == 0 then
        return nil
    end
    local var = game.call("Console_FindVar", con, name)
    if var == 0 then
        return nil
    end
    local to_string = game.read("ptr", game.read("ptr", var) + VAR_TO_STRING)
    game.write("u8", value_buffer, 0)
    game.call(to_string, var, value_buffer, 2048)
    return game.read("string", value_buffer, 2048)
end

--- Sets a registered variable from text (numbers and booleans are converted). Returns the value
--- the game kept, or nil and an error.
function console.set(name, value)
    if console.get(name) == nil then
        return nil, "no console variable named " .. name
    end
    console.exec(name .. " " .. tostring(value))
    return console.get(name)
end

local REGISTER = {bool = "Cvar_RegisterBool", int = "Cvar_RegisterInt", float = "Cvar_RegisterFloat",
                  string = "Cvar_RegisterString"}

--- Registers a variable with the game (if it does not exist yet) and sets it. kind: bool, int,
--- float or string; guessed from the value when omitted. Makes values the game only reads, like
--- StartingScore, take effect. Returns the value and the kind used.
function console.register(name, value, kind)
    value = tostring(value)
    kind = kind or ((value == "true" or value == "false") and "bool"
        or value:match("^%-?%d+$") and "int"
        or value:match("^%-?%d*%.%d+$") and "float"
        or "string")
    if not REGISTER[kind] then
        return nil, "kind must be bool, int, float or string"
    end
    if console.get(name) == nil then
        game.call(REGISTER[kind], name, value, 0, 0)
    end
    return console.set(name, value), kind
end

--- Every known variable: {name, type, default, used_by, lookup_only}.
function console.vars()
    return gamedef.cvars()
end

--- Every known command: {name, id, owner}.
function console.commands()
    return gamedef.commands()
end

return console
