-- boz.engine.animation: animation state machines and bones of any entity (weapons, arms, map
-- objects, characters).
--
--   local animation = require("boz.engine.animation")
--   animation.play(entity, "charge")              -- a state of its state machine, by name
--   animation.state(entity)                        -- the state it is in (name hash)
--   animation.bone_position(entity, "tag_flash")   -- where a bone is in the world
--   animation.on_play(function(machine, state) return "my_reload" end)  -- swap a state
--
-- An entity's CIsASMAnimator runs up to two state machine instances; a state plays its clips
-- and its events move on (back to idle when a one-shot clip ends). Your weapon's extra clips are
-- states of its own state machines (the Weapons tab's animation tools add them).
--
-- game: ASM_FindState, ASM_SetState, Skel_FindBone, CIsBoneAttachment

local animation = {}

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")
local entities = require("boz.engine.entities")
local components = require("boz.engine.components")

local INSTANCES = {core.offset("CIsASMAnimator", "instance"), core.offset("CIsASMAnimator", "layer")}
local MACHINE, STATE = core.offset("ASMInstance", "stateMachine"), core.offset("ASMInstance", "state")
local MACHINE_HASH = core.offset("CIsAnimStateMachine", "hash")
local STATE_HASH = core.offset("CIsAnimState", "hash")
local SKELETON = core.offset("CIsAnimator", "skeleton")
local BONE_POSITION = core.offset("CIwAnimBone", "position")
local BONES = core.offset("AnimSkeleton", "bones")
local STATES = core.offset("CIsAnimStateMachine", "states")
local DEFAULT_STATE = core.offset("CIsAnimStateMachine", "defaultState")
local WORLD_AXES = core.offset("CIsTransform", "worldAxes")
local WORLD_POSITION = core.offset("CIsTransform", "worldPosition")
local TOTAL_TIME = core.offset("CIsDirector", "totalTime")
local MISSING = 65535      -- ASM_FindState: no such state
local ONE = 4096

-- The running state machine instances of an animator component: {instance, machine} each.
local function instances_of(animator)
    local out = {}
    for _, offset in ipairs(INSTANCES) do
        local instance = animator + offset
        local machine = game.read("ptr", instance + MACHINE)
        if machine and machine ~= 0 then
            out[#out + 1] = {instance = instance, machine = machine}
        end
    end
    return out
end

--- The state machine instances of an entity ({instance, machine} each; none: {}).
function animation.instances(entity)
    local animator = entity and entities.component(entity, "CIsASMAnimator")
    return animator and instances_of(animator) or {}
end

local function now()
    return game.read("u32", core.sym("g_director") + TOTAL_TIME)
end

local function go(instance, machine, state, blend)
    local index = core.call("ASM_FindState", machine, hash.of(state)) & MISSING
    if index == MISSING then
        return false
    end
    core.call("ASM_SetState", instance, now(), index, math.floor((blend or 0) * ONE))
    return true
end

--- Plays a state of an entity's state machines ("charge", "reloading", ...; blend: seconds of
--- cross-fade). True when one of them has that state.
function animation.play(entity, state, blend)
    local played = false
    for _, run in ipairs(animation.instances(entity)) do
        played = go(run.instance, run.machine, state, blend) or played
    end
    return played
end

--- Sends state machines named in `machines` (or every one of `entity`) back to the state they
--- start in (idle). True when one went.
function animation.stop(machines, entity)
    local wanted = {}
    for _, name in ipairs(machines or {}) do
        wanted[hash.of(name)] = true
    end
    local done = false
    local function back(run)
        local index = game.read("i16", run.machine + DEFAULT_STATE)
        if index and index >= 0 then
            core.call("ASM_SetState", run.instance, now(), index, 0)
            done = true
        end
    end
    if entity then
        for _, run in ipairs(animation.instances(entity)) do back(run) end
        return done
    end
    for animator in components.each("CIsASMAnimator") do
        for _, run in ipairs(instances_of(animator)) do
            if wanted[game.read("u32", run.machine + MACHINE_HASH)] then back(run) end
        end
    end
    return done
end

--- Plays a state on every running state machine named in `machines` (names or hashes): a
--- weapon's are "<weapon>_gun" and "<weapon>_arms". True when one of them has the state.
function animation.play_machines(machines, state, blend)
    local wanted = {}
    for _, name in ipairs(machines) do
        wanted[hash.of(name)] = true
    end
    local played = false
    for animator in components.each("CIsASMAnimator") do
        for _, run in ipairs(instances_of(animator)) do
            if wanted[game.read("u32", run.machine + MACHINE_HASH)] then
                played = go(run.instance, run.machine, state, blend) or played
            end
        end
    end
    return played
end

--- The state an entity's main state machine is in (its name hash), or nil.
function animation.state(entity)
    local run = animation.instances(entity)[1]
    local state = run and game.read("ptr", run.instance + STATE)
    return state and state ~= 0 and game.read("u32", state + STATE_HASH) or nil
end

--- The entity running a state machine (by name or hash), or nil: a weapon's gun or arms.
function animation.entity_running(machine_name)
    local wanted = hash.of(machine_name)
    for animator in components.each("CIsASMAnimator") do
        for _, run in ipairs(instances_of(animator)) do
            if game.read("u32", run.machine + MACHINE_HASH) == wanted then
                return entities.of_component(animator)
            end
        end
    end
    return nil
end

local function parent_of(entity)
    local hierarchy = entities.component(entity, "CIsHierarchy")
    local parent = hierarchy and game.read("ptr", hierarchy + core.offset("CIsHierarchy", "parent"))
    return parent and parent ~= 0 and game.read("ptr", parent + core.offset("CIsComponent", "entity")) or nil
end

--- The gun in the player's hands: the animated entity hanging under the arms (the arms run a
--- state machine; the gun model, its skeleton and bones are their child). nil outside a match.
function animation.view_model()
    for animator in components.each("CIsAnimator") do
        local entity = entities.of_component(animator)
        local parent = parent_of(entity)
        if parent and entities.component(parent, "CIsASMAnimator") then
            return entity
        end
    end
    return nil
