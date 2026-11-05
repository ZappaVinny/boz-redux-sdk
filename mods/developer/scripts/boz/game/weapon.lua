-- boz.Weapon: a weapon of the map, for weapon scripts (Weapons tab → Script).
--
--   local IdGun = boz.Weapon:extend("IdGun")
--   function IdGun:on_fire(data) boz.player():message("Bang") end
--   return IdGun
--
-- Events: on_given, on_equip, on_fire(data), on_reload.

local Class = require("boz.class")
local weapons = require("boz.engine.weapons")

local Weapon = Class:extend("Weapon")

function Weapon:init(name, entry)
    self.name = name
    self.settings = require("boz.objects.settings").of(self, (entry or {}).settings or {})
end

-- The live weapon (boz.weapons handle) while the player has it, else nil.
function Weapon:_live()
    return weapons.get(self.name)
end

local function live(name, default)
    return function(self, ...)
        local weapon = self:_live()
        if weapon == nil then
            return default
        end
        return weapon[name](weapon, ...)
    end
end

--- Ammo in the clip / in reserve, and the most each holds (nil while the player lacks it).
Weapon.clip = live("clip")
Weapon.reserve = live("reserve")
Weapon.clip_size = live("clip_size")
Weapon.reserve_size = live("reserve_size")
--- Sets the clip and reserve.
Weapon.set_ammo = live("set_ammo", false)
--- Rounds per minute, and setting it.
Weapon.fire_rate = live("fire_rate")
Weapon.set_fire_rate = live("set_fire_rate", false)
--- Damage (head, torso, limbs), and setting it.
Weapon.damage = live("damage")
Weapon.set_damage = live("set_damage", false)
--- True while it is in the player's hand.
Weapon.in_hand = live("in_hand", false)
--- A field by its game name, and setting it.
Weapon.field = live("get")
Weapon.set_field = live("set", false)

function Weapon:_emit(event, ...)
    local method = self["on_" .. event]
    if type(method) == "function" then
        require("boz.engine.core").safely(self.name .. ":on_" .. event, method, self, ...)
    end
end

return Weapon
