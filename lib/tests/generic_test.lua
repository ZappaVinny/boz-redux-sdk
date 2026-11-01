-- boz.reflect, boz.game_events and boz.entities against a fake game:
-- lua5.4 lib/tests/generic_test.lua (from the SDK root).
package.path = "lib/?.lua;" .. package.path

local memory, strings, hooks, calls = {}, {}, {}, {}
local symbols = {["CIsComponentTableBase::Find"] = 0x10, ["CIsSubject::Dispatch"] = 0x20,
                 ["CIsSubject::NotifyVirtual"] = 0x30, ["CIsEntityDB::FindEntity"] = 0x40,
                 ["Spawn_ByHash"] = 0x50, ["EntityDB_Destroy"] = 0x60, ["CIsTransform::FromEntity"] = 0x70,
                 ["CIsTransform::UpdateWorld"] = 0x80, ["Transform_SetDirty"] = 0x90,
                 ["CSpawnManager::s_instance"] = 0x100, ["CIsEntityDB::s_instance"] = 0x104,
                 ["CHealth::s_table"] = 0x200, ["CIsTransform::s_table"] = 0x204}
local tables = {}        -- table address -> {id -> component}
local functions = {}
local next_alloc = 0x900000

game = {
    base = function() return 0x4a000000 end,
    symbol = function(name) return symbols[name] end,
    read = function(kind, at, size)
        if type(at) == "string" then at = symbols[at] end
        if kind == "string" then return strings[at] or "" end
        return memory[at] or 0
    end,
    write = function(kind, at, value) memory[at] = value end,
    alloc = function(size) next_alloc = next_alloc + size return next_alloc - size end,
    call = function(target, ...)
        if type(target) == "string" then target = symbols[target] end
        table.insert(calls, {target, ...})
        local fn = functions[target]
        return fn and fn(...) or 0
    end,
}
local hook_id = 0
hook = {add = function(target, h) hook_id = hook_id + 1 hooks[hook_id] = {target = target, h = h} return hook_id end,
        remove = function(id) hooks[id] = nil end}
events = {on = function() end}
function log(m) print("log: " .. m) end

local function check(condition, message)
    if not condition then error("FAILED: " .. message, 2) end
end

-- The fake world: entity 0x5000 (id 7) with a CHealth at 0x6000 and a transform at 0x7000.
memory[0x5000 + 4] = 7
tables[0x200] = {[7] = 0x6000}
tables[0x204] = {[7] = 0x7000}
memory[0x6000 + 0xc] = 0x5000
functions[0x10] = function(t, id) return (tables[t] or {})[id] or 0 end
functions[0x70] = function(e) return e == 0x5000 and 0x7000 or 0 end
functions[0x80] = function(t) for i = 0, 2 do memory[t + 0x5c + 4 * i] = memory[t + 0xa8 + 4 * i] end end
memory[0x104] = 0xdb
functions[0x40] = function(h) return h == require("boz.hash").name("MysteryBox_Lobby") and 0x5000 or 0 end
memory[0x100] = 0x5a
local spawned
functions[0x50] = function(manager, h, at, rot, name, parent)
    spawned = {h = h, x = memory[at], w = memory[rot], name = name, parent = parent}
    return 0x8000
end

-- boz.reflect
local reflect = require("boz.reflect")
check(reflect.class("CHealth") ~= nil, "CHealth is described")
local f = reflect.fields("CHealth")
check(f.m_Health and f.m_MaxHealth, "its fields")
memory[0x6000 + f.m_MaxHealth[1]] = 230
memory[0x6000 + f.m_Health[1]] = 199.5
check(reflect.get(0x6000, "CHealth", "m_MaxHealth") == 230, "an unsigned int")
check(reflect.get(0x6000, "CHealth", "m_Health") == 199.5, "a float")
check(reflect.set(0x6000, "CHealth", "m_MaxHealth", 400) and memory[0x6000 + f.m_MaxHealth[1]] == 400, "set")
local missing, why = reflect.get(0x6000, "CHealth", "nope")
check(missing == nil and why:find("no field"), "an unknown field says so")
check(reflect.component(0x5000, "CHealth") == 0x6000 and reflect.component({id = 7}, "CHealth") == 0x6000,
      "a component by entity or id")
check(reflect.dump(0x6000, "CHealth").m_MaxHealth == 400, "dump")
check(reflect.object(0x7020, "CTrap") == 0x7000 and reflect.object(0x6000, "CHealth") == 0x6000,
      "a table entry's object: CIsComponent at 0x20 in CTrap, at the start in CHealth")