end

--- Where a bone of an animated entity is in the world ({x, y, z}), or nil.
function animation.bone_position(entity, bone)
    local animator = entity and entities.component(entity, "CIsAnimator")
    local skeleton = animator and game.read("ptr", animator + SKELETON)
    if not skeleton or skeleton == 0 then
        return nil
    end
    local found = core.call("Skel_FindBone", skeleton + BONES, hash.of(bone))
    local transform = entities.component(entity, "CIsTransform")
    if found == 0 or not transform then
        return nil
    end
    core.call("CIsTransform::UpdateWorld", transform)
    local at = found + BONE_POSITION
    local bx, by, bz = game.read("i32", at), game.read("i32", at + 4), game.read("i32", at + 8)
    local axes = transform + WORLD_AXES
    local origin = core.read_vec3(transform + WORLD_POSITION)
    local function axis(i)
        return game.read("f32", axes + i * 12), game.read("f32", axes + i * 12 + 4), game.read("f32", axes + i * 12 + 8)
    end
    local ax, ay, az = axis(0)
    local cx, cy, cz = axis(1)
    local dx, dy, dz = axis(2)
    return {x = origin.x + bx * ax + by * cx + bz * dx,
            y = origin.y + bx * ay + by * cy + bz * dy,
            z = origin.z + bx * az + by * cz + bz * dz}
end

local swaps, hooked = {}, false

--- Calls fn(machine hash, state hash) whenever a state machine is about to play a state; fn
--- may return another state's name to play that instead (when the machine has it). Returns fn.
function animation.on_play(fn)
    table.insert(swaps, fn)
    if not hooked then
        hooked = true
        hook.add(core.sym("ASM_SetState"), {before = function(call)
            local instance, index = call:arg(1), call:arg(3)
            local machine = game.read("ptr", instance + MACHINE)
            if not machine or machine == 0 then
                return
            end
            local states = game.read("ptr", machine + STATES)
            local state = states and game.read("ptr", states + index * 4)
            local name = state and state ~= 0 and game.read("u32", state + STATE_HASH)
            if not name then
                return
            end
            for _, swap in ipairs(swaps) do
                local ok, other = pcall(swap, game.read("u32", machine + MACHINE_HASH), name)
                if ok and other then
                    local replacement = core.call("ASM_FindState", machine, hash.of(other)) & MISSING
                    if replacement ~= MISSING then
                        call:set_arg(3, replacement)
                        return
                    end
                end
            end
        end})
    end
    return fn
end

return animation
