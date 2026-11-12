-- boz.engine.check: what the standard library does with an argument it cannot use. It does not
-- stop the script: it logs once where the call is ("boz.on needs a function, at scripts/main.lua:12")
-- and the call does nothing.
--
--   if not check.fn(fn, "boz.on") then return end
--   local n = check.number(points, "give_points"); if not n then return nil end

local check = {}

local warned = {}

-- "scripts/main.lua:12" of the script that called the library (level: how far up).
local function caller(level)
    local _, where = pcall(error, "", level + 3)
    return type(where) == "string" and where:gsub(":%s*$", "") or "?"
end

--- Logs message once per place it comes from.
function check.warn(message, level)
    local where = caller((level or 1) + 1)
    local key = message .. "@" .. where
    if not warned[key] then
        warned[key] = true
        log(message .. (where ~= "" and where ~= "?" and (", at " .. where) or ""))
    end
end

local function shown(value)
    return value == nil and "nothing" or type(value) == "string" and ('"' .. value .. '"') or type(value)
end

--- True for a function; otherwise warns ("<what> needs a function, got nothing").
function check.fn(value, what, level)
    if type(value) == "function" then
        return true
    end
    check.warn(what .. " needs a function, got " .. shown(value), (level or 1) + 1)
    return false
end

--- The value as a number (a numeric string counts); otherwise warns and returns nil.
function check.number(value, what, level)
    local n = tonumber(value)
    if n then
        return n
    end
    check.warn(what .. " needs a number, got " .. shown(value), (level or 1) + 1)
    return nil
end

--- True for a non-empty string; otherwise warns.
function check.name(value, what, level)
    if type(value) == "string" and value ~= "" then
        return true
    end
    check.warn(what .. " needs a name (a string), got " .. shown(value), (level or 1) + 1)
    return false
end

return check
