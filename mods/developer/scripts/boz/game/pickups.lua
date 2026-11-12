-- boz.pickups: power-ups (Zombies mode).
--
--   pickups.spawn("max_ammo", position)    drops one there for the player to collect
--   pickups.give("insta_kill")             as if the player collected it
--   pickups.active()                       {insta_kill = ms left, double_points = ..., ...}
--   pickups.on_collect(fn)                 fn(name) when the player collects one
--
-- Names: double_points, insta_kill, max_ammo, nuke, carpenter, firesale, deathmachine,
-- perkbottle, lightningbolt (the game's order). How often they drop is the Game tab's economy
-- (docs/editor.md, Game rules).

local pickups = {}

local core = require("boz.engine.core")

pickups.TYPES = {"double_points", "insta_kill", "max_ammo", "nuke", "carpenter", "firesale",
                 "deathmachine", "perkbottle", "lightningbolt"}
local INDEX = {}
for i, name in ipairs(pickups.TYPES) do INDEX[name] = i - 1 end
local TIMERS = {insta_kill = core.offset("CPickupManager", "instaKillTimer"),
                double_points = core.offset("CPickupManager", "doublePointsTimer"),
                firesale = core.offset("CPickupManager", "firesaleTimer"),
                deathmachine = core.offset("CPickupManager", "deathMachineTimer"),
                carpenter = core.offset("CPickupManager", "carpenterTimer")}
local LOCAL_ROTATION, LOCAL_POSITION = core.offset("CIsTransform", "localRotation"),
    core.offset("CIsTransform", "localPosition")
local SPAWN_OFFSET = core.offset("PickupSpawn", "offset")

--- The pickup manager (CPickupManager), or nil outside a match.
function pickups.manager()
    return core.singleton("CPickupManager")
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
    scratch = scratch or game.alloc(core.size("PickupSpawn"))
    -- A stand-in transform: its position and rotation (none); then a zero offset.
    for i, value in ipairs({0, 0, 0, 1}) do game.write("f32", scratch + LOCAL_ROTATION + 4 * (i - 1), value) end
    core.write_vec3(scratch + LOCAL_POSITION, position)
    for i = 0, 2 do game.write("f32", scratch + SPAWN_OFFSET + 4 * i, 0) end
    core.call("CPickupManager::SpawnPickupAt", manager, index, scratch, scratch + SPAWN_OFFSET)
    return true
end

--- Applies a power-up as if the local player collected it. Returns true, or false and why.
function pickups.give(name)
    local manager, index = pickups.manager(), index_of(name)
    local player = require("boz.engine.map").player()
    if not manager or not player then
        return false, "not in a match"
    end
    if not index then
        return false, "no power-up " .. tostring(name)
    end
    core.call("CPickupManager::ApplyPickup", manager, player, index, 0)
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
    return require("boz.engine.game_events").on("SUBJECT_ON_PICKUP", function(event)
        if not event.a or event.a == 0 then
            return
        end
        local index = game.read("u32", event.a + 8)
        local player = require("boz.engine.entities").find(game.read("u32", event.a + 4))
        fn(pickups.TYPES[index + 1] or index, player)
    end)
end

return pickups
