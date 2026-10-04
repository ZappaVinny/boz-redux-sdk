-- boz.rounds: rounds and the match (Zombies mode).
--
--   rounds.start_next()   rounds.spawn_zombie()   rounds.kill_all()
--
-- How it works: these run the game's developer commands (StartWave, SpawnZombie, ...) through
-- boz.console.

local console = require("boz.console")

local rounds = {}

--- Starts the next round now.
function rounds.start_next()
    return console.exec("StartWave")
end

--- Spawns one zombie.
function rounds.spawn_zombie()
    return console.exec("SpawnZombie")
end

--- Kills every zombie.
function rounds.kill_all()
    return console.exec("KillAllZombies")
end

--- Turns the map's power on.
function rounds.power_on()
    return console.exec("SwitchPowerOn")
end

--- Pauses or resumes game time.
function rounds.toggle_pause()
    return console.exec("TimeTogglePause")
end

--- Game speed multiplier (1 = normal).
function rounds.set_time_scale(factor)
    return console.exec("TimeFactor " .. tostring(factor))
end

return rounds
