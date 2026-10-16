-- boz.effects: spawning the game's effects and projectiles anywhere, for as long as you want.
--
--   local effects = require("boz.effects")
--   effects.spawn("impactRayGun", {x = 0, y = 50, z = 0})            -- a one-off effect
--   local hole = effects.projectile("gersch", effects.aim(), {trigger = "open", lifetime = 6})
--   hole:remove()                                                    -- close it early
--   effects.explode(position, {radius = 400, damage = 2000})          -- a grenade's blast
--
-- Names are the game's effect and projectile names ("gersch_Effect", "impactRayGun",
-- "iceShatter", ...; any map's: the build bundles what scripts name, and the editor's Effects tab
-- lists them and can give them your own names), or "0x..." hashes.
--
-- Effects are visual (particles); projectiles bring the game's behaviour with them: a Gersch
-- device opens a black hole that pulls zombies in and kills them, a monkey bomb lures them, a
-- bolt explodes where it hits. What a projectile answers to (its triggers) depends on what it
-- is: "open" (black hole), "explode" (grenades, bolts).
--
-- How it works (Ghidra names in the game definition): Spawn_ByHash(CSpawnManager, spec hash,
-- position, rotation s x y z) creates any entity spec a loaded group holds; a projectile's
-- CProjectileEntity keeps its lifetime (ms) at +0xc0 (+0xc4 on), its open state at +0xc7, its
-- owner at +0x88, its rigid body at +0x80 (Bullet body +0x34); events go to its subject at +0x28
-- (SUBJECT_SPAWN_GERSCH_EFFECT opens a Gersch device, SUBJECT_EXPLODE, SUBJECT_TERMINATE ends
-- it with its own sounds); EntityDB_Destroy removes an entity. The crosshair point is the weapon
-- manager's +0xcc (WeaponManager_UpdateAim ray-casts it every frame; +0xf0: a live zombie).
-- A spawned entity's components are set up by the game a little later (CProjectileEntity::Init
-- links its transform at +0x7c, subscribes to its events and finds its rigid body): a projectile
-- gets its trigger and lifetime once that has happened; its owner (+0x88) right away, as the
-- game's own launcher does (zombies turning to a device read it). Entities are objects (their id at
-- +4); CIsEntityDB::GetEntity finds one by id, so a removed one is never touched.

local hash = require("boz.hash")

local effects = {}

