-- boz.effects: spawning the game's effects and projectiles anywhere, for as long as you want.
--
--   local effects = require("boz.game.effects")
--   effects.spawn("impactRayGun", {x = 0, y = 50, z = 0})            -- a one-off effect
--   local hole = effects.projectile("gersch", effects.aim(), {trigger = "open", lifetime = 6})
--   hole:remove()                                                    -- close it early
--   effects.explode(position, {radius = 400, damage = 2000})          -- a grenade's blast
--   local glow = effects.attach("frost_glow", "weapon", {bone = "tag_flash"})  -- follows the gun
--   glow:set({scale = 2, rate = {10, 20}})                            -- its particles, live
--
-- Names are the game's effect and projectile names ("gersch_Effect", "impactRayGun",
-- "iceShatter", ...; any map's: the build bundles what scripts name, and the editor's Effects tab
-- lists them and can give them your own names), or "0x..." hashes.
--
-- game: Spawn_ByHash, SUBJECT_SPAWN_GERSCH_EFFECT, SUBJECT_EXPLODE, SUBJECT_TERMINATE

local effects = {}

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")
local entities = require("boz.engine.entities")
local reflect = require("boz.engine.reflect")

--- Projectiles that explode (every map's weapon projectiles group has them).
effects.EXPLOSIONS = {frag = "projectile_frag_grenade", raygun = "projectile_raygun",
                      claymore = "projectile_claymore", monkey = "projectile_monkeyBomb"}

--- What a projectile answers to: the event it is sent, and whether the game restarts its
--- lifetime when it arrives (a Gersch device's lifetime starts again once it has opened).
effects.TRIGGERS = {
    open = {event = "SUBJECT_SPAWN_GERSCH_EFFECT", restarts_lifetime = true},
    explode = {event = "SUBJECT_EXPLODE"},
}

local function projectile(field) return core.offset("CProjectileEntity", field) end
local LINKED_TRANSFORM, RIGID, LIFETIME = projectile("linkedTransform"), projectile("rigidBody"),
    projectile("lifetime")
local OPENED, OWNER, SUBJECT = projectile("opened"), projectile("owner"), projectile("subject")
local BULLET_BODY = core.offset("CIsRigidBody", "body")
local AIM, AIM_ZOMBIE = core.offset("CWeaponManager", "aim"), core.offset("CWeaponManager", "aimZombie")
local PROJECTILE = "CProjectileEntity"
local SETUP_FRAMES = 120          -- how long a new projectile may take to be set up by the game

local known = {}         -- name -> {hash, kind, behaviour, triggers} (the map's effects)
local timed = {}         -- Effect -> seconds left (effects removed after their lifetime)
local restarting = {}    -- Effect -> ms: a lifetime to give again once its trigger restarted it
local waiting = {}       -- Effect -> frames left: projectiles the game has not set up yet

local function hash_of(name)
    local entry = type(name) == "string" and known[name]
    return entry and entry.hash or hash.of(name)
end

--- Tell boz.effects the map's effects: {name, hash, kind, behaviour, triggers} each (the map's
--- world data does this at level start).
function effects.know(list)
    for _, entry in ipairs(list or {}) do
        known[entry.name] = entry
    end
end

--- The map's effects by name ({hash, kind, behaviour, triggers}).
function effects.known()
    return known
end

--- The effect handle of an entity already in the world (a projectile the game launched).
function effects.handle(entity, name)
    return setmetatable({entity = entity, id = entities.id(entity), name = name}, effects._Effect)
end

local Effect = {}
Effect.__index = Effect
effects._Effect = Effect

local function make(entity, name)
    return setmetatable({entity = entity, id = entities.id(entity), name = name}, Effect)
end

--- True while it is still in the world.
function Effect:alive()
    return self.entity ~= 0 and entities.alive(self.id)
end

--- Its CProjectileEntity component, or 0 for a plain effect.
function Effect:projectile()
    return core.call("CProjectileEntity::FromEntity", self.entity)
end

--- True once the game has set it up (a projectile takes a frame or so after spawning; scripts
--- need not wait: what was asked for happens then).
function Effect:ready()
    if not self:alive() then
        return false
    end
    local projectile = self:projectile()
    if projectile == 0 then
        return true
    end
    local transform = core.call("CIsTransform::FromEntity", self.entity)
    return transform ~= 0 and game.read("u32", projectile + LINKED_TRANSFORM) == transform
end

--- Its position {x, y, z} (game centimetres, y up), or nil once it is gone.
function Effect:position()
    return self:alive() and entities.position(self.entity) or nil
end

--- Moves it to a position.
function Effect:move(position)
    return self:alive() and entities.set_position(self.entity, position)
end

local function send(self, name)
    local trigger = effects.TRIGGERS[name]
    local projectile = self:projectile()
    core.call("CIsSubject::NotifyVirtual", projectile + SUBJECT, hash.name(trigger.event), 0, 0, 0)
    if trigger.restarts_lifetime then
        self.restarted = true
        if self.wanted_ms and game.read("u8", projectile + OPENED) == 0 then
            restarting[self] = self.wanted_ms
        end
    end
end

local function wait_for_setup(self)
    waiting[self] = waiting[self] or SETUP_FRAMES
end

--- Sends a trigger (effects.TRIGGERS: "open", "explode"). A projectile still being set up gets
--- it as soon as it is. Returns false when it does not answer that trigger or is gone.
function Effect:trigger(name)
    if not effects.TRIGGERS[name] or not self:alive() or self:projectile() == 0 then
        return false
    end
    if self:ready() then
        send(self, name)
    else
        self.wanted_trigger = name
        wait_for_setup(self)
    end
    return true
end

--- Shows or hides its own model (a projectile's behaviour and the effects it spawns stay).
function Effect:set_visible(visible)
    return self:alive() and entities.set_visible(self.entity, visible)
end

--- Hides or shows its own model.
function Effect:hide() return self:set_visible(false) end
function Effect:show() return self:set_visible(true) end

--- Stops a projectile where it is (it no longer falls or rolls), once the game has set it up.
function Effect:freeze()
    if not self:ready() then
        self.wanted_freeze = true
        wait_for_setup(self)
        return true
    end
    local projectile = self:projectile()
    local rigid = projectile ~= 0 and core.call("CIsRigidBody::FromEntity", self.entity) or 0
    if rigid == 0 or game.read("u32", projectile + RIGID) ~= rigid then
        return false
    end
    local body = game.read("u32", rigid + BULLET_BODY)
    if body == 0 then
        return false
    end
    core.call("Physics_SetActivation", body, 2)
    return true
end

-- A projectile floating cm above the floor reaches that much further: zombies walk under it, and
-- its proximity check (m_proximityRadius, metres) measures from its centre in 3D.
local function reach_down(self, cm)
    local projectile = self:projectile()
    local radius = (reflect.get(projectile, PROJECTILE, "m_proximityRadius") or 0) * 100
    reflect.set(projectile, PROJECTILE, "m_proximityRadius", math.sqrt(radius * radius + cm * cm) / 100)
end

local function give_lifetime(self, ms)
    local projectile = self:projectile()
    game.write("u32", projectile + LIFETIME, ms)
    reflect.set(projectile, PROJECTILE, "m_bHasLifeTime", true)
    if self.restarted and game.read("u8", projectile + OPENED) == 0 then
        restarting[self] = ms
    end
end

--- Removes it after this many seconds from now. A projectile ends the game's way (a black hole
--- closes with its own sound and effect).
function Effect:lifetime(seconds)
    if not self:alive() then
        return self
    end
    local ms = math.max(1, math.floor(seconds * 1000))
    if self:projectile() == 0 then
        timed[self] = seconds
    else
        self.wanted_ms = ms
        if self:ready() then
            give_lifetime(self, ms)
        else
            wait_for_setup(self)
        end
    end
    return self
end

--- Removes it now (a projectile ends the game's way).
function Effect:remove()
    timed[self], restarting[self], waiting[self] = nil, nil, nil
    if not self:alive() then
        return
    end
    local projectile = self:projectile()
    if projectile ~= 0 and self:ready() then
        core.call("CIsSubject::NotifyVirtual", projectile + SUBJECT, hash.name("SUBJECT_TERMINATE"), 0, 0, 0)
    else
        entities.remove(self.entity)
    end
end

local function set_up(self)
    if self.wanted_hidden then
        self:set_visible(false)
    end
    if self.wanted_freeze then
        self:freeze()
    end
    if self.wanted_trigger then
        send(self, self.wanted_trigger)
    end
    if self.wanted_ms then
        give_lifetime(self, self.wanted_ms)
    end
    if self.wanted_raise then
        reach_down(self, self.wanted_raise)
    end
    self.wanted_hidden, self.wanted_freeze, self.wanted_trigger, self.wanted_raise = nil, nil, nil, nil
end

local function spawn(name, position, options)
    options = options or {}
    local x, y, z = core.xyz(position)
    local entity, err = entities.spawn(hash_of(name), {x, y + (options.lift or 0), z}, options.rotation)
    if not entity then
        if err == "not in a match" then
            return nil, err
        end
        return nil, "the map has no effect " .. tostring(name) ..
            " (name it in the Effects tab, or name it in a script so the build brings it)"
    end
    if core.call("CIsTransform::FromEntity", entity) == 0 then
        -- A part of another effect (no position of its own): drawing it would crash the game.
        entities.remove(entity)
        return nil, tostring(name) .. " is a part of another effect and cannot be spawned on its own"
    end
    return make(entity, name)
end

local function spawn_logged(name, position, options)
    local effect, err = spawn(name, position, options)
    if not effect then
        log("boz.effects: " .. tostring(err))
    end
    return effect, err
end

--- Spawns an effect at a position {x, y, z}. Options: rotation {x, y, z, w}, lifetime (seconds,
--- then it is removed). Returns the effect, or nil and why.
-- Co-op: the host spawns effects for every game (a guest's own action asks the host); what the
-- options hold that cannot travel (functions) stays behind.
local function shared(op, name, position, options)
    local plain = {}
    for key, value in pairs(options or {}) do
        if type(value) ~= "function" and type(value) ~= "userdata" then plain[key] = value end
    end
    local at = position and {x = position.x, y = position.y, z = position.z} or nil
    return require("boz.engine.net").route(op, {name = name, position = at, options = plain}) == "skip"
end

--- Runs pieces (Effects tab) at a position: blast {damage, radius}, lure {seconds}, black_hole
--- {seconds}. Projectiles run theirs where they hit, effects where they appear.
function effects.run_pieces(at, pieces)
    if pieces.blast then
        local radius, damage = pieces.blast.radius or {32, 64}, pieces.blast.damage or {1000, 1500}
        effects.explode(at, {inner = radius[1], radius = radius[2], min_damage = damage[1],
                             damage = damage[2], quiet = true})
    end
    if pieces.lure then
        require("boz").lure(at, {seconds = pieces.lure.seconds})
    end
    if pieces.black_hole then
        effects.projectile("boz_black_hole", at, {trigger = "open", lifetime = pieces.black_hole.seconds,
                                                  freeze = true, hidden = true})
    end
end

function effects.spawn(name, position, options)
    if shared("effect_spawn", name, position, options) then
        return nil, "the host spawns it"
    end
    local effect, err = spawn_logged(name, position, options)
    if effect and options and options.lifetime then
        timed[effect] = options.lifetime
    end
    local entry = effect and known[name]
    local keep
    if entry and entry.script and entry.script ~= "" then
        keep = select(2, require("boz.game.effect_script").start(effect, entry))   -- its script (Effects tab)
    end
    if entry and entry.pieces and next(entry.pieces) and keep ~= false then
        local at = effect:position() or position
        local ok, why = pcall(effects.run_pieces, at, entry.pieces)
        if not ok then log("boz.effects " .. tostring(name) .. ": pieces: " .. tostring(why)) end
    end
    return effect, err
end

--- Spawns a projectile at a position and lets the game run it. Options: trigger (e.g. "open"),
--- lifetime (seconds; after a trigger), raise (centimetres: it floats that far above the position,
--- and its proximity reach grows to match, so zombies walking under a black hole still die; for
--- one that "Stays where spawned"), hidden (its own model is not drawn), freeze (stay where
--- spawned instead of settling on the floor), lift (centimetres up, default 10; raise replaces
--- it), rotation. It is the player's (zombies turning to a device ask for its owner, so it always
--- has one). What it was asked for happens once the game has set it up (a frame or so). Returns
--- the projectile, or nil and why.
function effects.projectile(name, position, options)
    options = options or {}
    if shared("effect_projectile", name, position, options) then
        return nil, "the host spawns it"
    end
    local effect, err = spawn_logged(name, position, {rotation = options.rotation,
                                                      lift = options.raise or options.lift or 10})
    if not effect then
        return nil, err
    end
    local projectile = effect:projectile()
    if projectile == 0 then
        effect:remove()
        log("boz.effects: " .. tostring(name) .. " is not a projectile")
        return nil, tostring(name) .. " is not a projectile"
    end
    -- The owner and spec go in right away, as ProjectileManager_Launch does.
    local player = require("boz.engine.map").player()
    if not player then
        effect:remove()
        return nil, "no player to own it"
    end
    game.write("u32", projectile + OWNER, player)
    reflect.set(projectile, PROJECTILE, "m_EntitySpecHash", hash_of(name))
    effect.wanted_hidden = options.hidden or nil
    effect.wanted_freeze = options.freeze or nil
    effect.wanted_raise = options.raise
    effect.wanted_trigger = options.trigger
    effect.wanted_ms = options.lifetime and math.max(1, math.floor(options.lifetime * 1000)) or nil
    if effect:ready() then
        set_up(effect)
    else
        waiting[effect] = SETUP_FRAMES
    end
    return effect
end

--- An explosion at a position, the player's (its kills count; it hurts the player too, at
--- OwnExplosionDamageModifier percent, like their own grenade). Options: radius (centimetres;
--- default the grenade's), inner (full damage within it), damage (the most, at the centre),
--- min_damage (at the edge), kind (effects.EXPLOSIONS: "frag", the default, "raygun",
--- "claymore", "monkey"), quiet (no explosion effect). Returns the explosion's projectile, or
--- nil and why.
function effects.explode(position, options)
    options = options or {}
    if shared("effect_explode", nil, position, options) then
        return nil, "the host spawns it"
    end
    local spec = effects.EXPLOSIONS[options.kind or "frag"] or options.kind
    local net = require("boz.engine.net")
    local blast, err = net.local_only(effects.projectile, spec, position,
                                      {hidden = true, freeze = true, lift = 0})
    if not blast then
        return nil, err
    end
    local explosion = entities.component(blast.entity, "CExplosion")
    if not explosion then
        blast:remove()
        return nil, tostring(spec) .. " does not explode"
    end
    local fields = {m_Radius = options.radius, m_InnerRadius = options.inner, m_MaxDamage = options.damage,
                    m_MinDamage = options.min_damage}
    for field, value in pairs(fields) do
        reflect.set(explosion, "CExplosion", field, value)
    end
    if options.quiet then
        reflect.set(explosion, "CExplosion", "m_DoExplosionVFX", false)
    end
    blast.wanted_trigger = "explode"
    if blast:ready() then
        set_up(blast)
    else
        wait_for_setup(blast)
    end
    return blast
end

-- Live settings ---------------------------------------------------------------------------

local EMITTER_COMPONENT = "CIsRenderableGFXEmitter"
local RUNNING = core.offset("CIsRenderableGFXEmitter", "emitter")
local function em(field) return core.offset("CIwGFXEmitter", field) end
local SCALE, SPAWNING, AGE, DURATION = em("scale"), em("spawning"), em("age"), em("duration")
local OWN_RATE, RATE_MIN, RATE_MAX = em("ownRate"), em("rateMin"), em("rateMax")
local OWN_VELOCITY, VELOCITY_BOX = em("ownVelocity"), em("velocityBox")
local OWN_POSITION, POSITION_BOX = em("ownPosition"), em("positionBox")
local PARENT = core.offset("CIsHierarchy", "parent")
local COMPONENT_ENTITY = core.offset("CIsComponent", "entity")
local FIXED = 4096

local function parent_of(entity)
    local hierarchy = entities.component(entity, "CIsHierarchy")
    local parent = hierarchy and game.read("ptr", hierarchy + PARENT)
    return parent and parent ~= 0 and game.read("ptr", parent + COMPONENT_ENTITY) or nil
end

--- Its running particle emitters (its own and its children's): CIwGFXEmitter pointers.
function Effect:emitters()
    local out = {}
    if not self:alive() then
        return out
    end
    for component in require("boz.engine.components").each(EMITTER_COMPONENT) do
        local owner = entities.of_component(component)
        if owner == self.entity or parent_of(owner) == self.entity then
            local emitter = game.read("ptr", component + RUNNING)
            if emitter and emitter ~= 0 then
                out[#out + 1] = emitter
            end
        end
    end
    return out
end

local function write_box(at, base, spread, per_second)
    local x, y, z = core.xyz(base or {0, 0, 0})
    local sx, sy, sz = core.xyz(spread or {0, 0, 0})
    local k = per_second and FIXED / 1000 or 1
    for i, v in ipairs({x, y, z, sx, sy, sz}) do
        game.write("i32", at + (i - 1) * 4, math.floor(v * k))
    end
end

--- Changes its particles while it runs (each emitter): scale (x: speed, size and growth), rate
--- {min ms, max ms} between particles, velocity {x, y, z} units a second (and spread), position
--- {x, y, z} where particles start (and position_spread), duration (seconds; it stops spawning
--- after), spawning (false: stops making new ones; true: starts again). Returns the effect.
function Effect:set(settings)
    for _, emitter in ipairs(self:emitters()) do
        if settings.scale then
            game.write("i32", emitter + SCALE, math.floor(settings.scale * FIXED))
        end
        if settings.rate then
            local low, high = settings.rate[1] or settings.rate, settings.rate[2] or settings.rate[1] or settings.rate
            game.write("i32", emitter + RATE_MIN, math.floor(low * FIXED))
            game.write("i32", emitter + RATE_MAX, math.floor(high * FIXED))
            game.write("u8", emitter + OWN_RATE, 1)
        end
        if settings.velocity then
            write_box(emitter + VELOCITY_BOX, settings.velocity, settings.spread, true)
            game.write("u8", emitter + OWN_VELOCITY, 1)
        end
        if settings.position then
            write_box(emitter + POSITION_BOX, settings.position, settings.position_spread, false)
            game.write("u8", emitter + OWN_POSITION, 1)
        end
        if settings.duration then
            game.write("i32", emitter + DURATION, math.floor(settings.duration * 1000 * FIXED))
        end
        if settings.spawning == false then
            game.write("u8", emitter + SPAWNING, 0)
        elseif settings.spawning == true then
            game.write("i32", emitter + AGE, 0)
            game.write("u8", emitter + SPAWNING, 1)
        end
    end
    return self
end

-- Following -------------------------------------------------------------------------------

local following = {}     -- Effect -> {target, bone, offset}

local function target_entity(target)
    if target == "weapon" then
        local gun = require("boz.engine.weapons").current()
        return gun and gun:entity() or nil
    end
    if type(target) == "table" then
        if target._handle then          -- boz.get(...): a map object
            local entity = target._handle:entity_pointer()
            return entity ~= 0 and entity or nil
        end
        return target.entity          -- an Effect, a Zombie, ...
    end
    return target
end

local function place_of(follow)
    local entity = target_entity(follow.target)
    if not entity then
        return nil
    end
    local at = follow.bone and require("boz.engine.animation").bone_position(entity, follow.bone)
        or entities.position(entity)
    if not at then
        return nil
    end
    local dx, dy, dz = core.xyz(follow.offset or {0, 0, 0})
    return {x = at.x + dx, y = at.y + dy, z = at.z + dz}
end

--- Makes an effect (an Effect, or a name to spawn) follow something: an object (boz.get(...)),
--- an entity, or "weapon" (the gun in hand); options: bone (a bone of it, e.g. "tag_flash", the
--- muzzle), offset {x, y, z}, lifetime (seconds). Returns the effect, or nil and why.
function effects.attach(effect, target, options)
    options = options or {}
    local follow = {target = target, bone = options.bone, offset = options.offset}
    if type(effect) ~= "table" then
        local at = place_of(follow)
        if not at then
            return nil, "nothing to attach to"
        end
        local made, err = effects.spawn(effect, at, {lifetime = options.lifetime})
        if not made then
            return nil, err
        end
        effect = made
    end
    following[effect] = follow
    return effect
end

--- Stops an effect following what it was attached to (it stays where it is).
function effects.detach(effect)
    following[effect] = nil
end

--- The point the player's crosshair is on {x, y, z} (where a shot lands; up to 100 m away) and
--- whether it is a live zombie; nil outside a match.
function effects.aim()
    local manager = require("boz.engine.weapons").manager()
    if not manager then
        return nil
    end
    return core.read_vec3(manager + AIM), game.read("u8", manager + AIM_ZOMBIE) ~= 0
end

events.on("frame", function(dt)
    for effect, follow in pairs(following) do
        if not effect:alive() then
            following[effect] = nil
        else
            local at = place_of(follow)
            if at then effect:move(at) end
        end
    end
    for effect, frames in pairs(waiting) do
        if not effect:alive() or frames <= 0 then
            if frames <= 0 then
                log("boz.effects: " .. tostring(effect.name) .. " was never set up by the game")
            end
            waiting[effect] = nil
        elseif effect:ready() then
            waiting[effect] = nil
            set_up(effect)
        else
            waiting[effect] = frames - 1
        end
    end
    for effect, ms in pairs(restarting) do
        if not effect:alive() then
            restarting[effect] = nil
        elseif game.read("u8", effect:projectile() + OPENED) ~= 0 then
            game.write("u32", effect:projectile() + LIFETIME, ms)
            restarting[effect] = nil
        end
    end
    for effect, left in pairs(timed) do
        left = left - (dt or 0)
        if left <= 0 then
            effect:remove()
        else
            timed[effect] = left
        end
    end
end)

local net_ops = require("boz.engine.net")
net_ops.op("effect_spawn", function(args) effects.spawn(args.name, args.position, args.options) end)
net_ops.op("effect_projectile", function(args) effects.projectile(args.name, args.position, args.options) end)
net_ops.op("effect_explode", function(args) effects.explode(args.position, args.options) end)

return effects
