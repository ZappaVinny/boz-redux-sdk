-- boz.Sector: a room of the map (a Sector volume). The game draws a sector only while the camera
-- is in it or sees it through a portal.
--
--   local lobby = boz.get("Lobby")
--   lobby:on("enter", function(lobby, player) player:message("The lobby") end)
--   if lobby:contains(boz.player()) then ... end
--
-- Events: on_enter(player), on_exit(player).

local Object = require("boz.objects.object")
local boxes = require("boz.objects.boxes")
local engine = require("boz.engine.sectors")

---@class boz.Sector : boz.Object
local Sector = Object:extend("Sector")

function Sector:init(name, entry)
    Object.init(self, name, entry)
    self.kind = "sector"
    local ok, data = pcall(require, "boz.world_data")
    self._box = ok and type(data) == "table" and (data.sectors or {})[name] or nil
end

--- True when a position or anything with a position (a player, a zombie) is inside it.
function Sector:contains(target)
    return self._box ~= nil and boxes.contains(self._box, boxes.point(target))
end

--- The players in it.
function Sector:players()
    local out = {}
    for _, player in ipairs(require("boz.objects.runtime").players()) do
        if self:contains(player) then
            out[#out + 1] = player
        end
    end
    return out
end

--- True when the game drew it this frame.
function Sector:drawn()
    return self._box ~= nil and engine.drawn(engine.find(self._box.group))
end

--- Its middle.
function Sector:position()
    return self._box and boxes.centre(self._box) or nil
end

function Sector:exists()
    return self._box ~= nil and engine.find(self._box.group) ~= nil
end

return Sector
