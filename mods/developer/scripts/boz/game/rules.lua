-- boz.rules: the map's game rules from the Game tab (read only; change them while playing with
-- boz.rounds, boz.cvars and the mystery box).
--
--   rules.mode()        "easy" | "normal" | "hard" | "coop2" | "coop3" | "coop4"
--   rules.round_set()   the round set this mode plays ("" = the base map's own rounds)
--   rules.sets()        the map's round set names
--   rules.modes()       mode -> {set, zombies, health}

local rules = {}

local MODES = {"easy", "normal", "hard", "coop2", "coop3", "coop4"}
local data = {sets = {}, modes = {}}

--- Called by boz.game with the map's rules (world_data.game.rules).
function rules.set_data(value)
    if type(value) == "table" then
        data = {sets = value.sets or {}, modes = value.modes or {}}
    end
end

--- The mode being played: the difficulty alone, else co-op by the number of players (the way
--- the game picks its first round, Level_GetStartingWave). nil outside a match.
function rules.mode()
    local map = require("boz.engine.map")
    local players = 1 + #require("boz.engine.network").players()
    if players >= 2 then
        return MODES[math.min(players, 4) + 2]
    end
    local index = map.difficulty_index()
    return index and MODES[index + 1] or nil
end

--- The mode names, in order.
function rules.mode_names()
    return {table.unpack(MODES)}
end

--- The round set names the map has.
function rules.sets()
    return {table.unpack(data.sets)}
end

--- mode -> {set = name or "", zombies = x, health = x}.
function rules.modes()
    local out = {}
    for _, key in ipairs(MODES) do
        local mode = data.modes[key] or {}
        out[key] = {set = mode.set or "", zombies = mode.zombies or 1, health = mode.health or 1}
    end
    return out
end

--- The round set a mode plays (default: the current one); "" is the base map's own rounds.
function rules.round_set(mode)
    mode = mode or rules.mode()
    return mode and rules.modes()[mode].set or nil
end

return rules
