-- boz.Lure: zombies go somewhere on purpose, the way a monkey bomb pulls them. A Lure point from
-- the editor, or boz.lure(target) for any place or object.
--
--   local bait = boz.get("Bait")                       -- a Lure point
--   bait:start()                                        -- with its editor settings
--   bait:start({seconds = 10, zombies = 3, arrive = "attack"})
--   bait:on("hit", function(lure, zombie) generator_health = generator_health - 1 end)
--   bait:set_enabled(false)                             -- start() does nothing; a running one stops
--   local lure = boz.lure(boz.get("Generator"), {seconds = 15, radius = 1500})
--   lure:stop()
--
-- Options (a Lure point's editor settings are its defaults): seconds (0: until stop()), zombies
-- (0: all, else the nearest that many), radius (cm from the lure; 0: any distance), arrive
-- ("wait": they gather and wait; "attack": they swing at it, a "hit" event each time).
-- Events: started, arrived(zombie), hit(zombie), stopped. Zombies that spawn while it runs are
-- lured too. Only walking zombies come (not hellhounds, monkeys or George), and only where the
-- walkable area lets them.
--
-- game: CAIControllerZombie::SetTarget, CAIControllerZombie::ChooseTarget (CLocator AI goals)

local Object = require("boz.objects.object")
local core = require("boz.engine.core")
local entities = require("boz.engine.entities")
local engine = require("boz.engine.objects")
local timers = require("boz.engine.timers")

---@class boz.Lure : boz.Object
local Lure = Object:extend("Lure")

local LOCATOR_ONLY = core.offset("CAIControllerZombie", "locatorGoal")
local LOCATOR_NOTICED = core.offset("CAIControllerZombie", "locatorNoticed")
local LOCATOR_KIND = core.offset("CLocator", "kind")       -- 1: a goal zombies walk to
local NOTICE_TIMER = core.offset("CAIControllerZombie", "noticeTimer")
local STATE_MACHINE = core.offset("CAIControllerZombie", "stateMachine")
local GOAL_STATE = 26            -- turning toward a CLocator goal: it stands
local CHASE_STATE = 2
local TARGET = core.offset("CAIControllerZombie", "target")   -- +4: the transform it goes after
-- Zombies walk to the lure as to any target (not as to a Call of the Dead goal: the game freezes
-- zombies that reach one), then stand: held in the goal's notice state.
local NEAR = 150                 -- cm from the lure where a zombie stops and waits
local STALL = 1000               -- within this, a walking zombie that stopped getting closer
local STALL_SECONDS = 2.0        -- (others are in its way) waits where it is
local FOLLOW_SLACK = 250         -- a held zombie walks on when a followed object moves this far
local SWING = 1.5                -- seconds between an attacking zombie's swings
local CHECK = 0.25               -- seconds between looks for zombies
local POOL = "boz_lure_%d"       -- the SDK's lures for any place (bozkit.world LURE_POOL)
local POOL_SIZE = 4
local DEFAULTS = {zombies = 0, radius = 0, arrive = "wait", seconds = 0, enabled = true}

local running = {}               -- lower lure name -> run
local owner = {}                 -- zombie entity -> lower lure name
local ticking = false

--- Sets up the Lure point called name (entry: its settings from the map).
function Lure:init(name, entry)
    Object.init(self, name, entry)
    self.settings = require("boz.objects.settings").of(self, (entry or {}).settings or {})
end

local function setting(self, key)
    local value = self.settings and self.settings[key]
    if value == nil then
        return DEFAULTS[key]
    end
    return value
end

local function lure_position(run)
    if run.follow then
        local p = type(run.follow.position) == "function" and run.follow:position() or run.follow
        if p and p.x then
            entities.set_position(run.entity, p)    -- its navmesh goal follows (a moving object)
        end
    end
    return entities.position(run.entity)
end

local function flat_distance(a, b)
    local dx, dz = a.x - b.x, a.z - b.z
    return math.sqrt(dx * dx + dz * dz)
end

local function release(entity, record)
    owner[entity] = nil
    if record.controller and record.zombie:alive() and not record.zombie:dying() then
        game.write("u8", record.controller + LOCATOR_ONLY, record.was or 0)
        game.write("u8", record.controller + LOCATOR_NOTICED, 0)
        -- Back to the players: chasing again, after the nearest one.
        local player = require("boz.engine.map").player()
        if player then
            core.call("CAIControllerZombie::SetTarget", record.controller, player)
        end
        -- At once: a held zombie's turning state waits for a goal it no longer has.
        core.call("CIsStateMachine::ChangeState", record.controller + STATE_MACHINE, CHASE_STATE)
    end
end

local function walk(record, lure_entity)
    local c = record.controller
    game.write("u8", c + LOCATOR_ONLY, 0)
    game.write("u8", c + LOCATOR_NOTICED, 0)
    core.call("CAIControllerZombie::SetTarget", c, lure_entity)
end

local function goes_for(record, lure_entity)
    local ref = game.read("ptr", record.controller + TARGET + 4)
    return ref ~= 0 and game.read("ptr", ref + core.offset("CIsComponent", "entity")) == lure_entity
end

-- Every frame: zombies that reached the lure (or stopped getting closer to it) stand and wait;
-- a held zombie walks on when a followed object moved off.
local function hold(run, at, now)
    for _, record in pairs(run.zombies) do
        local c = record.controller
        local p = record.zombie:position()
        if p and c then
            local d = flat_distance(p, at)
            if not record.holding then
                if not record.best or d < record.best - 20 then
                    record.best, record.improved = d, now
                end
                local stalled = d <= STALL and record.zombie:state() == CHASE_STATE
                    and now - (record.improved or now) > STALL_SECONDS
                if (d <= NEAR or stalled) and math.abs(p.y - at.y) < 250 then
                    record.holding, record.held_at = true, d
                    game.write("u8", c + LOCATOR_ONLY, 1)       -- the goal's notice state: it stands
                    game.write("u8", c + LOCATOR_NOTICED, 0)
                end
            elseif d > (record.held_at or NEAR) + FOLLOW_SLACK then
                record.holding, record.best = false, nil
                walk(record, run.entity)
                core.call("CIsStateMachine::ChangeState", c + STATE_MACHINE, CHASE_STATE)
            end
            if record.holding and record.zombie:state() == GOAL_STATE then
                game.write("i32", c + NOTICE_TIMER, 1500)
            end
        end
    end
end

local function take(run, zombie)
    local controller = zombie.controller
    if not controller then
        return
    end
    local record = {zombie = zombie, controller = controller, was = game.read("u8", controller + LOCATOR_ONLY)}
    owner[zombie.entity] = run.key
    run.zombies[zombie.entity] = record
    run.count = run.count + 1
    walk(record, run.entity)
end

local function stop_run(key, run)
    running[key] = nil
    for entity, record in pairs(run.zombies) do
        release(entity, record)
    end
    run.object:_emit("stopped")
end

local function check(key, run, now)
    local at = lure_position(run)
    if not at then
        stop_run(key, run)
        return
    end
    -- Lured zombies: gone ones forgotten, arrivals reported, attackers swinging.
    local alive = 0
    for entity, record in pairs(run.zombies) do
        if not record.zombie:alive() or record.zombie:dying() then
            run.zombies[entity], owner[entity] = nil, nil
        else
            alive = alive + 1
            if not record.holding and not goes_for(record, run.entity) then
                walk(record, run.entity)    -- the game turned it back to a player: the lure again
            end
            local there = record.holding
            if there and not record.arrived then
                record.arrived = true
                record.swing = now + SWING / 2
                run.object:_emit("arrived", record.zombie)
            end
            if there and run.arrive == "attack" and now >= (record.swing or now) then
                record.swing = now + SWING
                record.zombie:send("SUBJECT_ZOMBIE_TRIGGER_ATTACK", 0)
                run.object:_emit("hit", record.zombie)
            end
        end
    end
    -- New zombies: the nearest first, within the radius, up to the count.
    local room = run.limit > 0 and run.limit - alive or math.huge
    if room > 0 then
        local free = {}
        for zombie in require("boz.game.zombies").each("zombie") do
            if not owner[zombie.entity] and zombie:alive() and not zombie:dying() then
                local p = zombie:position()
                local d = p and flat_distance(p, at)
                if d and (run.radius <= 0 or d <= run.radius) then
                    free[#free + 1] = {zombie = zombie, d = d}
                end
            end
        end
        table.sort(free, function(a, b) return a.d < b.d end)
        for i = 1, math.min(#free, room) do
            take(run, free[i].zombie)
        end
    end
end

local function tick()
    local now = timers.now()
    for key, run in pairs(running) do
        if run.until_ and now >= run.until_ then
            stop_run(key, run)
        else
            if now >= run.next then
                run.next = now + CHECK
                core.safely("boz lure " .. run.object.name, check, key, run, now)
            end
            local at = running[key] and entities.position(run.entity)
            if at then
                core.safely("boz lure " .. run.object.name, hold, run, at, now)
            end
        end
    end
    if next(running) == nil and ticking then
        ticking = false
        events.off("frame", tick)
    end
end

local function option(options, self, key)
    local value = options[key]
    if value == nil then
        value = setting(self, key)
    end
    return value
end

--- Starts luring (options as above; missing ones are its settings). A lure that runs starts
--- over with the new options. Returns the lure, or nil and why it cannot.
function Lure:start(options)
    options = options or {}
    if type(options) ~= "table" then
        error("start takes options such as {seconds = 10}", 2)
    end
    if not self:enabled() then
        return nil, "switched off"
    end
    local entity = engine.get(self.name):entity_pointer()
    if entity == 0 then
        log("boz: " .. self.name .. " cannot lure: it is not in the level")
        return nil, "not in the level"
    end
    local key = string.lower(self.name)
    if running[key] then
        stop_run(key, running[key])
    end
    local locator = entities.component(entity, "CLocator")
    if locator then
        game.write("u32", locator + LOCATOR_KIND, 1)
    end
    local arrive = option(options, self, "arrive")
    if arrive ~= "wait" and arrive ~= "attack" then
        error('arrive must be "wait" or "attack"', 2)
    end
    local seconds = tonumber(option(options, self, "seconds")) or 0
    local now = timers.now()
    running[key] = {key = key, object = self, entity = entity, follow = self._follow, zombies = {}, count = 0,
                    limit = math.floor(tonumber(option(options, self, "zombies")) or 0),
                    radius = tonumber(option(options, self, "radius")) or 0, arrive = arrive,
                    until_ = seconds > 0 and now + seconds or nil, next = now}
    if not ticking then
        ticking = true
        events.on("frame", tick)
    end
    self:_emit("started")
    return self
end

--- Stops luring: its zombies go back to the players. Returns the lure.
function Lure:stop()
    local key = string.lower(self.name)
    if running[key] then
        stop_run(key, running[key])
    end
    return self
end

--- True while it lures.
function Lure:running()
    return running[string.lower(self.name)] ~= nil
end

--- The zombies it holds now (boz.Zombie).
function Lure:zombies()
    local out = {}
    local run = running[string.lower(self.name)]
    for _, record in pairs(run and run.zombies or {}) do
        out[#out + 1] = record.zombie
    end
    return out
end

--- Switches it on or off: off, start() does nothing and a running lure stops. Returns the lure.
function Lure:set_enabled(on)
    self._enabled = on and true or false
    if not on then
        self:stop()
    end
    return self
end

--- True unless switched off (its editor setting, or set_enabled).
function Lure:enabled()
    if self._enabled ~= nil then
        return self._enabled
    end
    return setting(self, "enabled") ~= false
end

--- Lures zombies to a place ({x, y, z}) or an object (followed as it moves), with options as
--- Lure:start takes. Returns the lure (stop() it, or give seconds), or nil and why: the map
--- needs the BOZ SDK's lures (any map it builds has them).
function Lure.at(target, options)
    if type(target) ~= "table" or (not target.x and type(target.position) ~= "function") then
        error("boz.lure needs a position {x, y, z} or an object", 2)
    end
    local runtime = require("boz.objects.runtime")
    for i = 1, POOL_SIZE do
        local name = string.format(POOL, i)
        if not running[name] and engine.get(name):entity_pointer() ~= 0 then
            local lure = runtime.get(name) or Lure:new(name, {})
            if not lure.start then
                lure = Lure:new(name, {})
            end
            lure._follow = target
            return lure:start(options or {})
        end
    end
    local why = engine.get(string.format(POOL, 1)):entity_pointer() == 0
        and "this map has no lures (maps built with the BOZ SDK have them)" or "all lures are in use"
    log("boz.lure: " .. why)
    return nil, why
end

--- Stops every lure (a level that starts again).
function Lure.reset()
    for key, run in pairs(running) do
        running[key] = nil
        for entity in pairs(run.zombies) do
            owner[entity] = nil
        end
    end
    if ticking then
        ticking = false
        events.off("frame", tick)
    end
end

return Lure
