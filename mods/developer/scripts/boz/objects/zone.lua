-- boz.Zone: an area of the map (Zone volumes of one name). Its zombie spawns are used once it
-- is open: the starting zone from the start, others when a door that opens them opens.
--
--   local cellar = boz.get("Cellar")
--   cellar:on("opened", function(cellar) boz.hud.message("The cellar is open") end)
--   cellar:open()                       -- as if a door had opened it
--   cellar:close()                      -- its spawns are not used again until it opens
--
-- Events: on_opened(), on_closed(), on_enter(player), on_exit(player).
--
-- game: CArea::Activate, SpawnManager_SetPoint

local Object = require("boz.objects.object")
local boxes = require("boz.objects.boxes")
local core = require("boz.engine.core")
local hash = require("boz.engine.hash")

---@class boz.Zone : boz.Object
local Zone = Object:extend("Zone")

function Zone:init(name, entry)
    Object.init(self, name, entry)
    self.kind = "zone"
    local ok, data = pcall(require, "boz.world_data")
    self._data = ok and type(data) == "table" and (data.zones or {})[name] or {}
end

-- The game's area for this zone.
local function area(self)
    return self._data.area and require("boz.engine.resources").find(hash.name(self._data.area), "CArea")
end

-- Every spawn of the zone switched on or off the game's way.
local function set_spawns(self, on)
    local manager = core.singleton("CSpawnManager")
    if not manager then
        return false
    end
    for _, name in ipairs(self._data.spawns or {}) do
        core.call("SpawnManager_SetPoint", manager, hash.name(name), on and 1 or 0)
    end
    return true
end

--- True while its spawns are used.
function Zone:is_open()
    if self.closed then
        return false
    end
    if self.opened or self._data.starting then
        return true
    end
    for _, door in ipairs(self:linked_from("zones")) do
        if type(door.is_open) == "function" and door:is_open() then
            return true
        end
    end
    return false
end

-- A door (or the game) opened it: remember and tell scripts.
function Zone:_opened()
    if self.opened and not self.closed then
        return
    end
    self.opened, self.closed = true, nil
    self:_emit("opened")
    self:send("zone_opened", {zone = self.name})
end

--- Opens it, as a door that opens it would. False when it is open already.
function Zone:open()
    if self:is_open() then
        return false
    end
    local a = area(self)
    if a then
        core.call("CArea::Activate", a)
    else
        set_spawns(self, true)
    end
    self:_opened()
    return true
end

--- Closes it: its spawns are not used until it opens again. False when it is closed already.
function Zone:close()
    if not self:is_open() then
        return false
    end
    set_spawns(self, false)
    self.closed = true
    self:_emit("closed")
    self:send("zone_closed", {zone = self.name})
    return true
end

-- A loaded save: what scripts did to it, done again.
function Zone:start()
    if self.closed then
        set_spawns(self, false)
    elseif self.opened and area(self) then
        core.call("CArea::Activate", area(self))
    end
end

--- Its zombie spawns (boz.ZombieSpawn).
function Zone:spawns()
    local get = require("boz.objects.runtime").get
    local out = {}
    for _, name in ipairs(self._data.spawns or {}) do
        out[#out + 1] = get(name)
    end
    return out
end

--- The doors (and debris) that open it.
function Zone:doors()
    return self:linked_from("zones")
end

--- True when a position or anything with a position is inside one of its boxes.
function Zone:contains(target)
    local point = boxes.point(target)
    for _, box in ipairs(self._data.boxes or {}) do
        if boxes.contains(box, point) then
            return true
        end
    end
    return false
end

--- The players in it.
function Zone:players()
    local out = {}
    for _, player in ipairs(require("boz.objects.runtime").players()) do
        if self:contains(player) then
            out[#out + 1] = player
        end
    end
    return out
end

--- True for the zone players start in.
function Zone:starting()
    return self._data.starting == true
end

--- The middle of its first box.
function Zone:position()
    local box = (self._data.boxes or {})[1]
    return box and boxes.centre(box) or nil
end

function Zone:exists()
    return self._data.boxes ~= nil
end

return Zone
