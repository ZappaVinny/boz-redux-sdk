-- boz.camera: the field of view and camera shakes.
--
--   camera.set_fov(90)                        kept across matches; aiming down sights still zooms
--   camera.fov()                              the field of view and the map's default
--   camera.shake("romero-transform-shake")    George's transform shake (every map: misc group)
--   camera.shake("explosion-large")           a Dead Ops shake (a map build bundles it by name)
--   camera.stop_shake()
--
-- The game's shakes (CCameraShakeConfig resources): romero-transform-shake (misc, so every map),
-- explosion-large and explosion-lightning-bolt (Dead Ops). Fields: duration (ms, below 0: until
-- stopped), limit (the most it moves, x y z), switchInterval and rollInterval (ms between new
-- offsets), rollLimit.
--
-- How it works: CCameraShake (singleton) plays one config at a time (CameraShake_Play(shake,
-- name): +0x20 the config, +0x24 endless, +0x28 time left); each frame it picks offsets (+0x34
-- x y z, +0x40 roll) that CCameraProcessorShake adds to the camera's matrix when the camera
-- update event reaches it. Field of view: CWeaponManager::UpdateFov eases the current FOV (+0xc0)
-- up toward the base FOV (+0xc4, copied from the map's camera at match start) or down to the
-- weapon's sights; it never lowers the current FOV by itself and skips the camera write once it
-- arrived, so changing the base and setting the current FOV just below it makes the next update
-- land on the new value.

local camera = {}

local core = require("boz.core")

local CONFIG, ENDLESS, LEFT, OFFSET, ROLL = 0x20, 0x24, 0x28, 0x34, 0x40
local BASE_FOV, CURRENT_FOV, AIMING = 0xc4, 0xc0, 0xbc

--- The range of field of view the game handles well (degrees).
camera.FOV_RANGE = {min = 20, max = 140, default = 50}

local function shaker()
    return core.singleton("CCameraShake")
end

--- Shakes the camera with a shake config by name. Returns false when it is not loaded.
function camera.shake(name)
    local shake = shaker()
    if not shake then
        return false
    end
    return core.call("CameraShake_Play", shake, name) ~= 0
end

--- Stops the shake.
function camera.stop_shake()
    local shake = shaker()
    if not shake then
        return false
    end
    game.write("u32", shake + CONFIG, 0)
    game.write("u8", shake + ENDLESS, 0)
    game.write("u32", shake + LEFT, 0)
    for at = OFFSET, ROLL, 4 do
        game.write("f32", shake + at, 0)
    end
    return true
end

--- True while a shake plays.
function camera.shaking()
    local shake = shaker()
    return shake ~= nil and game.read("u32", shake + CONFIG) ~= 0
        and (game.read("u8", shake + ENDLESS) ~= 0 or game.read("i32", shake + LEFT) > 0)
end

local fov = {manager = nil, default = nil, wanted = nil, watching = false}

local function apply(manager, degrees, now)
    game.write("f32", manager + BASE_FOV, degrees)
    if now and not game.read("bool", manager + AIMING) then
        game.write("f32", manager + CURRENT_FOV, degrees - 0.01)
    end
end

-- The game resets the base FOV each match: keep the wanted one, and remember each match's own.
local function watch()
    local manager = require("boz.weapons").manager()
    if manager ~= fov.manager then
        fov.manager = manager
        fov.default = manager and game.read("f32", manager + BASE_FOV)
        if manager and fov.wanted then
            apply(manager, fov.wanted, true)
        end
    elseif manager and fov.wanted then
        game.write("f32", manager + BASE_FOV, fov.wanted)
    end
end

--- The field of view in degrees and the map's default, or nil outside a match.
function camera.fov()
    if not fov.watching then
        local manager = require("boz.weapons").manager()
        local base = manager and game.read("f32", manager + BASE_FOV)
        return base, base
    end
    if not fov.manager then
        return nil
    end
    return fov.wanted or fov.default, fov.default
end

--- Sets the field of view in degrees (aiming down sights still zooms); nil restores the map's
--- default. The value is kept across matches. Returns false outside a match (it still applies
--- when the next match starts).
function camera.set_fov(degrees)
    fov.wanted = degrees
    if not fov.watching then
        fov.watching = true
        events.on("frame", watch)
        watch()
        return fov.manager ~= nil
    end
    if not fov.manager then
        return false
    end
    apply(fov.manager, degrees or fov.default, true)
    return true
end

return camera
