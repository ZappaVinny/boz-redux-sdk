-- boz.entities: any entity of the game: find, spawn, move, inspect and remove.
--
--   local entities = require("boz.entities")
--   local box = entities.find("MysteryBox_Lobby")
--   print(entities.position(box).x, table.concat(entities.components(box), ", "))
--   local zombie = entities.spawn("zombie_dog", {x = 0, y = 220, z = 0})
--   for entity, health in entities.each("CHealth") do ... end
--   entities.remove(zombie)
--
-- An entity is the game's object: an id (+4), a name, and components (one per class: CIsTransform
-- for its place, CHealth, CAIControllerZombie, CPerk, ...) kept in one table per class (T::s_table,
-- keyed by the entity id). boz.reflect reads and writes any component's fields by name.
--
-- How it works: CIsEntityDB::FindEntity(name hash) finds one by name (a global map); Spawn_ByHash creates
-- one from any loaded entity spec (CIsEntitySpec, by name or hash) at a position and rotation;
-- EntityDB_Destroy removes one (with its children, at the end of the frame); a component's entity
-- is at component +0xc; a transform keeps its local position at +0xa8, rotation +0x98 (s x y z: the scalar first)
-- and world position at +0x5c (CIsTransform::UpdateWorld refreshes it, Transform_SetDirty marks a
-- change).

local entities = {}

local core = require("boz.core")
local hash = require("boz.hash")
local components = require("boz.components")

local ENTITY_ID, COMPONENT_ENTITY = 4, 0xc
local LOCAL_POSITION, LOCAL_ROTATION, WORLD_POSITION = 0xa8, 0x98, 0x5c

local function db()
    return core.singleton("CIsEntityDB")
end

--- The entity called `name` (or with that name hash) in the running level, or nil.
function entities.find(name)
    if not db() then
        return nil
    end
    local entity = core.call("CIsEntityDB::FindEntity", hash.of(name))
    return entity ~= 0 and entity or nil
end

--- An entity's id (+4).
function entities.id(entity)
    return game.read("u32", entity + ENTITY_ID)
end

--- The entity's record in the entity database (what Entity_GetNameHash and the managers use),
--- or nil once the entity is gone.
function entities.record(entity)
    local record = core.call("CIsEntityDB::GetEntity", entity)
    return record ~= 0 and record or nil
end

