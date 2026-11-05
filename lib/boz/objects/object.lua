-- boz.Object: any object in the map (a model, a volume, a part), by its editor name.
--
--   local wall = boz.get("Secret_Wall")
--   wall:hide()                        -- Visible off: unseen, walk and shoot through it
--   wall:set_blocks_walking(false)     -- players and zombies walk through it
--   wall:on("hit", function(wall, player) player:give_points(10) end)

local Class = require("boz.class")
local engine = require("boz.engine.objects")

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

--- Shows (true) or hides (false) it. Hidden, it stops nothing and blocks nothing.
function Object:set_visible(visible)
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
    self.walking_blocked = blocks
    self._handle:set_blocks_walking(blocks)
    return self
end

--- Stops bullets: false, shots pass through it.
function Object:set_stops_bullets(stops)
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
