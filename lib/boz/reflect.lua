-- boz.reflect: every reflected field of the game, by name.
--
--   local reflect = require("boz.reflect")
--   local perk = reflect.component(entity, "CPerk")       -- or an entity id, or an object handle
--   print(reflect.get(perk, "CPerk", "m_perkSinglePCost"))
--   reflect.set(perk, "CPerk", "m_perkSinglePCost", 500)
--   local waves = reflect.singleton("CWaveManager")      -- managers by class name
--   for name, value in pairs(reflect.dump(perk, "CPerk")) do print(name, value) end
--
-- The game describes its components and resources to its own reflection system (CIsClassInfo:
-- 359 classes, their bases and fields with offset, size and type); boz/reflection_data.lua holds
-- that description (tools/stdlib_data.py, from the game definition). docs/toolkit-fields.md
-- explains what the fields do.
--
-- Types read: unsigned int, int, short, char, unsigned char, bool, float, CIwFVec3 {x, y, z},
-- CIwFQuat {x, y, z, w}, CIwColour {r, g, b, a}, string (std::string: its characters' pointer
-- first), NetworkProperty<T> (the value at +4; writing marks it changed at +8), vector<T> (begin,
-- end), list<T> (header pointer; nodes: next, previous, value at +8), enums (unsigned int),
-- CIsTimer, bitset (raw bits). Containers and strings are read-only.

local reflect = {}

local classes = require("boz.reflection_data")

local SCALAR = {
    ["unsigned int"] = "u32", int = "i32", short = "i16", ["unsigned short"] = "u16",
    char = "i8", ["unsigned char"] = "u8", float = "f32", CIsTimer = "u32",
}

--- The class description {bases = {{name, offset}}, fields = {[name] = {offset, size, type}}},
--- or nil.
function reflect.class(name)
    return classes[name]
end

--- Every reflected class name, sorted.
function reflect.classes()
    local out = {}
    for name in pairs(classes) do
        table.insert(out, name)
    end
    table.sort(out)
    return out
end

-- A field of a class or one of its bases: offset (from the object), size, type.
local function find_field(class_name, field, base_offset, seen)
    local info = classes[class_name]
    seen = seen or {}
    if not info or seen[class_name] then
        return nil
    end
    seen[class_name] = true
    local own = info.fields[field]
    if own then
        return base_offset + own[1], own[2], own[3]
    end
    for _, base in ipairs(info.bases) do
        local offset, size, kind = find_field(base[1], field, base_offset + (base[2] or 0), seen)
        if offset then
            return offset, size, kind
        end
    end
    return nil
end

--- Every field of a class with its bases' fields: {[name] = {offset, size, type, class}}.
function reflect.fields(class_name)
    local out = {}
    local function walk(name, offset, seen)
        local info = classes[name]
        if not info or seen[name] then
            return
        end
        seen[name] = true
        for _, base in ipairs(info.bases) do
            walk(base[1], offset + (base[2] or 0), seen)
        end
        for field, f in pairs(info.fields) do
            out[field] = {offset + f[1], f[2], f[3], name}
        end
    end
    walk(class_name, 0, {})
    return out
end

local function read_value(address, kind, size)
    local scalar = SCALAR[kind]
    if scalar then
        return game.read(scalar, address)
    end
    if kind == "bool" then
        return game.read("u8", address) ~= 0
    end
    if kind:find("^CParsableEnumManager::") then
        return game.read("u32", address)
    end
    if kind == "CIwFVec3" then
        return {x = game.read("f32", address), y = game.read("f32", address + 4), z = game.read("f32", address + 8)}
    end
    if kind == "CIwFQuat" then
        return {x = game.read("f32", address), y = game.read("f32", address + 4),
                z = game.read("f32", address + 8), w = game.read("f32", address + 12)}
    end
    if kind == "CIwColour" then
        return {r = game.read("u8", address), g = game.read("u8", address + 1),
                b = game.read("u8", address + 2), a = game.read("u8", address + 3)}
    end
    if kind == "string" then
        local chars = game.read("ptr", address)
        return chars ~= 0 and game.read("string", chars, 256) or ""
    end
    local inner = kind:match("^NetworkProperty<(.+)>$")
    if inner then
        return read_value(address + 4, inner)
    end
    inner = kind:match("^vector<(.+)>$")
    if inner then
        local out = {}
        local first, last = game.read("ptr", address), game.read("ptr", address + 4)
        local step = (inner == "unsigned int" or inner == "int" or inner == "float") and 4 or nil
        if step and first ~= 0 and last >= first and (last - first) // step <= 4096 then
            for at = first, last - step, step do
                table.insert(out, read_value(at, inner))
            end
            return out
        end
        return {first = first, last = last}
    end
    inner = kind:match("^list<(.+)>$")
    if inner then
        local out = {}
        local header = game.read("ptr", address)
        local node = header ~= 0 and game.read("ptr", header) or 0
        local plain = inner == "unsigned int" or inner == "int" or inner == "float" or inner == "string"
        while node ~= 0 and node ~= header and #out < 4096 do
            table.insert(out, plain and read_value(node + 8, inner) or node + 8)
            node = game.read("ptr", node)
        end
        return out
    end
    if kind:find("^bitset") then
        return game.read("u32", address)
    end
    return address        -- other structs: their address, for reflect.get on their own class
