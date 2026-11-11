--! touch: true
--! timeout: 240
-- Phone controls: the game's own touch HUD, driven by test fingers. The left stick moves the
-- player and a swipe on the right half turns the view.
local player = require("boz.engine.player")

test.start_map("kino", {UnlimitedHealth = true})

local function distance(a, b)
    local dx, dz = a.x - b.x, a.z - b.z
    return math.sqrt(dx * dx + dz * dz)
end

test.step("the match starts", function()
    test.wait_until(test.in_match, 150, "the Kino match")
    test.wait(4)
    test.screenshot("touch_hud")
end)

test.step("the left stick moves the player", function()
    local before = player.position()
    test.drag(0.12, 0.78, 0.12, 0.62, 0.3, true)
    test.wait(2)
    test.touch(9, "up", 0.12, 0.62)
    local moved = distance(player.position(), before)
    test.expect(moved > 30, string.format("the player moved %.0f units (more than 30)", moved))
end)

test.step("a swipe turns the view", function()
    local effects = require("boz.game.effects")
    local before = test.wait_until(effects.aim, 10, "the crosshair point")
    test.drag(0.6, 0.45, 0.85, 0.45, 0.5)
    test.wait(0.5)
    test.screenshot("after_turn")
    local after = effects.aim()
    local moved = after and distance(after, before) or 0
    test.expect(moved > 50, string.format("the crosshair point moved %.0f units (more than 50)", moved))
end)

test.step("no Lua errors", function()
    test.expect(test.errors() == 0, test.errors() .. " Lua errors in mods")
end)
