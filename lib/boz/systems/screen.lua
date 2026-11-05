-- boz.screen: full-screen effects and fog.
--
--   screen.effect("nuke")                     the nuke's white flash
--   screen.effect("shockEffect", 2000)        Kino's electric shock, for 2 seconds
--   screen.fog("Monkeys")                     a fog config (the level's or one a round uses)

local screen = {}

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")


--- Plays a full-screen effect by name (or hash) for `ms` milliseconds (default: its own time).
--- Returns false when the effect is not loaded.
function screen.effect(name, ms)
    local manager = core.singleton("CFullscreenFXManager")
    if not manager then
        return false
    end
    local id = hash.of(name)
    if not require("boz.engine.resources").find(id, "CFullscreenFXConfig") then
        return false
    end
    local event = game.read("u32", core.sym("g_fullscreenFxPlayEvent"))
    core.call("CFullscreenFXManager::OnEvent", manager, 0, event, id, ms or 0)
    return true
end

--- Switches the fog to a fog config by name.
function screen.fog(name)
    return require("boz.systems.console").exec("SwitchFog " .. tostring(name))
end

return screen
