-- boz.engine.spawns: the zombies' spawn points (Zombies mode).
--
--   for point in spawns.each() do log(point:position().x) end
--   spawns.set_active(point, false)          zombies stop coming out there
--   spawns.nearest(position)
--
-- A spawn point handle: point.entity, point.component, point:position(), point:get(field) (CSpawnPoint:
-- m_StartActive, spawntype, users), point:active(), point:set_active(on), point:free().
--
-- game: SpawnManager_SetPoint, SpawnManager_HasPoint, CSpawnPoint::OnEvent

local spawns = {}

local entities = require("boz.engine.entities")
local reflect = require("boz.engine.reflect")

local ACTIVE = 0x34       -- free: SUBJECT_SPAWNPOINT_ACTIVATE / DEACTIVATE (CSpawnPoint::OnEvent)
local USERS = 0x2c        -- the AI configs allowed to spawn here

local Point = {}
Point.__index = Point

local function make(entity, component)
    return setmetatable({entity = entity, component = component}, Point)
end

--- Its position {x, y, z}.
function Point:position()
    return entities.position(self.entity)
end

--- A field of its CSpawnPoint.
function Point:get(field)
    return reflect.get(self.component, "CSpawnPoint", field)
end

-- The AI configs allowed to spawn here (CSpawnPoint users: a list of name hashes).
local function users(self)
    local out, head = {}, game.read("ptr", self.component + USERS)
    local node = head ~= 0 and game.read("ptr", head) or 0
    while node ~= 0 and node ~= head and #out < 16 do
        out[#out + 1] = game.read("u32", node + 8)
        node = game.read("ptr", node)
    end
    return out
end

--- True while zombies can come out here: its zone is open, or a script switched it on.
function Point:active()
    local core = require("boz.engine.core")
    local manager = core.singleton("CSpawnManager")
    if not manager then
        return false
    end
    local name = entities.name_hash(self.entity)
    for _, user in ipairs(users(self)) do
        if core.call("SpawnManager_HasPoint", manager, name, user) ~= 0 then
            return true
        end
    end
    return false
end

--- True while no zombie is coming out of it.
function Point:free()
    return game.read("u8", self.component + ACTIVE) ~= 0
end

--- Lets zombies come out here (true) or not (false), even in a zone not open yet.
function Point:set_active(on)
    local manager = require("boz.engine.core").singleton("CSpawnManager")
    if manager then
        -- The game picks from the points it was given (SpawnManager_PickPoint): the flag alone
        -- does nothing for a point it never had.
        require("boz.engine.core").call("SpawnManager_SetPoint", manager,
                                        entities.name_hash(self.entity), on and 1 or 0)
    end
    game.write("u8", self.component + ACTIVE, on and 1 or 0)
    return true
end

--- Iterates the spawn points: for point in spawns.each() do ... end
function spawns.each()
    local iterate = entities.each("CSpawnPoint")
    return function()
        local entity, component = iterate()
        if entity then
            return make(entity, component)
        end
        return nil
    end
end

--- The spawn points zombies can come out of now.
function spawns.active()
    local out = {}
    for point in spawns.each() do
        if point:active() then
            table.insert(out, point)
        end
    end
    return out
end

--- Every spawn point, as a list.
function spawns.list()
    local out = {}
    for point in spawns.each() do
        table.insert(out, point)
    end
    return out
end

--- The spawn point handle of an entity.
function spawns.point(entity)
    return make(entity, entities.component(entity, "CSpawnPoint"))
end

--- Switches a spawn point (a handle or entity) on or off.
function spawns.set_active(point, on)
    if type(point) == "number" then
        point = spawns.point(point)
    end
    return point:set_active(on)
end

--- The spawn point nearest a position and its distance.
function spawns.nearest(position)
    local entity, component, distance = entities.nearest("CSpawnPoint", position)
    return entity and make(entity, component) or nil, distance
end

return spawns
