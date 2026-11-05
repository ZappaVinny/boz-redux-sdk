-- boz.Volume: a Trigger, Hit or Use volume. Reach one with self:part("Keypad") or boz.get.
--
--   local keypad = self:part("Keypad")
--   keypad:set_cost(keypad:cost() * 2)
--   keypad:set_prompt("Try again")

local Prefab = require("boz.objects.prefab")

local Volume = Prefab:extend("Volume")

local function entry(self)
    return require("boz.objects.runtime").volume(self.name) or {}
end

--- "trigger", "hit" or "use".
function Volume:type() return entry(self).volume end
--- Who sets it off: "players", "zombies" or "anyone".
function Volume:set_off_by() return entry(self).who end
--- True when it works one time only.
function Volume:once() return entry(self).once == true end
--- True once it has fired.
function Volume:used() return entry(self)._fired == true end
--- A Use volume's text, and setting it (players see it the next time they reach the volume).
function Volume:prompt() return entry(self).prompt end
function Volume:set_prompt(text) entry(self).prompt = text return self end
--- A Use volume's points, and setting it.
function Volume:cost() return entry(self).cost end
function Volume:set_cost(points) entry(self).cost = points return self end

return Volume
