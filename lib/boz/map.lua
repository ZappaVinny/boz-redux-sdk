-- boz.map: the level being played, and the map systems the game has commands for.
--
--   map.name()            "kino", "ascension", "callofthedead", "tutorial" or a map project's
--   map.difficulty()      "easy", "normal" or "hard"        map.dead_ops()
--   map.restart()         map.power_on()                    map.fog("fog_name")
--   map.teleport("lobby")  (Kino's teleporters)              map.gersch_teleport()  (Ascension)
--   map.launch_rocket()   (Ascension)                       map.lighthouse(state)  (Call of the Dead)
--
-- How it works: CLevelManager (singleton) keeps the level's name at +0x55, the local player at
-- +0x1a0, Dead Ops Arcade at +0x208 and the difficulty at +0x20c (0 easy, 1 normal, 2 hard: the
-- single-player starting wave and the zombies' health multiplier). The map systems are the game's
-- developer commands (StartTeleportLobby, StartTeleportProjector, StartTeleportRandom,
-- GerschTeleportRandom, RocketAuthenticate, RocketLaunch, LighthouseState, SwitchFog, RestartLevel,
-- SwitchPowerOn) run through boz.console; docs/console-reference.md lists every command.

local map = {}

local console = require("boz.console")

local NAME, PLAYER, DEAD_OPS, DIFFICULTY = 0x55, 0x1a0, 0x208, 0x20c
map.DIFFICULTIES = {"easy", "normal", "hard"}

--- The level manager (CLevelManager), or nil outside a level.
function map.manager()
    local level = game.read("ptr", "CLevelManager::s_instance")
    return level ~= 0 and level or nil
end

--- The level's name (lower case), or nil.
function map.name()
    local level = map.manager()
    return level and string.lower(game.read("string", level + NAME, 64) or "") or nil
end

--- "easy", "normal" or "hard" (single player), or nil.
function map.difficulty()
    local level = map.manager()
    return level and map.DIFFICULTIES[game.read("u32", level + DIFFICULTY) + 1] or nil
end

--- True in Dead Ops Arcade.
function map.dead_ops()
    local level = map.manager()
    return level ~= nil and game.read("u8", level + DEAD_OPS) ~= 0
end

--- True while a level with a player is running.
function map.playing()
    local level = map.manager()
    return level ~= nil and game.read("ptr", level + PLAYER) ~= 0
end

--- Restarts the level.
function map.restart()
    return console.exec("RestartLevel")
end

--- Turns the power on.
function map.power_on()
    return console.exec("SwitchPowerOn")
end

--- Switches to a fog config by name (the level's CIwFogConfig resources, as rounds use them).
function map.fog(name)
    return console.exec("SwitchFog " .. tostring(name))
end

--- Kino: starts a teleport ("lobby": back to the lobby, "projector": to the projector room,
--- "random": to a random room).
function map.teleport(kind)
    local command = ({lobby = "StartTeleportLobby", projector = "StartTeleportProjector",
                      random = "StartTeleportRandom"})[kind or "random"]
    return command and console.exec(command) or nil, command and nil or "lobby, projector or random"
end

--- Ascension: sends the player to a random Gersch teleport point.
function map.gersch_teleport()
    return console.exec("GerschTeleportRandom")
end

--- Ascension: authenticates and launches the rocket.
function map.launch_rocket()
    console.exec("RocketAuthenticate")
    return console.exec("RocketLaunch")
end

--- Call of the Dead: sets the lighthouse's state (its beam searching for the Pack-a-Punch).
function map.lighthouse(state)
    return console.exec("LighthouseState " .. tostring(state))
end

return map
