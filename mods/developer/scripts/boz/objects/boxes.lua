-- Turned boxes (a zone's or sector's, from world_data): {position, rotation, size}, centimetres.

local boxes = {}

-- v turned by the quaternion q {x, y, z, w}.
local function rotate(q, v)
    local x, y, z, w = q[1], q[2], q[3], q[4]
    local tx = 2 * (y * v[3] - z * v[2])
    local ty = 2 * (z * v[1] - x * v[3])
    local tz = 2 * (x * v[2] - y * v[1])
    return {v[1] + w * tx + (y * tz - z * ty),
            v[2] + w * ty + (z * tx - x * tz),
            v[3] + w * tz + (x * ty - y * tx)}
end

--- A position {x, y, z} of a target: a position, or anything with :position().
function boxes.point(target)
    if type(target) == "table" and type(target.position) == "function" then
        return target:position()
    end
    return target
end

--- True when the point is inside the box.
function boxes.contains(box, point)
    if not point then
        return false
    end
    local q = box.rotation
    local local_point = rotate({-q[1], -q[2], -q[3], q[4]}, {point.x - box.position[1],
                                                             point.y - box.position[2],
                                                             point.z - box.position[3]})
    for i = 1, 3 do
        if math.abs(local_point[i]) > box.size[i] / 2 then
            return false
        end
    end
    return true
end

--- The middle of a box {x, y, z}.
function boxes.centre(box)
    return {x = box.position[1], y = box.position[2], z = box.position[3]}
end

return boxes
