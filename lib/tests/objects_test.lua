-- boz.objects against a fake game: lua5.4 lib/tests/objects_test.lua (from the SDK root).
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
local fake = require("fake_game").install({strict = true})
local memory, symbols, functions, hooks, calls, frames = fake.memory, fake.symbols, fake.functions, fake.hooks,
    fake.calls, fake.frames
local address, run_hook, frame, check, called = fake.address, fake.run_hook, fake.frame, fake.check, fake.called

-- A level: the level manager, a player, a wall (with a child model) and a trigger volume.
local LEVEL, PLAYER, WALL, WALL_PART, TRIGGER, TRIGGER_BOX = 0x8000, 0x8100, 0x8200, 0x8300, 0x8400, 0x8500
memory[address("CLevelManager::s_instance")] = LEVEL
memory[LEVEL + 0x1a0] = PLAYER
memory[LEVEL + 0x290] = 0x9000
for entity, id in pairs({[PLAYER] = 1, [WALL] = 2, [WALL_PART] = 3, [TRIGGER] = 4}) do
    memory[entity + 4] = id
end
local hash = require("boz.hash")
local entities = {[hash.name("Secret_Wall")] = WALL, [hash.name("Secret_Trigger")] = TRIGGER}
local components = {   -- table -> entity id -> component
    ["CIsRenderableModel::s_table"] = {[2] = 0xa200, [3] = 0xa300},
    ["CIsCollisionBox::s_table"] = {[2] = 0xb200, [4] = TRIGGER_BOX},
    ["CIsHierarchy::s_table"] = {[2] = 0xc200},
}
-- The wall's hierarchy: one child (list head 0xd000 -> node 0xd010 -> head).
memory[0xc200 + 0x24] = 0xd000
memory[0xd000] = 0xd010
memory[0xd010] = 0xd000
memory[0xd010 + 8] = 0xe000
memory[0xe000 + 0xc] = WALL_PART
memory[TRIGGER_BOX + 0xc] = TRIGGER
memory[0xf000 + 0xc] = PLAYER   -- the player's collision object

functions["CIsEntityDB::FindEntity"] = function(h) return entities[h] or 0 end
functions["CIsComponentTableBase::Find"] = function(tbl, id)
    for name, at in pairs(symbols) do
        if at == tbl then
            return (components[name] or {})[id] or 0
        end
    end
    return 0
end
for _, name in ipairs({"CIsRenderableModel::SetVisible", "CIsCollisionObject::Enable",
                       "CIsCollisionObject::Disable", "NavMesh_SetTagOpen"}) do
    functions[name] = function() return 0 end
end

local objects = require("boz.objects")
local function check(condition, message)
    if not condition then
        error("FAILED: " .. message, 2)
    end
end
local function called(name)
    local found = {}
    for _, call in ipairs(calls) do
        if call[1] == name then
            table.insert(found, call)
        end
    end
    return found
end

check(objects.find("secret_wall"), "objects are found by name, any case")
check(objects.find("Nope") == nil, "missing objects are nil")

objects.get("Secret_Wall"):hide()
local shown = called("CIsRenderableModel::SetVisible")
check(#shown == 2 and shown[1][2] == 0xa200 and shown[2][2] == 0xa300 and shown[1][3] == 0,
      "hide reaches the object's model and its child's")
objects.get("Secret_Wall"):set_collision(false):open_navmesh()
check(#called("CIsCollisionObject::Disable") == 1, "collision off")
local nav = called("NavMesh_SetTagOpen")
check(#nav == 1 and nav[1][2] == 0x9000 and nav[1][3] == hash.name("Secret_Wall") and nav[1][4] == 1,
      "the walkable area under it opens, tagged with its name")

local entered, used, hurt = nil, nil, nil
objects.on("Secret_Trigger", "enter", function(object, who) entered = {object.name, who.player} end)
objects.on("Secret_Wall", "use", function(object) used = object.name end)
objects.on("Secret_Wall", "damage", function(_, info) hurt = info.amount end)
run_hook("CIsCollisionObject::OnCollisionEnter", {TRIGGER_BOX, 0xf000})
check(entered and entered[1] == "Secret_Trigger" and entered[2] == true, "the player entering a trigger")
memory[LEVEL + 0x214] = WALL
run_hook("Poi_SendUse", {})
check(used and used:lower() == "secret_wall", "use at an object")
memory[0xa900 + 0xc] = WALL
run_hook("CHealth::Damage", {0xa900, 75, PLAYER})
check(hurt == 75, "damage to an object")
objects.on("Secret_Wall", "use", function() error("broken handler") end)
run_hook("Poi_SendUse", {})   -- logged, the other handlers keep working
print("objects_test: OK")
