-- boz.score: points (Zombies mode).
--
--   score.get()          the player's points        score.add(500)   score.spend(950)
--   score.set(10000)     score.points_for("SUBJECT_ZOMBIE_SCORE_KILL_HEAD")
--   score.on_change(fn)  fn(points, delta) after every change
--   score.free_purchases(3)   purchases cost nothing for 3 seconds
--
-- How it works: CScoreManager (singleton) keeps each player's points in a map keyed by the
-- player's name hash (Entity_GetNameHash of its entity record; +0x40; earned points for stats at
-- +0x4c): GetLocalScore(manager) reads the local player's, AddScore(manager, player, delta,
-- countForStats) changes them (clamped at 0; purchases cost nothing with the UnlimitedScore cvar)
-- and calls OnScoreChanged(manager, score, player, delta) for the HUD. Points for actions come
-- from the score table (CScoreConfig, the ScoreConfigName cvar; the Game tab's economy changes a
-- map's own): ScoreConfig_GetScore.

local score = {}

local core = require("boz.core")

--- The score manager (CScoreManager), or nil outside a match.
function score.manager()
    return core.singleton("CScoreManager")
end

local function player_id()
    return require("boz.player").name_hash()
end

--- The local player's points, or nil outside a match.
function score.get()
    local manager = score.manager()
    return manager and core.call("CScoreManager::GetLocalScore", manager) or nil
end

--- Gives the player points (negative takes them, never below 0). counts: also count them as
--- earned (stats, power-up drops). Returns the new points.
function score.add(points, counts)
    local manager, id = score.manager(), player_id()
    if not manager or not id then
        return nil
    end
    core.call("CScoreManager::AddScore", manager, id, math.floor(points) & 0xffffffff, counts and 1 or 0)
    return score.get()
end

--- Takes points for a purchase; false (and nothing taken) when the player has too few.
function score.spend(points)
    local now = score.get()
    if not now or now < points then
        return false
    end
    score.add(-points)
    return true
end

--- Sets the player's points.
function score.set(points)
    local now = score.get()
    if not now then
        return nil
    end
    return score.add(points - now)
end

--- Points the map's score table gives for an action ("SUBJECT_ZOMBIE_SCORE_HIT", ...).
function score.points_for(action)
    local manager = score.manager()
    if not manager then
        return nil
    end
    local config = core.call("CScoreManager::GetConfig", manager)
    if config == 0 then
        return 0
    end
    return core.call("ScoreConfig_GetScore", config, require("boz.hash").name(action))
end

local changes, hooked = {}, false

--- Calls fn(points, delta) after every change of the local player's points. Returns fn.
function score.on_change(fn)
    table.insert(changes, fn)
    if not hooked then
        hooked = true
        hook.add(core.sym("CScoreManager::OnScoreChanged"), {after = function(c)
            local id = player_id()
            if id and c:arg(3) == id then
                for _, handler in ipairs(changes) do
                    handler(c:arg(2), c:arg_signed(4))
                end
            end
        end})
    end
    return fn
end

local free = {left = 0, before = nil, watching = false}

local function count_down(dt)
    if free.left <= 0 then
        return
    end
    free.left = free.left - (dt or 0)
    if free.left <= 0 then
        require("boz.console").register("UnlimitedScore", free.before or "false", "bool")
        free.before = nil
    end
end

--- Makes purchases cost nothing for `seconds` from now (the UnlimitedScore cvar: the score
--- manager skips every charge), then restores the cvar. Calling it again extends the time.
function score.free_purchases(seconds)
    local console = require("boz.console")
    if free.left <= 0 then
        free.before = console.get("UnlimitedScore") or "false"
        console.register("UnlimitedScore", "true", "bool")
    end
    free.left = math.max(free.left, seconds)
    if not free.watching then
        free.watching = true
        events.on("frame", count_down)
    end
end

return score
