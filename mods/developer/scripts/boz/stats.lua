-- boz.stats: the player's statistics and achievements.
--
--   stats.get("STAT_ZOMBIESKILLED")     stats.add("STAT_HEADSHOTS", 1)
--   stats.unlock("BOGravity")           stats.progress("BOWhackAZombie")  -> current, target
--
-- Stats: STAT_ZOMBIESKILLED, STAT_HEADSHOTS, STAT_REVIVED, STAT_COMRADESREVIVED,
-- STAT_PLAYERDEATHS, STAT_POINTSSPENT, STAT_WAVES (this match) and their _TOTAL forms (all time).
-- Achievements are CAchievement resources by name (BOGravity, BOWhackAZombie, BOEagleLanded, ...).
--
-- How it works: CStatsManager (singleton) keeps a map per mode (Stats_GetMode: 1 Zombies, 2 Dead
-- Ops) from a stat's name hash to its value: Stats_Get(manager, name), Stats_Add(manager, mode,
-- hash, delta). Achievements are CAchievement resources (boz.resources): target at +0x24, progress
-- +0x28, enabled +0x36; Achievement_SetProgress clamps, unlocks at the target and saves
-- (CAchievementDB).

local stats = {}

local hash = require("boz.hash")

stats.NAMES = {"STAT_ZOMBIESKILLED", "STAT_HEADSHOTS", "STAT_REVIVED", "STAT_COMRADESREVIVED",
               "STAT_PLAYERDEATHS", "STAT_POINTSSPENT", "STAT_WAVES", "STAT_ZOMBIESKILLED_TOTAL",
               "STAT_HEADSHOTS_TOTAL", "STAT_REVIVED_TOTAL", "STAT_PLAYERDEATHS_TOTAL",
               "STAT_POINTSSPENT_TOTAL"}
stats.ACHIEVEMENTS = {"BOCanYouFlyBobby", "BOCanineCaution", "BOChimpOnBarbie", "BODamnDirtyApes",
                      "BODepthCharge", "BOEagleLanded", "BOFluxCapacitor", "BOGravity", "BOGrossProfit",
                      "BOHangingGardens", "BOHayBail", "BOItWasNotMe", "BOPlacesEveryone",
                      "BOQuietOnSet", "BORagingRomero", "BORussianRoulette", "BOThrustMaster",
                      "BOWeHaveAProblem", "BOWhackAZombie"}

local FALLBACK = {["CStatsManager::s_instance"] = 0x46107c, ["CAchievementDB::s_instance"] = 0x461088,
                  ["Stats_Get"] = 0x19e554 + 1, ["Stats_Add"] = 0x1fcb7a + 1, ["Stats_GetMode"] = 0x1fc760 + 1,
                  ["Achievement_SetProgress"] = 0x11ce00 + 1}
local TARGET, PROGRESS = 0x24, 0x28

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function call(...)
    return (game.call(...) or 0) & 0xffffffff
end

local function singleton(name)
    local value = game.read("ptr", sym(name .. "::s_instance"))
    return value ~= 0 and value or nil
end

--- A stat's value (this mode's), or nil when the game has no stats manager.
function stats.get(name)
    local manager = singleton("CStatsManager")
    return manager and call(sym("Stats_Get"), manager, name) or nil
end

--- Adds to a stat. Returns the new value.
function stats.add(name, amount)
    local manager = singleton("CStatsManager")
    if not manager then
        return nil
    end
    call(sym("Stats_Add"), manager, call(sym("Stats_GetMode")), hash.name(name), math.floor(amount) & 0xffffffff)
    return stats.get(name)
end

--- Every stat: {[name] = value}.
function stats.all()
    local out = {}
    for _, name in ipairs(stats.NAMES) do
        out[name] = stats.get(name)
    end
    return out
end

local function achievement(name)
    return require("boz.resources").find(name, "CAchievement")
end

--- An achievement's progress and target, or nil when the game has no such achievement.
function stats.progress(name)
    local a = achievement(name)
    if not a then
        return nil
    end
    return game.read("u32", a + PROGRESS), game.read("u32", a + TARGET)
end

--- Sets an achievement's progress (the target unlocks it, and the game saves).
function stats.set_progress(name, value)
    local a = achievement(name)
    if not a then
        return false
    end
    call(sym("Achievement_SetProgress"), a, math.floor(value))
    return true
end

--- Unlocks an achievement.
function stats.unlock(name)
    local _, target = stats.progress(name)
    return target ~= nil and stats.set_progress(name, target)
end

--- True once an achievement is unlocked.
function stats.unlocked(name)
    local progress, target = stats.progress(name)
    return progress ~= nil and progress >= target
end

return stats