--- True while the entity with this id is in the world (CIsEntityDB::GetEntity only reads the id
--- at +4, so a removed entity's memory is never touched).
function entities.alive(id)
    if not id or id == 0 then
        return false
    end
    local probe = core.scratch("entities.alive", 8)
    game.write("u32", probe + ENTITY_ID, id)
    return core.call("CIsEntityDB::GetEntity", probe) ~= 0
end

--- The hash of an entity's name (the key the score manager and navmesh tags use).
function entities.name_hash(entity)
    local record = entities.record(entity)
    return record and core.call("Entity_GetNameHash", record) or nil
end

--- The entity a component belongs to.
function entities.of_component(component)
    return game.read("ptr", component + COMPONENT_ENTITY)
end

--- True when an entity spec (name or hash) is in a loaded group, so it can spawn
--- (Spawn_FindSpec).
function entities.spec_loaded(spec)
    return core.call("Spawn_FindSpec", hash.of(spec), 2) ~= 0
end

--- Spawns an entity spec (its name, "0x..." hash or hash) at a position {x, y, z} with a
--- rotation {x, y, z, w} (default none). Returns the entity, or nil and why (the spec must be
--- in a loaded group: a map project's build brings every spec its scripts name).
function entities.spawn(spec, position, rotation)
    local manager = core.singleton("CSpawnManager")
    if not manager then
        return nil, "not in a match"
    end
    local at = core.scratch("entities.spawn", 32)
    core.write_vec3(at, position)
    core.write_quat(at + 16, rotation)
    -- Spawn_ByHash(manager, hash, position, rotation, name, parent): name 0 makes up a unique
    -- one, parent 0 puts it in the world on its own.
    local entity = core.call("Spawn_ByHash", manager, hash.of(spec), at, at + 16, 0, 0)
    if entity == 0 then
        return nil, "no loaded entity spec " .. tostring(spec)
    end
    return entity
end

--- Removes an entity (and its children) at the end of the frame.
function entities.remove(entity)
    local database = db()
    if database and entity and entity ~= 0 then
        core.call("EntityDB_Destroy", database, entity, 0)
    end
end

local function transform(entity)
    local t = core.call("CIsTransform::FromEntity", entity)
    return t ~= 0 and t or nil
end

--- The entity's world position {x, y, z} (game centimetres, y up), or nil without a transform.
function entities.position(entity)
    local t = transform(entity)
    if not t then
        return nil
    end
    core.call("CIsTransform::UpdateWorld", t)
    return core.read_vec3(t + WORLD_POSITION)
end

--- Moves the entity (its local position: the world position for an entity without a parent).
function entities.set_position(entity, position)
    local t = transform(entity)
    if not t then
        return false
    end
    core.write_vec3(t + LOCAL_POSITION, position)
    core.call("Transform_SetDirty", t)
    return true
end

--- The entity's rotation {x, y, z, w} (a quaternion), or nil.
function entities.rotation(entity)
    local t = transform(entity)
    if not t then
        return nil
    end
    return core.read_quat(t + LOCAL_ROTATION)
end

--- Turns the entity: a quaternion {x, y, z, w}, or a number (degrees about the vertical axis).
function entities.set_rotation(entity, rotation)
    local t = transform(entity)
    if not t then
        return false
    end
    if type(rotation) == "number" then
        local half = math.rad(rotation) / 2
        rotation = {0, math.sin(half), 0, math.cos(half)}
    end
    core.write_quat(t + LOCAL_ROTATION, rotation)
    core.call("Transform_SetDirty", t)
    return true
end

--- Shows or hides the entity's own model (CIsRenderableModel::SetVisible: its collision and
--- behaviour stay). Returns false when it has no model.
function entities.set_visible(entity, visible)
    local model = entities.component(entity, "CIsRenderableModel")
    if not model then
        return false
    end
    core.call("CIsRenderableModel::SetVisible", model, visible and 1 or 0)
    return true
end

--- The entity's component of a class ("CHealth", "CPerk", ...), or nil.
function entities.component(entity, class_name)
    return components.find(class_name, entities.id(entity))
end

--- The classes of the components an entity has (that the library knows a table for).
function entities.components(entity)
    local out = {}
    local id = entities.id(entity)
    for class_name in pairs(require("boz.symbol_data").tables) do
        if components.find(class_name, id) then
            table.insert(out, class_name)
        end
    end
    table.sort(out)
    return out
end

--- Iterates the entities with a component of a class: for entity, component in each("CHealth").
function entities.each(class_name)
    local iterate = components.each(class_name)
    return function()
        local component = iterate()
        if component then
            return entities.of_component(component), component
        end
        return nil
    end
end

--- Sends an event (a name such as "SUBJECT_SPAWNPOINT_ACTIVATE", or an id) to one entity, the way
--- hits and uses reach it (CIsBroadcaster::Send on its broadcaster). Returns false when the entity
--- has no broadcaster.
function entities.send(entity, event, a, b)
    local broadcaster = core.call("CIsBroadcaster::FromEntity", entity)
    if broadcaster == 0 then
        return false
    end
    local id = require("boz.game_events").id(event)
    core.call("CIsBroadcaster::Send", broadcaster, id, a or 0, b or 0, 0, 0)
    return true
end

--- The nearest entity with a component of a class to a position, its component and distance.
function entities.nearest(class_name, position)
    local best, best_component, best_distance = nil, nil, math.huge
    for entity, component in entities.each(class_name) do
        local at = entities.position(entity)
        if at then
            local d = math.sqrt((at.x - position.x) ^ 2 + (at.y - position.y) ^ 2 + (at.z - position.z) ^ 2)
            if d < best_distance then
                best, best_component, best_distance = entity, component, d
            end
        end
    end
    return best, best_component, best ~= nil and best_distance or nil
end

return entities
