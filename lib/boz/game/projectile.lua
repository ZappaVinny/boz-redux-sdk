-- boz.Projectile: your projectiles (Effects tab) while they fly, and their scripts.
--
--   local IceBolt = boz.Projectile:extend("IceBolt")
--   function IceBolt:on_launch(shooter) self:attach("frost") end      -- an effect rides along
--   function IceBolt:on_update(dt) end                                -- every frame it flies
--   function IceBolt:on_hit(hit)                                      -- "zombie", "player", "world"
--       if hit.kind == "zombie" then hit.zombie:freeze() return false end   -- false: keep flying
--   end
--   function IceBolt:on_enter(what) end            -- something came within its radius (Effects
--   function IceBolt:on_leave(what) end            -- tab); what.kind: "zombie" or "player"
--   function IceBolt:on_end() end                  -- it hit, timed out or was removed
--   return IceBolt
--
-- Its pieces (blast, lure, black hole, trail, impact effect) run unless a function returns false
-- (on_hit: the hit pieces; on_launch: the trail). The game launches it (a launcher weapon, or
-- boz.effects.projectile); this module takes over its impact (Projectile_Impact) so nothing of
-- the game's own explosion happens.
--
-- game: Projectile_Impact, CProjectileEntity (flightVelocity, spec), btRigidBody

local Class = require("boz.class")
local core = require("boz.engine.core")
local entities = require("boz.engine.entities")
local components = require("boz.engine.components")
local effects = require("boz.game.effects")

local function pe(field) return core.offset("CProjectileEntity", field) end
local SPEC, OWNER, RIGID = pe("spec"), pe("owner"), pe("rigidBody")
local FLIGHT_VELOCITY, LAUNCH_VELOCITY = pe("flightVelocity"), pe("launchVelocity")
local BODY = core.offset("CIsRigidBody", "body")
local BODY_VELOCITY = core.offset("btRigidBody", "linearVelocity")

local Projectile = Class:extend("Projectile")

function Projectile:init(effect, entry, component)
    self.effect, self.name, self.entry, self.component = effect, entry.name, entry, component
    self.entity = effect.entity
    self.radius = entry.radius or 0
    self._attached, self._inside, self._ignored = {}, {}, {}
end

--- Its position {x, y, z}, or nil once it is gone.
function Projectile:position() return self.effect:position() end

-- Its physics body (gravity projectiles), once the game has set it up: before that the field
-- holds whatever was in memory, and writing through it crashes the game.
local function body_of(self)
    if not self.effect:ready() then
        return nil
    end
    local rigid = game.read("ptr", self.component + RIGID)
    if rigid == 0 or rigid ~= core.call("CIsRigidBody::FromEntity", self.entity) then
        return nil
    end
    local body = game.read("ptr", rigid + BODY)
    return body ~= 0 and body or nil
end

--- Its velocity {x, y, z} (units a second).
function Projectile:velocity()
    local body = body_of(self)
    return core.read_vec3((body and body + BODY_VELOCITY) or (self.component + FLIGHT_VELOCITY))
end

--- Sets its velocity {x, y, z} (units a second): steering, homing, stopping.
function Projectile:set_velocity(velocity)
    self._velocity, self._velocity_frames = velocity, 6     -- the game finishes setting it up after launch
    local body = body_of(self)
    if body then
        core.write_vec3(body + BODY_VELOCITY, velocity)
    else
        -- Its first flight step copies the launch velocity into the flight velocity: both.
        core.write_vec3(self.component + LAUNCH_VELOCITY, velocity)
        core.write_vec3(self.component + FLIGHT_VELOCITY, velocity)
    end
    return self
end

