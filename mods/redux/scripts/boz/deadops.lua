-- boz.deadops: Dead Ops Arcade (the top-down mode).
--
--   deadops.active()            deadops.set_round(12)        deadops.god(true)
--   deadops.score()             deadops.set_score(100000)    deadops.lives()
--   deadops.spawn_enemy()       deadops.spawning(false)      deadops.spawn_pickup()
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

local console = require("boz.console")
local reflect = require("boz.reflect")
local components = require("boz.components")

--- True in Dead Ops Arcade.
function deadops.active()
    return require("boz.map").dead_ops()
end

--- Jumps to a round (the SetRound command).
function deadops.set_round(number)
    return console.exec("SetRound " .. tostring(math.floor(number)))
end

--- God mode on or off (the GodMode command toggles it; this asks for a state).
local god = false
function deadops.god(on)
    if on == nil or (on and not god) or (not on and god) then
        god = not god
        console.exec("GodMode")
    end
    return god
end

--- Many lives (the ManyLives command).
function deadops.many_lives()
    return console.exec("ManyLives")
end

--- Unlimited bombs and speed boosts (InfiniteBombBoost).
function deadops.infinite_bombs()
    return console.exec("InfiniteBombBoost")
end

--- Spawns an enemy; switches enemy spawning on or off; spawns a pickup; spawns death gems; auto aim.
function deadops.spawn_enemy() return console.exec("spawnEnemy") end
function deadops.spawning() return console.exec("toggleEnemySpawn") end
function deadops.spawn_pickup() return console.exec("spawnPickup") end
function deadops.spawn_gems() return console.exec("SpawnDeathGems") end
function deadops.auto_aim() return console.exec("AutoAim") end

local function player_component(class_name)
    local _, id = components.local_player()
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
