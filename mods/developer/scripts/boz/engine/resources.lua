-- boz.engine.resources: the game's loaded resources (anything in the loaded .group files) by name.
--
--   local wave = resources.find("wave1", "CWave")           -- a round's settings
--   require("boz.engine.reflect").get(wave, "CWave", "m_ZombieCount")
--   resources.find("BOGravity", "CAchievement")              -- an achievement
--   resources.group("ingame")                                -- a loaded group
--
-- game: CIwResManager_GetResNamed, CIwResManager_GetResHashed, CIwResManager_GetGroupNamed

local resources = {}

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")

--- The resource manager, or nil before the game set it up.
function resources.manager()
    local manager = game.read("ptr", core.sym("g_iwResManager"))
    return manager ~= 0 and manager or nil
end

--- A loaded resource by name (or hash, or "0x..." hash) and type, or nil.
function resources.find(name, type_name)
    local manager = resources.manager()
    if not manager then
        return nil
    end
    local found
    if type(name) == "number" or name:lower():find("^0x") then
        found = core.call("CIwResManager_GetResHashed", manager, hash.of(name), type_name, 0)
    else
        found = core.call("CIwResManager_GetResNamed", manager, name, type_name, 0)
    end
    return found ~= 0 and found or nil
end

--- True when a resource of that name and type is loaded.
function resources.loaded(name, type_name)
    return resources.find(name, type_name) ~= nil
end

--- A loaded group by name ("ingame", "kino_statics", ...), or nil.
function resources.group(name)
    local manager = resources.manager()
    if not manager then
        return nil
    end
    local found = core.call("CIwResManager_GetGroupNamed", manager, name)
    return found ~= 0 and found or nil
end

--- The hash the game names resources by (IwHashString).
function resources.hash(name)
    return hash.name(name)
end

return resources
