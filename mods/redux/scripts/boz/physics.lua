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

local FALLBACK = {["Physics_RayCastAll"] = 0x126a78 + 1, ["operator_new_cpp"] = 0x016772 + 1,
                  ["operator_delete_cpp"] = 0x34a4c0}
local NODE_SIZE = 0x30      -- next, previous and the hit (position, normal, entity, shape, distance, material)
local DEFAULT_FILTER = 0xffffffef

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local buffer = nil

local function write_vec(at, v)
    game.write("f32", at, v.x or v[1] or 0)
    game.write("f32", at + 4, v.y or v[2] or 0)
    game.write("f32", at + 8, v.z or v[3] or 0)
end

local function read_vec(at)
    return {x = game.read("f32", at), y = game.read("f32", at + 4), z = game.read("f32", at + 8)}
end

--- Every hit of a ray from `from` to `to`, nearest first: {{position, normal, entity}, ...}.
function physics.raycast_all(from, to, filter)
    buffer = buffer or game.alloc(64)
    write_vec(buffer, from)
    write_vec(buffer + 12, to)
    -- An STLport list: the list object (+24) points at a sentinel node from the game's own
    -- allocator (sorting swaps sentinels with temporary lists, which free theirs).
    local list = buffer + 24
    local sentinel = (game.call(sym("operator_new_cpp"), NODE_SIZE) or 0) & 0xffffffff
    if sentinel == 0 then
        return {}
    end
    game.write("u32", sentinel, sentinel)
    game.write("u32", sentinel + 4, sentinel)
    game.write("u32", list, sentinel)
    game.call(sym("Physics_RayCastAll"), buffer, buffer + 12, list, filter or DEFAULT_FILTER, 0xffffffff)
    sentinel = game.read("ptr", list)
    local hits, node, guard = {}, game.read("ptr", sentinel), 0
    while node ~= sentinel and node ~= 0 and guard < 256 do
        local entity = game.read("ptr", node + 0x20)
        table.insert(hits, {position = read_vec(node + 8), normal = read_vec(node + 0x14),
                            entity = entity ~= 0 and entity or nil})
        local next_node = game.read("ptr", node)
        game.call(sym("operator_delete_cpp"), node)
        node, guard = next_node, guard + 1
    end
    game.call(sym("operator_delete_cpp"), sentinel)
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
