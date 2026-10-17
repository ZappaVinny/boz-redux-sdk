-- boz.rounds: rounds and the match (Zombies mode).
--
--   rounds.current()            the round number          rounds.zombies_left()
--   rounds.set(10)              rounds.start_next()       rounds.set_spawning(false)
--   rounds.wave()               the round's settings (zombies, health, speeds, ...)
--   rounds.on_start(fn)         rounds.on_end(fn)
--
-- How it works: CWaveManager (singleton) runs the rounds: +0x50 the round's CWave, +0x70 zombies
-- alive, +0x78 the round number, +0x7c spawned and +0x84 killed this round (the round ends when
-- killed reaches the wave's zombie count: vtable +0x50 GetZombieCount(round, powerOn)), +0x88 the
-- next round's wave, timers +0x8c (next spawn), +0x90 (next round), +0x94 (spawning starts),
-- +0xb8 power on. A round starts with SUBJECT_NEW_WAVE (CWaveManager::StartWave: the next wave,
-- round + 1; WaveManager_FillNextWave picks the next wave or a special round) and ends with
-- SUBJECT_WAVE_ENDED. The new-wave info SUBJECT_NEW_WAVE carries (a StartWaveInfo): +4 the wave,
-- +8 / +0xc a special round's health and count, +0x10 the wave after it, +0x14 the round it
-- follows. The Game tab sets a map's rounds (docs/game.md).

local rounds = {}

local core = require("boz.core")
local hash = require("boz.hash")

local WAVE_NEXT = 0x84               -- a CWave: m_NextWave
local SUBJECT = 0x20                 -- CWaveManager: its subject (SUBJECT_NEW_WAVE starts a round)
local WAVE, ALIVE, ROUND, SPAWNED, KILLED = 0x50, 0x70, 0x78, 0x7c, 0x84
local SPAWN_TIMER, NEXT_ROUND_TIMER, START_TIMER, POWER = 0x8c, 0x90, 0x94, 0xb8
local SPECIAL_ROUND, SPECIAL_COUNT = 0x54, 0x58
local GET_ZOMBIE_COUNT, GET_CLASS_NAME, IS_SPECIAL = 0x50, 0x4c, 0x88

--- The round manager (CWaveManager), or nil outside a match.
function rounds.manager()
    return core.singleton("CWaveManager")
end

local function read(offset, kind)
    local manager = rounds.manager()
    return manager and game.read(kind or "u32", manager + offset) or nil
end

--- The round number (0 before the first round), or nil outside a match.
function rounds.current()
    return read(ROUND)
end

--- Zombies alive now.
function rounds.alive()
    return read(ALIVE)
end

--- Zombies spawned this round.
function rounds.spawned() return read(SPAWNED) end
--- Zombies killed this round.
function rounds.killed() return read(KILLED) end

--- True once the power is on.
function rounds.powered()
    local value = read(POWER, "u8")
    return value ~= nil and value ~= 0
end

--- The round's wave (a CWave resource: boz.reflect fields of its class), or nil.
function rounds.wave_pointer()
    local wave = read(WAVE)
    return wave ~= nil and wave ~= 0 and wave or nil
end

--- The round's wave class ("CWave", "CWaveRepeatable", "CWaveSpeciality", "CWaveMonkey").
function rounds.wave_class()
    local wave = rounds.wave_pointer()
    if not wave then
        return nil
    end
    local name = core.virtual(wave, GET_CLASS_NAME)
    return name ~= 0 and game.read("string", name, 32) or nil
end

--- True during a special round (dogs, monkeys).
function rounds.special()
    local wave = rounds.wave_pointer()
    return wave ~= nil and core.virtual(wave, IS_SPECIAL) ~= 0
end

--- How many zombies the round has in all (as the game counts it, with the power's extra ones).
function rounds.total()
    local wave = rounds.wave_pointer()
    if not wave then
        return nil
    end
    return core.virtual(wave, GET_ZOMBIE_COUNT, rounds.current() or 0, rounds.powered() and 1 or 0)
end

--- Zombies still to kill this round.
function rounds.zombies_left()
    local total, killed = rounds.total(), rounds.killed()
    return total and killed and math.max(0, total - killed) or nil
end

--- The round's settings: every field of its wave class by name (boz.reflect), plus "class".
function rounds.wave()
    local wave, class_name = rounds.wave_pointer(), rounds.wave_class()
    if not wave or not class_name then
        return nil
    end
    local values = require("boz.reflect").dump(wave, class_name)
    values.class = class_name
    return values
end

--- Changes a setting of the running round's wave (e.g. "m_ZombieHealth"); it lasts until the
--- level loads again. Returns true, or false and why.
function rounds.set_wave(field, value)
    local wave, class_name = rounds.wave_pointer(), rounds.wave_class()
    if not wave then
        return false, "no round running"
    end
    return require("boz.reflect").set(wave, class_name, field, value)
end

--- Milliseconds until the next spawn, until the next round starts, and until spawning starts.
function rounds.timers()
    return read(SPAWN_TIMER, "i32"), read(NEXT_ROUND_TIMER, "i32"), read(START_TIMER, "i32")
end

--- The round the last special round ran in, and how many have run.
function rounds.special_history()
    return read(SPECIAL_ROUND), read(SPECIAL_COUNT)
end

local function new_wave_info()
    local info = core.scratch("rounds.info", 0x20)
    for at = 0, 0x1c, 4 do
        game.write("u32", info + at, 0)
    end
    game.write("u32", info, core.sym("s_StartWaveInfoVtable"))
    return info
end

local function send_new_wave(manager, info)
    return require("boz.game_events").send(manager + SUBJECT, "SUBJECT_NEW_WAVE", info)
end

--- Starts the next round now, as the game does when the pause between rounds ends: the next
--- wave of the chain (or a special round when one is due), round + 1; zombies left over go.
--- Returns false outside a round. (The console's StartWave needs a wave name: without one it
--- stops the rounds.)
function rounds.start_next()
    local manager = rounds.manager()
    if not manager or game.read("ptr", manager + WAVE) == 0 then
        return false
    end
    local info = new_wave_info()
    core.call("WaveManager_FillNextWave", manager, game.read("u8", manager + POWER), info)
    game.write("u32", info + 0x14, game.read("u32", manager + ROUND))
    return send_new_wave(manager, info)
end

local function start(manager, wave_hash, next_hash, after_round)
    local info = new_wave_info()
    game.write("u32", info + 4, wave_hash)
    game.write("u32", info + 0x10, next_hash)
    game.write("u32", info + 0x14, after_round)
    game.write("u32", manager + ROUND, after_round)   -- the event leaves a 0 round alone
    return send_new_wave(manager, info)
end

--- The level's first wave (its name hash): the level's starting wave for the difficulty
--- (CLevel m_StartingWavesSP: easy, normal, hard), else "wave1".
function rounds.first_wave()
    local map = require("boz.map")
    local info = map.level_info()
    if info then
        local ok, starts = pcall(require("boz.reflect").get, info, "CLevel", "m_StartingWavesSP")
        local first = ok and type(starts) == "table" and starts[(map.difficulty_index() or 0) + 1]
        if first and first ~= 0 then
            return first
        end
    end
    return hash.name("wave1")
end

--- The wave round `number` plays (its name hash): the level's first wave, followed along each
--- wave's next wave (a repeating wave stays, growing with the round number). Special rounds are
--- not counted.
function rounds.wave_for(number)
    local current = rounds.first_wave()
    for _ = 2, number do
        local wave = core.call("Wave_Find", current)
        local next_hash = wave ~= 0 and game.read("u32", wave + WAVE_NEXT) or 0
        if next_hash == 0 or next_hash == current then
            break
        end
        current = next_hash
    end
    return current
end

--- Starts round `number` now (1 or more): its wave from the level's chain, zombie count and
--- health as that round has them; zombies left over go. Returns false outside a match.
function rounds.set(number)
    local manager = rounds.manager()
    number = math.floor(tonumber(number) or 0)
    if not manager or number < 1 or game.read("ptr", manager + WAVE) == 0 then
        return false
    end
    local wave_hash = rounds.wave_for(number)
    local wave = core.call("Wave_Find", wave_hash)
    if wave == 0 then
        return false
    end
    return start(manager, wave_hash, game.read("u32", wave + WAVE_NEXT), number - 1)
end

--- Makes the next round started be round `number` (its wave stays the chain's next one; the
--- repeating round's growth and the game's health use the number).
function rounds.go_to(number)
    local manager = rounds.manager()
    if not manager then
        return false
    end
    game.write("u32", manager + ROUND, math.max(0, number - 1))
    return true
end

--- Queues a wave by name or hash (one of the level's CWave resources: "wave1", "boz_normal_3",
--- ...) as the next round.
function rounds.queue(wave)
    local manager = rounds.manager()
    if not manager then
        return false
    end
    core.call("CWaveManager::QueueWave", manager, hash.of(wave))
    return true
end

--- Calls fn(round) when a round starts. Returns a handle (boz.game_events.off).
function rounds.on_start(fn)
    return require("boz.game_events").on("SUBJECT_NEW_WAVE", function()
        fn((rounds.current() or 0) + 1)
    end)
end

--- Calls fn(round) when a round's last zombie dies.
function rounds.on_end(fn)
    return require("boz.game_events").on("SUBJECT_WAVE_ENDED", function()
        fn(rounds.current() or 0)
    end)
end

--- Stops (false) or resumes (true) zombie spawning: no new zombie appears, the round waits
--- (DisableZombieSpawning; CWaveManager::CreateZombie checks it).
function rounds.set_spawning(on)
    return require("boz.console").exec("DisableZombieSpawning " .. (on and "false" or "true"))
end

--- True while zombies spawn (rounds.set_spawning).
function rounds.spawning()
    return require("boz.console").get("DisableZombieSpawning") ~= "true"
end

return rounds
