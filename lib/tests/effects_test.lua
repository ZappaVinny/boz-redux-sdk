-- boz.effects against a fake game: lua5.4 lib/tests/effects_test.lua (from the SDK root).
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
local fake = require("fake_game").install({strict = true, signed = true})
local memory, symbols, functions, hooks, calls, frames = fake.memory, fake.symbols, fake.functions, fake.hooks,
    fake.calls, fake.frames
local address, run_hook, frame, check, called = fake.address, fake.run_hook, fake.frame, fake.check, fake.called

local hash = require("boz.hash")
local MANAGER, PLAYER, GERSCH = 0xa000, 0x77, 0x8eae245e
package.loaded["boz.weapons"] = {manager = function() return MANAGER end}
memory[address("CSpawnManager::s_instance")] = 0x5000
memory[address("CIsEntityDB::s_instance")] = 0x5100
memory[address("CIwSoundManager::s_instance")] = 0x5200
memory[address("CLevelManager::s_instance")] = 0x5300
memory[0x5300 + 0x1a0] = PLAYER

-- The fake world: entities are objects (id at +4) with a transform; a projectile is set up by
-- "the game" (its transform linked at +0x7c, its rigid body found) only on the next frame, and
-- touching its body or sending it events before that is what crashed the real game.
local alive, spawned, defer_open, unset = {}, {}, false, {}
local next_id = 0x100
local function transform(e) return e + 0x1000 end
local function projectile(e) return e + 0x2000 end
local function rigid(e) return e + 0x3000 end
functions["Spawn_ByHash"] = function(manager, h, at, rot, name, parent)
    if name ~= 0 or parent ~= 0 then error("Spawn_ByHash needs name 0 and parent 0") end
    if h == hash.name("nothing") then return 0 end
    next_id = next_id + 1
    local e = 0xa0000000 + next_id * 0x10000          -- heap addresses above 0x80000000
    memory[e + 4] = next_id
    alive[next_id] = e
    spawned[e] = {hash = h, x = memory[at], y = memory[at + 4], z = memory[at + 8], w = memory[rot]}
    for i = 0, 2 do memory[transform(e) + 0xa8 + 4 * i] = memory[at + 4 * i] end
    if h == GERSCH then unset[e] = true end
    return e
end
local function game_sets_up()          -- what CProjectileEntity::Init does, a frame later
    for e in pairs(unset) do
        memory[projectile(e) + 0x7c] = transform(e)
        memory[projectile(e) + 0x80] = rigid(e)
        memory[rigid(e) + 0x34] = e + 0x4000
        memory[projectile(e) + 0x90] = memory[projectile(e) + 0x90] or 1.5      -- m_proximityRadius
        unset[e] = nil
    end
end
functions["CIsEntityDB::GetEntity"] = function(lookup)      -- the record: not the spawn handle
    return alive[memory[lookup + 4]] and alive[memory[lookup + 4]] + 0x8000 or 0
end
functions["CIsTransform::FromEntity"] = function(e)
    return spawned[e] and spawned[e].hash == hash.name("a_part") and 0 or transform(e)
end
functions["CIsRigidBody::FromEntity"] = function(e) return rigid(e) end
functions["CIsTransform::UpdateWorld"] = function(t)
    for i = 0, 2 do memory[t + 0x5c + 4 * i] = memory[t + 0xa8 + 4 * i] end
end
functions["Transform_SetDirty"] = function() end
functions["CProjectileEntity::FromEntity"] = function(e)
    return spawned[e] and spawned[e].hash == GERSCH and projectile(e) or 0
end
local function open(p)
    memory[p + 0xc7] = 1
    memory[p + 0xc0] = 8000
end
local early = false
functions["CIsSubject::NotifyVirtual"] = function(subject, event)
    local p = subject - 0x28
    if memory[p + 0x7c] == nil then early = true end
    if event == hash.name("SUBJECT_SPAWN_GERSCH_EFFECT") and not defer_open then open(p) end
    if event == hash.name("SUBJECT_TERMINATE") then
        for id, e in pairs(alive) do if projectile(e) == p then alive[id] = nil end end
    end
end
functions["EntityDB_Destroy"] = function(_db, e) alive[memory[e + 4]] = nil end
functions["Physics_SetActivation"] = function(body)
    if body == nil or body == 0 then early = true end
end
functions["CIwSoundManager::Play"] = function() end
functions["CIsComponentTableBase::Find"] = function(table, id) return alive[id] and alive[id] + 0x5000 or 0 end
functions["CIsRenderableModel::SetVisible"] = function() end
local real_frame = frame
frame = function(dt) game_sets_up(); real_frame(dt) end

local effects = require("boz.effects")

-- A one-off effect by the game's name, removed after its lifetime.
local spark = effects.spawn("impactRayGun", {x = 1, y = 2, z = 3}, {lifetime = 0.5})
check(spark and spawned[spark.entity].hash == hash.name("impactRayGun"), "an effect spawns by its game name")
check(spawned[spark.entity].x == 1 and spawned[spark.entity].y == 2 and spawned[spark.entity].w == 1,
      "at the position, unturned")
