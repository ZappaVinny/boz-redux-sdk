-- boz.saved: Lua tables kept in the mod's settings (saves/mods/<id>.cfg).
--
--   local saved = require("boz.saved")
--   saved.write("progress.kino", {round = 12, parts = {"plug", "fuse"}})
--   local progress = saved.read("progress.kino")
--
-- Numbers, strings, booleans and tables of those are kept; functions, handles and loops are left
-- out. Tables are stored as Lua table text in chunks (a settings line holds up to 4 KB).

local saved = {}

local CHUNK = 3000

--- A copy of a value with only what can be saved (nil when nothing can).
function saved.saveable(value, seen, depth)
    seen, depth = seen or {}, depth or 0
    local kind = type(value)
    if kind == "number" or kind == "string" or kind == "boolean" then
        return value
    end
    if kind ~= "table" or getmetatable(value) ~= nil or seen[value] or depth > 16 then
        return nil
    end
    seen[value] = true
    local copy = {}
    for k, v in pairs(value) do
        local key_kind = type(k)
        if key_kind == "string" or key_kind == "number" then
            local kept = saved.saveable(v, seen, depth + 1)
            if kept ~= nil then
                copy[k] = kept
            end
        end
    end
    seen[value] = nil
    return copy
end

--- A saveable value as Lua text (keys sorted, so the same table gives the same text).
function saved.encode(value)
    local kind = type(value)
    if kind == "table" then
        local keys = {}
        for k in pairs(value) do
            table.insert(keys, k)
        end
        table.sort(keys, function(a, b)
            if type(a) == type(b) then
                return a < b
            end
            return type(a) == "number"
        end)
        local out = {}
        for _, k in ipairs(keys) do
            table.insert(out, "[" .. saved.encode(k) .. "]=" .. saved.encode(value[k]))
        end
        return "{" .. table.concat(out, ",") .. "}"
    elseif kind == "string" then
        return (string.format("%q", value):gsub("\\\n", "\\n"))
    elseif kind == "number" then
        if value ~= value then
            return "(0/0)"
        elseif value == math.huge then
            return "1e999"
        elseif value == -math.huge then
            return "-1e999"
        elseif math.type(value) == "integer" then
            return tostring(value)
        end
        return string.format("%.17g", value)
    end
    return tostring(value)
end

--- The table a text from saved.encode holds, or nil.
function saved.decode(text)
    local chunk = load("return " .. text, "=saved", "t", {})
    if not chunk then
        return nil
    end
    local ok, value = pcall(chunk)
    return ok and type(value) == "table" and value or nil
end

--- Writes a table under a key of the mod's settings.
function saved.write(key, value)
    local text = saved.encode(saved.saveable(value) or {})
    local before = settings.get(key .. ".count", 0)
    local count = 0
    for at = 1, #text, CHUNK do
        count = count + 1
        settings.set(key .. "." .. count, string.sub(text, at, at + CHUNK - 1))
    end
    for i = count + 1, before do
        settings.set(key .. "." .. i, nil)
    end
    settings.set(key .. ".count", count)
end

--- The table written under a key, or nil.
function saved.read(key)
    local parts = {}
    for i = 1, settings.get(key .. ".count", 0) do
        local part = settings.get(key .. "." .. i)
        if type(part) ~= "string" then
            return nil
        end
        table.insert(parts, part)
    end
    return #parts > 0 and saved.decode(table.concat(parts)) or nil
end

return saved
