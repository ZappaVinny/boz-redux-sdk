-- boz.physics: ray casts against the world and everything in it.
--
--   local hit = physics.raycast(from, to)          -- {position, normal, entity} or nil
--   physics.ground(position)                       -- the floor under a position (its y), or nil
--   physics.line_of_sight(a, b)                    -- true when nothing is between two points
--
-- Positions are {x, y, z} in game centimetres (y up). `filter` chooses what the ray can hit
-- (collision groups as bits; default 0xffffffef: everything but triggers, like bullets).
--
-- How it works: Physics_RayCastAll(from, to, outList, filter, mask) casts through the Bullet world
-- (CIsBulletWorld) and fills a list (STLport: the list object points at a sentinel node; nodes link
-- next +0, previous +4) with every hit: node +8
-- position, +0x14 normal, +0x20 entity, +0x24 shape, +0x28 distance squared, +0x2c material, sorted
-- nearest first. Nodes and the sentinel come from the game's operator new and go back to its
-- operator delete (list::sort swaps sentinels, so the list's own must be the game's). Physics_RayCast (nine arguments) is what the game's own code
-- uses for the first hit.

local physics = {}

local core = require("boz.core")

local NODE_SIZE = 0x30      -- next, previous and the hit (position, normal, entity, shape, distance, material)
local DEFAULT_FILTER = 0xffffffef

local buffer = nil


--- Every hit of a ray from `from` to `to`, nearest first: {{position, normal, entity}, ...}.
function physics.raycast_all(from, to, filter)
    buffer = buffer or game.alloc(64)
    core.write_vec3(buffer, from)
    core.write_vec3(buffer + 12, to)
    -- An STLport list: the list object (+24) points at a sentinel node from the game's own
    -- allocator (sorting swaps sentinels with temporary lists, which free theirs).
    local list = buffer + 24
    local sentinel = core.call("operator_new_cpp", NODE_SIZE)
    if sentinel == 0 then
        return {}
    end
    game.write("u32", sentinel, sentinel)
    game.write("u32", sentinel + 4, sentinel)
    game.write("u32", list, sentinel)
    core.call("Physics_RayCastAll", buffer, buffer + 12, list, filter or DEFAULT_FILTER, 0xffffffff)
    sentinel = game.read("ptr", list)
    local hits, node, guard = {}, game.read("ptr", sentinel), 0
    while node ~= sentinel and node ~= 0 and guard < 256 do
        local entity = game.read("ptr", node + 0x20)
        table.insert(hits, {position = core.read_vec3(node + 8), normal = core.read_vec3(node + 0x14),
                            entity = entity ~= 0 and entity or nil})
        local next_node = game.read("ptr", node)
        core.call("operator_delete_cpp", node)
        node, guard = next_node, guard + 1
    end
    core.call("operator_delete_cpp", sentinel)
    return hits         -- the game sorts them nearest first
end

--- Casts a ray from `from` to `to`. Returns {position, normal, entity} of the first hit, or nil.
function physics.raycast(from, to, filter)
    return physics.raycast_all(from, to, filter)[1]
end

--- The floor's height (y) under a position, looking down `depth` centimetres (default 2000).
function physics.ground(position, depth)
    local hit = physics.raycast(position, {x = position.x, y = position.y - (depth or 2000), z = position.z}, 1)
    return hit and hit.position.y or nil
end

--- True when the world blocks nothing between two points.
function physics.line_of_sight(a, b)
    return physics.raycast(a, b, 1) == nil
end

return physics
