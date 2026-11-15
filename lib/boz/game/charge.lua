-- boz.charge: a charged shot for a launcher (a staff): hold fire to charge, release to fire the
-- projectile of the level reached; a tap fires the first level.
--
--   boz.charge("ice_staff", {
--       levels = {{projectile = "ice_bolt"}, {after = 1.2, projectile = "ice_blast", ammo = 3}},
--       effect = "frost_glow", bone = "tag_flash",   -- glows on the gun while charging
--       clip = "charge",                             -- an extra clip of the weapon (Weapons tab)
--       sound = "charge_up", max = 3,                -- fires by itself after 3 seconds
--   })
--
-- The game fires each shot (ammo, recoil, sound and co-op as usual): the weapon's projectile is
-- set to the level's, then the shoot action is sent. Callbacks: on_start(), on_level(n),
-- on_fire(n).

local charge = {}

local weapons = require("boz.engine.weapons")
local input = require("boz.systems.input")
local effects = require("boz.game.effects")

local Charge = {}
Charge.__index = Charge

local active = {}         -- weapon name -> Charge
local listening = false

local function in_hand(name)
    local gun = weapons.current()
    return gun and gun.name == name and gun or nil
end

local function level_at(self, seconds)
    local level = 1
    for i, entry in ipairs(self.levels) do
        if seconds >= (entry.after or 0) then
            level = i
        end
    end
    return level
end

local function stop_glow(self)
    if self.glow then
        effects.detach(self.glow)
        self.glow:remove()
        self.glow = nil
    end
end

function Charge:_start()
    self.held, self.level = 0, 1
    if self.options.effect then
        self.glow = effects.attach(self.options.effect, "weapon",
            {bone = self.options.bone, offset = self.options.offset})
    end
    if self.options.clip then
        local gun = in_hand(self.weapon)
        if gun then gun:play(self.options.clip) end
    end
    if self.options.sound then
        require("boz.systems.audio").play(self.options.sound)
    end
    if self.options.on_start then self.options.on_start() end
end

function Charge:_fire()
    local level = self.level or 1
    self.held, self.level = nil, nil
    stop_glow(self)
    local gun = in_hand(self.weapon)
    local entry = self.levels[level]
    if not gun or not entry then
        return
    end
    local extra = (entry.ammo or 1) - 1
    if extra > 0 then
        gun:set_ammo(math.max(1, gun:clip() - extra))
    end
    if entry.projectile then
        gun:set_projectile(entry.projectile)
    end
    if self.options.on_fire then self.options.on_fire(level) end
    -- The shot comes from the shoot animation: the charge clip ends first (back to idle).
    if self.options.clip then
        gun:stop_animation()
    end
    local timers = require("boz.engine.timers")
    timers.after(self.options.clip and 0.4 or 0.05, function()
        input.send("shoot", true)
        timers.after(0.15, function() input.send("shoot", false) end)
    end)
end

function Charge:_update(dt)
    if not self.held then
        return
    end
    if not in_hand(self.weapon) then
        self.held, self.level = nil, nil
        stop_glow(self)
        return
    end
    self.held = self.held + dt
    local level = level_at(self, self.held)
    if level ~= self.level then
        self.level = level
        if self.glow and self.options.grow ~= false then
            self.glow:set({scale = 1 + (level - 1) * 0.5})
        end
        if self.options.on_level then self.options.on_level(level) end
    end
    if self.options.max and self.held >= self.options.max then
        self:_fire()
    end
end

--- Stops the charged shot (the weapon fires as the game makes it again).
function Charge:stop()
    stop_glow(self)
    active[self.weapon] = nil
end

local function listen()
    if listening then
        return
    end
    listening = true
    input.on_action("shoot", function(down)
        local gun = weapons.current()
        local self = gun and active[gun.name]
        if not self then
            return false
        end
        if down then
            if not self.held and (gun:clip() or 0) > 0 then
                self:_start()
            end
        elseif self.held then
            self:_fire()
        end
        return true
    end)
    events.on("frame", function(dt)
        for _, self in pairs(active) do
            self:_update(dt or 0)
        end
    end)
end

--- A charged shot for a weapon (see the top). Returns it (:stop() ends it).
function charge.new(weapon, options)
    options = options or {}
    local self = setmetatable({weapon = weapon, options = options,
                               levels = options.levels or {{}}}, Charge)
    active[weapon] = self
    listen()
    return self
end

return charge
