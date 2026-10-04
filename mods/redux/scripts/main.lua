-- Redux: quality-of-life settings for playing on PC, in the game's own pause menu
-- (pause > Settings). Settings are saved with the mod.

local pause_settings = require("boz.pause_settings")
local player = require("boz.player")

local DEFAULT_FOV = 50   -- the game's own field of view on every map

local function saved_fov()
    local value = settings.get("fov")
    return type(value) == "number" and value or DEFAULT_FOV
end

local function apply_fov(value)
    player.set_fov(value ~= DEFAULT_FOV and value or nil)
end

pause_settings.add_slider{
    id = "fov",
    label = "Field of view",
    min = DEFAULT_FOV,
    max = 120,
    step = 1,
    get = saved_fov,
    set = function(value)
        settings.set("fov", value)
        apply_fov(value)
    end,
}

apply_fov(saved_fov())
