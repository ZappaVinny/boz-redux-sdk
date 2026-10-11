-- boz.objects: the map's objects by name: show and hide them, switch their collision, open and
-- close the walkable area under them, and react when players walk into them, use them or shoot
-- them. The building blocks for triggers and easter eggs.
--
--   local objects = require("boz.objects")
--   local skull = objects.get("Skull_1")
--   skull:on("use", function(object) object:hide() end)
--   objects.on("Secret_Room_Trigger", "enter", function(object, who)
--       if who.player then objects.get("Secret_Wall"):hide():set_collision(false):open_navmesh() end
--   end)
--
-- Names are the script names the editor shows for each object (Properties → Object → Game →
-- Scripts): turn on "Scripts can change it" there. Shipped entities use their own names.
--
-- How it works (Ghidra names in the game definition):
-- - CIsEntityDB::FindEntity(name hash) gives the entity (a pointer; its id is at +4). A
--   component's entity pointer is at component +0xc; children hang off CIsHierarchy +0x24.
-- - Visibility: CIsRenderableModel::SetVisible (doors hide this way after opening).
-- - Collision: CIsCollisionObject::Enable / Disable on the entity's collision box, sphere,
--   capsule or mesh (what SUBJECT_ENABLE/DISABLE_COLLISION do).
-- - Walkable area: navmesh polygons carry a tag (a name hash); NavMesh_SetTagOpen(navmesh, tag,
--   open) opens or closes them, as doors do with their own name. The editor tags the polygons
--   under objects set to block the walkable area with the object's name.
-- - "enter"/"exit": CIsCollisionObject::OnCollisionEnter/OnCollisionExit (this, other) run
--   when two collision objects start or stop touching; ghost volumes (triggers) get them too.
-- - "use": Poi_SendUse runs when the player presses use at the point of interest in reach
--   (entity at CLevelManager +0x214).
-- - "damage": CHealth::Damage(health, amount, attacker) on objects with health (shootables).

local hash = require("boz.hash")
local components = require("boz.components")

local objects = {}

-- Image offsets of what is used here, for clients whose game definition predates these names.
local FALLBACK = {
    ["CIsEntityDB::FindEntity"] = 0x0bd514 + 1,
    ["CIsRenderableModel::SetVisible"] = 0x22c5a8 + 1,
    ["CIsCollisionObject::Enable"] = 0x052c78 + 1,
    ["CIsCollisionObject::Disable"] = 0x052df4 + 1,
    ["CIsCollisionObject::OnCollisionEnter"] = 0x052c10 + 1,
    ["CIsCollisionObject::OnCollisionExit"] = 0x052c58 + 1,
    ["NavMesh_SetTagOpen"] = 0x0a3a0c + 1,
    ["Poi_SendUse"] = 0x19fd48 + 1,
    ["CHealth::Damage"] = 0x199754 + 1,
    ["CIsRenderableModel::s_table"] = 0x4712e4,
    ["CIsCollisionBox::s_table"] = 0x4519ac,
    ["CIsCollisionSphere::s_table"] = 0x451da4,
    ["CIsCollisionCapsule::s_table"] = 0x451aec,
    ["CIsCollisionMesh::s_table"] = 0x451c50,
    ["CIsHierarchy::s_table"] = 0x457a5c,
    ["CEntityFlags::s_table"] = 0x4669cc,
    ["CAIControllerZombie::s_table"] = 0x460d24,
}
local COLLISION_TABLES = {"CIsCollisionBox::s_table", "CIsCollisionSphere::s_table",
                          "CIsCollisionCapsule::s_table", "CIsCollisionMesh::s_table"}
local LEVEL_PLAYER = 0x1a0      -- CLevelManager: the local player's entity
local LEVEL_NEAREST_POI = 0x214 -- CLevelManager: the point of interest in reach
local LEVEL_NAVMESH = 0x290     -- CLevelManager: the level's NavMesh resource
local COMPONENT_ENTITY = 0xc
local ENTITY_ID = 4
local HIERARCHY_CHILDREN = 0x24

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function find_component(table_name, entity)
    if entity == 0 then
        return nil
    end
    local found = game.call("CIsComponentTableBase::Find", sym(table_name),
                            game.read("u32", entity + ENTITY_ID))
    return found ~= 0 and found or nil
end

local function level_manager()
    local level = game.read("ptr", "CLevelManager::s_instance")
    return level ~= 0 and level or nil