end

--- A field's value on an object (a pointer to an instance of the class or a subclass), or nil
--- and why.
function reflect.get(object, class_name, field)
    if not object or object == 0 then
        return nil, "no object"
    end
    local offset, size, kind = find_field(class_name, field, 0)
    if not offset then
        return nil, class_name .. " has no field " .. tostring(field)
    end
    return read_value(object + offset, kind, size)
end

--- Sets a field (numbers, booleans, {x, y, z} vectors, NetworkProperty values). Returns true, or
--- false and why.
function reflect.set(object, class_name, field, value)
    if not object or object == 0 then
        return false, "no object"
    end
    local offset, _, kind = find_field(class_name, field, 0)
    if not offset then
        return false, class_name .. " has no field " .. tostring(field)
    end
    local address = object + offset
    local inner = kind:match("^NetworkProperty<(.+)>$")
    if inner then
        address, kind = address + 4, inner
        game.write("u8", object + offset + 8, 1)      -- changed: sent to the other players
    end
    local scalar = SCALAR[kind] or (kind:find("^CParsableEnumManager::") and "u32")
    if scalar then
        game.write(scalar, address, scalar == "f32" and value or math.floor(value))
    elseif kind == "bool" then
        game.write("u8", address, value and 1 or 0)
    elseif kind == "CIwFVec3" or kind == "CIwFQuat" then
        local keys = kind == "CIwFVec3" and {"x", "y", "z"} or {"x", "y", "z", "w"}
        for i, key in ipairs(keys) do
            game.write("f32", address + 4 * (i - 1), value[key] or value[i] or 0)
        end
    else
        return false, kind .. " fields are read-only"
    end
    return true
end

--- Every field's value: {[field] = value}.
function reflect.dump(object, class_name)
    local out = {}
    for field, f in pairs(reflect.fields(class_name)) do
        out[field] = read_value(object + f[1], f[3], f[2])
    end
    return out
end

local function entity_of(target)
    if type(target) == "table" and target.entity_pointer then
        return target:entity_pointer()
    end
    if type(target) == "table" and target.entity then
        return target.entity
    end
    return target
end

--- The component of class `class_name` on an entity (its pointer, {id = entity id}, or a
--- boz.objects / boz.effects handle), or nil.
function reflect.component(target, class_name)
    local components = require("boz.components")
    if type(target) == "table" and target.id and not target.entity_pointer then
        return components.find(class_name, target.id)
    end
    local entity = entity_of(target)
    if not entity or entity == 0 then
        return nil
    end
    return components.find(class_name, game.read("u32", entity + 4))
end

--- A manager by class name ("CWaveManager", "CPickupManager", ...): its singleton, or nil.
function reflect.singleton(class_name)
    local address = game.symbol(class_name .. "::s_instance")
    if not address then
        local ok, data = pcall(require, "boz.symbol_data")
        local offset = ok and data.singletons[class_name]
        address = offset and game.base() + offset
    end
    if not address then
        return nil
    end
    local instance = game.read("ptr", address)
    return instance ~= 0 and instance or nil
end

--- Every singleton class name the library knows, sorted.
function reflect.singletons()
    local ok, data = pcall(require, "boz.symbol_data")
    local out = {}
    for name in pairs(ok and data.singletons or {}) do
        table.insert(out, name)
    end
    table.sort(out)
    return out
end

return reflect
