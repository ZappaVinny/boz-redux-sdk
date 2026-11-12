-- boz.engine.motion: moves and turns map objects while the game runs, at once or gliding over
-- game time. An object moves as one: a prefab of yours with all its parts around the spot it
-- stands on in the editor, any object with its own collision and use prompt. Players standing
-- on a gliding object ride along (held in place, free to look), set down where it stops.
--
--   local motion = require("boz.engine.motion")
--   motion.move(object, {position = {x = 0, y = 300, z = 0}, seconds = 4})
--
-- The walkable area (navmesh) cannot move: an object that blocks walking opens its block once it
-- leaves its start and closes it again when it is back.
--
-- game: CIsTransform, Transform_SetDirty, CPlayerController::PlaceAt

local motion = {}

local core = require("boz.engine.core")
local entities = require("boz.engine.entities")
local objects = require("boz.engine.objects")
local physics = require("boz.engine.physics")
local timers = require("boz.engine.timers")

local RIDE_REACH = 260                  -- how far below the camera a ride's floor may be
local YAW, PITCH = core.offset("CPlayerController", "yaw"), core.offset("CPlayerController", "pitch")

-- Quaternions are {x, y, z, w}, as the build composes them (bozkit.spec_fields).
local function qmul(a, b)
    return {x = a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            y = a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            z = a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
            w = a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z}
end

local function qinv(q)
    return {x = -q.x, y = -q.y, z = -q.z, w = q.w}
end

local function rotate(q, v)
    local x, y, z, w = q.x, q.y, q.z, q.w
    return {x = (1 - 2 * (y * y + z * z)) * v.x + 2 * (x * y - z * w) * v.y + 2 * (x * z + y * w) * v.z,
            y = 2 * (x * y + z * w) * v.x + (1 - 2 * (x * x + z * z)) * v.y + 2 * (y * z - x * w) * v.z,
            z = 2 * (x * z - y * w) * v.x + 2 * (y * z + x * w) * v.y + (1 - 2 * (x * x + y * y)) * v.z}
end

local function slerp(a, b, t)
    local dot = a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w
    if dot < 0 then
        b, dot = {x = -b.x, y = -b.y, z = -b.z, w = -b.w}, -dot
    end
    if dot > 0.9995 then
        local q = {x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t, z = a.z + (b.z - a.z) * t,
                   w = a.w + (b.w - a.w) * t}
        local n = math.sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
        return {x = q.x / n, y = q.y / n, z = q.z / n, w = q.w / n}
    end
    local theta = math.acos(dot)
    local s = math.sin(theta)
    local wa, wb = math.sin((1 - t) * theta) / s, math.sin(t * theta) / s
    return {x = a.x * wa + b.x * wb, y = a.y * wa + b.y * wb, z = a.z * wa + b.z * wb, w = a.w * wa + b.w * wb}
end

--- A rotation from a quaternion ({x, y, z, w} or a list in that order) or degrees about the
--- vertical axis (a number).
function motion.rotation(value)
    if type(value) == "number" then
        local half = math.rad(value) / 2
        return {x = 0, y = math.sin(half), z = 0, w = math.cos(half)}
    end
    if type(value) == "table" then
        return {x = value.x or value[1] or 0, y = value.y or value[2] or 0, z = value.z or value[3] or 0,
                w = value.w or value[4] or 1}
    end
    return nil
end

local function vec(value)
    if type(value) ~= "table" then
        return nil
    end
    local x, y, z = value.x or value[1], value.y or value[2], value.z or value[3]
    if type(x) ~= "number" or type(y) ~= "number" or type(z) ~= "number" then
        return nil
    end
    return {x = x, y = y, z = z}
end
motion.vec = vec

local function transform_of(entity)
    local t = core.call("CIsTransform::FromEntity", entity)
    return t ~= 0 and t or nil
end

-- A group: what moves together, around an origin {position, rotation}.
--   {name, origin, start, parts = {{entity, offset, turn}}, blocking = {names}, displaced}
local groups = {}    -- lower name -> group

local function entity_place(entity)
    local p = entities.position(entity)
    local r = entities.rotation(entity)
    return p and r and {position = p, rotation = {x = r.x, y = r.y, z = r.z, w = r.w}} or nil
