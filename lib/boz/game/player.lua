-- boz.player: the local player in a Zombies match: health, place, stance, speed and perks.
--
--   local player = require("boz.engine.player")
--   player.give_all_perks()
--   player.health()  player.set_health(500, true)  player.set_god(true)
--   player.position()  player.teleport({x = 0, y = 250, z = 0})
--   player.downed()  player.stance()  player.set_speed("SprintSpeed", 1.5)
--
-- game: CHealth::SetHealth

local Class = require("boz.class")
local engine = require("boz.engine.player")
local score = require("boz.engine.score")
local weapons = require("boz.engine.weapons")

local Player = Class:extend("Player")

function Player:init(entity)
    self.entity = entity or 0
end

--- Points the player has.
function Player:points() return score.get() end
--- Gives points (negative takes them).
function Player:give_points(points) return score.add(points) end
--- Takes points if the player has enough; returns true when paid.
function Player:spend(points) return score.spend(points) end

--- Health and the most it can have.
function Player:health() return engine.health() end
--- Sets health (raise_max: raise the most it can have too).
function Player:set_health(value, raise_max) return engine.set_health(value, raise_max) end
--- No damage (true) or normal damage again.
function Player:set_god(on) return engine.set_god(on) end

--- Gives a perk by name ("Juggernog", "Quick Revive", ...).
function Player:give_perk(name) return engine.give_perk(name) end
--- Takes a perk away.
function Player:take_perk(name) return engine.take_perk(name) end
--- True when the player has the perk.
function Player:has_perk(name) return (engine.perks() or {})[name] == true end
--- The perks the player has ({["Juggernog"] = true, ...}).
function Player:perks() return engine.perks() or {} end

--- Gives a weapon by name and puts it in hand.
function Player:give_weapon(name) return weapons.give(name) end
--- Takes a weapon away.
function Player:take_weapon(name) return weapons.take(name) end
--- The weapon in hand (a boz.weapons handle), or nil.
function Player:weapon() return weapons.current() end

--- Position {x, y, z} (centimetres, y up; the camera, about 136 above the feet).
function Player:position() return engine.position() end
--- Moves the player.
function Player:teleport(position)
    if type(position) == "table" and type(position.position) == "function" then
        position = position:position()
    end
    return engine.teleport(position)
end

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
--- Shows a line of text on the HUD for seconds (default 3).
function Player:message(text, seconds) return require("boz.systems.hud").message(text, seconds) end

return Player
