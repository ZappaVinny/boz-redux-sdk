-- boz.Object: any object in the map (a model, a volume, a part), by its editor name.
--
--   local wall = boz.get("Secret_Wall")
--   wall:hide()                        -- Visible off: unseen, walk and shoot through it
--   wall:set_blocks_walking(false)     -- players and zombies walk through it
--   wall:on("hit", function(wall, player) player:give_points(10) end)

local Class = require("boz.class")
local engine = require("boz.engine.objects")
local net = require("boz.engine.net")

---@class boz.Object
local Object = Class:extend("Object")

-- event name -> {lower object name -> {{fn, level}, ...}}: who listens (Object:on). Listeners a
-- level's objects add (level = true) go when the level ends; a map script's stay.
local listeners = {}
Object._in_level = false   -- true while the level's objects run their code (boz.prefabs)

--- Sets up the object called name (entry: what the map knows about it).
function Object:init(name, entry)
    self.name = name
    self.kind = (entry or {}).kind or "model"      -- "model", "volume" or "prefab"
    self._entry = entry or {}
    self._handle = engine.get(name)
end

-- Co-op: a change the host makes goes to every game; a guest leaves it to the host
-- (boz.engine.net). True when this game should not make it now.
function Object:_shared(op, value)
    return net.route(op, {name = self.name, value = value}) == "skip"
end

local function knows(args)
    return require("boz.objects.runtime").knows(args.name)
end

for op, method in pairs({visible = "set_visible", walking = "set_blocks_walking",
                          bullets = "set_stops_bullets"}) do
    net.op(op, function(args)
        local object = require("boz.objects.runtime").get(args.name)
        if object then object[method](object, args.value) end
    end, knows)
end

--- Shows (true) or hides (false) it. Hidden, it stops nothing and blocks nothing.
function Object:set_visible(visible)
    if self:_shared("visible", visible) then return self end
    self._handle:set_visible(visible)
    return self
end

function Object:show() return self:set_visible(true) end
function Object:hide() return self:set_visible(false) end

--- True unless hidden.
function Object:visible()
    return not engine.is_hidden(self.name)
end

--- Walking: true, players and zombies cannot walk through it (needs Walking: Blocks).
function Object:set_blocks_walking(blocks)
    if self:_shared("walking", blocks) then return self end
    self.walking_blocked = blocks
    self._handle:set_blocks_walking(blocks)
    return self
end

--- Stops bullets: false, shots pass through it.
function Object:set_stops_bullets(stops)
    if self:_shared("bullets", stops) then return self end
    self.bullets_stopped = stops
    self._handle:set_stops_bullets(stops)
    return self
end

--- True while players and zombies cannot walk through it (hidden, nothing is blocked).
function Object:blocks_walking()
    local blocks = self.walking_blocked
    if blocks == nil then
        blocks = engine.starts_blocking(self.name)
    end
    return blocks and self:visible()
end

--- True while shots hit it (hidden, nothing is hit).
function Object:stops_bullets()
    local stops = self.bullets_stopped
    if stops == nil then
        stops = engine.starts_solid(self.name)
    end
    return stops and self:visible()
end

-- Moving and turning (boz.engine.motion). A prefab of yours moves around where it stands in
-- the editor, with all its parts; anything else around itself.
local motion = require("boz.engine.motion")

-- What motion needs for it: the place a prefab of yours stands on and its parts (Prefab).
function Object:_motion() return nil, nil end

local function point(value, what)
    if type(value) == "table" and type(value.position) == "function" then
        value = value:position()
    end
    local p = motion.vec(value)
    if not p then
        error(what .. " needs a position {x =, y =, z =} or an object", 3)
    end
    return p
end

local function glide(self, target, options)
    options = options or {}
    if type(options) ~= "table" then
        error("options must be a table such as {seconds = 2}", 3)
    end
    local done = options.done
    target.seconds, target.ride = options.seconds, options.ride
    if net.route("move", {name = self.name, target = {position = target.position, rotation = target.rotation,
                                                      seconds = target.seconds, ride = target.ride}}) == "skip" then
        return self
    end
    target.done = done and function() done(self) end or nil
    local origin, members = self:_motion()
    if not motion.move(self.name, target, origin, members) then
        log("boz: " .. self.name .. " cannot move: it is not in the level (or has nothing to move)")
    end
    return self
end

net.op("move", function(args)
    local object = require("boz.objects.runtime").get(args.name)
    if object then glide(object, args.target, {seconds = args.target.seconds, ride = args.target.ride}) end
end, knows)

--- Moves it to a position or another object's, at once or over options.seconds. options:
--- seconds, rotation (degrees about the vertical axis or a quaternion), ride (players standing
--- on it ride along; default true), done(object) when it arrives. Returns the object.
function Object:move_to(position, options)
    local rotation = options and options.rotation
    return glide(self, {position = point(position, "move_to"), rotation = rotation}, options)
end

--- Moves it by an offset {x, y, z} (centimetres; y is up), like move_to.
function Object:move_by(offset, options)
    local d = point(offset, "move_by")
    local origin, members = self:_motion()
    local place = motion.place(self.name, origin, members)
    if not place then
        return self
    end
    local p = place.position
    return glide(self, {position = {x = p.x + d.x, y = p.y + d.y, z = p.z + d.z},
                        rotation = options and options.rotation}, options)
end

