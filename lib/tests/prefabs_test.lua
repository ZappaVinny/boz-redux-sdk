-- boz.prefabs against a fake game: lua5.4 lib/tests/prefabs_test.lua (from the SDK root).
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
local fake = require("fake_game").install({strict = true})
local memory, symbols, functions, hooks, calls, frames = fake.memory, fake.symbols, fake.functions, fake.hooks,
    fake.calls, fake.frames
local address, run_hook, frame, check, called = fake.address, fake.run_hook, fake.frame, fake.check, fake.called

local hash = require("boz.hash")
local LEVEL, PLAYER, SCORE = 0x8000, 0x8100, 0x9100
local entities = {}
local next_entity, next_id = 0x20000, 10
local function entity(name)
    next_entity, next_id = next_entity + 0x100, next_id + 1
    entities[hash.name(name)] = next_entity
    memory[next_entity + 4] = next_id
    return next_entity
end
memory[address("CLevelManager::s_instance")] = LEVEL
memory[address("CScoreManager::s_instance")] = SCORE
memory[LEVEL + 0x1a0] = PLAYER
memory[PLAYER + 4] = 1
local DOOR, SKULL, BUTTON, ROOM = entity("Vault_1.Door"), entity("Vault_1.Skull"),
    entity("Vault_1.Button"), entity("Room")
local models = {}            -- entity id -> renderable component
local GUN, STAND = entity("Statue.Pickup.Gun"), entity("Statue.Pickup.Stand")
for _, e in ipairs({DOOR, GUN, STAND}) do models[memory[e + 4]] = e + 0x50 end
local SKULL_EGG = SKULL + 0x60   -- the hit volume's CEasterEgg component
memory[SKULL_EGG + 0xc] = SKULL
local score = 1000

functions["CIsEntityDB::FindEntity"] = function(h) return entities[h] or 0 end
functions["CIsComponentTableBase::Find"] = function(tbl, id)
    if tbl == address("CIsRenderableModel::s_table") then return models[id] or 0 end
    return 0
end
for _, name in ipairs({"CIsRenderableModel::SetVisible", "CIsCollisionObject::Enable",
                       "CIsCollisionObject::Disable", "NavMesh_SetTagOpen", "Poi_ShowPrompt"}) do
    functions[name] = function() return 0 end
end
functions["Poi_FindPromptElement"] = function() return 0x5555 end
functions["CScoreManager::GetLocalScore"] = function() return score end
functions["CScoreManager::AddScore"] = function(_, id, delta)
    if delta >= 0x80000000 then delta = delta - 0x100000000 end   -- an int32 in the game
    if id == 77 then score = score + delta end
end
-- The entity database's record of an entity (what Entity_GetNameHash must be asked).
functions["CIsEntityDB::GetEntity"] = function(e) return e + 0x10000000 end
local score_hashes = {}
functions["Entity_GetNameHash"] = function(record)
    assert(record > 0x10000000, "Entity_GetNameHash needs the entity database's record")
    if record == DOOR + 0x10000000 then return hash.name("Vault_1.Door") end
    return 77
end
functions["CIsTransform::UpdateWorld"] = function() return 0 end
functions["StateKind"] = function(machine) return memory[machine + 4] or 0 end
local saved_settings = {}
settings = {
    get = function(key, default) local v = saved_settings[key]; if v == nil then return default end; return v end,
    set = function(key, value) saved_settings[key] = value end,
}
memory[LEVEL + 0x55] = "testlevel"

-- Scripts on disk, loaded the way the client's loadscript(name, env) loads them.
local dir = os.tmpname()
os.remove(dir)
os.execute("mkdir -p " .. dir .. "/prefabs")
local function write(name, text)
    local file = assert(io.open(dir .. "/prefabs/" .. name .. ".lua", "w"))
    file:write(text)
    file:close()
end
function loadscript(name, env)
    return assert(loadfile(dir .. "/" .. name:gsub("%.", "/") .. ".lua", "t", env))