end

-- The current level, to drop cached entities when another one loads.
local function level_key()
    local level = level_manager()
    return level and game.read("ptr", level + LEVEL_PLAYER) or 0
end

local Object = {}
Object.__index = Object

local by_name = {}      -- lower-case name -> Object
local handlers = {}     -- event -> {object -> {fn, ...}}
local hooked = {}
local captured_navmesh = nil

--- A key that changes when another level loads (0 outside a match).
function objects.level()
    return level_key()
end

--- The object called `name` (a handle: it finds the entity when used, so it can be made before
--- the level loads). Names are not case-sensitive.
function objects.get(name)
    local key = string.lower(name)
    local object = by_name[key]
    if not object then
        object = setmetatable({name = name, hash = hash.name(name), entity = 0, level = nil}, Object)
        by_name[key] = object
    end
    return object
end

--- The object called `name` if it exists in the running level, else nil.
function objects.find(name)
    local object = objects.get(name)
    return object:exists() and object or nil
end

--- The entity pointer, or 0 when the object is not in the running level.
function Object:entity_pointer()
    local key = level_key()
    if self.level ~= key or (key ~= 0 and self.entity == 0) then
        self.level = key
        self.entity = key ~= 0 and game.call(sym("CIsEntityDB::FindEntity"), self.hash) or 0
    end
    return self.entity
end

--- True when the object is in the running level.
function Object:exists()
    return self:entity_pointer() ~= 0
end

