-- boz.deadops: Dead Ops Arcade (the top-down mode).
--
--   deadops.active()            deadops.set_round(12)        deadops.set_god(true)
--   deadops.score()             deadops.set_score(100000)    deadops.health()
--   deadops.spawn_enemy()       deadops.toggle_spawning()    deadops.spawn_pickup()
--   deadops.horde()             every field of the horde manager (spawn timers, horde size, ...)
--   deadops.storage()           the persistent storage: stats and power timers
--
-- How it works: Dead Ops runs in the same level manager with CLevelManager +0x208 set. Its systems
-- are singletons (CDORoundManager, CDOHordeManager, CDOPickupManager, CDOPersistentStorage,
-- CDOPlayerInput, CDOGoreManager) and components (CDOPlayer: m_Score; CDOHealth: maxHealth,
-- m_Health; CDOPlayerController: walking body, helicopter, tank; CDOAIController for enemies),
-- all reflected (boz.reflect). The rounds are 42 CDORound resources (arena, lighting, music,
-- hordes). The developer commands (SetRound, GodMode, ManyLives, InfiniteBombBoost, spawnEnemy,
-- toggleEnemySpawn, spawnPickup, SpawnDeathGems, AutoAim) run through boz.console.

local deadops = {}

local reflect = require("boz.reflect")
local components = require("boz.components")

local function exec(line)
    return require("boz.console").exec(line)
end

--- True in Dead Ops Arcade.
function deadops.active()
    return require("boz.map").dead_ops()
end

--- Jumps to a round (the SetRound command).
function deadops.set_round(number)
    return exec("SetRound " .. tostring(math.floor(number)))
end

local god = false

--- God mode on or off (the GodMode command toggles it; this asks for a state). Returns the state.
function deadops.set_god(on)
    if on == nil or (on and not god) or (not on and god) then
        god = not god
        exec("GodMode")
    end
    return god
end

--- Many lives (the ManyLives command).
function deadops.many_lives()
    return exec("ManyLives")
end

--- Unlimited bombs and speed boosts (InfiniteBombBoost).
function deadops.infinite_bombs()
    return exec("InfiniteBombBoost")
end

--- Spawns an enemy (spawnEnemy).
function deadops.spawn_enemy() return exec("spawnEnemy") end
--- Switches enemy spawning on or off (toggleEnemySpawn).
function deadops.toggle_spawning() return exec("toggleEnemySpawn") end
--- Spawns a pickup (spawnPickup).
function deadops.spawn_pickup() return exec("spawnPickup") end
--- Spawns death gems (SpawnDeathGems).
function deadops.spawn_gems() return exec("SpawnDeathGems") end
--- Switches auto aim (AutoAim).
function deadops.auto_aim() return exec("AutoAim") end

local function player_component(class_name)
    local _, id = require("boz.map").player()
    return id and components.find(class_name, id) or nil
end

--- The local player's score (CDOPlayer m_Score), or nil.
function deadops.score()
    local p = player_component("CDOPlayer")
    return p and reflect.get(p, "CDOPlayer", "m_Score") or nil
end

--- Sets the local player's score.
function deadops.set_score(points)
    local p = player_component("CDOPlayer")
    return p ~= nil and reflect.set(p, "CDOPlayer", "m_Score", points)
end

--- The local player's health and maximum (CDOHealth), or nil.
function deadops.health()
    local h = player_component("CDOHealth")
    if not h then
        return nil
    end
    return reflect.get(h, "CDOHealth", "m_Health"), reflect.get(h, "CDOHealth", "maxHealth")
end

--- The horde manager's fields (spawn timers, horde size, pickups this round, ...), or nil.
function deadops.horde()
    local horde = reflect.singleton("CDOHordeManager")
    return horde and reflect.dump(horde, "CDOHordeManager") or nil
end

--- The persistent storage's fields (stats, the player body / shield / speed shoes timers), or nil.
function deadops.storage()
    local storage = reflect.singleton("CDOPersistentStorage")
    return storage and reflect.dump(storage, "CDOPersistentStorage") or nil
end

--- The enemies alive: {entity, health component} for each CDOAIController.
function deadops.enemies()
    local out = {}
    for entity, controller in require("boz.entities").each("CDOAIController") do
        table.insert(out, {entity = entity, controller = controller,
                           health = components.find("CDOHealth", game.read("u32", entity + 4))})
    end
    return out
end

return deadops
