-- boz.hooks: a map's hook scripts (the Game tab's Hooks list).
--
--   scripts/hooks/<event>.lua returns a function; it runs every time the event happens, with
--   the event's data (see the Game tab or boz.prefabs for each event's data):
--
--     return function(data)
--         log("round " .. data.round)
--     end
--
-- boz.world starts the hooks the build found (world_data.hooks: their event names).

local hooks = {}

local started = {}

--- Starts the hook scripts for these event names (each scripts/hooks/<event>.lua). Returns how
--- many started; a script that fails to load is logged and skipped.
function hooks.start(names)
    local prefabs = require("boz.prefabs")
    local count = 0
    for _, name in ipairs(names or {}) do
        if not started[name] then
            local ok, fn = pcall(require, "hooks." .. name)
            if ok and type(fn) == "function" then
                started[name] = fn
                prefabs.on(name, function(data) fn(data or {}) end)
                count = count + 1
            else
                log("boz.hooks: hooks/" .. name .. ".lua: " ..
                    (ok and "does not return a function" or tostring(fn)))
            end
        end
    end
    return count
end

return hooks
