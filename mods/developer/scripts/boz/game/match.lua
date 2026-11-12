-- boz.game.match: ending a match from a script, as the game does when nobody is left standing
-- (its game over and results). The game has no screen of its own for a win: scripts hear
-- match_ended with win = true and can say so themselves (boz.hud) first.
--
--   boz.on("match_ended", function(data) if data.win then log("escaped!") end end)
--   boz.end_match({win = true})
--
-- game: SUBJECT_END_GAME (CLevelManager's subject)

local match = {}

local core = require("boz.engine.core")
local game_events = require("boz.engine.game_events")

local LEVEL_SUBJECT = core.offset("CLevelManager", "subject")

local ended = nil     -- the level manager whose match a script ended

--- Ends the match. options: win (true: scripts hear match_ended with win = true). Returns false
--- when there is no match to end or it already ended.
function match.finish(options)
    options = options or {}
    if type(options) ~= "table" then
        error("end_match takes options such as {win = true}", 2)
    end
    local manager = core.singleton("CLevelManager")
    if not manager or not require("boz.engine.map").player() or ended == manager then
        return false
    end
    ended = manager
    require("boz.objects.runtime").send("match_ended", {win = options.win == true})
    game_events.send(manager + LEVEL_SUBJECT, "SUBJECT_END_GAME")
    return true
end

--- A level starts: its match can be ended again.
function match.reset()
    ended = nil
end

return match
