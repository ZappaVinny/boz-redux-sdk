-- boz.Teleporter: a teleporter of yours. A Use volume (its cost and prompt) sends the player to
-- its Destination link, stopping over at its "Stop over at" link (a Wormhole spot, or anything)
-- for its Wait setting; then it charges for its Cooldown setting. Extend it for your own kind:
--
--   local Booth = boz.Teleporter:extend("Booth")
--   function Booth:on_arrived(player) player:give_points(100) end
--   return Booth
--
-- Events: on_teleported(player) as they leave, on_arrived(player), on_ready() after charging.

local Prefab = require("boz.objects.prefab")

---@class boz.Teleporter : boz.Prefab
local Teleporter = Prefab:extend("Teleporter")

--- Used at its Use volume (the volume took the cost): sends the player.
function Teleporter:on_use(player)
    if self:teleport(player) then
        self:charge()
    end
end

--- While it charges, or without a destination, a use costs nothing and the prompt says why.
function Teleporter:usable()
    if not self:links("destination")[1] then
        return false, "It goes nowhere"
    end
    if not self:ready() then
        return false, "Charging"
    end
    return true
end

--- Sends a player to its Destination, by way of its stop-over. False without a destination.
function Teleporter:teleport(player)
    local target = self:links("destination")[1]
    if not target then
        return false
    end
    player:teleport(target, {
        via = self:links("stop_over")[1],
        seconds = self.settings.wait or 2,
        done = function(arrived) self:_emit("arrived", arrived) end,
    })
    self:_emit("teleported", player)
    return true
end

--- Charges for its Cooldown setting: uses meanwhile are refused before they cost anything.
function Teleporter:charge()
    local seconds = self.settings.cooldown or 30
    if seconds <= 0 then
        return
    end
    self._charging = true
    require("boz.engine.timers").after(seconds, function()
        self._charging = nil
        self:_emit("ready")
    end)
end

--- True when it can send someone now.
function Teleporter:ready()
    return not self._charging
end

return Teleporter
