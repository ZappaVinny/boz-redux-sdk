-- boz.audio: sounds, sound sequences and music.
--
--   audio.play("gersch_opens", position)       a sound (spec) by name, at a place or everywhere
--   audio.sequence("dog_wave_start")           a sequence (voice lines, stings, wave starts)
--   audio.music("115.mp3", {loop = true})      a music track from blackops-music
--   audio.pause_music()  audio.resume_music()  audio.music_volume(0.5)
--
-- game: CIwSoundManager::Play, CSoundSequenceManager::Play, Music_Play, Music_Pause, Music_Resume

local audio = {}

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")

local MUSIC_TRACK = 4

local singleton = core.singleton

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
    core.call("CIwSoundManager::Play", manager, id(name), at, 0, 0)
    return true
end

--- Runs a sound sequence by name or hash (wave starts, announcer lines, stings).
function audio.sequence(name)
    local manager = singleton("CSoundSequenceManager")
    if not manager then
        return false
    end
    core.call("CSoundSequenceManager::Play", manager, id(name), 0x1000, 0)
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
    core.call("Music_Play", manager, path, options.loop and 1 or 0, options.fade and 0 or 1,
              hook.float_bits(options.volume or 1.0), options.lock and 1 or 0)
    return true
end

--- The hash of the music track playing (IwHashString of its path), or 0.
function audio.music_track()
    local manager = singleton("CMusicManager")
    return manager and game.read("u32", manager + MUSIC_TRACK) or 0
end

--- Pauses the music.
function audio.pause_music()
    core.call("Music_Pause", singleton("CMusicManager") or 0)
    return true
end
--- Resumes the music.
function audio.resume_music()
    core.call("Music_Resume", singleton("CMusicManager") or 0)
    return true
end

--- Sets the music volume (0-1).
function audio.music_volume(volume)
    local manager = singleton("CMusicManager")
    if not manager then
        return false
    end
    core.call("Music_SetVolume", manager, math.floor(math.max(0, math.min(1, volume)) * 4096))
    return true
end

return audio
