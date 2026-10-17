-- boz.game and boz.hooks against a fake game: lua5.4 lib/tests/game_test.lua (from the SDK root).
package.path = "lib/?.lua;" .. package.path

local memory, hooks_added, frames, cvars, executed = {}, {}, {}, {}, {}
local level_name = "mymap"
local LEVEL = 0x5300

game = {
    base = function() return 0x4a000000 end,
    symbol = function(name) return ({["Level_Load"] = 0x100, ["CWaveRepeatable::GetZombieHealth"] = 0x200,
                                     ["String_Equals"] = 0x300, ["CLevelManager::s_instance"] = 0x400})[name] end,
    read = function(kind, at, size)
        if at == 0x400 then return LEVEL end
        if kind == "string" then return at == 0x9000 and "callofthedead" or at == 0x9100 and "kino" or level_name end
        return memory[at] or 0
    end,
}
hook = {add = function(target, h) hooks_added[target] = h end}
events = {on = function(name, fn) if name == "frame" then table.insert(frames, fn) end end}
function log(message) print("log: " .. message) end
package.loaded["boz.console"] = {
    get = function(name) return cvars[name] end,
    register = function(name, value) cvars[name] = value end,
    exec = function(line) table.insert(executed, line) return "" end,
}
local listeners = {}
package.loaded["boz.prefabs"] = {on = function(name, fn) listeners[name] = fn end}

local function check(condition, message)
    if not condition then error("FAILED: " .. message, 2) end
end

local rules = require("boz.game")
cvars.StartingScore = "500"
rules.start({level = "mymap", cvars = {StartingScore = 2000, ScoreConfigName = "boz_score_mymap"},
             power_on = true, grow_health = true, behaves_like = "callofthedead"})

-- The map's level loads: its values; another level: the game's back.
hooks_added[0x100].before()
check(rules.active() and cvars.StartingScore == "2000", "the map's points at start")
check(cvars.ScoreConfigName == "boz_score_mymap", "the map's score table")
level_name = "kino"
hooks_added[0x100].before()
check(not rules.active() and cvars.StartingScore == "500", "another level gets the game's value back")
level_name = "mymap"
hooks_added[0x100].before()

-- Repeating rounds' health from the wave's data.
local wave = 0x7000
memory[wave + 0x78], memory[wave + 0xa4], memory[wave + 0xac] = 300, 2.0, 3
local result
local call = {arg = function(_, i) return i == 1 and wave or 5 end, set_result = function(_, v) result = v end}
hooks_added[0x200].after(call)
check(result == 1200, "health 300 x 2^(5-3)")

-- The level manager's name checks answer as Call of the Dead (only for the level's name).
local eq_result
local function eq(a, b) return {arg = function(_, i) return i == 1 and a or b end, result = function() return 0 end,
                               set_result = function(_, v) eq_result = v end} end
hooks_added[0x300].after(eq(LEVEL + 0x55, 0x9000))
check(eq_result == 1, "the level is Call of the Dead for its checks")
eq_result = nil
hooks_added[0x300].after(eq(LEVEL + 0x55, 0x9100))
check(eq_result == nil, "but not Kino")
hooks_added[0x300].after(eq(0x1234, 0x9000))
check(eq_result == nil, "and other strings are left alone")

-- Power on once per level start.
memory[LEVEL + 0x1a0], memory[0xabc + 4] = 0xabc, 1
for _, fn in ipairs(frames) do fn(0.016) end
for _, fn in ipairs(frames) do fn(0.016) end
check(#executed == 1 and executed[1] == "SwitchPowerOn", "power on once when the level starts")

-- Hook scripts.
package.preload["hooks.round_started"] = function()
    return function(data) result = data.round end
end
package.preload["hooks.broken"] = function() return 42 end
local count = require("boz.hooks").start({"round_started", "broken"})
check(count == 1, "one hook started, the broken one skipped")
listeners.round_started({round = 7})
check(result == 7, "the hook gets the event's data")
print("game_test: OK")
