-- boz.score: points (Zombies mode).
--
--   score.get()          the player's points        score.add(500)   score.spend(950)
--   score.set(10000)     score.points_for("SUBJECT_ZOMBIE_SCORE_KILL_HEAD")
--   score.on_change(fn)  fn(points, delta) after every change
--
-- How it works: CScoreManager (singleton) keeps each player's points in a map keyed by the
-- player's name hash (Entity_GetNameHash of its entity record; +0x40; earned points for stats at
-- +0x4c): GetLocalScore(manager) reads the local player's, AddScore(manager, player, delta,
-- countForStats) changes them (clamped at 0; purchases cost nothing with the UnlimitedScore cvar)
-- and calls OnScoreChanged(manager, score, player, delta) for the HUD. Points for actions come
-- from the score table (CScoreConfig, the ScoreConfigName cvar; the Game tab's economy changes a
-- map's own): ScoreConfig_GetScore.

local score = {}

local FALLBACK = {["CScoreManager::s_instance"] = 0x461080, ["CScoreManager::GetLocalScore"] = 0x1f6148 + 1,
                  ["CScoreManager::AddScore"] = 0x1f73e0 + 1, ["CScoreManager::OnScoreChanged"] = 0x1f61c0 + 1,
                  ["CScoreManager::GetConfig"] = 0x1f77e0 + 1, ["ScoreConfig_GetScore"] = 0x1f632e + 1}

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function call(...)
    return (game.call(...) or 0) & 0xffffffff
end

--- The score manager (CScoreManager), or nil outside a match.
function score.manager()
    local manager = game.read("ptr", sym("CScoreManager::s_instance"))
    return manager ~= 0 and manager or nil
end

local function player_id()
    local player = require("boz.components").local_player()
    return player and require("boz.entities").name_hash(player) or nil
end

--- The local player's points, or nil outside a match.
function score.get()
    local manager = score.manager()
    return manager and call(sym("CScoreManager::GetLocalScore"), manager) or nil
end

--- Gives the player points (negative takes them, never below 0). counts: also count them as
--- earned (stats, power-up drops). Returns the new points.
function score.add(points, counts)
    local manager, id = score.manager(), player_id()
    if not manager or not id then
        return nil
    end
    call(sym("CScoreManager::AddScore"), manager, id, math.floor(points) & 0xffffffff, counts and 1 or 0)
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
    local config = call(sym("CScoreManager::GetConfig"), manager)
    if config == 0 then
        return 0
    end
    return call(sym("ScoreConfig_GetScore"), config, require("boz.hash").name(action))
end

local changes, hooked = {}, false

--- Calls fn(points, delta) after every change of the local player's points. Returns fn.
function score.on_change(fn)
    table.insert(changes, fn)
    if not hooked then
        hooked = true
        hook.add(sym("CScoreManager::OnScoreChanged"), {after = function(c)
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

return score