--- An effect that rides along with it (one of yours); removed when it ends. (self.effect is the
--- projectile itself: position, move, remove.)
function Projectile:attach(name, options)
    local made = effects.attach(name, self, options)
    if made then self._attached[#self._attached + 1] = made end
    return made
end

--- An explosion where it is (boz.effects.explode options: radius, inner, damage, min_damage).
function Projectile:explode(options)
    local at = self:position()
    return at and effects.explode(at, options)
end

--- Zombies go where it is (boz.lure options: seconds, ...).
function Projectile:lure(options)
    local at = self:position()
    return at and require("boz").lure(at, options)
end

--- Takes it out of the world (on_end follows).
function Projectile:remove()
    self.effect:remove()
end

-- Running ----------------------------------------------------------------------------------

local projectile = {}
local script = require("boz.game.effect_script")
local by_hash = {}       -- spec hash -> entry (your projectiles)
local flying = {}        -- component -> instance
local hits = {}          -- {component, entity id}
local started = false

local function own_entries()
    by_hash = {}
    for _, entry in pairs(effects.known()) do
        if entry.own and entry.kind == "projectile" then
            by_hash[entry.hash] = entry
        end
    end
end

local HIT_REACH = 60     -- units: what is this close to the hit point is what it hit

-- What a hit was: the game's impact does not say, so the nearest zombie or player to the hit
-- point (its centre within HIT_REACH, a body's width), else the world.
local function classify(at)
    if not at then
        return {kind = "world"}
    end
    local function close(p)
        return p and (p.x - at.x) ^ 2 + (p.z - at.z) ^ 2 <= HIT_REACH ^ 2 and at.y >= p.y - 20 and at.y <= p.y + 200
    end
    for _, zombie in ipairs(require("boz").zombies("all")) do
        if close(zombie:position()) then
            return {kind = "zombie", zombie = zombie, entity = zombie.entity}
        end
    end
    local player = require("boz.engine.map").player()
    if player and close(entities.position(player)) then
        return {kind = "player", entity = player}
    end
    return {kind = "world"}
end

local function pieces_on_hit(self, at)
    local pieces = self.entry.pieces or {}
    if pieces.impact and pieces.impact ~= "" then
        effects.spawn(pieces.impact, at, {lifetime = 4})
    end
    effects.run_pieces(at, pieces)
end

local function finish(component, self)
    flying[component] = nil
    for _, attached in ipairs(self._attached) do
        effects.detach(attached)
        attached:remove()
    end
    script.safely(self, "on_end")
end

local function launch(component, entry)
    local entity = entities.of_component(component)
    local effect = effects.handle(entity, entry.name)
    local class = entry.script ~= "" and script.class_of(entry.script) or nil
    local self = (class or Projectile):new(effect, entry, component)
    flying[component] = self
    local owner = game.read("ptr", component + OWNER)
    local keep = script.safely(self, "on_launch", owner ~= 0 and owner or nil)
    local trail = (entry.pieces or {}).trail
    if keep ~= false and trail and trail ~= "" then
        self:attach(trail)
    end
end

local function update(dt)
    -- New ones (the game launched them) and gone ones.
    for component in components.each("CProjectileEntity") do
        if not flying[component] then
            local entry = by_hash[game.read("u32", component + SPEC)]
            if entry then
                local ok, err = pcall(launch, component, entry)
                if not ok then log("boz.Projectile " .. entry.name .. ": " .. tostring(err)) end
            end
        end
    end
    for component, self in pairs(flying) do
        if not self.effect:alive() then
            finish(component, self)
        end
    end
    -- Hits the game reported this frame.
    local pending = hits
    hits = {}
    for _, hit in ipairs(pending) do
        local self = flying[hit.component]
        local at = self and self:position()
        local info = self and classify(at)
        local key = info and (info.entity or "world")
        if self and not self._ignored[key] then
            info.position = at
            local result = script.safely(self, "on_hit", info)
            if result == false then
                self._ignored[key] = true          -- it flies on through this one
            else
                if info.position then
                    local ok, err = pcall(pieces_on_hit, self, info.position)
                    if not ok then log("boz.Projectile " .. self.name .. ": pieces: " .. tostring(err)) end
                end
                self:remove()
                finish(hit.component, self)
            end
        end
    end
    -- Velocities set at launch, again while the game finishes setting the projectile up.
    for _, self in pairs(flying) do
        if self._velocity_frames and self._velocity_frames > 0 then
            self._velocity_frames = self._velocity_frames - 1
            local body = body_of(self)
            if body then
                core.write_vec3(body + BODY_VELOCITY, self._velocity)
            else
                core.write_vec3(self.component + LAUNCH_VELOCITY, self._velocity)
                core.write_vec3(self.component + FLIGHT_VELOCITY, self._velocity)
            end
        end
    end
    -- In and out of its radius: zombies and players, as on_hit sees them.
    for _, self in pairs(flying) do
        if self.radius > 0 and (self.on_enter or self.on_leave) then
            local at = self:position()
            if at then
                local now = {}
                local function near(entity, what)
                    local p = entities.position(entity)
                    if p and (p.x - at.x) ^ 2 + (p.y - at.y) ^ 2 + (p.z - at.z) ^ 2 <= self.radius ^ 2 then
                        now[entity] = what
                        if not self._inside[entity] then script.safely(self, "on_enter", what) end
                    end
                end
                for _, zombie in ipairs(require("boz").zombies("all")) do
                    near(zombie.entity, {kind = "zombie", zombie = zombie, entity = zombie.entity})
                end
                local player = require("boz.engine.map").player()
                if player then near(player, {kind = "player", entity = player}) end
                for entity, what in pairs(self._inside) do
                    if not now[entity] then script.safely(self, "on_leave", what) end
                end
                self._inside = now
            end
        end
        script.safely(self, "on_update", dt)
    end
end

--- Starts watching the map's own projectiles (boz.world calls it when the level starts).
function projectile.start()
    own_entries()
    if started or next(by_hash) == nil then
        return
    end
    started = true
    hook.add(core.sym("Projectile_Impact"), {before = function(call)
        local component = call:arg(1)
        if by_hash[game.read("u32", component + SPEC)] then
            -- Ours: no game explosion, sound or terminate; the script and pieces decide.
            hits[#hits + 1] = {component = component, id = call:arg(2)}
            call:skip()
        end
    end})
    events.on("frame", function(dt) core.safely("boz.Projectile", update, dt or 0) end)
end

projectile.Projectile = Projectile
return projectile
