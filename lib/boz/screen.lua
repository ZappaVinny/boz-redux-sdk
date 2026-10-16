-- boz.screen: full-screen effects and fog.
--
--   screen.effect("nuke")                     the nuke's white flash
--   screen.effect("shockEffect", 2000)        Kino's electric shock, for 2 seconds
--   screen.fog("Monkeys")                     a fog config (the level's or one a round uses)
--
-- Full-screen effects (CFullscreenFXConfig resources): nuke (every map), shockEffect and
-- crawler_gas (Kino), lazarus and romeroElectricutionEffect (Call of the Dead). Fogs (CIwFogConfig,
-- misc group): KINO, Ascension, Monkeys, callofthedead and the level's others. A map project's
-- build brings any effect or fog its scripts name from another map.
--
-- How it works: CFullscreenFXManager (singleton) plays one when it gets its play event (id kept at
-- image +0x4672f0) with the config's name hash and a display time (0: the config's own):
-- materials fade in, show and fade out (m_FadeTime, m_DurationTime, m_InitialDelay). Fog: the
-- SwitchFog command (CVFXManager, CIwFogManager).

local screen = {}

local hash = require("boz.hash")

local FALLBACK = {["CFullscreenFXManager::s_instance"] = 0x461084, ["CFullscreenFXManager::OnEvent"] = 0x18bdec + 1}
local PLAY_EVENT = 0x4672f0

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

--- Plays a full-screen effect by name (or hash) for `ms` milliseconds (default: its own time).
--- Returns false when the effect is not loaded.
function screen.effect(name, ms)
    local manager = game.read("ptr", sym("CFullscreenFXManager::s_instance"))
    if manager == 0 then
        return false
    end
    local id = type(name) == "number" and name or hash.name(name)
    if not require("boz.resources").find(id, "CFullscreenFXConfig") then
        return false
    end
    local event = game.read("u32", game.base() + PLAY_EVENT)
    game.call(sym("CFullscreenFXManager::OnEvent"), manager, 0, event, id, ms or 0)
    return true
end

--- Switches the fog to a fog config by name.
function screen.fog(name)
    return require("boz.console").exec("SwitchFog " .. tostring(name))
end

return screen