end
stats, hits, used, events_seen, plain_log = {started = 0}, {}, {}, {}, {}
event_data = {}
write("Vault", [[
function start() stats.started = stats.started + 1 end
function on_hit(volume, info) table.insert(hits, volume); self:part("Door"):hide() end
function on_use(volume) table.insert(used, volume) end
function on_event(name, data) table.insert(events_seen, name); event_data[name] = data end
]])
write("Counter", [[
skulls = 0
progress = {found = {}}
local not_saved = 5
function start() stats.counter_start = skulls end
function on_hit() skulls = skulls + 1 end
function bump() skulls = skulls + 1; not_saved = not_saved + 1; progress.found.altar = true end
function say() print("50% done", 2) end
]])
-- A script as written now: plain functions, self already set, top-level state per object.
write("Plain", [[
local count = 0
function on_enter(volume, who)
    count = count + 1
    table.insert(plain_log, self.name .. ":" .. volume .. ":" .. count .. ":" .. self.properties.tag)
end
function on_exit(volume, who) table.insert(plain_log, self.name .. ":exit") end
function open() return self.name .. " opened" end
]])
write("Broken", "this is not lua")

local prefabs = require("boz.prefabs")

local bus = {}
prefabs.on("Vault_1.Skull.hit", function(data, name) table.insert(bus, name) end)
prefabs.start({
    {name = "Vault_1", kind = "prefab", script = "prefabs.Vault", properties = {delay = 5.0},
     parts = {{name = "Vault_1.Door", part = "Door"}, {name = "Vault_1.Skull", part = "Skull"},
              {name = "Vault_1.Button", part = "Button"}},
     members = {"Vault_1.Door", "Vault_1.Skull", "Vault_1.Button"}},
    {name = "Vault_1.Skull", kind = "volume", volume = "hit", who = "players", once = true,
     owner = "Vault_1", script = ""},
    {name = "Vault_1.Button", kind = "volume", volume = "use", who = "players", once = false,
     prompt = "Open", cost = 600, owner = "Vault_1", script = ""},
    {name = "Room", kind = "volume", volume = "trigger", who = "anyone", owner = "", script = ""},
    {name = "Bad", kind = "model", script = "prefabs.Broken"},
    {name = "Gate_A", kind = "prefab", script = "prefabs.Plain", properties = {tag = "a"},
     parts = {{name = "Gate_A.Zone", part = "Zone"}}, members = {"Gate_A.Zone"}},
    {name = "Gate_A.Zone", kind = "volume", volume = "trigger", who = "anyone", owner = "Gate_A", script = ""},
    {name = "Gate_B", kind = "prefab", script = "prefabs.Plain", properties = {tag = "b"},
     parts = {{name = "Gate_B.Zone", part = "Zone"}}, members = {"Gate_B.Zone"}},
    {name = "Gate_B.Zone", kind = "volume", volume = "trigger", who = "anyone", owner = "Gate_B", script = ""},
    -- Prefabs inside prefabs: one without a script of its own, one with one.
    {name = "Statue", kind = "prefab", script = "prefabs.Plain", properties = {tag = "s"},
     parts = {{name = "Statue.Pickup", part = "Pickup"}, {name = "Statue.Shrine", part = "Shrine"},
              {name = "Statue.Rock", part = "Rock"}},
     members = {"Statue.Pickup.Gun", "Statue.Pickup.Stand", "Statue.Shrine.Altar", "Statue.Rock"}},
    {name = "Statue.Shrine", kind = "prefab", script = "prefabs.Plain", properties = {tag = "n"},
     owner = "Statue", parts = {{name = "Statue.Shrine.Altar", part = "Altar"}},
     members = {"Statue.Shrine.Altar"}},
})
check(stats.started == 1, "start() runs once per scripted object")
local vault = prefabs.find("vault_1")
check(vault and vault.properties.delay == 5.0, "instances carry their property values")
check(vault:part("Door").name == "Vault_1.Door", "parts by name")

