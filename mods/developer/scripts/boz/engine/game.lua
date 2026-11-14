-- boz.engine.game: the Game tab's rules a map needs at run time.
--
--   require("boz.engine.game").start(data)   (boz.world calls it with the map's world_data.game)

local game_rules = {}

local core = require("boz.engine.core")
local map = require("boz.engine.map")

local BEHAVES_LIKE = {kino = true, ascension = true, callofthedead = true}
local WAVE_HEALTH = core.offset("CWaveRepeatable", "m_ZombieHealth")
local WAVE_HEALTH_MULT = core.offset("CWaveRepeatable", "m_ZombieHealthMultiplier")
local WAVE_START = core.offset("CWaveRepeatable", "m_StartingWave")

local started = false
local saved = {}          -- cvar -> the game's value before the map changed it
local active = false      -- the map's level is the one loaded

local function level_name()
    return map.name() or ""
end

--- True while the map's own level is loaded (after start()).
function game_rules.active()
    return active
end

local function kind_of(value)
    if type(value) == "boolean" then return "bool" end
    if type(value) == "string" then return "string" end
    if math.type(value) == "integer" then return "int" end
    return "float"
end

local function set_cvars(cvars, ours)
    local console = require("boz.systems.console")
    for name, value in pairs(cvars) do
        if ours then
            if saved[name] == nil then
                saved[name] = console.get(name) or false
            end
            console.register(name, tostring(value), kind_of(value))
        elseif saved[name] ~= nil and saved[name] ~= false then
            console.register(name, saved[name], kind_of(value))
        end
    end
end

--- Applies the map's rules (world_data.game: {cvars, power_on, repeating, behaves_like, level, rules}).
function game_rules.start(data)
    if started or type(data) ~= "table" then
        return
    end
    started = true
    local wanted = string.lower(data.level or "")
    local cvars = data.cvars or {}
    hook.add(core.sym("Level_Load"), {before = function()
        active = wanted == "" or level_name() == wanted
        set_cvars(cvars, active)
    end})
    -- Repeating rounds' health: the game's own 10 x round^2 - 150, times the mode's health x
    -- ("scale"), or the round's health growing by its multiplier ("grow"). Older builds:
    -- grow_health = true grows every repeating round.
    local wanted, by_wave, resolved = data.repeating or {}, {}, false
    hook.add(core.sym("Level_Load"), {before = function() resolved = false end})
    if data.grow_health or next(wanted) then
        hook.add(core.sym("CWaveRepeatable::GetZombieHealth"), {after = function(call)
            if not active then
                return
            end
            if not resolved then
                resolved, by_wave = true, {}
                for name, rule in pairs(wanted) do
                    local wave = core.call("Wave_Find", tonumber(name, 16)) or 0
                    if wave ~= 0 then by_wave[wave] = rule end
                end
            end
            local wave, round = call:arg(1), call:arg(2)
            local rule = data.grow_health and {grow = true} or by_wave[wave]
            if not rule then
                return
            end
            local health
            if rule.grow then
                health = game.read("u32", wave + WAVE_HEALTH)
                local start = game.read("u32", wave + WAVE_START)
                if round > start then
                    health = health * game.read("f32", wave + WAVE_HEALTH_MULT) ^ (round - start)
                end
            else
                health = call:result() * (rule.scale or 1)
            end
            call:set_result(math.max(1, math.floor(health)))
        end})
    end
    require("boz.game.rules").set_data(data.rules)
    local like = string.lower(data.behaves_like or "")
    if BEHAVES_LIKE[like] then
        -- The level manager's own checks of the level's name (String_Equals: Ascension's round
        -- effects, Call of the Dead's snow camera and start, Kino's teleport start) answer as if
        -- the map were that one. Checks the game makes with strcmp elsewhere stay the map's own.
        hook.add(core.sym("String_Equals"), {after = function(call)
            if not active or call:result() ~= 0 then
                return
            end
            if call:arg(1) == map.name_address() and
                    string.lower(game.read("string", call:arg(2), 32) or "") == like then
                call:set_result(1)
            end
        end})
    end
    if data.power_on then
        map.on_level_start(function()
            if active then
                map.power_on()
            end
        end)
    end
end

return game_rules
