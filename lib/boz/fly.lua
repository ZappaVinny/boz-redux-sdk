-- boz.fly: noclip, using the game's developer fly mode.
--
--   local fly = require("boz.fly")
--   fly.set(true)                       -- fly through walls; movement keys fly where you look
--   fly.move_vertical(1, dt)            -- call each frame while an "up" key is held
--
-- How it works: CPlayerFreeFly toggles on SUBJECT_PLAYER_FREE_MODE (sent to CInputManager's
-- subject); while flying, movement moves the player along the view at FreeFlySpeed and
-- SUBJECT_PLAYER_ASCEND raises it by FreeFlySpeed (sent here with the speed scaled and signed).

local components = require("boz.components")

local fly = {}

local SUBJECT_PLAYER_FREE_MODE = 0xe8d65346   -- ids from gamedef/events
local SUBJECT_PLAYER_ASCEND = 0x77f7c70e
local FLYING, SPEED_VAR = 0x30, 0x34

local function component()
    return components.on_player("CPlayerFreeFly::s_table")
end

local function input_event(event)
    local input = game.read("ptr", "CInputManager::s_instance")
    if input ~= 0 then
        game.call("CIsSubject::NotifyVirtual", input + 0x20, event, 0, 0, 0)
    end
end

--- True if fly mode can be used now (a Zombies match whose player has the fly component).
function fly.available()
    return component() ~= nil
end

--- True while flying.
function fly.active()
    local c = component()
    return c ~= nil and game.read("bool", c + FLYING)
end

--- Turns fly mode on or off (nil toggles). Returns the new state, or nil if unavailable.
function fly.set(on)
    local c = component()
    if not c then
        return nil
    end
    if on == nil or on ~= game.read("bool", c + FLYING) then
        input_event(SUBJECT_PLAYER_FREE_MODE)
    end
    return game.read("bool", c + FLYING)
end

--- Fly speed (FreeFlySpeed): distance per frame at full speed.
function fly.speed()
    local c = component()
    return c and game.read("f32", game.read("ptr", c + SPEED_VAR) + 0x10)
end

--- Sets the fly speed (FreeFlySpeed).
function fly.set_speed(speed)
    local c = component()
    if c then
        game.write("f32", game.read("ptr", c + SPEED_VAR) + 0x10, speed)
    end
end

--- Moves up (direction 1) or down (-1) for dt seconds at fly speed. Call it every frame while a
--- key is held.
function fly.move_vertical(direction, dt)
    local c = component()
    if not c or not game.read("bool", c + FLYING) then
        return
    end
    local var = game.read("ptr", c + SPEED_VAR)
    local speed = game.read("f32", var + 0x10)
    game.write("f32", var + 0x10, speed * 60 * dt * direction)
    input_event(SUBJECT_PLAYER_ASCEND)
    game.write("f32", var + 0x10, speed)
end

return fly