-- The entity and its children (parts such as a wall buy's weapon model).
local function each_entity(entity, fn, depth)
    if entity == 0 or (depth or 0) > 8 then
        return
    end
    fn(entity)
    local hierarchy = find_component("CIsHierarchy::s_table", entity)
    if not hierarchy then
        return
    end
    local list = game.read("ptr", hierarchy + HIERARCHY_CHILDREN)
    if list == 0 then
        return
    end
    local node = game.read("ptr", list)
    local steps = 0
    while node ~= 0 and node ~= list and steps < 64 do
        local child = game.read("ptr", node + 8)
        if child ~= 0 then
            each_entity(game.read("ptr", child + COMPONENT_ENTITY), fn, (depth or 0) + 1)
        end
        node = game.read("ptr", node)
        steps = steps + 1
    end
end

--- Shows or hides the object's models (its collision and behaviour stay). Returns the object.
function Object:set_visible(visible)
    each_entity(self:entity_pointer(), function(entity)
        local model = find_component("CIsRenderableModel::s_table", entity)
        if model then
            game.call(sym("CIsRenderableModel::SetVisible"), model, visible and 1 or 0)
        end
    end)
    return self
end

--- Shows the object. Returns the object.
function Object:show()
    return self:set_visible(true)
end

--- Hides the object. Returns the object.
function Object:hide()
    return self:set_visible(false)
end

--- Switches the object's collision on or off (players and bullets pass through it when off).
--- Returns the object.
function Object:set_collision(enabled)
    local target = sym(enabled and "CIsCollisionObject::Enable" or "CIsCollisionObject::Disable")
    local function switch(entity)
        for _, table_name in ipairs(COLLISION_TABLES) do
            local shape = find_component(table_name, entity)
            if shape then
                game.call(target, shape)
            end
        end
    end
    each_entity(self:entity_pointer(), switch)
    -- Meshes and props scripts change have their collision in an entity of its own.
    each_entity(objects.get(self.name .. "_collision"):entity_pointer(), switch)
    return self
end

local function navmesh()
    if captured_navmesh and captured_navmesh.level == level_key() then
        return captured_navmesh.resource
    end
    local level = level_manager()   -- Level_Load stores the NavMesh resource here
    local resource = level and game.read("ptr", level + LEVEL_NAVMESH) or 0
    return resource ~= 0 and resource or nil
end

--- Opens (true) or closes (false) the walkable area tagged `tag` (a name: an object set to block
--- the walkable area, or a door). Returns true when the level has a navmesh.
function objects.set_navmesh(tag, open)
    local resource = navmesh()
    if not resource then
        return false
    end
    game.call(sym("NavMesh_SetTagOpen"), resource, hash.name(tag), open and 1 or 0)
    return true
end

--- Opens or closes the walkable area under the object (it must be set to block the walkable
--- area in the editor). Returns the object.
function Object:set_navmesh(open)
    objects.set_navmesh(self.name, open)
    return self
end

--- Lets zombies and players walk where the object blocked them. Returns the object.
function Object:open_navmesh()
    return self:set_navmesh(true)
end

--- Blocks the walkable area under the object again. Returns the object.
function Object:close_navmesh()
    return self:set_navmesh(false)
end

-- Event plumbing: one hook per event type, installed when the first handler is added.

local function object_of(entity)
    if entity == 0 then
        return nil
    end
    for _, object in pairs(by_name) do
        if object:entity_pointer() == entity then
            return object
        end
    end
    return nil
end

-- Entities of the objects with "enter"/"exit" handlers (and their children: a trigger's box may
-- be a child), rebuilt when a level loads or handlers change. Collisions are frequent, so this
-- stays a table lookup.
local watched = {level = nil, entities = {}}

local function root_object(entity)
    local key = level_key()
    if watched.level ~= key then
        watched.level, watched.entities = key, {}
        for _, event in ipairs({"enter", "exit"}) do
            for object in pairs(handlers[event] or {}) do
                each_entity(object:entity_pointer(), function(child)
                    watched.entities[child] = object
                end)
            end
        end
    end
    return watched.entities[entity]
end

local function who_is(entity)
    local level = level_manager()
    local player = level and game.read("ptr", level + LEVEL_PLAYER) or 0
    return {
        entity = entity,
        player = entity ~= 0 and entity == player,
        zombie = find_component("CAIControllerZombie::s_table", entity) ~= nil,
    }
end

local function fire(event, object, ...)
    local list = handlers[event] and handlers[event][object]
    if not list then
        return
    end
    for _, fn in ipairs(list) do
        local ok, err = pcall(fn, object, ...)
        if not ok then
            log("boz.objects: " .. event .. " handler of " .. object.name .. ": " .. tostring(err))
        end
    end
end

local function collision_hook(event, target)
    hook.add(sym(target), {before = function(call)
        local this, other = call:arg(1), call:arg(2)
        if this == 0 or other == 0 then
            return
        end
        local object = root_object(game.read("ptr", this + COMPONENT_ENTITY))
        if object then
            fire(event, object, who_is(game.read("ptr", other + COMPONENT_ENTITY)))
        end
    end})
end

local INSTALL = {
    enter = function() collision_hook("enter", "CIsCollisionObject::OnCollisionEnter") end,
    exit = function() collision_hook("exit", "CIsCollisionObject::OnCollisionExit") end,
    use = function()
        hook.add(sym("Poi_SendUse"), {before = function()
            local level = level_manager()
            local entity = level and game.read("ptr", level + LEVEL_NEAREST_POI) or 0
            -- The game keeps an entity pointer here (CIsEntityDB::GetEntity reads its +4).
            local object = object_of(entity)
            if object then
                fire("use", object, who_is(game.read("ptr", level + LEVEL_PLAYER)))
            end
        end})
    end,
    damage = function()
        hook.add(sym("CHealth::Damage"), {before = function(call)
            local health = call:arg(1)
            local object = health ~= 0 and object_of(game.read("ptr", health + COMPONENT_ENTITY))
            if object then
                fire("damage", object, {amount = call:arg_signed(2),
                                        attacker = who_is(call:arg(3))})
            end
        end})
    end,
}

--- Calls `fn(object, info)` on the object's `event`:
--- "enter" / "exit" (something starts or stops touching it; info.player, info.zombie,
--- info.entity), "use" (the player pressed use at it), "damage" (it was hurt; info.amount,
--- info.attacker). Returns the object.
function Object:on(event, fn)
    assert(INSTALL[event], "boz.objects: unknown event " .. tostring(event))
    if not hooked[event] then
        hooked[event] = true
        INSTALL[event]()
    end
    handlers[event] = handlers[event] or {}
    handlers[event][self] = handlers[event][self] or {}
    table.insert(handlers[event][self], fn)
    watched.level = nil
    return self
end

--- objects.on(name, event, fn): the same as objects.get(name):on(event, fn).
function objects.on(name, event, fn)
    return objects.get(name):on(event, fn)
end

-- Doors call NavMesh_SetTagOpen when they start: remember the navmesh in case the level
-- manager's pointer moves in another game version.
hook.add(sym("NavMesh_SetTagOpen"), {before = function(call)
    captured_navmesh = {resource = call:arg(1), level = level_key()}
end})

return objects
