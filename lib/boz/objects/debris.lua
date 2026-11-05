-- boz.Debris: a door of yours. Any model plus a Use volume (its cost and prompt); bought, it
-- vanishes, so walking and bullets open, and the doors it opens with ("Opens with") open too.
-- Extend it for your own kind of door:
--
--   local Gate = boz.Debris:extend("Gate")
--   function Gate:open(player)
--       if not boz.Debris.open(self, player) then return false end
--       player:message("The gate falls")
--       return true
--   end
--   return Gate

local Door = require("boz.objects.native").Door

local Debris = Door:extend("Debris")

--- Bought at its Use volume (the volume took the cost): opens.
function Debris:on_use(player)
    self:open(player)
end

--- Opens it: hides it, then the doors it opens with. Returns false when it was open already.
function Debris:open(player)
    if self.opened then
        return false
    end
    self.opened = true
    self:hide()
    pcall(require("boz.systems.audio").play, "buy_debris")
    self:_emit("opened", player)
    for _, other in ipairs(self:links("siblings")) do
        if other ~= self and other.open then
            other:open(player)
        end
    end
    return true
end

--- True once it is open.
function Debris:is_open()
    return self.opened == true
end

--- An opened debris stays open in a continued save.
function Debris:start()
    if self.opened then
        self:hide()
    end
end

return Debris
