-- boz.pickups: power-ups (Zombies mode).
--
--   pickups.spawn("max_ammo", position)    drops one there for the player to collect
--   pickups.give("insta_kill")             as if the player collected it
--   pickups.active()                       {insta_kill = ms left, double_points = ..., ...}
--   pickups.on_collect(fn)                 fn(name) when the player collects one
--
-- Names: double_points, insta_kill, max_ammo, nuke, carpenter, firesale, deathmachine,
-- perkbottle, lightningbolt (the game's order). How often they drop is the Game tab's economy
-- (docs/game.md).
--
-- How it works: CPickupManager (singleton) spawns them with SpawnPickupAt(manager, type,
-- transform, offset) (the spec <name>_pickup at the transform's position +0xa8 plus the offset)
-- and applies a collected one with ApplyPickup(manager, player, type, sound): it sets the timers
-- (+0xb8 insta-kill, +0xbc double points, +0xc0 fire sale, +0xc4 death machine, +0xc8 carpenter
-- points; milliseconds, from the InstaKillTime / DoublePointsTime / FireSaleTime /
-- DeathMachineTime / CarpenterScoreTime cvars), refills ammo, sends the nuke or carpenter, gives
-- the death machine or lightning bolt weapon or a perk.

local pickups = {}

pickups.TYPES = {"double_points", "insta_kill", "max_ammo", "nuke", "carpenter", "firesale",
                 "deathmachine", "perkbottle", "lightningbolt"}
local INDEX = {}
for i, name in ipairs(pickups.TYPES) do INDEX[name] = i - 1 end
local TIMERS = {insta_kill = 0xb8, double_points = 0xbc, firesale = 0xc0, deathmachine = 0xc4,
                carpenter = 0xc8}

local FALLBACK = {["CPickupManager::s_instance"] = 0x46083c, ["CPickupManager::SpawnPickupAt"] = 0x1d0dac + 1,
                  ["CPickupManager::ApplyPickup"] = 0x1d2c98 + 1}

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

--- The pickup manager (CPickupManager), or nil outside a match.
function pickups.manager()
    local manager = game.read("ptr", sym("CPickupManager::s_instance"))
    return manager ~= 0 and manager or nil
end

local function index_of(name)
    if type(name) == "number" then
        return name
    end
    return INDEX[(name or ""):gsub("_pickup$", "")]
end

local scratch = nil

--- Drops a power-up at a position {x, y, z} for the player to collect. Returns true, or false and
--- why.
function pickups.spawn(name, position)
    local manager, index = pickups.manager(), index_of(name)
    if not manager then
        return false, "not in a match"
    end
    if not index then
        return false, "no power-up " .. tostring(name)
    end
    scratch = scratch or game.alloc(0xd0)
    -- A stand-in transform: position +0xa8, rotation +0x98 (none); then a zero offset at +0xc0.
    for i, value in ipairs({0, 0, 0, 1}) do game.write("f32", scratch + 0x98 + 4 * (i - 1), value) end
    game.write("f32", scratch + 0xa8, position.x or position[1] or 0)
    game.write("f32", scratch + 0xac, position.y or position[2] or 0)
    game.write("f32", scratch + 0xb0, position.z or position[3] or 0)
    for i = 0, 2 do game.write("f32", scratch + 0xc0 + 4 * i, 0) end
    game.call(sym("CPickupManager::SpawnPickupAt"), manager, index, scratch, scratch + 0xc0)
    return true
end

--- Applies a power-up as if the local player collected it. Returns true, or false and why.
function pickups.give(name)
    local manager, index = pickups.manager(), index_of(name)
    local player = require("boz.components").local_player()
    if not manager or not player then
        return false, "not in a match"
    end
    if not index then
        return false, "no power-up " .. tostring(name)
    end
    game.call(sym("CPickupManager::ApplyPickup"), manager, player, index, 0)
    return true
end

--- The timed power-ups running now: {insta_kill = ms, double_points = ms, firesale = ms,
--- deathmachine = ms, carpenter = ms} (only those with time left).
function pickups.active()
    local manager = pickups.manager()
    local out = {}
    if not manager then
        return out
    end
    for name, offset in pairs(TIMERS) do
        local left = game.read("i32", manager + offset)
        if left > 0 then
            out[name] = left
        end
    end
    return out
end

--- Sets how long a running timed power-up lasts from now (ms; 0 ends it).
function pickups.set_time(name, ms)
    local manager, offset = pickups.manager(), TIMERS[name]
    if not manager or not offset then
        return false
    end
    game.write("i32", manager + offset, math.max(0, math.floor(ms)))
    return true
end

--- Calls fn(name, player_entity) whenever a power-up is collected (SUBJECT_ON_PICKUP: its first
--- argument points at {?, player id +4, type +8, sound +0xc}). Returns a handle
--- (boz.game_events.off).
function pickups.on_collect(fn)
    return require("boz.game_events").on("SUBJECT_ON_PICKUP", function(event)
        if not event.a or event.a == 0 then
            return
        end
        local index = game.read("u32", event.a + 8)
        local player = require("boz.entities").find(game.read("u32", event.a + 4))
        fn(pickups.TYPES[index + 1] or index, player)
    end)
end

return pickups
