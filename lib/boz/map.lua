-- boz.map: the level being played, and the map systems the game has commands for.
--
--   map.name()            "kino", "ascension", "callofthedead", "tutorial" or a map project's
--   map.difficulty()      "easy", "normal" or "hard"        map.dead_ops()
--   map.player()          the local player's entity and id
--   map.on_level_start(fn)                                   fn() each time a level has started
--   map.restart()         map.power_on()                    map.fog("fog_name")
--   map.toggle_pause()    map.set_time_scale(0.5)
--   map.kino.teleport("lobby")      map.ascension.gersch_teleport()      map.ascension.launch_rocket()
--   map.callofthedead.lighthouse(state)
--
-- How it works: CLevelManager (singleton) keeps the level's name at +0x55, the local player's
-- entity at +0x1a0, the level's CLevel resource at +0x204, Dead Ops Arcade at +0x208, the
-- difficulty at +0x20c (0 easy, 1 normal, 2 hard: the single-player starting wave and the
-- zombies' health multiplier), the point of interest in reach at +0x214 (an entity) and whether
-- the level started from a save at +0x298. The map systems are the game's developer commands
-- (StartTeleportLobby, GerschTeleportRandom, RocketLaunch, LighthouseState, SwitchFog,
-- RestartLevel, SwitchPowerOn, TimeTogglePause, TimeFactor) run through boz.console;
-- docs/console-reference.md lists every command.

local map = {}

local core = require("boz.core")

local function exec(line)
    return require("boz.console").exec(line)
end

local NAME, PLAYER, LEVEL, DEAD_OPS, DIFFICULTY = 0x55, 0x1a0, 0x204, 0x208, 0x20c
local NEAREST_POI, RESUMING = 0x214, 0x298
local ENTITY_ID = 4
map.DIFFICULTIES = {"easy", "normal", "hard"}

--- The level manager (CLevelManager), or nil outside a level.
function map.level_manager()
    return core.singleton("CLevelManager")
end

--- The level's name (lower case), or nil.
function map.name()
    local level = map.level_manager()
    return level and string.lower(game.read("string", level + NAME, 64) or "") or nil
end

--- The address of the level manager's name text (what the game's own name checks compare).
function map.name_address()
    local level = map.level_manager()
    return level and level + NAME or nil
end

--- The local player's entity and its id, or nil outside a Zombies match.
function map.player()
    local level = map.level_manager()
    local entity = level and game.read("ptr", level + PLAYER) or 0
    if entity == 0 then
        return nil
    end
    return entity, game.read("u32", entity + ENTITY_ID)
end

--- The level's CLevel resource (its starting waves, zombie looks, ...), or nil.
function map.level_info()
    local level = map.level_manager()
    local info = level and game.read("ptr", level + LEVEL) or 0
    return info ~= 0 and info or nil
end

--- The difficulty's index (0 easy, 1 normal, 2 hard), or nil.
function map.difficulty_index()
    local level = map.level_manager()
    return level and game.read("u32", level + DIFFICULTY) or nil
end

--- "easy", "normal" or "hard" (single player), or nil.
function map.difficulty()
    local index = map.difficulty_index()
    return index and map.DIFFICULTIES[index + 1] or nil
end

--- True in Dead Ops Arcade.
function map.dead_ops()
    local level = map.level_manager()
    return level ~= nil and game.read("u8", level + DEAD_OPS) ~= 0
end

--- True while a level with a player is running.
function map.playing()
    return map.player() ~= nil
end

--- True when the running level was started from a save (continuing a game).
function map.resuming()
    local level = map.level_manager()
    return level ~= nil and game.read("u8", level + RESUMING) ~= 0
end

--- The point of interest in reach (an entity: the box, a perk, a door the player can use), or 0.
function map.nearest_poi()
    local level = map.level_manager()
    return level and game.read("u32", level + NEAREST_POI) or 0
end

--- Makes an entity the point of interest in reach (what the use button acts on). Returns the
--- previous one.
function map.set_nearest_poi(entity)
    local level = map.level_manager()
    if not level then
        return nil
    end
    local before = game.read("u32", level + NEAREST_POI)
    game.write("u32", level + NEAREST_POI, entity)
    return before
end

--- A number that changes when another level starts (0 outside a match).
function map.level_key()
    return map.player() or 0
end

local level_starts = {}
local started_key = 0

--- Calls fn() every time a level has started (its player exists), and at once when one is
--- running. Returns fn.
function map.on_level_start(fn)
    if #level_starts == 0 then
        events.on("frame", function()
            local key = map.level_key()
            if key == started_key then
                return
            end
            started_key = key
            if key ~= 0 then
                for _, handler in ipairs(level_starts) do
                    core.safely("boz.map: level start", handler)
                end
            end
        end)
    end
    table.insert(level_starts, fn)
    return fn
end

--- Restarts the level.
function map.restart()
    return exec("RestartLevel")
end

--- Turns the power on.
function map.power_on()
    return exec("SwitchPowerOn")
end

--- Switches to a fog config by name (the level's CIwFogConfig resources, as rounds use them).
function map.fog(name)
    return exec("SwitchFog " .. tostring(name))
end

--- Pauses or resumes game time.
function map.toggle_pause()
    return exec("TimeTogglePause")
end

--- Game speed multiplier (1 = normal).
function map.set_time_scale(factor)
    return exec("TimeFactor " .. tostring(factor))
end

--- Kino der Toten.
map.kino = {}

--- Starts a teleport ("lobby": back to the lobby, "projector": to the projector room, "random":
--- to a random room).
function map.kino.teleport(kind)
    local command = ({lobby = "StartTeleportLobby", projector = "StartTeleportProjector",
                      random = "StartTeleportRandom"})[kind or "random"]
    if not command then
        return nil, "lobby, projector or random"
    end
    return exec(command)
end

--- Ascension.
map.ascension = {}

--- Sends the player to a random Gersch teleport point.
function map.ascension.gersch_teleport()
    return exec("GerschTeleportRandom")
end

--- Authenticates and launches the rocket.
function map.ascension.launch_rocket()
    exec("RocketAuthenticate")
    return exec("RocketLaunch")
end

--- Call of the Dead.
map.callofthedead = {}

--- Sets the lighthouse's state (its beam searching for the Pack-a-Punch).
function map.callofthedead.lighthouse(state)
    return exec("LighthouseState " .. tostring(state))
end

return map