-- Projectiles that explode (every map's weapon projectiles group has them).
local EXPLOSIONS = {frag = "projectile_frag_grenade", raygun = "projectile_raygun",
                    claymore = "projectile_claymore", monkey = "projectile_monkeyBomb"}

local FALLBACK = {
    ["Spawn_ByHash"] = 0x1fa9c6 + 1,
    ["EntityDB_Destroy"] = 0x0bb2d8 + 1,
    ["Physics_SetActivation"] = 0x029924 + 1,
    ["CProjectileEntity::FromEntity"] = 0x1e2fa0 + 1,
    ["CIsRigidBody::FromEntity"] = 0x054098 + 1,
    ["CIsTransform::FromEntity"] = 0x0c23e4 + 1,
    ["CIsTransform::UpdateWorld"] = 0x0c2488 + 1,
    ["Transform_SetDirty"] = 0x0c2430 + 1,
    ["CIsEntityDB::GetEntity"] = 0x0bd4c8 + 1,
    ["CIsSubject::NotifyVirtual"] = 0x0c12f8 + 1,
    ["CIwSoundManager::Play"] = 0x0d6dae + 1,
    ["CSpawnManager::s_instance"] = 0x460830,
    ["CIsEntityDB::s_instance"] = 0x457920,
    ["CIwSoundManager::s_instance"] = 0x4535d8,
    ["CLevelManager::s_instance"] = 0x460840,
    ["CIsRenderableModel::SetVisible"] = 0x22c5a8 + 1,
    ["CIsRenderableModel::s_table"] = 0x4712e4,
}
local ENTITY_ID = 4
local LOCAL_POSITION, WORLD_POSITION = 0xa8, 0x5c
local LINKED_TRANSFORM, RIGID = 0x7c, 0x80
local LIFETIME, HAS_LIFETIME, OPEN, OWNER, SPEC, SUBJECT = 0xc0, 0xc4, 0xc7, 0x88, 0xec, 0x28
local KILL_RADIUS = 0x90        -- m_proximityRadius (metres): a black hole kills within it, in 3D
local BULLET_BODY = 0x34
local AIM, AIM_ZOMBIE = 0xcc, 0xf0
local SETUP_FRAMES = 120          -- how long a new projectile may take to be set up by the game
local EVENTS = {open = "SUBJECT_SPAWN_GERSCH_EFFECT", explode = "SUBJECT_EXPLODE"}

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

-- A game function's result as an address: game.call returns signed numbers, game.read("u32")
-- unsigned ones, and heap addresses are often above 0x80000000.
local function call(...)
    return (game.call(...) or 0) & 0xffffffff
end

local known = {}         -- name -> {hash, kind, behaviour, triggers} (the map's effects)
local timed = {}         -- Effect -> seconds left (effects removed after their lifetime)
local opening = {}       -- Effect -> ms: a lifetime to give a black hole once it has opened
local waiting = {}       -- Effect -> frames left: projectiles the game has not set up yet
local scratch            -- 32 bytes for positions and rotations passed to the game
local lookup             -- 8 bytes: an entity id for CIsEntityDB::GetEntity

local function buffer()
    scratch = scratch or game.alloc(32)
    return scratch
end

local function vec(position)
    return position.x or position[1] or 0, position.y or position[2] or 0,
        position.z or position[3] or 0
end

local function hash_of(name)
    if type(name) == "number" then
        return name
    end
    local entry = known[name]
    if entry then
        return entry.hash
    end
    if string.sub(name, 1, 2) == "0x" then
        return tonumber(string.sub(name, 3), 16)
    end
    return hash.name(name)
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

-- An effect or projectile in the world.
local Effect = {}
Effect.__index = Effect

local function make(entity, name)
    return setmetatable({entity = entity, id = game.read("u32", entity + ENTITY_ID), name = name},
                        Effect)
end

--- True while it is still in the world.
function Effect:alive()
    if self.entity == 0 then
        return false
    end
    lookup = lookup or game.alloc(8)
    game.write("u32", lookup + ENTITY_ID, self.id)
    -- GetEntity gives the entity's record (another object than the handle Spawn_ByHash returns)
    -- while its id is in use, 0 once it is gone.
    return call(sym("CIsEntityDB::GetEntity"), lookup) ~= 0
end

function Effect:transform()
    return call(sym("CIsTransform::FromEntity"), self.entity)
end

function Effect:projectile()
    return call(sym("CProjectileEntity::FromEntity"), self.entity)
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
    local transform = self:transform()
    return transform ~= 0 and game.read("u32", projectile + LINKED_TRANSFORM) == transform
end

--- Its position {x, y, z} (game centimetres, y up), or nil once it is gone.
function Effect:position()
    if not self:alive() then
        return nil
    end
    local transform = self:transform()
    if transform == 0 then
        return nil
    end
    call(sym("CIsTransform::UpdateWorld"), transform)
    return {x = game.read("f32", transform + WORLD_POSITION),
            y = game.read("f32", transform + WORLD_POSITION + 4),
            z = game.read("f32", transform + WORLD_POSITION + 8)}
end

--- Moves it to a position.
function Effect:move(position)
    local transform = self:alive() and self:transform() or 0
    if transform == 0 then
        return false
    end
    local x, y, z = vec(position)
    game.write("f32", transform + LOCAL_POSITION, x)
    game.write("f32", transform + LOCAL_POSITION + 4, y)
    game.write("f32", transform + LOCAL_POSITION + 8, z)
    call(sym("Transform_SetDirty"), transform)
    return true
end

local function send(self, name)
    local projectile = self:projectile()
    call(sym("CIsSubject::NotifyVirtual"), projectile + SUBJECT, hash.name(EVENTS[name]), 0, 0, 0)
    if name == "open" then
        self.opened = true
        if self.wanted_ms and game.read("u8", projectile + OPEN) == 0 then
            opening[self] = self.wanted_ms      -- it opens a frame later: its lifetime then
        end
    end
end

--- Sends a trigger: "open" (a black hole opens now), "explode". A projectile still being set up
--- gets it as soon as it is. Returns false when it does not answer that trigger or is gone.
function Effect:trigger(name)
    if not EVENTS[name] or not self:alive() or self:projectile() == 0 then
        return false
    end
    if self:ready() then
        send(self, name)
    else
        self.wanted_trigger = name
        waiting[self] = waiting[self] or SETUP_FRAMES
    end
    return true
end

--- Shows or hides its own model (a projectile's behaviour and the effects it spawns stay).
function Effect:set_visible(visible)
    if not self:alive() then
        return false
    end
    local find = game.symbol("CIsComponentTableBase::Find")
    local model = find and call(find, sym("CIsRenderableModel::s_table"), self.id) or 0
    if model == 0 then
        return false
    end
    call(sym("CIsRenderableModel::SetVisible"), model, visible and 1 or 0)
    return true
end

function Effect:hide()
    return self:set_visible(false)
end

function Effect:show()
    return self:set_visible(true)
end

--- Stops a projectile where it is (it no longer falls or rolls), once the game has set it up.
function Effect:freeze()
    if not self:ready() then
        self.wanted_freeze = true
        waiting[self] = waiting[self] or SETUP_FRAMES
        return true
    end
    local projectile = self:projectile()
    local rigid = projectile ~= 0 and call(sym("CIsRigidBody::FromEntity"), self.entity) or 0
    if rigid == 0 or game.read("u32", projectile + RIGID) ~= rigid then
        return false
    end
    local body = game.read("u32", rigid + BULLET_BODY)
    if body == 0 then
        return false
    end
    call(sym("Physics_SetActivation"), body, 2)
    return true
end

-- A projectile floating cm above the floor reaches that much further: zombies walk under it, and
-- the kill check measures from its centre in 3D.
local function reach_down(self, cm)
    local projectile = self:projectile()
    local radius = game.read("f32", projectile + KILL_RADIUS) * 100
    game.write("f32", projectile + KILL_RADIUS, math.sqrt(radius * radius + cm * cm) / 100)
end

local function give_lifetime(self, ms)
    local projectile = self:projectile()
    game.write("u32", projectile + LIFETIME, ms)
    game.write("u8", projectile + HAS_LIFETIME, 1)
    if self.opened and game.read("u8", projectile + OPEN) == 0 then
        opening[self] = ms          -- opening resets its lifetime: given again once open
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
    elseif self:ready() then
        self.wanted_ms = ms
        give_lifetime(self, ms)
    else
        self.wanted_ms = ms
        waiting[self] = waiting[self] or SETUP_FRAMES
    end
    return self
end

--- Removes it now (a projectile ends the game's way).
function Effect:remove()
    timed[self], opening[self], waiting[self] = nil, nil, nil
    if not self:alive() then
        return
    end
    local projectile = self:projectile()
    if projectile ~= 0 and self:ready() then
        call(sym("CIsSubject::NotifyVirtual"), projectile + SUBJECT, hash.name("SUBJECT_TERMINATE"), 0, 0, 0)
    else
        local db = game.read("u32", sym("CIsEntityDB::s_instance"))
        call(sym("EntityDB_Destroy"), db, self.entity, 0)
    end
end

-- What a projectile was asked for, once the game has set it up.
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

local function spawn_entity(name, position, options)
    options = options or {}
    local manager = game.read("u32", sym("CSpawnManager::s_instance"))
    if manager == 0 then
        return nil, "not in a match"
    end
    local at = buffer()
    local x, y, z = vec(position)
    local rotation = options.rotation or {0, 0, 0, 1}
    for i, value in ipairs({x, y + (options.lift or 0), z, 0}) do
        game.write("f32", at + 4 * (i - 1), value)
    end
    -- The game's quaternions keep the scalar first (s, x, y, z).
    local values = {rotation.w or rotation[4] or 1, rotation.x or rotation[1] or 0,
                    rotation.y or rotation[2] or 0, rotation.z or rotation[3] or 0}
    for i, value in ipairs(values) do
        game.write("f32", at + 16 + 4 * (i - 1), value)
    end
    -- Spawn_ByHash(manager, hash, position, rotation, name, parent, named): name 0 makes up a
    -- unique one, parent 0 puts it in the world on its own (the 7th only matters with a name).
    local entity = call(sym("Spawn_ByHash"), manager, hash_of(name), at, at + 16, 0, 0)
    if entity == 0 then
        return nil, "the map has no effect " .. tostring(name) ..
            " (name it in the Effects tab, or name it in a script so the build brings it)"
    end
    if call(sym("CIsTransform::FromEntity"), entity) == 0 then
        -- A part of another effect (no position of its own): drawing it would crash the game.
        local db = game.read("u32", sym("CIsEntityDB::s_instance"))
        call(sym("EntityDB_Destroy"), db, entity, 0)
        return nil, tostring(name) .. " is a part of another effect and cannot be spawned on its own"
    end
    return make(entity, name)
end

local function spawn(name, position, options)
    local effect, err = spawn_entity(name, position, options)
    if not effect then
        log("boz.effects: " .. tostring(err))
    end
    return effect, err
end

--- Spawns an effect at a position {x, y, z}. Options: rotation {x, y, z, w}, lifetime (seconds,
--- then it is removed). Returns the effect, or nil and why.
function effects.spawn(name, position, options)
    local effect, err = spawn(name, position, options)
    if effect and options and options.lifetime then
        timed[effect] = options.lifetime
    end
    return effect, err
end

--- Spawns a projectile at a position and lets the game run it. Options: trigger (e.g. "open"),
--- lifetime (seconds; after a trigger), raise (centimetres: it floats that far above the position,
--- and a black hole's kill reach grows to match, so zombies walking under it still die; for one
--- that "Stays where spawned"), hidden (its own model is not drawn), freeze (stay where spawned
--- instead of settling on the floor), lift (centimetres up, default 10; raise replaces it),
--- rotation. It is the player's (its kills too; zombies turning to
--- a device ask for its owner, so it always has one). What it was asked for happens once the game
--- has set it up (a frame or so). Returns the projectile, or nil and why.
function effects.projectile(name, position, options)
    options = options or {}
    local lift = options.raise or options.lift or 10
    local effect, err = spawn(name, position, {rotation = options.rotation, lift = lift})
    if not effect then
        return nil, err
    end
    if effect:projectile() == 0 then
        effect:remove()
        log("boz.effects: " .. tostring(name) .. " is not a projectile")
        return nil, tostring(name) .. " is not a projectile"
    end
    -- The owner and spec go in right away, as ProjectileManager_Launch does: zombies turning to
    -- a device read its owner (CIsEntityDB::GetEntity of +0x88) from the first frame.
    local projectile = effect:projectile()
    local level = game.read("u32", sym("CLevelManager::s_instance"))
    local player = level ~= 0 and game.read("u32", level + 0x1a0) or 0
    if player == 0 then
        effect:remove()
        return nil, "no player to own it"
    end
    game.write("u32", projectile + OWNER, player)
    game.write("u32", projectile + SPEC, hash_of(name))
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
--- min_damage (at the edge), kind ("frag", the default, "raygun", "claymore", "monkey"),
--- quiet (no explosion effect). Returns the explosion's projectile, or nil and why.
function effects.explode(position, options)
    options = options or {}
    local spec = EXPLOSIONS[options.kind or "frag"] or options.kind
    local blast, err = effects.projectile(spec, position, {hidden = true, freeze = true, lift = 0})
    if not blast then
        return nil, err
    end
    local explosion = require("boz.entities").component(blast.entity, "CExplosion")
    if not explosion then
        blast:remove()
        return nil, tostring(spec) .. " does not explode"
    end
    local reflect = require("boz.reflect")
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
        waiting[blast] = waiting[blast] or SETUP_FRAMES
    end
    return blast
end

--- The point the player's crosshair is on {x, y, z} (where a shot lands; up to 100 m away) and
--- whether it is a live zombie; nil outside a match.
function effects.aim()
    local weapons = require("boz.weapons")
    local manager = weapons.manager()
    if not manager then
        return nil
    end
    return {x = game.read("f32", manager + AIM), y = game.read("f32", manager + AIM + 4),
            z = game.read("f32", manager + AIM + 8)}, game.read("u8", manager + AIM_ZOMBIE) ~= 0
end

--- Plays a game sound (its name or hash) at a position.
function effects.sound(name, position)
    local manager = game.read("u32", sym("CIwSoundManager::s_instance"))
    if manager == 0 then
        return false
    end
    local at = buffer()
    local x, y, z = vec(position)
    game.write("i32", at, math.floor(x))
    game.write("i32", at + 4, math.floor(y))
    game.write("i32", at + 8, math.floor(z))
    call(sym("CIwSoundManager::Play"), manager, hash_of(name), at, 0, 0)
    return true
end

events.on("frame", function(dt)
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
    for effect, ms in pairs(opening) do
        if not effect:alive() then
            opening[effect] = nil
        elseif game.read("u8", effect:projectile() + OPEN) ~= 0 then
            game.write("u32", effect:projectile() + LIFETIME, ms)
            opening[effect] = nil
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

return effects