end

local function add_part(group, entity)
    if not entity or entity == 0 or group.seen[entity] then
        return
    end
    local place = entity_place(entity)
    if not place then
        return
    end
    group.seen[entity] = true
    local back = qinv(group.origin.rotation)
    local d = {x = place.position.x - group.origin.position.x, y = place.position.y - group.origin.position.y,
               z = place.position.z - group.origin.position.z}
    table.insert(group.parts, {entity = entity, offset = rotate(back, d), turn = qmul(back, place.rotation)})
end

-- The entities of the object called name: its own and its collision's ("<name>_collision").
local function add_named(group, name)
    add_part(group, objects.get(name):entity_pointer())
    add_part(group, objects.get(name .. "_collision"):entity_pointer())
    if objects.starts_blocking(name) then
        table.insert(group.blocking, name)
    end
end

-- origin: where a prefab of yours stands ({position, rotation} from the map), else nil (the
-- object's own entity is the origin). members: its parts' names (a prefab of yours).
local function group_of(name, origin, members)
    local key = string.lower(name)
    local group = groups[key]
    if group and #group.parts > 0 then
        return group
    end
    if not origin then
        origin = entity_place(objects.get(name):entity_pointer())
        if not origin then
            return nil
        end
    end
    origin = {position = vec(origin.position), rotation = motion.rotation(origin.rotation)}
    group = {name = name, origin = origin, parts = {}, blocking = {}, seen = {},
             start = {position = origin.position, rotation = origin.rotation}}
    if members and #members > 0 then
        for _, member in ipairs(members) do
            add_named(group, member)
        end
    else
        add_named(group, name)
    end
    if #group.parts == 0 then
        return nil
    end
    if objects.starts_blocking(name) then
        table.insert(group.blocking, name)
    end
    groups[key] = group
    return group
end

local function at_start(group)
    local p, s = group.origin.position, group.start.position
    local q, r = group.origin.rotation, group.start.rotation
    local moved = math.abs(p.x - s.x) + math.abs(p.y - s.y) + math.abs(p.z - s.z)
    local turned = 1 - math.abs(q.x * r.x + q.y * r.y + q.z * r.z + q.w * r.w)
    return moved < 1 and turned < 1e-5
end

local function place_group(group, position, rotation)
    group.origin = {position = position, rotation = rotation}
    for _, part in ipairs(group.parts) do
        local turned = rotate(rotation, part.offset)
        entities.set_position(part.entity, {x = position.x + turned.x, y = position.y + turned.y,
                                            z = position.z + turned.z})
        entities.set_rotation(part.entity, qmul(rotation, part.turn))
    end
    -- The walkable area stays: leaving the start opens a blocking object's block, coming back
    -- closes it (unless a script switched it in the meantime).
    local displaced = not at_start(group)
    if displaced ~= group.displaced then
        group.displaced = displaced
        for _, name in ipairs(group.blocking) do
            if not objects.is_hidden(name) then
                objects.set_navmesh(name, displaced)
            end
        end
    end
end

-- Riding: the local player, when the floor under them belongs to the group.
local function player_module()
    return require("boz.engine.player")
end

local function standing_on(group)
    local eye = player_module().position()
    if not eye then
        return nil
    end
    -- The first few hits: the player's own body may come before the floor.
    local hits = physics.raycast_all(eye, {x = eye.x, y = eye.y - RIDE_REACH, z = eye.z})
    for i = 1, math.min(#hits, 4) do
        for _, part in ipairs(group.parts) do
            if part.entity == hits[i].entity then
                return eye, eye.y - hits[i].position.y
            end
        end
    end
    return nil
end

local function controller()
    local _, id = require("boz.engine.map").player()
    return id and require("boz.engine.components").find("CPlayerController", id) or nil
end

local function start_ride(group)
    local eye, height = standing_on(group)
    if not eye then
        return nil
    end
    local back = qinv(group.origin.rotation)
    local d = {x = eye.x - group.origin.position.x, y = eye.y - group.origin.position.y,
               z = eye.z - group.origin.position.z}
    local ride = {offset = rotate(back, d), height = height, could_move = player_module().movement()}
    player_module().set_movement(false)
    return ride
end

local function carry(group, ride)
    local turned = rotate(group.origin.rotation, ride.offset)
    local eye = {x = group.origin.position.x + turned.x, y = group.origin.position.y + turned.y,
                 z = group.origin.position.z + turned.z}
    player_module().teleport(eye)
    return eye
end

local function end_ride(group, ride)
    local eye = carry(group, ride)
    local c = controller()
    local yaw, pitch = c and game.read("f32", c + YAW), c and game.read("f32", c + PITCH)
    -- Stand them on the walkable area where the ride stopped (the game finds it again), facing
    -- where they look.
    player_module().place_at({x = eye.x, y = eye.y - ride.height, z = eye.z})
    if c then
        game.write("f32", c + YAW, yaw)
        game.write("f32", c + PITCH, pitch)
    end
    player_module().set_movement(ride.could_move ~= false)
end

-- Glides in progress: group key -> {group, from, to, started, seconds, ride, done}
local glides = {}
local ticking = false

local function finish(key, glide)
    glides[key] = nil
    place_group(glide.group, glide.to.position, glide.to.rotation)
    if glide.ride then
        end_ride(glide.group, glide.ride)
    end
    if glide.done then
        core.safely("boz motion done", glide.done)
    end
end

local function tick()
    local now = timers.now()
    for key, glide in pairs(glides) do
        local t = glide.seconds > 0 and (now - glide.started) / glide.seconds or 1
        if t >= 1 then
            finish(key, glide)
        else
            -- Eased at both ends, as lifts and doors move.
            local e = t * t * (3 - 2 * t)
            local a, b = glide.from.position, glide.to.position
            place_group(glide.group, {x = a.x + (b.x - a.x) * e, y = a.y + (b.y - a.y) * e,
                                      z = a.z + (b.z - a.z) * e},
                        slerp(glide.from.rotation, glide.to.rotation, e))
            if glide.ride then
                carry(glide.group, glide.ride)
            end
        end
    end
    if next(glides) == nil and ticking then
        ticking = false
        events.off("frame", tick)
    end
end

--- Moves the object called name. target: position (a point), rotation (a quaternion or degrees
--- about the vertical axis), seconds (0: at once), ride (players on it ride along; default
--- true), done (called when it arrives); origin and members: a prefab of yours (its place in the
--- map and its parts). Returns false when it is not in the level.
function motion.move(name, target, origin, members)
    local group = group_of(name, origin, members)
    if not group then
        return false
    end
    local key = string.lower(name)
    local running = glides[key]
    if running then
        glides[key] = nil
        if running.ride then
            end_ride(group, running.ride)
        end
    end
    local to = {position = vec(target.position) or group.origin.position,
                rotation = motion.rotation(target.rotation) or group.origin.rotation}
    local seconds = tonumber(target.seconds) or 0
    if seconds <= 0 then
        place_group(group, to.position, to.rotation)
        if target.done then
            core.safely("boz motion done", target.done)
        end
        return true
    end
    glides[key] = {group = group, from = {position = group.origin.position, rotation = group.origin.rotation},
                   to = to, started = timers.now(), seconds = seconds, done = target.done,
                   ride = target.ride ~= false and start_ride(group) or nil}
    if not ticking then
        ticking = true
        events.on("frame", tick)
    end
    return true
end

--- Where the object stands now ({position, rotation}), as motion moves it; nil when it is not
--- in the level.
function motion.place(name, origin, members)
    local group = group_of(name, origin, members)
    return group and {position = group.origin.position, rotation = group.origin.rotation} or nil
end

--- True while it glides.
function motion.moving(name)
    return glides[string.lower(name)] ~= nil
end

--- Stops a glide where it is (done is not called).
function motion.stop(name)
    local key = string.lower(name)
    local glide = glides[key]
    if glide then
        glides[key] = nil
        if glide.ride then
            end_ride(glide.group, glide.ride)
        end
    end
end

--- Forgets every group (a level that starts again builds them anew).
function motion.reset()
    groups, glides = {}, {}
    if ticking then
        ticking = false
        events.off("frame", tick)
    end
end

return motion
