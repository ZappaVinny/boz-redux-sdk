-- boz.Effect: an effect's script (Effects tab: Script on one of your effects). It runs for each
-- copy of the effect while it is in the world:
--
--   local Frost = boz.Effect:extend("Frost")
--   function Frost:on_spawn() self.effect:set({scale = 0.5}) end   -- false: its pieces don't run
--   function Frost:on_update(dt) self.age = (self.age or 0) + dt end
--   function Frost:on_end() end
--   return Frost
--
-- self.effect is the effect (position, move, set, emitters, remove); self.name its name.

local Class = require("boz.class")

local Effect = Class:extend("Effect")

function Effect:init(effect, entry)
    self.effect, self.name, self.entry = effect, entry.name, entry
end

--- Its position {x, y, z}, or nil once it is gone.
function Effect:position() return self.effect:position() end

--- Takes it out of the world (on_end follows).
function Effect:remove() self.effect:remove() end

--- Zombies go where it is (boz.lure options: seconds, ...).
function Effect:lure(options)
    local at = self:position()
    return at and require("boz").lure(at, options)
end

--- An explosion where it is (boz.effects.explode options: radius, inner, damage, min_damage).
function Effect:explode(options)
    local at = self:position()
    return at and require("boz.game.effects").explode(at, options)
end

local script = {}
local classes = {}       -- script path -> class (false: did not load)
local running = {}       -- instance -> true
local listening = false

local function safely(self, method, ...)
    local fn = self[method]
    if type(fn) == "function" then
        local ok, result = pcall(fn, self, ...)
        if not ok then
            log("boz.Effect " .. tostring(self.name) .. ": " .. method .. ": " .. tostring(result))
            return nil
        end
        return result
    end
end
script.safely = safely

local function listen()
    if listening then return end
    listening = true
    events.on("frame", function(dt)
        for self in pairs(running) do
            if not self.effect:alive() then
                running[self] = nil
                safely(self, "on_end")
            else
                safely(self, "on_update", dt or 0)
            end
        end
    end)
end

--- The class a script defines (loaded once), or nil.
function script.class_of(path)
    if classes[path] == nil then
        classes[path] = require("boz.objects.runtime").load_class(path) or false
    end
    return classes[path] or nil
end

--- Runs an effect's script for a copy of it in the world; returns it and what on_spawn returned.
function script.start(effect, entry)
    local class = script.class_of(entry.script)
    if not class then return nil end
    local self = class:new(effect, entry)
    running[self] = true
    listen()
    return self, safely(self, "on_spawn")
end

script.Effect = Effect
return script
