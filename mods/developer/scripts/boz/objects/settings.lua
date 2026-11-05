-- self.settings: a prefab's settings by name, the panel's and its script's alike. Native ones
-- (a field of the game's: cost, needs power, ...) read and write the running game; a script's
-- own are plain values.

local reflect = require("boz.engine.reflect")

local settings = {}

local LIVE = {int = true, float = true, bool = true, seconds = true}   -- read/write the field

local function field_of(object, spec)
    local class, name = spec.field:match("^([%w_]+)%.([%w_]+)$")
    local entity = class and object._handle:entity_pointer()
    local component = entity and entity ~= 0 and reflect.component(entity, class)
    if not component then
        return nil
    end
    return reflect.object(component, class), class, name
end

local function read(object, spec)
    if spec.field and LIVE[spec.kind] then
        local target, class, name = field_of(object, spec)
        local value = target and reflect.get(target, class, name)
        if value ~= nil then
            return spec.kind == "seconds" and value / 1000 or value
        end
    end
    return spec.value
end

local function write(object, spec, value)
    spec.value = value
    if spec.field and LIVE[spec.kind] then
        local target, class, name = field_of(object, spec)
        if target then
            reflect.set(target, class, name, spec.kind == "seconds" and math.floor(value * 1000) or value)
        end
    end
end

--- The settings table of object, from the map's entry ({name = {value, kind, field}}).
function settings.of(object, specs)
    return setmetatable({}, {
        __index = function(_, key)
            local spec = specs[key]
            return spec and read(object, spec)
        end,
        __newindex = function(_, key, value)
            local spec = specs[key]
            if not spec then
                error(object.name .. " has no setting " .. tostring(key), 2)
            end
            write(object, spec, value)
        end,
        __pairs = function()
            local key
            return function()
                key = next(specs, key)
                if key ~= nil then
                    return key, read(object, specs[key])
                end
            end
        end,
    })
end

return settings
