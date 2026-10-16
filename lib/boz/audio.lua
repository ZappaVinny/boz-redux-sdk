-- boz.audio: sounds, sound sequences and music.
--
--   audio.play("gersch_opens", position)       a sound (spec) by name, at a place or everywhere
--   audio.sequence("dog_wave_start")           a sequence (voice lines, stings, wave starts)
--   audio.music("115.mp3", {loop = true})      a music track from blackops-music
--   audio.pause_music()  audio.resume_music()  audio.music_volume(0.5)
--
-- Music tracks (assets/blackops-music): 115.mp3, a7x.mp3, abracadavre.mp3,
-- mus_theatre_underscore.mp3, mus_gameover.mp3, mus_game_over_element_115.mp3 and the perk and
-- Pack-a-Punch stings (mus_jugganog_sting.mp3, mus_revive_sting.mp3, ...). A map ships its own
-- music by putting an .mp3 in its mod's assets (it replaces one of the same name).
--
-- How it works: CIwSoundManager::Play(manager, spec hash, position, 0, 0) plays a sound spec
-- (positioned when a position {x, y, z} in whole centimetres is given); CSoundSequenceManager::Play
-- (manager, hash, 0x1000, 0) runs a CSoundSequence; Music_Play(CMusicManager, path, repeat, now,
-- volume, lock) streams an mp3 (now: switch at once instead of fading; lock: nothing else may
-- change the music until it ends), Music_Pause / Music_Resume (s3eAudio), Music_SetVolume
-- (+0xb0, 0-256). The music's current track hash is at +4.

local audio = {}

local hash = require("boz.hash")

local FALLBACK = {["CIwSoundManager::s_instance"] = 0x4535d8, ["CIwSoundManager::Play"] = 0x0d6dae + 1,
                  ["CSoundSequenceManager::s_instance"] = 0x460cf8, ["CSoundSequenceManager::Play"] = 0x1f9fe8 + 1,
                  ["CMusicManager::s_instance"] = 0x463654, ["Music_Play"] = 0x1b9d1c + 1,
                  ["Music_Pause"] = 0x1b9bbe + 1, ["Music_Resume"] = 0x1b9bc2 + 1,
                  ["Music_SetVolume"] = 0x1b9bc6 + 1}
local MUSIC_TRACK = 4

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function singleton(name)
    local value = game.read("ptr", sym(name .. "::s_instance"))
    return value ~= 0 and value or nil
end

local function id(name)
    return type(name) == "number" and name or hash.name(name)
end

local scratch = nil

--- Plays a sound spec by name or hash; at a position {x, y, z} when given. Returns true.
function audio.play(name, position)
    local manager = singleton("CIwSoundManager")
    if not manager then
        return false
    end
    local at = 0
    if position then
        scratch = scratch or game.alloc(16)
        game.write("i32", scratch, math.floor(position.x or position[1] or 0))
        game.write("i32", scratch + 4, math.floor(position.y or position[2] or 0))
        game.write("i32", scratch + 8, math.floor(position.z or position[3] or 0))
        at = scratch
    end
    game.call(sym("CIwSoundManager::Play"), manager, id(name), at, 0, 0)
    return true
end

--- Runs a sound sequence by name or hash (wave starts, announcer lines, stings).
function audio.sequence(name)
    local manager = singleton("CSoundSequenceManager")
    if not manager then
        return false
    end
    game.call(sym("CSoundSequenceManager::Play"), manager, id(name), 0x1000, 0)
    return true
end

--- Plays a music track (a file of blackops-music, e.g. "115.mp3"). Options: loop (repeat it),
--- fade (fade from the current track instead of switching at once), volume (0-1, default 1),
--- lock (nothing else changes the music until it ends).
function audio.music(file, options)
    options = options or {}
    local manager = singleton("CMusicManager")
    if not manager then
        return false
    end
    local path = file:find("/", 1, true) and file or "blackops-music/" .. file
    game.call(sym("Music_Play"), manager, path, options.loop and 1 or 0, options.fade and 0 or 1,
              hook.float_bits(options.volume or 1.0), options.lock and 1 or 0)
    return true
end

--- The hash of the music track playing (IwHashString of its path), or 0.
function audio.music_track()
    local manager = singleton("CMusicManager")
    return manager and game.read("u32", manager + MUSIC_TRACK) or 0
end

--- Pauses and resumes the music.
function audio.pause_music()
    game.call(sym("Music_Pause"), singleton("CMusicManager") or 0)
    return true
end
function audio.resume_music()
    game.call(sym("Music_Resume"), singleton("CMusicManager") or 0)
    return true
end

--- Sets the music volume (0-1).
function audio.music_volume(volume)
    local manager = singleton("CMusicManager")
    if not manager then
        return false
    end
    game.call(sym("Music_SetVolume"), manager, math.floor(math.max(0, math.min(1, volume)) * 4096))
    return true
end

return audio