--- Turns it to a rotation (degrees about the vertical axis, or a quaternion), like move_to.
function Object:turn_to(rotation, options)
    if motion.rotation(rotation) == nil then
        error("turn_to needs degrees or a quaternion {x, y, z, w}", 2)
    end
    return glide(self, {rotation = rotation}, options)
end

--- Turns it by degrees about the vertical axis (positive turns left seen from above), like
--- move_to.
function Object:turn_by(degrees, options)
    if type(degrees) ~= "number" then
        error("turn_by needs a number of degrees", 2)
    end
    local origin, members = self:_motion()
    local place = motion.place(self.name, origin, members)
    if not place then
        return self
    end
    local q, r = motion.rotation(degrees), place.rotation
    local turned = {x = q.w * r.x + q.x * r.w + q.y * r.z - q.z * r.y,
                    y = q.w * r.y - q.x * r.z + q.y * r.w + q.z * r.x,
                    z = q.w * r.z + q.x * r.y - q.y * r.x + q.z * r.w,
                    w = q.w * r.w - q.x * r.x - q.y * r.y - q.z * r.z}
    return glide(self, {rotation = turned}, options)
end

--- Puts it at a position at once (move_to without seconds).
function Object:set_position(position)
    return self:move_to(position)
end

--- Turns it at once (turn_to without seconds).
function Object:set_rotation(rotation)
    return self:turn_to(rotation)
end

--- True while it glides (move_to and friends with seconds).
function Object:moving()
    return motion.moving(self.name)
end

--- Stops a glide where it is (its done is not called). Returns the object.
function Object:stop()
    motion.stop(self.name)
    return self
end

--- Its name in the prefab it is part of ("Door" of "Vault.Door"), or nil.
function Object:part_name()
    return self.name:match("%.([^.]+)$")
end

--- The prefab it is part of, or nil.
function Object:parent()
    local name = self.name:match("^(.+)%.[^.]+$")
    return name and require("boz.objects.runtime").get(name) or nil
end

--- Its rotation {x, y, z, w} (a quaternion), or nil when it is not in the level.
function Object:rotation()
    local entity = self._handle:entity_pointer()
    return entity ~= 0 and require("boz.engine.entities").rotation(entity) or nil
end

--- Plays a state of its animation state machine (an animated object or character): "open",
--- "idle", ...; blend: seconds of cross-fade. True when it has that state.
function Object:play_animation(state, blend)
    local entity = self._handle:entity_pointer()
    return entity ~= 0 and require("boz.engine.animation").play(entity, state, blend) or false
end

--- Where one of its bones is ({x, y, z}), for an animated object or character; nil otherwise.
function Object:bone_position(bone)
    local entity = self._handle:entity_pointer()
    return entity ~= 0 and require("boz.engine.animation").bone_position(entity, bone) or nil
end

--- Its position {x, y, z} (centimetres, y up), or nil when it is not in the level.
function Object:position()
    return self._handle:position()
end

--- True when it is within distance (cm) of target (a position or another object).
function Object:near(target, distance)
    if type(target) == "table" and target.position and type(target.position) == "function" then
        target = target:position()
    end
    return target ~= nil and self._handle:near(target, distance)
end

--- True while it is in the running level.
function Object:exists()
    return self._handle:exists()
end

--- The objects it links to by the link kind ("power", "traps", or a script's own).
function Object:links(kind)
    local get = require("boz.objects.runtime").get
    local out = {}
    for _, target in ipairs(engine.links(self.name, kind)) do
        out[#out + 1] = get(target.name)
    end
    return out
end

--- The objects that link to it by the link kind.
function Object:linked_from(kind)
    local get = require("boz.objects.runtime").get
    local out = {}
    for _, source in ipairs(engine.linked_from(self.name, kind)) do
        out[#out + 1] = get(source.name)
    end
    return out
end

--- Calls fn(object, ...) when the event happens to it ("use", "hit", "opened", ...).
function Object:on(event, fn)
    local check = require("boz.engine.check")
    if not check.name(event, self.name .. ":on") or not check.fn(fn, self.name .. ":on") then
        return fn
    end
    local by_object = listeners[event] or {}
    listeners[event] = by_object
    local key = string.lower(self.name)
    by_object[key] = by_object[key] or {}
    table.insert(by_object[key], {fn = fn, level = Object._in_level})
    return fn
end

--- Sends an event to every script (boz.send).
function Object:send(name, data)
    require("boz.objects.runtime").send(name, data)
end

-- The event reached the object: its class's on_<event> first (whose return value is kept:
-- true stops the game's own handling where it can be stopped), then map scripts' listeners.
function Object:_emit(event, ...)
    local core = require("boz.engine.core")
    local result
    local method = self["on_" .. event]
    if type(method) == "function" then
        local ok, value = core.safely(self.name .. ":on_" .. event, method, self, ...)
        result = ok and value or nil
    end
    self:_notify(event, ...)
    return result
end

-- The event reached the object: map scripts' listeners only (the game does the rest).
function Object:_notify(event, ...)
    local core = require("boz.engine.core")
    for _, listener in ipairs((listeners[event] or {})[string.lower(self.name)] or {}) do
        core.safely(self.name .. " " .. event .. " listener", listener.fn, self, ...)
    end
end

-- A level ends: its objects' listeners go, map scripts' stay.
function Object.forget_level_listeners()
    for _, by_object in pairs(listeners) do
        for key, list in pairs(by_object) do
            for i = #list, 1, -1 do
                if list[i].level then
                    table.remove(list, i)
                end
            end
            if #list == 0 then
                by_object[key] = nil
            end
        end
    end
end

return Object
