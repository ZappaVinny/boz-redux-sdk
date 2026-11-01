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
--   (boz.map.nearest_poi).
-- - "damage": CHealth::Damage(health, amount, attacker name hash) on objects with health.
-- - "hit": CEasterEgg::OnEvent runs when a weapon hits a skull (Hit volumes are made from the
--   musical easter egg's skulls); for objects with "hit" handlers the game's handling is skipped,
--   so they stay out of the level's own easter egg.
-- - Positions: the entity's CIsTransform keeps its world matrix at +0x38, the position at
--   +0x5c/+0x60/+0x64 (game centimetres, y up); CIsTransform::UpdateWorld refreshes it when the
--   transform moved.

local core = require("boz.core")
local hash = require("boz.hash")
local components = require("boz.components")
local map = require("boz.map")

local objects = {}

local COLLISION_CLASSES = {"CIsCollisionBox", "CIsCollisionSphere", "CIsCollisionCapsule", "CIsCollisionMesh"}
local LEVEL_NAVMESH = 0x290     -- CLevelManager: the level's NavMesh resource
local COMPONENT_ENTITY = 0xc
local ENTITY_ID = 4
local HIERARCHY_CHILDREN = 0x24
local TRANSFORM_POSITION = 0x5c

local function find_component(class_name, entity)
    if entity == 0 then
        return nil
    end
    return components.find(class_name, game.read("u32", entity + ENTITY_ID))
end

local level_key = map.level_key

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

local aliases = nil   -- lower world name -> the entity's name in the game

-- The name an object's entity has in the game: its world name, except where the map renamed it
-- (world_data aliases: a new map's power switch is always PowerSwitch, the level listens to it).
local function entity_name(name)
    if aliases == nil then
        aliases = {}
        local ok, data = pcall(require, "boz.world_data")
        for world_name, game_name in pairs(ok and type(data) == "table" and data.aliases or {}) do
            aliases[string.lower(world_name)] = game_name
        end
    end
    return aliases[string.lower(name)] or name
end

--- The object called `name` (a handle: it finds the entity when used, so it can be made before
--- the level loads). Names are not case-sensitive.
function objects.get(name)
    local key = string.lower(name)
    local object = by_name[key]
    if not object then
        object = setmetatable({name = name, hash = hash.name(entity_name(name)), entity = 0,
                               level = nil}, Object)
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
        self.entity = key ~= 0 and core.call("CIsEntityDB::FindEntity", self.hash) or 0
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
    local hierarchy = find_component("CIsHierarchy", entity)
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

local hidden = {}   -- lower name -> true while hidden

--- True while the object called *name* is hidden (set_visible): a hidden volume sends nothing.
function objects.is_hidden(name)
    return hidden[string.lower(name)] == true
end

--- Forgets which objects were hidden: a level that starts (or restarts) shows every object, so
--- the volumes of objects a script hid in the last run send their events again.
function objects.forget_hidden()
    hidden = {}
end

--- Shows or hides the object's models (its collision stays; a hidden volume sends no events and
--- shows no prompt). Returns the object.
function Object:set_visible(visible)
    hidden[string.lower(self.name)] = not visible or nil
    each_entity(self:entity_pointer(), function(entity)
        local model = find_component("CIsRenderableModel", entity)
        if model then
            core.call("CIsRenderableModel::SetVisible", model, visible and 1 or 0)
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
    local target = enabled and "CIsCollisionObject::Enable" or "CIsCollisionObject::Disable"
    local function switch(entity)
        for _, class_name in ipairs(COLLISION_CLASSES) do
            local shape = find_component(class_name, entity)
            if shape then
                core.call(target, shape)
            end
        end
    end
    each_entity(self:entity_pointer(), switch)
    -- Meshes and props scripts change have their collision in an entity of its own.
    each_entity(objects.get(self.name .. "_collision"):entity_pointer(), switch)
    return self
end

-- Doors call NavMesh_SetTagOpen when they start: the navmesh it is given keeps this working if
-- the level manager's pointer moves in another game version.
local function capture_navmesh()
    if captured_navmesh ~= nil then
        return
    end
    captured_navmesh = false
    hook.add(core.sym("NavMesh_SetTagOpen"), {before = function(call)
        captured_navmesh = {resource = call:arg(1), level = level_key()}
    end})
end

local function navmesh()
    capture_navmesh()
    if captured_navmesh and captured_navmesh.level == level_key() then
        return captured_navmesh.resource
    end
    local level = map.level_manager()   -- Level_Load stores the NavMesh resource here
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
    core.call("NavMesh_SetTagOpen", resource, hash.name(tag), open and 1 or 0)
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

--- The world position of a CIsTransform component: {x, y, z} in game centimetres (y is up).
function objects.transform_position(transform)
    if transform == 0 then
        return nil
    end
    core.call("CIsTransform::UpdateWorld", transform)
    return core.read_vec3(transform + TRANSFORM_POSITION)
end

--- The world position of an entity (pointer), or nil when it has no transform.
function objects.position_of(entity)
    local transform = find_component("CIsTransform", entity or 0)
    return transform and objects.transform_position(transform)
end

local function point_of(target)
    if type(target) == "table" and target.x then
        return target
    end
    if type(target) == "table" and type(target.position) == "function" then
        return target:position()
    end
    return nil
end

--- The distance in centimetres between two positions or objects (anything with :position()),
--- or nil when either has no position.
function objects.distance(a, b)
    local p, q = point_of(a), point_of(b)
    if not p or not q then
        return nil
    end
    local dx, dy, dz = p.x - q.x, p.y - q.y, p.z - q.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)
end

--- The object's world position {x, y, z} (game centimetres, y is up), or nil when it is not in
--- the running level.
function Object:position()
    return objects.position_of(self:entity_pointer())
end

--- True when the object is within `distance` centimetres of `target` (a position such as
--- zombie_killed's data.position, or another object).
function Object:near(target, distance)
    local d = objects.distance(self, target)
    return d ~= nil and d <= distance
end

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
    return {
        entity = entity,
        player = entity ~= 0 and entity == map.player(),
        zombie = find_component("CAIControllerZombie", entity) ~= nil,
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
    hook.add(core.sym(target), {before = function(call)
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
        hook.add(core.sym("Poi_SendUse"), {before = function()
            local object = object_of(map.nearest_poi())
            if object then
                fire("use", object, who_is(map.player() or 0))
            end
        end})
    end,
    hit = function()
        hook.add(core.sym("CEasterEgg::OnEvent"), {before = function(call)
            local egg = call:arg(1)
            local object = egg ~= 0 and object_of(game.read("ptr", egg + COMPONENT_ENTITY))
            if object and handlers.hit and handlers.hit[object] then
                fire("hit", object, who_is(map.player() or 0))
                call:skip()
            end
        end})
    end,
    damage = function()
        hook.add(core.sym("CHealth::Damage"), {before = function(call)
            local health = call:arg(1)
            local object = health ~= 0 and object_of(game.read("ptr", health + COMPONENT_ENTITY))
            if object then
                local attacker = call:arg(3)
                local entity = attacker ~= 0 and require("boz.entities").find(attacker) or 0
                fire("damage", object, {amount = call:arg_signed(2), attacker = who_is(entity or 0)})
            end
        end})
    end,
}

--- Calls `fn(object, info)` on the object's `event`:
--- "enter" / "exit" (something starts or stops touching it; info.player, info.zombie,
--- info.entity), "use" (the player pressed use at it), "hit" (a weapon hit it: Hit volumes),
--- "damage" (it was hurt; info.amount, info.attacker). Returns the object.
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

return objects
