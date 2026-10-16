-- boz.resources: the game's loaded resources (anything in the loaded .group files) by name.
--
--   local wave = resources.find("wave1", "CWave")           -- a round's settings
--   require("boz.reflect").get(wave, "CWave", "m_ZombieCount")
--   resources.find("BOGravity", "CAchievement")              -- an achievement
--   resources.group("ingame")                                -- a loaded group
--
-- Types are the game's resource class names: CWave, CLevel, CZombieConfiguration, CIsEntitySpec,
-- CIwModel, CIwTexture, CIwMaterial, CIwSoundSpec, CIwSoundData, CSoundSequence, CAchievement,
-- CScoreConfig, ... Reflected ones (CIsReflectedResource: waves, levels, zombie configurations,
-- score tables, ...) are readable and writable with boz.reflect by their class; a change lasts
-- until the group loads again.
--
-- How it works: the Marmalade resource manager (its pointer at image +0x492b10) finds resources in
-- every loaded group: CIwResManager_GetResNamed(manager, name, type, flags) and
-- CIwResManager_GetResHashed(manager, hash, type, flags); CIwResManager_GetGroupNamed(manager,
-- name) a loaded group.

local resources = {}

local hash = require("boz.hash")

local FALLBACK = {["g_iwResManager"] = 0x492b10, ["CIwResManager_GetResNamed"] = 0x2352f8 + 1,
                  ["CIwResManager_GetResHashed"] = 0x235220 + 1, ["CIwResManager_GetGroupNamed"] = 0x2351c0 + 1}

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function call(...)
    return (game.call(...) or 0) & 0xffffffff
end

--- The resource manager, or nil before the game set it up.
function resources.manager()
    local manager = game.read("ptr", sym("g_iwResManager"))
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
        local value = type(name) == "number" and name or tonumber(name:sub(3), 16)
        found = call(sym("CIwResManager_GetResHashed"), manager, value, type_name, 0)
    else
        found = call(sym("CIwResManager_GetResNamed"), manager, name, type_name, 0)
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
    local found = call(sym("CIwResManager_GetGroupNamed"), manager, name)
    return found ~= 0 and found or nil
end

--- The hash the game names resources by (IwHashString).
function resources.hash(name)
    return hash.name(name)
end

return resources
