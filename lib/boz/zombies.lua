-- boz.zombies: the zombies (and dogs, monkeys, George) alive in the match.
--
--   for z in zombies.each() do if z:health() < 100 then z:kill() end end
--   zombies.count()          zombies.nearest(position)
--   zombies.on_death(fn)     fn(zombie_entity) when one dies
--   zombies.kill_all()       zombies.credit_kills("SUBJECT_ZOMBIE_GERSCH_DEATH")
--   zombies.spawn("zombie", spawns.nearest(pos):position(), {health = 500, speed = "sprint"})
--   zombies.spawn("zombie_dog", at)      zombies.spawn_george(at)      zombies.dogs()
--
-- Spawn on the navmesh (a spawn point's position is safe): an AI that cannot reach the navmesh
-- dies within seconds.
--
-- A handle (zombies.each(kind), zombies.of(entity)): z.entity, z:kind(), z:get(field) /
-- z:set(field, value) (its AI controller's reflected fields), z:position(), z:health(),
-- z:max_health(), z:set_health(n), z:damage(n), z:kill(), z:alive(), z:teleport(position),
-- z:component(class) (any of its components: CHealth, CIsCrowdAgent, ... for boz.reflect).
-- Zombies also: z:set_speed(tier),
-- z:crawler(), z:state(), z:dying(), the game's effects (z:freeze(), z:shatter(), z:burn(),
-- z:explode(), z:lightning(), z:gersch(), z:shockwave()), z:frozen(), z:burning(), z:human(),
-- z:send(event).
--
-- How it works: each kind has its AI controller class (zombies.KINDS); CWaveManager::OnSpawnZombie
-- spawns one from a ZombieSpawnInfo (CreateZombie: the round's health and speed, a look, tracked
-- for the round when it counts); a plain zombie's spec comes from its look (CZombieConfiguration
-- +0x58). George spawns through the wave manager's boss spawn (+0xb4 holds him). Every zombie has
-- a CAIControllerZombie (its table lists them; +0x9d crawler, +0xc4
-- its transform, +0xd4 its health, +0xec its broadcaster, +0x30 its subject: the weapons' and
-- traps' effects arrive there as events (CAIControllerZombie::OnEvent), +0x150 its state machine;
-- AIGodmode makes zombies ignore damage);
-- CHealth keeps its health (+0x48 float, +0x44 the most it can be now, set by CreateZombie from
-- the round; +0x40 m_MaxHealth the spec's) and takes damage with CHealth::Damage(health,
-- amount, attacker name hash): it sends SUBJECT_HEALTH_DECREASE to itself and the zombie dies
-- below 1 (SUBJECT_DIED, then SUBJECT_ZOMBIE_DEATH from the level manager with its name hash).
-- SUBJECT_DIED adds a kill to the player's stats (STAT_ZOMBIESKILLED) only when the attacker is
-- the local player's name hash; deaths the game deals itself (a black hole's
-- SUBJECT_ZOMBIE_GERSCH_DEATH, chain lightning, traps) pass none.

local zombies = {}

local core = require("boz.core")
local hash = require("boz.hash")
local entities = require("boz.entities")
local components = require("boz.components")
local WAVE, BOSS = 0x50, 0xb4           -- CWaveManager: the current wave; George's entity
local NAME_BASE, NAME_NEXT = 0xd4, 0xd8 -- g_game: spawned entities' name hashes (base + counter)
local HEALTH, MAX_HEALTH, CRAWLER = 0x48, 0x44, 0x9d   -- CHealth health, its maximum now
local SET_SPEED = 0x60     -- CAIControllerZombie vtable: the speed tier (CWaveManager::CreateZombie)
local SUBJECT, STATE = 0x30, 0x158   -- its CIsSubject; its state machine (+0x150): the state
local TURNED, FROZEN, BURNING = 0x234, 0xb7, 0x10c
local LEVEL_LOOKS = 0x68   -- CLevel: the zombie looks (begin, end)
local CONTROLLER_HEALTH = 0xd4   -- CAIControllerZombie: its CHealth
local GEORGE = "george_romero"

