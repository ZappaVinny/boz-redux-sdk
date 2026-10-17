-- boz.world: game behaviour a map project's world asks for that the game's data cannot express.
--
--   require("boz.world").start()   (map projects call this from main.lua; the SDK adds it)
--
-- The map's objects: the editor writes each map's start state and scripted objects into
-- boz/world_data.lua (hidden objects, objects without collision, walkable areas that start
-- blocked, scripts and their property values); as soon as each level has started this applies
-- the start state with boz.objects and starts the scripts with boz.prefabs.
--
-- Perk machines that work without power: the editor's "Needs power" off writes the power switch
-- name "boz_no_power". The game only powers a machine when its power switch is turned on (Quick
-- Revive in solo is the exception), so when such a machine starts this powers it the same way
-- (CPerk +0x7c powered, +0x7d lit, and the machine's own "power_switch_on" event for its lights
-- and jingle).

local core = require("boz.core")
local hash = require("boz.hash")
local map = require("boz.map")

local world = {}

local NO_POWER = hash.name("boz_no_power")
local POWER_ON = hash.name("power_switch_on")
local PERK_POWER_SWITCH = 0x90          -- CPerk powerSwitch (reflected)
local PERK_POWERED = 0x7c               -- checked by CPerk::Interact
local PERK_LIT = 0x7d
local PERK_SUBJECT = 0x20               -- the machine's CIsNetworkSubject
-- What the game gives on other maps (the PlayerStartWeapon and PlayerStartAmmo defaults).
local GAME_START_WEAPON, GAME_START_AMMO = "colt45", 40

local started = false

local function power_unpowered_perks()
    hook.add(core.sym("CPerk::Init"), {after = function(call)
        local perk = call:arg(1)
        if game.read("u32", perk + PERK_POWER_SWITCH) ~= NO_POWER then
            return
        end
        game.write("u8", perk + PERK_POWERED, 1)
        game.write("u8", perk + PERK_LIT, 1)
        core.call("CIsSubject::NotifyVirtual", perk + PERK_SUBJECT, POWER_ON, 0, 0, 0)
    end})
end

-- The weapon players start with: WeaponManager_GiveStartWeapons gives the PlayerStartWeapon
-- cvar's weapon with PlayerStartAmmo spare rounds (the game registers both when the first player
-- spawns; registering them first makes a value stick). Set just before it runs, on this map only:
-- the mod stays enabled on other maps, which get the game's own back.
local function start_weapon(data)
    local wanted = data.start_weapon
    if type(wanted) ~= "table" or not wanted.name then
        return
    end
    local console = require("boz.console")
    hook.add(core.sym("WeaponManager_GiveStartWeapons"), {before = function()
        local ours = wanted.level == nil or map.name() == string.lower(wanted.level)
        console.register("PlayerStartWeapon", ours and wanted.name or GAME_START_WEAPON, "string")
        console.register("PlayerStartAmmo", tostring(ours and (wanted.reserve or GAME_START_AMMO) or GAME_START_AMMO), "int")
    end})
end

local function start_state()
    local ok, data = pcall(require, "boz.world_data")
    if not ok or type(data) ~= "table" then
        return
    end
    start_weapon(data)
    require("boz.game").start(data.game)
    require("boz.hooks").start(data.hooks)
    local objects = require("boz.objects")
    local prefabs = require("boz.prefabs")
    map.on_level_start(function()
        for _, name in ipairs(data.hidden or {}) do
            objects.get(name):hide()
        end
        for _, name in ipairs(data.no_collision or {}) do
            objects.get(name):set_collision(false)
        end
        for _, name in ipairs(data.blocked or {}) do
            objects.set_navmesh(name, false)
        end
        require("boz.effects").know(data.effects)
        prefabs.start(data.objects or {}, data.names, data.weapons)
    end)
end

--- Turns on what map projects need from the standard library (call once, from main.lua), and
--- starts the mod's map when the launcher asked for it (its "autostart_level" setting).
function world.start()
    if started then
        return
    end
    started = true
    power_unpowered_perks()
    start_state()
    require("boz.levels").autostart_from_settings()
end

return world
