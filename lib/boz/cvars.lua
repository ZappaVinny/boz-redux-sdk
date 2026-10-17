-- boz.cvars: every console variable of the game, typed, with its default and what it does.
--
--   cvars.get("SprintSpeed")            -> 1.85 (a number, boolean or string by its type)
--   cvars.set("SprintSpeed", 3)         registers it when the game has not yet, then sets it
--   cvars.reset("SprintSpeed")          back to the game's default
--   cvars.info("SprintSpeed")           {type, default, note}
--   cvars.find("Zombie")                every variable whose name has "Zombie" in it
--   cvars.commands()                    every command {name, args, note}
--
-- 664 variables: the player (WalkSpeed, SprintSpeed, PlayerStartWeapon, ...), zombies (AI*,
-- Zombie*), rounds (StartWaveOnStart, StaggerStartingZombies, ...), power-ups (Pickup*,
-- *Time), the HUD (HUD*), Dead Ops (do*), the camera, sound, saves and debug.
-- docs/console-reference.md lists them all. Changes last for the session; the Game tab sets a
-- map's own (only on that map).
--
-- How it works: boz.console registers and sets them (CIwConsole); boz/cvar_data.lua is the game
-- definition's catalog (tools/stdlib/generate_data.py) with the notes of tools/symbols/console_notes.toml.

local cvars = {}

local console = require("boz.console")
local data = require("boz.cvar_data")

local KINDS = {bool = "bool", int = "int", float = "float", fixed = "float", string = "string"}

local function convert(kind, text)
    if text == nil then
        return nil
    end
    if kind == "bool" then
        return text == "true" or text == "1"
    end
    if kind == "int" or kind == "float" or kind == "fixed" then
        return tonumber(text) or text
    end
    return text
end

--- What the library knows of a variable: {type, default, note}, or nil.
function cvars.info(name)
    local entry = data.cvars[name]
    return entry and {type = entry[1], default = entry[2], note = entry[3]} or nil
end

--- A variable's value (by its type), or nil when the game has not registered it.
function cvars.get(name)
    local entry = data.cvars[name]
    return convert(entry and entry[1] or "string", console.get(name))
end

--- Sets a variable (registering it first when the game has not: values the game only reads, like
--- StartingScore, then take effect). Returns the value kept.
function cvars.set(name, value)
    local entry = data.cvars[name]
    local kind = entry and KINDS[entry[1]] or nil
    if type(value) == "boolean" then
        value = value and "true" or "false"
    end
    return console.register(name, tostring(value), kind)
end

--- Sets a variable back to the game's default.
function cvars.reset(name)
    local entry = data.cvars[name]
    if not entry or entry[2] == nil then
        return nil
    end
    return cvars.set(name, entry[2])
end

--- Every variable whose name contains `text` (any case), sorted: {name, ...}.
function cvars.find(text)
    local out, needle = {}, string.lower(text or "")
    for name in pairs(data.cvars) do
        if string.lower(name):find(needle, 1, true) then
            table.insert(out, name)
        end
    end
    table.sort(out)
    return out
end

--- Every variable name, sorted.
function cvars.all()
    return cvars.find("")
end

--- Every command: {{name, args, note}, ...}, sorted by name.
function cvars.commands()
    local out = {}
    for name, entry in pairs(data.commands) do
        table.insert(out, {name = name, args = entry[1], note = entry[2]})
    end
    table.sort(out, function(a, b) return a.name:lower() < b.name:lower() end)
    return out
end

--- Runs a command with arguments (as typed in the console). Returns what it printed.
function cvars.run(name, ...)
    local parts = {name}
    for _, arg in ipairs({...}) do
        table.insert(parts, tostring(arg))
    end
    return console.exec(table.concat(parts, " "))
end

return cvars
