-- boz.engine.saves: the game's saves.
--
--   saves.save()                 saves the match now (as the round-start autosave does)
--   saves.on_save(fn)            fn() when the game writes its save (every system adds its part)
--   saves.on_load(fn)            fn() when a saved match is continued
--
-- A script's own state: boz.globals / script globals are saved with the game (boz.prefabs).
-- Saving on pause and on suspend: the SaveOnPause and SaveOnSuspend variables (boz.cvars).
--
-- game: CSaveManager::AutoSave, SUBJECT_SAVE, SUBJECT_LOAD, CSaveManager::NotifyLoad

local saves = {}

local core = require("boz.engine.core")

--- Saves the match now (single player). Returns false outside a match.
function saves.save()
    if not core.singleton("CSaveManager") or not require("boz.engine.map").playing() then
        return false
    end
    core.call("CSaveManager::AutoSave")
    return true
end

--- Calls fn() whenever the game writes its save. Returns a handle (boz.game_events.off).
function saves.on_save(fn)
    return require("boz.engine.game_events").on("SUBJECT_SAVE", function() fn() end)
end

--- Calls fn() when a saved match is continued.
function saves.on_load(fn)
    return require("boz.engine.game_events").on("SUBJECT_LOAD", function() fn() end)
end

return saves