-- a NetworkProperty field: value at +4, changed flag at +8
local pm = reflect.fields("CPickupManager")
local carpenter = pm.m_CanUseCarpenter[1]
memory[0x9000 + carpenter + 4] = 1
check(reflect.get(0x9000, "CPickupManager", "m_CanUseCarpenter") == true, "a NetworkProperty<bool>")
reflect.set(0x9000, "CPickupManager", "m_CanUseCarpenter", false)
check(memory[0x9000 + carpenter + 4] == 0 and memory[0x9000 + carpenter + 8] == 1, "set marks it changed")
-- a vector<unsigned int>
local wave = reflect.fields("CWaveSpeciality")
memory[0xa000 + wave.m_ZombieTypes[1]] = 0xb000
memory[0xa000 + wave.m_ZombieTypes[1] + 4] = 0xb008
memory[0xb000], memory[0xb004] = 11, 22
local looks = reflect.get(0xa000, "CWaveSpeciality", "m_ZombieTypes")
check(#looks == 2 and looks[2] == 22, "a vector")
check(#reflect.classes() > 300, "every class")

-- boz.game_events
local game_events = require("boz.game_events")
local hash = require("boz.hash")
check(game_events.id("zombie_death") == hash.name("SUBJECT_ZOMBIE_DEATH"), "the SUBJECT_ prefix is optional")
check(game_events.name(hash.name("SUBJECT_TRANSFORM_UPDATED")) == "SUBJECT_TRANSFORM_UPDATED", "engine events are named")
check(next(hooks) == nil, "no hook while nothing listens")
local got
local handle = game_events.on("SUBJECT_ZOMBIE_DEATH", function(e) got = e end)
local dispatch = next(hooks)
check(dispatch and hooks[dispatch].target == 0x20, "Dispatch is hooked once something listens")
local skipped = false
local function fire(id, a)
    local c = {arg = function(_, i) return ({0xd00, id, a, 0, 0xe00})[i] end, skip = function() skipped = true end}
    hooks[dispatch].h.before(c)
end
fire(hash.name("SUBJECT_ZOMBIE_DEATH"), 5)
check(got and got.name == "SUBJECT_ZOMBIE_DEATH" and got.a == 5 and got.subject == 0xd00 and got.sender == 0xe00,
      "a handler gets the event")
got = nil
fire(hash.name("SUBJECT_UPDATE_LOD"), 1)
check(got == nil, "other events do not reach it")
local blocker = game_events.on("SUBJECT_NUKE_NOW", function() return true end)
fire(hash.name("SUBJECT_NUKE_NOW"), 0)
check(skipped, "returning true stops the event")
game_events.off(handle)
game_events.off(blocker)
check(next(hooks) == nil, "the hook goes once nothing listens")
check(game_events.send(0xd00, "nuke_now") and calls[#calls][1] == 0x30 and calls[#calls][3] == hash.name("SUBJECT_NUKE_NOW"),
      "send")

-- boz.entities
local entities = require("boz.entities")
check(entities.find("MysteryBox_Lobby") == 0x5000 and entities.find("nothing") == nil, "find by name")
memory[0x7000 + 0xa8], memory[0x7000 + 0xac], memory[0x7000 + 0xb0] = 10, 20, 30
check(entities.position(0x5000).y == 20, "position")
check(entities.set_position(0x5000, {x = 1, y = 2, z = 3}) and memory[0x7000 + 0xac] == 2, "set position")
check(entities.set_rotation(0x5000, 180) and math.abs(memory[0x7000 + 0x98 + 8] - 1) < 1e-9, "rotation by degrees")
check(entities.component(0x5000, "CHealth") == 0x6000, "a component")
local list = entities.components(0x5000)
check(#list == 2 and list[1] == "CHealth", "its components")
local seen = {}
for entity, component in entities.each("CHealth") do seen[entity] = component end
check(entities.of_component(0x6000) == 0x5000, "a component's entity")
check(entities.spawn("zombie_dog", {x = 5, y = 0, z = 0}) == 0x8000 and spawned.h == hash.name("zombie_dog")
      and spawned.x == 5 and spawned.w == 1 and spawned.name == 0 and spawned.parent == 0, "spawn")
entities.remove(0x8000)
check(calls[#calls][1] == 0x60 and calls[#calls][3] == 0x8000, "remove")
print("generic_test: OK")
