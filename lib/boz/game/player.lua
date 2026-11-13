-- boz.Player: the local player in a Zombies match: points, health, perks, weapons and place.
--
--   local player = boz.player()
--   player:give_points(500)  player:set_health(500, true)  player:give_perk("Juggernog")
--   player:teleport(boz.get("Roof"))                          stand on it, facing its way
--   player:teleport(boz.get("Roof"), {via = boz.get("Wormhole.Spot"), seconds = 3})
--
-- game: CPlayerController::PlaceAt

local Class = require("boz.class")
local engine = require("boz.engine.player")
local score = require("boz.engine.score")
local weapons = require("boz.engine.weapons")

---@class boz.Player
local Player = Class:extend("Player")

function Player:init(entity)
    self.entity = entity or 0
end

--- True for you; false for another player in co-op.
function Player:is_local()
    return true
end

-- Co-op: another game's player. Its methods run on that game (points, perks, teleports, ...);
-- what they return is not known here (nil). Its position is the one its game reported last.
local function send_value(value)
    if type(value) == "table" and type(value.position) == "function" and value.name then
        return {object = value.name}            -- an object: by name
    end
    return value
end

function Player.remote(tag)
    local net = require("boz.engine.net")
    return setmetatable({tag = tag, remote = true}, {__index = function(_, key)
        if key == "position" then
            return function() local peer = net.peers()[tag]; return peer and peer.position or nil end
        elseif key == "is_local" then
            return function() return false end
        elseif key == "is_a" then
            return function(_, class) return class == Player end
        end
        if type(Player[key]) ~= "function" then
            return nil
        end
        return function(_, ...)
            local args = table.pack(...)
            for i = 1, args.n do args[i] = send_value(args[i]) end
            net.tell(tag, "player", {method = key, args = args})
            return nil
        end
    end})
end

-- Another game asked this one to do something to its player.
require("boz.engine.net").op("player", function(args)
    local runtime = require("boz.objects.runtime")
    local list = args.args or {}
    for i = 1, (list.n or #list) do
        local value = list[i]
        if type(value) == "table" and value.object then list[i] = runtime.get(value.object) end
    end
    local me = runtime.player()
    local method = type(args.method) == "string" and me[args.method]
    if type(method) == "function" then method(me, table.unpack(list, 1, list.n or #list)) end
end, function() return require("boz.objects.runtime").running_map() end)

--- Points the player has.
function Player:points() return score.get() end
--- Gives points (negative takes them).
function Player:give_points(points)
    points = require("boz.engine.check").number(points, "give_points")
    return points and score.add(points) or nil
end
--- Takes points if the player has enough; returns true when paid.
function Player:spend(points)
    points = require("boz.engine.check").number(points, "spend")
    return points ~= nil and score.spend(points)
end

--- Health and the most it can have.
function Player:health() return engine.health() end
--- Sets health (raise_max: raise the most it can have too).
function Player:set_health(value, raise_max) return engine.set_health(value, raise_max) end
--- No damage (true) or normal damage again.
function Player:set_god(on) return engine.set_god(on) end

--- Gives a perk by name ("Juggernog", "Quick Revive", ...).
function Player:give_perk(name)
    return require("boz.engine.check").name(name, "give_perk") and engine.give_perk(name) or false
end
--- Takes a perk away.
function Player:take_perk(name) return engine.take_perk(name) end
--- True when the player has the perk.
function Player:has_perk(name) return (engine.perks() or {})[name] == true end
--- The perks the player has ({["Juggernog"] = true, ...}).
function Player:perks() return engine.perks() or {} end

--- Gives a weapon by name and puts it in hand.
function Player:give_weapon(name)
    return require("boz.engine.check").name(name, "give_weapon") and weapons.give(name) or false
end
--- Takes a weapon away.
function Player:take_weapon(name) return weapons.take(name) end
--- The weapon in hand (a boz.weapons handle), or nil.
function Player:weapon() return weapons.current() end

--- Position {x, y, z} (centimetres, y up; the camera, about 136 above the feet).
function Player:position() return engine.position() end
local TELEPORT_FLASH = 0x43d9cbd8   -- the game's teleport flash (CTeleportSpawnConfig)

-- Puts the player at a target: on an object (facing its way), else at a position {x, y, z}
-- (eye height, like position()).
local function place(target)
    if type(target) == "table" and target._handle then
        local entity = target._handle:entity_pointer()
        if entity ~= 0 then
            return engine.place_on(entity)
        end
        local spot = target._entry and target._entry.place   -- a prefab of yours: its own place
        if spot then
            local p = spot.position
            return engine.place_at({x = p[1], y = p[2], z = p[3]}, spot.rotation)
        end
        local position = target:position()
        return position ~= nil and engine.place_at(position, target:rotation())
    end
    return target ~= nil and engine.teleport(target)
end

--- Moves the player to an object (standing on it, facing its way) or a position.
--- options: via (an object or position to stop at first, held there, view too, like the game's
--- wormhole), seconds (how long, 2: the game's wormhole time),
--- effect (the teleport flash, true), done(player) (runs on arrival).
function Player:teleport(target, options)
    options = options or {}
    local function jump(to)
        if options.effect ~= false then
            require("boz.systems.screen").effect(TELEPORT_FLASH)
        end
        return place(to)
    end
    if options.via == nil then
        local ok = jump(target)
        if ok and options.done then
            options.done(self)
        end
        return ok
    end
    if not jump(options.via) then
        return false
    end
    engine.set_movement(false, false)
    require("boz.engine.timers").after(options.seconds or 2, function()
        engine.set_movement(true, true)
        jump(target)
        if options.done then
            options.done(self)
        end
    end)
    return true
end

--- True while the player may walk; set_movement(false) holds them where they stand, and
--- set_movement(false, false) holds their view too.
function Player:movement() return engine.movement() end
function Player:set_movement(on, look) return engine.set_movement(on, look) end

--- True while down (last stand).
function Player:downed() return engine.downed() end
--- Kills the player.
function Player:kill() return engine.kill() end
--- True while the player takes no damage.
function Player:god() return engine.god() end
--- The stance ("standing", "crouching", "prone", "downed"), and setting it.
function Player:stance() return engine.stance() end
function Player:set_stance(name) return engine.set_stance(name) end
--- A movement speed by name (boz.engine.player.SPEEDS), and setting it.
function Player:speed(name) return engine.speed(name) end
function Player:set_speed(name, value) return engine.set_speed(name, value) end
--- A stat by name ("STAT_ZOMBIESKILLED", ...; boz.stats), and adding to it.
function Player:stat(name) return require("boz.game.stats").get(name) end
function Player:add_stat(name, amount) return require("boz.game.stats").add(name, amount) end
--- The zone it is in (boz.Zone), or nil.
function Player:zone() return self:_in(require("boz.objects.zone")) end
--- The sector it is in (boz.Sector), or nil.
function Player:sector() return self:_in(require("boz.objects.sector")) end

function Player:_in(class)
    for _, area in ipairs(require("boz.objects.runtime").each(class)) do
        if area:contains(self) then
            return area
        end
    end
    return nil
end

--- Shows a line of text on the HUD for seconds (default 3).
function Player:message(text, seconds) return require("boz.systems.hud").message(text, seconds) end

return Player