-- Shooting the skull: reported to the prefab, the game's easter egg handling skipped, once only.
check(run_hook("CEasterEgg::OnEvent", {SKULL_EGG}) == true, "the game's easter egg handling is skipped")
check(#hits == 1 and hits[1] == "Skull", "on_hit gets the part name")
check(#called("CIsRenderableModel::SetVisible") == 1, "the script hid the door")
check(#bus == 1, "the bus hears Vault_1.Skull.hit")
check(events_seen[#events_seen] ~= "Vault_1.Skull.hit", "on_event does not get the volume's own events")
run_hook("CEasterEgg::OnEvent", {SKULL_EGG})
check(#hits == 1, "a once-only volume fires once")

-- Use: the prompt shows while it is the point of interest in reach; the cost is paid.
memory[LEVEL + 0x214] = BUTTON
frame()
check(#called("Poi_ShowPrompt") == 0, "no prompt until the game's prompt handler runs")
check(run_hook("CIngameStatePlaying::UpdatePoiPrompt", {0, 0, hash.name("SUBJECT_POI_TRIGGER"), BUTTON}),
      "the game's prompt handling is skipped for a Use volume")
check(not run_hook("CIngameStatePlaying::UpdatePoiPrompt", {0, 0, hash.name("SUBJECT_POI_TRIGGER"), DOOR}),
      "other points of interest keep the game's prompt")
local prompts = called("Poi_ShowPrompt")
check(#prompts >= 1 and prompts[#prompts][2] == 0x5555, "the Use volume's prompt is shown")
run_hook("Poi_SendUse", {})
check(#used == 1 and used[1] == "Button" and score == 400, "use pays its cost (" .. score .. ")")
run_hook("Poi_SendUse", {})
check(#used == 1, "not enough points: nothing happens")

-- A hidden Use volume shows no prompt and does nothing, even with points to pay; shown, it works.
score = 5000
vault:part("Button"):hide()
check(not run_hook("CIngameStatePlaying::UpdatePoiPrompt", {0, 0, hash.name("SUBJECT_POI_TRIGGER"), BUTTON}),
      "a hidden Use volume shows no prompt")
run_hook("Poi_SendUse", {})
check(#used == 1 and score == 5000, "a hidden Use volume does nothing")
vault:part("Button"):show()
check(run_hook("CIngameStatePlaying::UpdatePoiPrompt", {0, 0, hash.name("SUBJECT_POI_TRIGGER"), BUTTON}),
      "shown again, its prompt is back")
run_hook("Poi_SendUse", {})
check(#used == 2 and score == 4400, "shown again, it works (" .. score .. ")")

-- Events on the bus and from the game.
prefabs.send("vault_open", {by = "test"})
check(events_seen[#events_seen] == "vault_open", "on_event hears boz.send")
memory[0x6000 + 0x78] = 7
run_hook("CWaveManager::StartWave", {0x6000}, "after")
check(events_seen[#events_seen] == "round_started", "round_started from the game")

-- A prefab's hide() reaches every member.
local before = #called("CIsRenderableModel::SetVisible")
vault:hide()
check(#called("CIsRenderableModel::SetVisible") == before + 1, "hide reaches the members that draw")
-- Hidden survives only until the level starts again (a restart shows everything).
local objects_module = require("boz.objects")
objects_module.get("Vault_1.Skull"):hide()
check(objects_module.is_hidden("Vault_1.Skull"), "hidden until the level starts again")

-- A part that is a prefab is that prefab: hide() reaches all of its parts.
local statue = prefabs.find("Statue")
local pickup = statue:part("Pickup")
check(pickup.name == "Statue.Pickup" and #pickup._members == 2, "a nested prefab part groups its parts")
before = #called("CIsRenderableModel::SetVisible")
pickup:hide():set_collision(false):open_navmesh()
check(#called("CIsRenderableModel::SetVisible") == before + 2, "hiding a nested prefab hides both its parts")
check(statue:part("Shrine") == prefabs.find("Statue.Shrine"), "a nested prefab with a script is its instance")
check(statue:part("Rock").name == "Statue.Rock", "a plain part is still its object")
-- Plain scripts: one run per object, each with its own self and its own top-level variables.
local ZONE_A, ZONE_B = entity("Gate_A.Zone"), entity("Gate_B.Zone")
memory[0xc000 + 0xc], memory[0xc100 + 0xc], memory[0xc200 + 0xc] = ZONE_A, ZONE_B, PLAYER
local function wait(seconds)
    for _ = 1, math.floor(seconds / 0.05 + 0.5) do frame_dt(0.05) end
end
function frame_dt(dt) for _, fn in ipairs(frames) do fn(dt) end end
run_hook("CIsCollisionObject::OnCollisionEnter", {0xc000, 0xc200})
run_hook("CIsCollisionObject::OnCollisionEnter", {0xc000, 0xc200})   -- a second shape
run_hook("CIsCollisionObject::OnCollisionExit", {0xc000, 0xc200})
run_hook("CIsCollisionObject::OnCollisionExit", {0xc000, 0xc200})    -- flicker: out ...
run_hook("CIsCollisionObject::OnCollisionEnter", {0xc000, 0xc200})   -- ... and straight back
wait(0.5)
check(table.concat(plain_log, " ") == "Gate_A:Zone:1:a",
      "one enter while standing in a trigger (" .. table.concat(plain_log, " ") .. ")")
run_hook("CIsCollisionObject::OnCollisionExit", {0xc000, 0xc200})
check(#plain_log == 1, "exit waits to be sure")
wait(0.5)
run_hook("CIsCollisionObject::OnCollisionEnter", {0xc000, 0xc200})
run_hook("CIsCollisionObject::OnCollisionEnter", {0xc100, 0xc200})
check(table.concat(plain_log, " ") == "Gate_A:Zone:1:a Gate_A:exit Gate_A:Zone:2:a Gate_B:Zone:1:b",
      "plain scripts: self and state per object (" .. table.concat(plain_log, " ") .. ")")
check(prefabs.find("Gate_B"):open() == "Gate_B opened", "other scripts call a plain script's functions")
-- Timers run on game time: frames in which the player's fixed step ran.
local fired, ticks = {}, 0
prefabs.after(1.0, function() table.insert(fired, "after") end)
local every = prefabs.every(0.5, function() ticks = ticks + 1 end)
-- The game simulates 30 steps a second (the physics step), none while paused, and draws any
-- number of frames: here three steps and `drawn` frames per tenth of a second.
local function play(seconds, paused, drawn)
    for _ = 1, math.floor(seconds / 0.1 + 0.5) do
        if not paused then
            for _ = 1, 3 do run_hook("CIsBulletWorld::FixedStep", {}) end
        end
        for _ = 1, drawn or 1 do
            for _, fn in ipairs(frames) do fn(0.1 / (drawn or 1)) end
        end
    end
end
play(2.0, true)
check(#fired == 0 and ticks == 0, "timers wait while the game is paused")
play(1.05)
check(#fired == 1 and ticks == 2, "after fires once, every repeats (" .. ticks .. ")")
every:cancel()
play(1.0)
check(#fired == 1 and ticks == 2, "a cancelled timer stops")
-- Game time follows the simulation, not the frame rate: 4 s pass in 4 s at any frame rate.
local late = {}
prefabs.after(4, function() table.insert(late, "fired") end)
play(3.9, false, 6)   -- six frames drawn per tenth of a second (a fast PC drawing between steps)
check(#late == 0, "not before its time")
play(0.2, false, 6)
check(#late == 1, "a 4 s timer fires after 4 s however many frames are drawn")

-- Perks: a perk not yet owned.
local PERKS = 0xa000
memory[PERKS + 0xc] = PLAYER
memory[PERKS + 0x58] = 1 << 2
run_hook("CPerkManager::GainPerk", {PERKS, 2, 1})
check(events_seen[#events_seen] ~= "perk_bought", "an owned perk is not bought again")
run_hook("CPerkManager::GainPerk", {PERKS, 5, 1})
check(events_seen[#events_seen] == "perk_bought" and event_data.perk_bought.perk == "Quick Revive"
      and event_data.perk_bought.player, "perk_bought names the perk")

-- Doors: m_DoorState moving to 2.
local DOOR_C = 0xa100
memory[DOOR_C + 0xc] = DOOR
memory[DOOR_C + 0x9c] = 0
local components = require("boz.components")
local real_each = components.each
components.each = function(tbl)
    if tbl == "CDoor" or tbl == address("CDoor::s_table") then
        local done = false
        return function() if not done then done = true; return DOOR_C end end
    end
    return real_each(tbl)
end
frame()
check(events_seen[#events_seen] ~= "door_opened", "a closed door is not news")
memory[DOOR_C + 0x9c] = 2
frame()
check(events_seen[#events_seen] == "door_opened" and event_data.door_opened.door == "Vault_1.Door",
      "door_opened names the door")

-- Zombies: entering the dead state, with where it died.
local ZOMBIE_C, MACHINE, VTABLE, TRANSFORM = 0xa200, 0xa300, 0xa400, 0xa500
memory[ZOMBIE_C + 0xc4], memory[ZOMBIE_C + 0x138] = TRANSFORM, PLAYER
memory[ZOMBIE_C + 0x22c], memory[ZOMBIE_C + 0x124] = -1, 0
memory[MACHINE], memory[VTABLE + 0x18] = VTABLE, address("StateKind")
memory[TRANSFORM + 0x5c], memory[TRANSFORM + 0x60], memory[TRANSFORM + 0x64] = 100.0, 0.0, 50.0
memory[MACHINE + 4] = 3
local before_kills = #events_seen
run_hook("CAIControllerZombie::State_Dead", {ZOMBIE_C, MACHINE})
check(#events_seen == before_kills, "a dead zombie's later frames are not kills")
memory[MACHINE + 4] = 1
run_hook("CAIControllerZombie::State_Dead", {ZOMBIE_C, MACHINE})
local kill = event_data.zombie_killed
check(kill and kill.by_player and kill.headshot and kill.position.x == 100.0,
      "zombie_killed: where, by whom, headshot")

-- near: an object's position against a point.
local DOOR_TRANSFORM = 0xa600
memory[DOOR_TRANSFORM + 0x5c], memory[DOOR_TRANSFORM + 0x60], memory[DOOR_TRANSFORM + 0x64] = 100.0, 0.0, 250.0
local real_find = functions["CIsComponentTableBase::Find"]
functions["CIsComponentTableBase::Find"] = function(tbl, id)
    if tbl == address("CIsTransform::s_table") and id == memory[DOOR + 4] then return DOOR_TRANSFORM end
    if tbl == address("CPlayerController::s_table") and id == memory[PLAYER + 4] then return 0xa700 end
    return real_find(tbl, id)
end
check(vault:part("Door"):near(kill.position, 250) and not vault:part("Door"):near(kill.position, 150),
      "near compares distances in centimetres")

-- Downed and revived: the player's stance.
memory[0xa700 + 0x1f4], memory[0xa700 + 0x1d4] = 8, 3
frame()
check(events_seen[#events_seen] == "player_downed", "player_downed")
memory[0xa700 + 0x1f4] = 1
frame()
check(events_seen[#events_seen] == "player_revived", "player_revived")

-- Saved globals: written when the game saves, back before start() when the save is continued.
local counter_level = {
    {name = "Altar", kind = "prefab", script = "prefabs.Counter", properties = {}, parts = {}, members = {}},
}
require("boz.objects").forget_hidden()   -- what boz.world does when a level (re)starts
check(not require("boz.objects").is_hidden("Vault_1.Skull"), "forgotten when a level starts again")
prefabs.start(counter_level)
local altar = prefabs.find("Altar")
altar:bump(); altar:bump()
prefabs.globals.eggs = {done = 2, names = {"a", "b\nc"}}
run_hook("CSaveManager::SaveGame", {})
check((saved_settings["globals.testlevel.count"] or 0) >= 1, "the save writes the globals")
memory[LEVEL + 0x298] = 1           -- continuing that save
stats.counter_start = nil
prefabs.start(counter_level)
check(stats.counter_start == nil, "start() waits for the save to load")
check(prefabs.globals.eggs == nil, "a new level starts with empty globals")
run_hook("CSaveManager::NotifyLoad", {}, "before")
run_hook("CSaveManager::NotifyLoad", {}, "after")
check(stats.counter_start == 2, "start() sees the saved globals (" .. tostring(stats.counter_start) .. ")")
check(prefabs.globals.eggs.done == 2 and prefabs.globals.eggs.names[2] == "b\nc", "boz.globals come back")
memory[LEVEL + 0x298] = 0

-- print reaches the game console (the Developer console shows it), "%" escaped for its format.
local console_lines = {}
memory[address("g_console")] = 0xb000
functions["Console_Print"] = function(_, text) table.insert(console_lines, text) end
prefabs.find("Altar"):say()
check(console_lines[1] == "50%% done\t2", "print goes to the game console (" .. tostring(console_lines[1]) .. ")")
-- A weapon's in-game name answers the wall buy prompt's string id "<weapon>_S_WEAPON".
prefabs.start({}, {}, {{name = "idgun", script = "", display = "Apothicon Servant"}})
local function localise(id)
    local answer
    for _, handlers in ipairs(hooks[address("Localise_GetString")] or {}) do
        handlers.before({arg = function(_, i) return i == 1 and id or 0 end,
                         skip = function(_, value) answer = value end})
    end
    if not answer then
        return nil
    end
    local chars = {}
    while memory[answer + #chars] and memory[answer + #chars] ~= 0 do
        table.insert(chars, string.char(memory[answer + #chars]))
    end
    return table.concat(chars)
end
check(localise(hash.name("idgun_S_WEAPON")) == "Apothicon Servant", "the in-game name is the prompt's")
check(localise(hash.name("thundergun_S_WEAPON")) == nil, "other weapons keep the game's names")
os.execute("rm -rf " .. dir)
print("prefabs_test: OK")
