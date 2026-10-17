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

local core = require("boz.core")
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

local TARGET, PROGRESS = 0x24, 0x28

local singleton = core.singleton

--- A stat's value (this mode's), or nil when the game has no stats manager.
function stats.get(name)
    local manager = singleton("CStatsManager")
    return manager and core.call("Stats_Get", manager, name) or nil
end

--- Adds to a stat. Returns the new value.
function stats.add(name, amount)
    local manager = singleton("CStatsManager")
    if not manager then
        return nil
    end
    core.call("Stats_Add", manager, core.call("Stats_GetMode"), hash.name(name), math.floor(amount) & 0xffffffff)
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
    core.call("Achievement_SetProgress", a, math.floor(value))
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
