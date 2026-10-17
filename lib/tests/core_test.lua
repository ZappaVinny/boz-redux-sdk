-- boz.core, boz.map, boz.score and boz.pieces against a fake game: lua5.4 lib/tests/core_test.lua.
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
local fake = require("fake_game").install()
local memory, functions, check, last = fake.memory, fake.functions, fake.check, fake.last

-- core.sym: the client's name first, then the standard library's own table of offsets.
local symbol_data = require("boz.symbol_data")
local real_symbol = game.symbol
game.symbol = function(name) if name == "CHealth::Damage" then return nil end return real_symbol(name) end
local core = require("boz.core")
check(core.sym("CHealth::Damage") == game.base() + symbol_data.functions["CHealth::Damage"], "a name the client lacks")
check(core.sym("CHealth::Damage") & 1 == 1, "Thumb functions carry bit 0")
game.symbol = real_symbol
check(core.sym("Spawn_ByHash") == fake.address("Spawn_ByHash"), "the client's name wins")

-- Every function the library calls by name is in the game definition.
local missing = {}
for path in io.popen("ls lib/boz/*.lua"):lines() do
    local text = io.open(path):read("a")
    for name in text:gmatch('core%.call%("([%w_:]+)"') do
        if not symbol_data.functions[name] then table.insert(missing, name) end
    end
    for name in text:gmatch('core%.sym%("([%w_:]+)"') do
        if not symbol_data.functions[name] and not symbol_data.globals[name] then table.insert(missing, name) end
    end
end
check(#missing == 0, "names missing from the game definition: " .. table.concat(missing, ", "))

-- Quaternions are written scalar first.
core.write_quat(0x100, {x = 0.1, y = 0.2, z = 0.3, w = 0.9})
check(memory[0x100] == 0.9 and memory[0x104] == 0.1 and memory[0x10c] == 0.3, "s x y z")
check(core.scratch("a", 8) == core.scratch("a", 8) and core.scratch("a", 8) ~= core.scratch("b", 8), "scratch buffers per key")

-- boz.map: the level manager's data, and level starts once per level.
local map = require("boz.map")
local LEVEL, PLAYER = 0x6000, 0x5000
check(map.player() == nil and not map.playing(), "no level")
memory[fake.address("CLevelManager::s_instance")] = LEVEL
memory[LEVEL + 0x1a0], memory[PLAYER + 4] = PLAYER, 7
memory[LEVEL + 0x214] = 0x1234
local entity, id = map.player()
check(entity == PLAYER and id == 7, "the player and its id")
check(map.set_nearest_poi(0x4321) == 0x1234 and map.nearest_poi() == 0x4321, "the point of interest in reach")
local starts = 0
map.on_level_start(function() starts = starts + 1 end)
fake.frame(); fake.frame()
check(starts == 1, "a level start runs once")
memory[LEVEL + 0x1a0] = 0
fake.frame()
memory[LEVEL + 0x1a0] = PLAYER
fake.frame()
check(starts == 2, "the next level starts again")

-- boz.game_events: dedupe.
local game_events = require("boz.game_events")
local seen = 0
game_events.on("SUBJECT_ZOMBIE_DEATH", function() seen = seen + 1 end, {dedupe_frames = 1})
local function dispatch(a, b)
    fake.run_hook("CIsSubject::Dispatch", {0x10, game_events.id("SUBJECT_ZOMBIE_DEATH"), a, b, 0})
end
dispatch(1, 2); dispatch(1, 2)
check(seen == 1, "one event reaching two subjects is one event")
fake.frame(); fake.frame()
dispatch(1, 2)
check(seen == 2, "the same event later is a new one")

-- boz.score.free_purchases: UnlimitedScore on for a while, then back as it was.
local cvars = {UnlimitedScore = "false"}
package.loaded["boz.console"] = {get = function(n) return cvars[n] end,
                                 register = function(n, v) cvars[n] = v return v end}
local score = require("boz.score")
score.free_purchases(1)
check(cvars.UnlimitedScore == "true", "purchases are free")
for _ = 1, 30 do fake.frame(0.05) end
check(cvars.UnlimitedScore == "false", "and cost again afterwards")

-- boz.pieces.use_free: the cost credited, used a frame later with purchases free, credit back.
memory[fake.address("CScoreManager::s_instance")] = 0x8400
functions["CIsEntityDB::GetEntity"] = function(e) return e == PLAYER and 0x5800 or 0 end
functions["Entity_GetNameHash"] = function(r) return r == 0x5800 and 0xabc or 0 end
local points = 100
functions["CScoreManager::GetLocalScore"] = function() return points end
functions["CScoreManager::AddScore"] = function(_, who, delta)
    if who == 0xabc then points = points + (delta >= 0x80000000 and delta - 0x100000000 or delta) end
end
local pieces = require("boz.pieces")
local DOOR, DOOR_C = 0x7000, 0x7100
memory[DOOR + 4] = 9
functions["CIsComponentTableBase::Find"] = function(tbl, id)
    return tbl == fake.address("CDoor::s_table") and id == 9 and DOOR_C or 0
end
local used_at = nil
functions["Poi_SendUse"] = function() used_at = map.nearest_poi() end
local door = pieces.of(DOOR, "CDoor")
require("boz.reflect").set(DOOR_C, "CDoor", "m_Cost", 750)
check(door and door:cost() == 750, "a door's cost")
check(door:use_free() and points == 850, "the cost is credited first")
fake.frame()
check(used_at == nil, "the use waits a frame (the game checks the points a frame before)")
fake.frame()
check(used_at == DOOR and map.nearest_poi() == 0x4321 and cvars.UnlimitedScore == "true",
      "used as the point of interest in reach, with purchases free")
fake.frame(); fake.frame(); fake.frame()
check(points == 100, "the credit is taken back (" .. points .. ")")
print("core_test: OK")
