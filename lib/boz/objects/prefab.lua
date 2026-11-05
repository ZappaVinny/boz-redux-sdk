-- boz.Prefab: a prefab (yours: parts and a script; or the game's, through its own class).
--
--   local Skull = boz.Prefab:extend("Skull")
--   ---@setting points int 100 "Points for shooting it"
--   function Skull:on_hit(player) self:hide(); player:give_points(self.settings.points) end
--   return Skull
--
-- Events a script can handle: start(), on_use / on_hit / on_enter / on_exit(who, volume)
-- (volume: the part's name), on_event(name, data) for boz.send. Map scripts listen with :on().

local Object = require("boz.objects.object")
local engine = require("boz.engine.objects")

local Prefab = Object:extend("Prefab")

--- Sets up the prefab called name (entry: its parts, members and settings from the map).
function Prefab:init(name, entry)
    Object.init(self, name, entry)
    entry = entry or {}
    self._parts = {}
    for _, part in ipairs(entry.parts or {}) do
        self._parts[part.part] = part.name
    end
    self._members = entry.members or {}
    self.settings = require("boz.objects.settings").of(self, entry.settings or {})
end

-- Every game object under it (a prefab of yours acts on all its parts), else itself.
local function each(self, fn)
    if #self._members == 0 then
        fn(self._handle)
        return
    end
    for _, name in ipairs(self._members) do
        fn(engine.get(name))
    end
end

--- One of its parts by its name in the prefab ("Door"), as its class.
function Prefab:part(name)
    return require("boz.objects.runtime").get(self._parts[name] or (self.name .. "." .. name))
end

--- Its parts: a list of {name =, object =}.
function Prefab:parts()
    local out = {}
    for name in pairs(self._parts) do
        out[#out + 1] = {name = name, object = self:part(name)}
    end
    table.sort(out, function(a, b) return a.name < b.name end)
    return out
end

function Prefab:set_visible(visible)
    each(self, function(handle) handle:set_visible(visible) end)
    return self
end

function Prefab:set_blocks_walking(blocks)
    self.walking_blocked = blocks
    engine.set_navmesh(self.name, not blocks)
    each(self, function(handle) handle:set_blocks_walking(blocks) end)
    return self
end

function Prefab:set_stops_bullets(stops)
    self.bullets_stopped = stops
    each(self, function(handle) handle:set_stops_bullets(stops) end)
    return self
end

-- True when the map or a script says so of it, or of any of its parts.
local function any_part(self, method, own)
    if own ~= nil or #self._members == 0 then
        return Object[method](self)
    end
    for _, name in ipairs(self._members) do
        local part = require("boz.objects.runtime").get(name)
        if part and part[method](part) then
            return true
        end
    end
    return Object[method](self)
end

function Prefab:blocks_walking() return any_part(self, "blocks_walking", self.walking_blocked) end
function Prefab:stops_bullets() return any_part(self, "stops_bullets", self.bullets_stopped) end

--- Its rotation, or its first part's when it has none of its own.
function Prefab:rotation()
    local name = self._members[1]
    return Object.rotation(self) or (name and Object.rotation({_handle = engine.get(name)})) or nil
end

--- The middle of its parts, or nil when none is in the level.
function Prefab:position()
    local sum, count = {x = 0, y = 0, z = 0}, 0
    each(self, function(handle)
        local p = handle:position()
        if p then
            sum.x, sum.y, sum.z, count = sum.x + p.x, sum.y + p.y, sum.z + p.z, count + 1
        end
    end)
    return count > 0 and {x = sum.x / count, y = sum.y / count, z = sum.z / count} or nil
end

function Prefab:near(target, distance)
    if type(target) == "table" and type(target.position) == "function" then
        target = target:position()
    end
    local found = false
    each(self, function(handle) found = found or (target ~= nil and handle:near(target, distance)) end)
    return found
end

--- True while any of its parts is shown.
function Prefab:visible()
    if #self._members == 0 then
        return Object.visible(self)
    end
    for _, name in ipairs(self._members) do
        if not engine.is_hidden(name) then
            return true
        end
    end
    return false
end

function Prefab:exists()
    local found = false
    each(self, function(handle) found = found or handle:exists() end)
    return found
end

return Prefab
