-- boz.spawns: the zombies' spawn points (Zombies mode).
--
--   for point in spawns.each() do log(point:position().x) end
--   spawns.set_active(point, false)          zombies stop coming out there
--   spawns.nearest(position)
--
-- A spawn point handle: point.entity, point.component, point:position(), point:get(field) (CSpawnPoint:
-- m_StartActive, spawntype, users), point:active(), point:set_active(on).
--
-- How it works: every spawn point is an entity with a CSpawnPoint; opening an area's door sends its
-- spawn points SUBJECT_SPAWNPOINT_ACTIVATE (DEACTIVATE closes them), which CSpawnPoint::OnEvent
-- turns into the active flag at +0x34; CWaveManager spawns zombies at active points.

local spawns = {}

local entities = require("boz.entities")
local reflect = require("boz.reflect")

local ACTIVE = 0x34       -- set by SUBJECT_SPAWNPOINT_ACTIVATE / DEACTIVATE (CSpawnPoint::OnEvent)

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

--- True while zombies can come out here.
function Point:active()
    return game.read("u8", self.component + ACTIVE) ~= 0
end

--- Lets zombies come out here (true) or not (false).
function Point:set_active(on)
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

--- Switches a spawn point (a handle or entity) on or off.
function spawns.set_active(point, on)
    if type(point) == "number" then
        point = make(point, entities.component(point, "CSpawnPoint"))
    end
    return point:set_active(on)
end

--- The spawn point nearest a position and its distance.
function spawns.nearest(position)
    local entity, component, distance = entities.nearest("CSpawnPoint", position)
    return entity and make(entity, component) or nil, distance
end

return spawns