--- The kinds of AI and their controller classes.
zombies.KINDS = {zombie = "CAIControllerZombie", dog = "CAIControllerHellhound",
                 monkey = "CAIControllerMonkey", george = "CAIControllerRomero"}

local Zombie = {}
Zombie.__index = Zombie

local function make(entity, controller, class_name)
    class_name = class_name or "CAIControllerZombie"
    local handle = {entity = entity, id = entities.id(entity), class = class_name, controller_component = controller}
    -- The zombie controller's offsets (state, effects) only apply to zombies.
    handle.controller = class_name == "CAIControllerZombie" and controller or nil
    return setmetatable(handle, Zombie)
end

--- Its kind: "zombie", "dog", "monkey" or "george".
function Zombie:kind()
    for kind, class_name in pairs(zombies.KINDS) do
        if class_name == self.class then
            return kind
        end
    end
    return nil
end

--- True while it is still in the match.
function Zombie:alive()
    return components.find(self.class, self.id) ~= nil
end

--- A field of its AI controller (reflected: dogs' attackingRadius, monkeys' m_damage, George's
--- m_zombieModeDamageMultiplier, ...), and setting one.
function Zombie:get(field)
    return require("boz.reflect").get(self.controller_component, self.class, field)
end
--- Sets a field of its AI controller. Returns true, or false and why.
function Zombie:set(field, value)
    return require("boz.reflect").set(self.controller_component, self.class, field, value)
end

--- One of its components by class (CHealth, CPathWalker, ...), or nil.
function Zombie:component(class_name)
    return components.find(class_name, self.id)
end

--- Its CHealth component, or nil.
function Zombie:health_component()
    return self:component("CHealth")
end

--- Its position {x, y, z}.
function Zombie:position()
    return entities.position(self.entity)
end

--- Moves it (on the navmesh: its crowd agent is placed there too, so it walks on from the new
--- spot). Returns false when it has no crowd agent.
function Zombie:teleport(position)
    local agent = self:component("CIsCrowdAgent")
    if not agent then
        return false
    end
    local x, y, z = core.xyz(position)
    entities.set_position(self.entity, {x = x, y = y, z = z})
    core.call("CrowdAgent_Place", agent, hook.float_bits(x), hook.float_bits(y), hook.float_bits(z))
    return true
end

--- Its health and the most it can have.
function Zombie:health()
    local h = self:health_component()
    return h and game.read("f32", h + HEALTH) or 0
end
--- The most health it can have now.
function Zombie:max_health()
    local h = self:health_component()
    return h and game.read("i32", h + MAX_HEALTH) or 0
end

--- Hurts it (as if the player did, so the kill counts). Returns the zombie.
function Zombie:damage(amount)
    local h = self:health_component()
    if h then
        core.call("CHealth::Damage", h, math.floor(amount), require("boz.player").name_hash() or 0)
    end
    return self
end

--- Kills it.
function Zombie:kill()
    return self:damage(self:health() + 1)
end

--- Sets its health (up to its maximum, z:max_health(); zombies.spawn's health raises it).
function Zombie:set_health(value)
    local h = self:health_component()
    if h then
        core.call("CHealth::SetHealth", h, hook.float_bits(value), 0, 0)
        game.write("f32", h + HEALTH, math.min(value, game.read("i32", h + MAX_HEALTH)))
    end
    return self
end

--- Sets its speed tier: "walk", "walk_fast", "run" or "sprint" (or 0-3), as rounds pick them.
function Zombie:set_speed(tier)
    local value = type(tier) == "number" and tier or ({walk = 0, walk_fast = 1, run = 2, sprint = 3})[tier]
    if not self.controller or not value then
        return self
    end
    core.virtual(self.controller, SET_SPEED, value)
    return self
end

--- Sends the zombie's own subject an event (what the game's weapons and effects do to it).
function Zombie:send(event, a, b, c)
    if not self.controller then
        return false
    end
    return require("boz.game_events").send(self.controller + SUBJECT, event, a, b, c)
