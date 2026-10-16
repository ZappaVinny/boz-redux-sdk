-- boz.camera: camera shakes and the field of view.
--
--   camera.shake("romero-transform-shake")    George's transform shake (every map: misc group)
--   camera.shake("explosion-large")           a Dead Ops shake (a map build bundles it by name)
--   camera.stop_shake()
--   camera.set_fov(70)                        boz.player's field of view
--
-- The game's shakes (CCameraShakeConfig resources): romero-transform-shake (misc, so every map),
-- explosion-large and explosion-lightning-bolt (Dead Ops). Fields: duration (ms, below 0: until
-- stopped), limit (the most it moves, x y z), switchInterval and rollInterval (ms between new
-- offsets), rollLimit.
--
-- How it works: CCameraShake (singleton) plays one config at a time (CameraShake_Play(shake,
-- name): +0x20 the config, +0x24 endless, +0x28 time left); each frame it picks offsets (+0x34
-- x y z, +0x40 roll) that CCameraProcessorShake adds to the camera's matrix when the camera
-- update event reaches it.

local camera = {}

local FALLBACK = {["CCameraShake::s_instance"] = 0x460cf4, ["CameraShake_Play"] = 0x127e30 + 1}
local CONFIG, ENDLESS, LEFT, OFFSET, ROLL = 0x20, 0x24, 0x28, 0x34, 0x40

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function shaker()
    local shake = game.read("ptr", sym("CCameraShake::s_instance"))
    return shake ~= 0 and shake or nil
end

--- Shakes the camera with a shake config by name. Returns false when it is not loaded.
function camera.shake(name)
    local shake = shaker()
    if not shake then
        return false
    end
    return game.call(sym("CameraShake_Play"), shake, name) ~= 0
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

--- The field of view (boz.player.set_fov: degrees, nil for the map's own).
function camera.set_fov(degrees)
    return require("boz.player").set_fov(degrees)
end

return camera
