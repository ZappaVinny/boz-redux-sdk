-- boz.frontend: changing the main menu (front end), one Flash movie played by gameswf.
--
-- Building blocks for mods that change main-menu screens; higher-level helpers (adding widgets
-- to a screen) will grow here. frontend.patch_screen adds ActionScript (built with boz.avm1) to a
-- screen; frontend.call runs one of the movie's ActionScript functions.
--
-- How it works: ActionScript talks to the game with _root.sendMsg(name, a, b), which the native
-- IsSendMessage turns into the active CFlashMenuState's OnEvent(IwHashString(name), a, b)
-- (numbers arrive as integers); screens pass events they do not know to CFlashMenuState::OnEvent,
-- so hooks can add new ones. The game calls ActionScript with
-- CFlashMenuState::CallActionScript(state, function, format, ...) (gameswf format: "%d", "%f",
-- "%s", comma separated). The movie is patched as it loads (assets.patch), so no game file is
-- changed or shipped.

local avm1 = require("boz.avm1")
local swf = require("boz.swf")
local flash = require("boz.flash")

local frontend = {}

frontend.MOVIE = "fe_v4_cs4_swf.bin"

local screen_patches = {}
local registered = false

local function patch_movie(bytes)
    local movie, err = swf.parse(bytes)
    if not movie then
        log("boz.frontend: cannot read the menu movie: " .. err)
        return nil
    end
    for _, patch in ipairs(screen_patches) do
        local sprite = movie:find_sprite_using(table.unpack(patch.names))
        if sprite then
            local b = avm1.builder()
            patch.build(b)
            sprite:add_first_frame_action(b:bytes())
        else
            log("boz.frontend: no screen uses " .. table.concat(patch.names, ", "))
        end
    end
    return movie:serialize()
end

--- Adds a frame script to the screen (sprite) whose scripts use all of names (e.g.
--- {"initialise", "SUBJECT_OPTIONS_VOLUME"} is the Options screen). build(b) fills an avm1
--- builder; the script runs after the screen's own first-frame script. Call while the mod's
--- script starts (before the menu loads).
function frontend.patch_screen(names, build)
    screen_patches[#screen_patches + 1] = {names = names, build = build}
    if not registered then
        registered = true
        assets.patch(frontend.MOVIE, patch_movie)
    end
end

--- Calls an ActionScript function on a Flash menu state (CFlashMenuState) with gameswf's
--- format, e.g. frontend.call(state, "setMusicVol", "%d", 50).
function frontend.call(state, fn, format, ...)
    return game.call("CFlashMenuState::CallActionScript", state, fn, format, ...)
end

--- Shows ActionScript trace() output and gameswf warnings in the log (boz.flash.capture_log).
frontend.capture_log = flash.capture_log

return frontend