end

--- Effects the game has for zombies (each as its weapons and traps do it):
--- freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a
--- frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart
--- (the human gun's death), lightning() (chain lightning death), gersch() (black hole death),
--- shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of
--- the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is
--- usually 0 (use kill()).
function Zombie:freeze() return self:send("SUBJECT_ZOMBIE_SPAWN_ICE") end
function Zombie:shatter() return self:send("SUBJECT_ZOMBIE_ICE_SHATTER") end
function Zombie:burn() return self:send("SUBJECT_START_BURNING", 0, 1, 1) end
function Zombie:explode() return self:send("SUBJECT_ZOMBIE_TRIGGER_FULL_BODY_EXPLOSION") end
function Zombie:lightning() return self:send("SUBJECT_ZOMBIE_CHAIN_LIGHTNING_DEATH") end
function Zombie:gersch() return self:send("SUBJECT_ZOMBIE_GERSCH_DEATH") end
function Zombie:shockwave() return self:send("SUBJECT_ZOMBIE_SHOCKWAVE_DEATH") end

--- True once the human gun turned it.
function Zombie:human()
    return self.controller ~= nil and game.read("u8", self.controller + TURNED) ~= 0
end

--- True while frozen in ice.
function Zombie:frozen()
    return self.controller ~= nil and game.read("u8", self.controller + FROZEN) ~= 0
end

--- True while on fire.
function Zombie:burning()
    return self.controller ~= nil and game.read("u8", self.controller + BURNING) ~= 0
end

--- Its AI state number (CIsStateMachine at +0x150): 2 chasing, 13 frozen, 15 dying, 21 dead.
function Zombie:state()
    return self.controller and game.read("u32", self.controller + STATE) or nil
end

--- True once it is dying (or dead).
function Zombie:dying()
    local state = self:state()
    return state == 15 or state == 0x15
end

--- True for a crawler (legs gone).
function Zombie:crawler()
    return self.controller ~= nil and game.read("u8", self.controller + CRAWLER) ~= 0
end

--- The AI handle of an entity (a zombie, dog, monkey or George), or nil.
function zombies.of(entity)
    if not entity then
        return nil
    end
    local id = entities.id(entity)
    for _, class_name in pairs(zombies.KINDS) do
        local controller = components.find(class_name, id)
        if controller then
            return make(entity, controller, class_name)
        end
    end
    return nil
end

--- Iterates the zombies: for z in zombies.each() do ... end. `kind` picks another kind ("dog",
--- "monkey", "george") or "all".
function zombies.each(kind)
    local kinds = {}
    if kind == "all" then
        for _, class_name in pairs(zombies.KINDS) do table.insert(kinds, class_name) end
        table.sort(kinds)
    else
        kinds[1] = zombies.KINDS[kind or "zombie"] or kind
    end
    local index, iterate = 0, nil
    return function()
        while true do
            if not iterate then
                index = index + 1
                if not kinds[index] then
                    return nil
                end
                iterate = entities.each(kinds[index])
            end
            local entity, controller = iterate()
            if entity then
                return make(entity, controller, kinds[index])
            end
            iterate = nil
        end
    end
end

--- Every one of a kind (default zombies), as a list.
function zombies.list(kind)
    local out = {}
    for z in zombies.each(kind) do
        table.insert(out, z)
    end
    return out
end

--- How many of a kind (default zombies) are in the match.
function zombies.count(kind)
    local n = 0
    for _ in zombies.each(kind) do
        n = n + 1
    end
    return n
end

--- The zombie nearest a position, and its distance.
function zombies.nearest(position)
    local entity, controller, distance = entities.nearest("CAIControllerZombie", position)
    return entity and make(entity, controller) or nil, distance
end

--- Every hellhound, and every monkey, in the match.
function zombies.dogs() return zombies.list("dog") end
function zombies.monkeys() return zombies.list("monkey") end

--- George (Call of the Dead's boss) while he is in the match, or nil.
function zombies.george()
    local manager = core.singleton("CWaveManager")
    local entity = manager and game.read("ptr", manager + BOSS) or 0
    return entity ~= 0 and zombies.of(entity) or nil
end

--- Spawns one AI the way rounds do (health from the round and difficulty, speed tier, look):
--- `spec` is "zombie" (or nil: a zombie in one of the level's looks) or an entity spec
--- ("zombie_dog", "zombie_dog_flaming", "zombie_monkey"), at a position. options: look (a
--- CZombieConfiguration name or hash: zombies.looks()), health (instead of
--- the round's), speed ("walk" .. "sprint"), counts (true: it is one of the round's zombies, so
--- killing it counts toward the round), powered (a powered zombie: the round's powered health).
--- Needs a round running. Returns its handle, or nil and why.
function zombies.spawn(spec, position, options)
    options = options or {}
    local manager = core.singleton("CWaveManager")
    if not manager or game.read("ptr", manager + WAVE) == 0 then
        return nil, "no round running"
    end
    local look = options.look and hash.of(options.look)
    if spec == nil or spec == "zombie" then
        -- A plain zombie: the spec comes with a look (one of the level's, at random).
        local looks = zombies.looks()
        look = look or looks[math.random(math.max(#looks, 1))]
        if not look then
            return nil, "the level has no zombie looks"
        end
        spec = 0
    end
    local spec_hash = hash.of(spec)
    if spec_hash ~= 0 and not entities.spec_loaded(spec_hash) then
        return nil, "no loaded entity spec " .. tostring(spec)
    end
    local g = game.read("ptr", core.sym("g_game"))
    local counter = game.read("u32", g + NAME_NEXT)
    game.write("u32", g + NAME_NEXT, counter + 1)
    local name = (game.read("u32", g + NAME_BASE) + counter) & 0xffffffff
    -- A ZombieSpawnInfo: +4 spec, +8 name, +0xc spawn animation, +0x10 spawn point, +0x14
    -- configuration, +0x18 speed share, +0x1c position, +0x28 rotation, +0x38 tracked by the
    -- round, +0x39 powered, +0x3a counts as spawned, +0x3c health, +0x40, +0x44 restoring a save.
    local info = core.scratch("zombies.spawn", 0x48)
    for at = 0, 0x44, 4 do game.write("u32", info + at, 0) end
    game.write("u32", info + 4, spec_hash)
    game.write("u32", info + 8, name)
    game.write("u32", info + 0x14, look or 0)
    core.write_vec3(info + 0x1c, position)
    core.write_quat(info + 0x28)
    game.write("u8", info + 0x38, options.counts and 1 or 0)
    game.write("u8", info + 0x39, options.powered and 1 or 0)
    core.call("CWaveManager::OnSpawnZombie", manager, info)
    -- The new one carries the name hash it was given.
    local handle = nil
    for z in zombies.each("all") do
        if entities.name_hash(z.entity) == name then
            handle = z
            break
        end
    end
    if not handle then
        return nil, "not spawned"
    end
    if options.health then
        local h = handle:health_component()
        if h then
            core.call("CHealth::SetMaxHealth", h, math.floor(options.health))
        end
        handle:set_health(options.health)
    end
    if options.speed then
        handle:set_speed(options.speed)
    end
    return handle
end

--- Spawns one of the round's own zombies at a spawn point (its entity name; nil: the game picks
--- a spawn point near the player). counts: it is one of the round's (default false: an extra).
function zombies.spawn_at_point(point, counts)
    local manager = core.singleton("CWaveManager")
    if not manager or game.read("ptr", manager + WAVE) == 0 then
        return false
    end
    core.call("CWaveManager::SpawnZombies", manager, counts and 1 or 0, 0, 0, point and hash.of(point) or 0)
    return true
end

--- The level's zombie looks (CZombieConfiguration hashes; zombies spawn in one at random), from
--- the level's CLevel.
function zombies.looks()
    local info = require("boz.map").level_info()
    if not info then
        return {}
    end
    local out, first, last = {}, game.read("ptr", info + LEVEL_LOOKS), game.read("ptr", info + LEVEL_LOOKS + 4)
    for at = first, last - 4, 4 do
        if #out >= 64 then break end
        table.insert(out, game.read("u32", at))
    end
    return out
end

--- Spawns George (Call of the Dead's boss, entity spec george_romero) at a position, as the round
--- does. Returns his handle, or nil and why (his spec must be loaded: a map built with
--- zombies.spawn_george in its scripts bundles it).
function zombies.spawn_george(position)
    local manager = core.singleton("CWaveManager")
    if not manager then
        return nil, "not in a match"
    end
    local george = hash.name(GEORGE)
    if not entities.spec_loaded(george) then
        return nil, GEORGE .. " is not loaded (bundle it from Call of the Dead)"
    end
    local at = core.scratch("zombies.spawn", 0x48)
    core.write_vec3(at, position)
    core.write_quat(at + 12)
    core.call("WaveManager_SpawnBoss", manager, george, at, at + 12, 0, 0)
    return zombies.george()
end

--- Zombies within `radius` centimetres of a position.
function zombies.within(position, radius)
    local out = {}
    for z in zombies.each() do
        local at = z:position()
        if at and (at.x - position.x) ^ 2 + (at.y - position.y) ^ 2 + (at.z - position.z) ^ 2 <= radius * radius then
            table.insert(out, z)
        end
    end
    return out
end

--- Calls fn(entity, name_hash) when a zombie dies (SUBJECT_ZOMBIE_DEATH: its second argument is
--- the zombie's name hash; the entity may already be gone, then nil). Returns a handle
--- (boz.game_events.off).
function zombies.on_death(fn)
    return require("boz.game_events").on("SUBJECT_ZOMBIE_DEATH", function(event)
        fn(entities.find(event.b), event.b)
    end, {dedupe_key = function(event) return event.b end, dedupe_frames = math.huge})
end

--- Kills every living AI of a kind (default "all"), each as if the player did (the kills count).
--- Returns how many.
function zombies.kill_all(kind)
    local n = 0
    for z in zombies.each(kind or "all") do
        if z:alive() and not z:dying() then
            z:kill()
            n = n + 1
        end
    end
    return n
end

--- Spawns one zombie the game's way (SpawnZombie: at a spawn point near the player).
function zombies.spawn_one()
    return require("boz.console").exec("SpawnZombie")
end

--- Makes zombies and the other AI unhurtable (true) or normal again (the AIGodmode cvar).
function zombies.set_invulnerable(on)
    return require("boz.console").exec("AIGodmode " .. (on and "true" or "false"))
end

local credited = {}       -- event id -> true
local marked = {}         -- CHealth -> true: zombies handling a credited event

--- Makes the kills a zombie deals itself while handling `event` count as the player's (stats,
--- achievements), e.g. "SUBJECT_ZOMBIE_GERSCH_DEATH" for the zombies a black hole takes. The game
--- kills them with CHealth::Damage and no attacker; that damage becomes the player's.
function zombies.credit_kills(event)
    local first = next(credited) == nil
    credited[require("boz.game_events").id(event) & 0xffffffff] = true
    if not first then
        return
    end
    -- Before hooks only: OnEvent sends events to itself, and an after hook's return trap on it
    -- crashed the game. The zombie's health is marked here and its damage credited below.
    hook.add(core.sym("CAIControllerZombie::OnEvent"), {before = function(call)
        if credited[call:arg(3) & 0xffffffff] then
            local health = game.read("ptr", call:arg(1) + CONTROLLER_HEALTH)
            if health ~= 0 then
                marked[health] = true
            end
        end
    end})
    hook.add(core.sym("CHealth::Damage"), {before = function(call)
        local health = call:arg(1)
        if marked[health] then
            marked[health] = nil
            if call:arg(3) == 0 then
                local id = require("boz.player").name_hash()
                if id then
                    call:set_arg(3, id)
                end
            end
        end
    end})
    events.on("frame", function() marked = {} end)
end

return zombies