check(spark:position().z == 3, "its position")
frame(0.3)
check(spark:alive(), "alive within its lifetime")
frame(0.3)
check(not spark:alive() and #called("EntityDB_Destroy") == 1, "removed after its lifetime")
local missing, why = effects.spawn("nothing", {0, 0, 0})
check(missing == nil and why:find("Effects tab"), "an effect the map does not have says so")
local destroyed = #called("EntityDB_Destroy")
local part, part_why = effects.spawn("a_part", {0, 0, 0})
check(part == nil and part_why:find("part of another") and #called("EntityDB_Destroy") == destroyed + 1,
      "a part of another effect is removed at once (drawing it would crash)")

-- The map's black hole by its project name: set up only once the game has set it up.
effects.know({{name = "gersch", hash = GERSCH, kind = "projectile", behaviour = 6, triggers = {"open"}}})
check(effects.known().gersch.behaviour == 6, "the map's effects are known")
local hole = effects.projectile("gersch", {x = 10, y = 0, z = 20}, {trigger = "open", lifetime = 6, hidden = true, raise = 120})
local p = projectile(hole.entity)
check(spawned[hole.entity].hash == GERSCH and spawned[hole.entity].y == 120, "a raised one floats 120 cm up")
check(memory[p + 0x88] == PLAYER and memory[p + 0xec] == GERSCH,
      "its owner and spec go in right away (zombies read the owner)")
check(not hole:ready() and memory[p + 0xc7] == nil and #called("CIsRenderableModel::SetVisible") == 0,
      "nothing else touches it before the game has set it up")
frame(0.016)
check(hole:ready() and not early, "set up a frame later, never before")
check(called("CIsRenderableModel::SetVisible")[1][3] == 0, "its model is hidden")
check(memory[p + 0xc7] == 1, "it opens")
check(math.abs(memory[p + 0x90] - math.sqrt(1.5 ^ 2 + 1.2 ^ 2)) < 1e-6, "its kill reach grows to the floor")
check(memory[p + 0xc0] == 6000 and memory[p + 0xc4] == 1, "for the lifetime asked (not the game's 8 s)")
check(hole:freeze() and #called("Physics_SetActivation") == 1, "freeze once set up")
hole:remove()
check(not hole:alive(), "remove ends it the game's way")
check(hole:position() == nil and not hole:trigger("open"), "a removed one is left alone")

-- A black hole that opens a frame after the trigger still gets its lifetime.
defer_open = true
local late = effects.projectile("gersch", {x = 0, y = 0, z = 0}, {trigger = "open", lifetime = 3})
check(spawned[late.entity].y == 10, "a projectile spawns 10 cm up")
frame(0.016)                            -- set up and triggered; the game opens it next frame
open(projectile(late.entity))           -- ... with its 8 s
frame(0.016)
check(memory[projectile(late.entity) + 0xc0] == 3000, "the lifetime is given again once it opens")
check(memory[projectile(late.entity) + 0x90] == 1.5, "an unraised one keeps the game's kill reach")
check(not late:trigger("bogus") and late:trigger("explode"), "triggers it answers")
check(effects.projectile("impactRayGun", {0, 0, 0}) == nil, "an effect is not a projectile")
check(not early, "nothing ever touched a projectile before it was set up")

-- Where the crosshair is.
memory[MANAGER + 0xcc], memory[MANAGER + 0xd0], memory[MANAGER + 0xd4] = 100.0, 5.0, -40.0
memory[MANAGER + 0xf0] = 1
local aim, zombie = effects.aim()
check(aim.x == 100.0 and aim.z == -40.0 and zombie, "the crosshair point")
-- zombies.credit_kills: damage a zombie deals itself handling the event is the player's.
do
    local h = require("boz.hash")
    require("boz.zombies").credit_kills("SUBJECT_ZOMBIE_GERSCH_DEATH")
    memory[0x7100 + 0xd4] = 0x7000          -- the zombie controller's CHealth
    functions["CIsEntityDB::GetEntity"] = function(e) return e == PLAYER and 0x6300 or 0 end
    functions["Entity_GetNameHash"] = function(r) return r == 0x6300 and 0xabc or 0 end
    local args = {0x7000, 0x7ffffffe, 0}
    run_hook("CHealth::Damage", args)
    check(args[3] == 0, "other damage keeps its attacker")
    run_hook("CAIControllerZombie::OnEvent", {0x7100, 0, h.name("SUBJECT_ZOMBIE_GERSCH_DEATH")})
    args = {0x7000, 0x7ffffffe, 0}
    run_hook("CHealth::Damage", args)
    check(args[3] == 0xabc, "a black hole kill is the player's")
    args = {0x7000, 0x7ffffffe, 0}
    run_hook("CHealth::Damage", args)
    check(args[3] == 0, "only the damage of that event")
end
print("effects_test: OK")
