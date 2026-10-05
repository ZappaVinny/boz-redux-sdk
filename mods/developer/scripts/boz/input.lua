-- boz.input: the player's controls during a Zombies match: watch, change or send the game's actions.
--
--   local input = require("boz.input")
--   input.on_action("melee", function(down)
--       log("knife " .. (down and "pressed" or "released"))
--   end)
--   input.send("reload")
--
-- Actions: shoot, aim, reload, use, melee, grenade, tactical, crouch, fire_mode, switch_weapon.
-- They are the game's own actions, whatever keys the player bound to them.
--
-- How it works: the client sends the player's key presses straight to the game's input
-- (native controls) and raises the "action" event first; a handler that returns true keeps the
-- action from the game. Dead Ops Arcade still uses the touchpad path and raises no actions.

local M = {}

--- The action names.
M.ACTIONS = {"shoot", "aim", "reload", "use", "melee", "grenade", "tactical", "crouch", "fire_mode",
             "switch_weapon"}

local handlers = {}   -- action name -> list of functions
local listening = false

local function listen()
    if listening then
        return
    end
    listening = true
    events.on("action", function(name, down)
        local list = handlers[name]
        if not list then
            return false
        end
        local used = false
        for _, fn in ipairs(list) do
            if fn(down) then
                used = true
            end
        end
        return used
    end)
end

--- Calls fn(down) when the player presses (true) or releases (false) the action. If fn returns
--- true the game does not get it. Several handlers may watch one action; any one returning true
--- keeps it from the game.
function M.on_action(name, fn)
    listen()
    handlers[name] = handlers[name] or {}
    table.insert(handlers[name], fn)
end

--- Sends an action to the game as if its button was pressed (down = true, the default) or
--- released. Handlers from on_action do not see it.
function M.send(name, down)
    input.send(name, down ~= false)
end

--- True while the player holds the action's key or button.
function M.held(name)
    return input.down(name)
end

--- True while the player is aiming down sights (approximate: it can miss aiming in some states).
function M.aiming()
    return input.aiming()
end

--- True when the client sends controls straight to the game (actions work); false with the old
--- touchpad controls.
function M.native()
    return input.native()
end

return M
