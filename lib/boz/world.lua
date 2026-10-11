-- boz.world: game behaviour a map project's world asks for that the game's data cannot express.
--
--   require("boz.world").start()   (map projects call this from main.lua; the SDK adds it)
--
-- Objects scripts change: the editor writes each map's start state into boz/world_data.lua
-- (hidden objects, objects without collision, walkable areas that start blocked); this applies
-- it with boz.objects as soon as each level has started.
--
-- Perk machines that work without power: the editor's "Needs power" off writes the power switch
-- name "boz_no_power". The game only powers a machine when its power switch is turned on (Quick
-- Revive in solo is the exception), so when such a machine starts this powers it the same way
-- (CPerk +0x7c powered, +0x7d lit, and the machine's own "power_switch_on" event for its lights
-- and jingle).

local hash = require("boz.hash")

local world = {}

local NO_POWER = hash.name("boz_no_power")
local POWER_ON = hash.name("power_switch_on")
-- CPerk::Init (component vtable slot 22) and its fields, from the 1.0.11 image.
local PERK_INIT_OFFSET = 0x1ca960 + 1   -- Thumb
local PERK_POWER_SWITCH = 0x90          -- powerSwitch (reflected)
local PERK_POWERED = 0x7c               -- checked by CPerk::Interact
local PERK_LIT = 0x7d
local PERK_SUBJECT = 0x20               -- the machine's CIsNetworkSubject

local started = false
local applied_level = nil

local function perk_init_address()
    return game.symbol("CPerk::Init") or (game.base() + PERK_INIT_OFFSET)
end

local function power_unpowered_perks()
    hook.add(perk_init_address(), {after = function(call)
        local perk = call:arg(1)
        if game.read("u32", perk + PERK_POWER_SWITCH) ~= NO_POWER then
            return
        end
        game.write("u8", perk + PERK_POWERED, 1)
        game.write("u8", perk + PERK_LIT, 1)
        game.call("CIsSubject::NotifyVirtual", perk + PERK_SUBJECT, POWER_ON, 0, 0, 0)
    end})
end

local function start_state()
    local ok, data = pcall(require, "boz.world_data")
    if not ok or type(data) ~= "table" then
        return
    end
    local objects = require("boz.objects")
    events.on("frame", function()
        local level = objects.level()
        if level == 0 then
            applied_level = nil   -- between levels: the next one starts fresh
            return
        end
        if level == applied_level then
            return
        end
        applied_level = level
        for _, name in ipairs(data.hidden or {}) do
            objects.get(name):hide()
        end
        for _, name in ipairs(data.no_collision or {}) do
            objects.get(name):set_collision(false)
        end
        for _, name in ipairs(data.blocked or {}) do
            objects.set_navmesh(name, false)
        end
    end)
end

--- Turns on what map projects need from the standard library (call once, from main.lua).
function world.start()
    if started then
        return
    end
    started = true
    power_unpowered_perks()
    start_state()
end

return world
