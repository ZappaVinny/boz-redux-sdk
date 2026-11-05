-- boz: what map and object scripts use. Objects are classes you can extend.
--
--   local door = boz.get("Front_Door")                     -- a boz.Door
--   door:on("opened", function(door, player) player:give_points(500) end)
--   boz.on("round_started", function(data) log("round " .. data.round) end)
--
--   local SealedDoor = boz.Door:extend("SealedDoor")        -- a script attached to a door
--   function SealedDoor:on_use(player)
--       if boz.saved.egg_done then boz.Door.on_use(self, player) end
--   end
--   return SealedDoor

local runtime = require("boz.objects.runtime")
local native = require("boz.objects.native")
local timers = require("boz.engine.timers")

local boz = {}

boz.class = require("boz.class")
boz.Object = require("boz.objects.object")
boz.Prefab = require("boz.objects.prefab")
for name, class in pairs(native) do
    if name ~= "Native" then
        boz[name] = class
    end
end
boz.Debris = require("boz.objects.debris")
boz.Player = require("boz.game.player")
boz.Weapon = require("boz.game.weapon")

--- The object called name (its editor name; a part is "Prefab.Part"), as its class.
boz.get = runtime.get
--- Every object of a class: boz.all(boz.Perk).
boz.all = runtime.each
--- You, and every player in the match (boz.Player).
boz.player = runtime.player
boz.players = runtime.players
--- Calls fn(data, name) on a game event ("round_started", "power_on", ...) or a boz.send.
boz.on = runtime.on
--- Sends an event to every boz.on listener and every object's on_event.
boz.send = runtime.send
--- Runs fn once after seconds of game time; every seconds until cancelled. Return :cancel().
boz.after = timers.after
boz.every = timers.every
--- Values every script shares, kept in saves.
boz.saved = runtime.saved

local zombies = require("boz.game.zombies")
local rounds = require("boz.game.rounds")
boz.Zombie = zombies.Zombie

--- The zombies alive (boz.Zombie), of a kind ("zombie", "dog", "monkey", "george", "all").
function boz.zombies(kind)
    local out = {}
    for zombie in zombies.each(kind or "all") do
        out[#out + 1] = zombie
    end
    return out
end
--- Spawns a zombie ("zombie", "zombie_dog", ...) at a position; options: health, speed.
boz.spawn_zombie = zombies.spawn
--- The round number, and starting another.
boz.round = rounds.current
boz.start_round = rounds.go_to

-- The game's systems, as boz.<name> (loaded when first used).
local SYSTEMS = {audio = "boz.systems.audio", camera = "boz.systems.camera",
                 hud = "boz.systems.hud", input = "boz.systems.input",
                 console = "boz.systems.console", cvars = "boz.systems.cvars",
                 menu = "boz.systems.pause_settings", text = "boz.systems.text",
                 screen = "boz.systems.screen", effects = "boz.game.effects",
                 pickups = "boz.game.pickups", rounds = "boz.game.rounds",
                 stats = "boz.game.stats", fly = "boz.game.fly", deadops = "boz.game.deadops",
                 weapons = "boz.engine.weapons", map = "boz.engine.map"}

return setmetatable(boz, {__index = function(_, key)
    local path = SYSTEMS[key]
    if path then
        local module = require(path)
        rawset(boz, key, module)
        return module
    end
end})
