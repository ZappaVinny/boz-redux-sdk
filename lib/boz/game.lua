-- boz.game: the Game tab's rules a map needs at run time.
--
--   require("boz.game").start(data)   (boz.world calls it with the map's world_data.game)
--
-- Console variables (points at start, power-up drops and times, the score table, ...) are set
-- just before the map's level loads (Level_Load, when the level manager has the level's name),
-- and the game's own values come back when another level loads, so the map mod can stay enabled.
-- Power on at start runs the game's SwitchPowerOn once the level has started. Repeating rounds'
-- health: the game hard-codes 10 x round^2 - 150 (CWaveRepeatable::GetZombieHealth); with
-- grow_health the round's own data is used instead: health x health multiplier ^ (round -
-- m_StartingWave).

local game_rules = {}

local LEVEL_NAME = 0x55                 -- CLevelManager: the level's name
local LEVEL_LOAD = 0x1aae4c + 1         -- Level_Load (Thumb), when the gamedef has no name
local REPEAT_HEALTH = 0x2142cc + 1      -- CWaveRepeatable::GetZombieHealth(wave, round)
local STRING_EQUALS = 0x18cc3c + 1      -- String_Equals(a, b): the level manager's level name checks
local BEHAVES_LIKE = {kino = true, ascension = true, callofthedead = true}
local WAVE_HEALTH, WAVE_HEALTH_MULT, WAVE_START = 0x78, 0xa4, 0xac

local started = false
local saved = {}          -- cvar -> the game's value before the map changed it
local active = false      -- the map's level is the one loaded

local function level_name()
    local level = game.read("ptr", "CLevelManager::s_instance")
    return level ~= 0 and string.lower(game.read("string", level + LEVEL_NAME, 64) or "") or ""
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
    local console = require("boz.console")
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

--- Applies the map's rules (world_data.game: {cvars, power_on, grow_health, behaves_like, level}).
function game_rules.start(data)
    if started or type(data) ~= "table" then
        return
    end
    started = true
    local wanted = string.lower(data.level or "")
    local cvars = data.cvars or {}
    local target = game.symbol("Level_Load") or (game.base() + LEVEL_LOAD)
    hook.add(target, {before = function()
        active = wanted == "" or level_name() == wanted
        set_cvars(cvars, active)
    end})
    if data.grow_health then
        local health = game.symbol("CWaveRepeatable::GetZombieHealth") or (game.base() + REPEAT_HEALTH)
        hook.add(health, {after = function(call)
            if not active then
                return
            end
            local wave, round = call:arg(1), call:arg(2)
            local base = game.read("u32", wave + WAVE_HEALTH)
            local start = game.read("u32", wave + WAVE_START)
            if round > start then
                base = base * game.read("f32", wave + WAVE_HEALTH_MULT) ^ (round - start)
            end
            call:set_result(math.max(1, math.floor(base)))
        end})
    end
    local like = string.lower(data.behaves_like or "")
    if BEHAVES_LIKE[like] then
        -- The level manager's own checks of the level's name (String_Equals: Ascension's round
        -- effects, Call of the Dead's snow camera and start, Kino's teleport start) answer as if
        -- the map were that one. Checks the game makes with strcmp elsewhere stay the map's own.
        local equals = game.symbol("String_Equals") or (game.base() + STRING_EQUALS)
        hook.add(equals, {after = function(call)
            if not active or call:result() ~= 0 then
                return
            end
            local level = game.read("ptr", "CLevelManager::s_instance")
            if level ~= 0 and call:arg(1) == level + LEVEL_NAME and
                    string.lower(game.read("string", call:arg(2), 32) or "") == like then
                call:set_result(1)
            end
        end})
    end
    if data.power_on then
        local objects = require("boz.objects")
        local powered = nil
        events.on("frame", function()
            local level = objects.level()
            if level == 0 then
                powered = nil
                return
            end
            if level ~= powered and active then
                powered = level
                require("boz.console").exec("SwitchPowerOn")
            end
        end)
    end
end

return game_rules
