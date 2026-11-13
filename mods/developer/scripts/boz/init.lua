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

local net = require("boz.engine.net")
net.start()
if type(mod) == "table" then
    net.add_mod(mod.id, mod.version)     -- co-op: every player needs the same scripted mods
end
local runtime = require("boz.objects.runtime")
local native = require("boz.objects.native")
local timers = require("boz.engine.timers")

local boz = {}

local version = require("boz.version")
--- This standard library's version ("0.3.0").
boz.VERSION = version.VERSION
--- The client Lua API it is written for; client.api is the running client's.
boz.CLIENT_API = version.CLIENT_API
if type(client) ~= "table" or (client.api or 0) ~= boz.CLIENT_API then
    log("BOZ library " .. boz.VERSION .. " is written for BOZ Redux API " .. boz.CLIENT_API .. ", this client has "
        .. tostring(type(client) == "table" and client.api or "an older one") .. "; some things may not work")
end

boz.class = require("boz.class")
boz.Object = require("boz.objects.object")
boz.Prefab = require("boz.objects.prefab")
for name, class in pairs(native) do
    if name ~= "Native" then
        boz[name] = class
    end
end
boz.Debris = require("boz.objects.debris")
boz.Volume = require("boz.objects.volume")
boz.Zone = require("boz.objects.zone")
boz.Sector = require("boz.objects.sector")
boz.Teleporter = require("boz.objects.teleporter")
boz.Player = require("boz.game.player")
boz.Weapon = require("boz.game.weapon")
boz.Lure = require("boz.game.lure")

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
--- Co-op (boz.engine.net): true on the game that runs the match (single player too).
boz.is_host = net.host
--- Runs fn for this game alone: what it changes or shows is not shared with the other players.
boz["local"] = net.local_only
--- Scripts in co-op: send(name, data) to the other games, on(name, fn(data, from)) to hear them,
--- shared() (every player runs these mods: the host runs the scripts), players(), private()
--- (this mod is a tool each player may lack: left out of the check).
boz.net = {
    send = net.send,
    on = net.on,
    shared = net.shared,
    host = net.host,
    players = function() return runtime.players() end,
    private = function() if type(mod) == "table" then net.private(mod.id) end end,
}

--- Ends the match (the game's game over and results); options: win (scripts hear match_ended
--- with win = true; the game has no win screen of its own).
boz.end_match = require("boz.game.match").finish

--- Lures zombies to a place or an object (boz.Lure options: seconds, zombies, radius, arrive).
boz.lure = boz.Lure.at

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
                 weapons = "boz.engine.weapons", map = "boz.engine.map",
                 sectors = "boz.engine.sectors", online = "boz.systems.online"}

return setmetatable(boz, {__index = function(_, key)
    local path = SYSTEMS[key]
    if path then
        local module = require(path)
        rawset(boz, key, module)
        return module
    end
end})
