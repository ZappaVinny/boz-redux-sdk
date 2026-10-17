-- boz.levels: start levels (Zombies maps) without going through the menus.
--
--   levels.start("kino")      levels.autostart_from_settings()
--
-- How it works: the front end's StartLevel console command starts a single-player match on a
-- level by name (it sends the game's own start-game event). The command only works once the
-- front end is running, so levels.start waits for the Flash menu's first ActionScript call and a
-- short settling time. levels.autostart_from_settings reads a one-shot request from the mod's
-- settings: the editor's Build & Run writes it to start the level just saved.

local levels = {}

local AUTOSTART_KEY = "autostart_level"
local AUTOSTART_VARS_KEY = "autostart_vars"   -- "Name=value;Name=value", set before the level starts
local SETTLE_FRAMES = 60

local pending = nil      -- level waiting for the front end
local pending_vars = nil -- console variables to set just before it starts
local countdown = nil    -- frames left once the front end is up
local watching = false

local function start_now(name)
    local console = require("boz.console")
    if not console.ready() then
        log("boz.levels: the console is not ready; start " .. name .. " from the menu")
        return false
    end
    for entry in string.gmatch(pending_vars or "", "[^;]+") do
        local var, value = string.match(entry, "^%s*([%w_]+)%s*=%s*(.-)%s*$")
        if var then
            local kept, err = console.register(var, value)
            log("boz.levels: " .. var .. " = " .. tostring(kept or err))
        end
    end
    pending_vars = nil
    log("boz.levels: starting " .. name)
    console.exec("StartLevel " .. name)
    return true
end

local function tick()
    if not countdown then
        return
    end
    countdown = countdown - 1
    if countdown > 0 then
        return
    end
    events.off("frame", tick)
    countdown = nil
    local name = pending
    pending = nil
    start_now(name)
end

local function watch()
    if watching then
        return
    end
    watching = true
    hook.add(require("boz.core").sym("CFlashMenuState::CallActionScript"), {after = function()
        if pending and not countdown then
            countdown = SETTLE_FRAMES
            events.on("frame", tick)
        end
    end})
end

--- Starts a single-player match on the level (e.g. "kino") once the front end is up. Call it
--- while the mod's script starts; the match starts after the main menu appears.
function levels.start(name)
    if type(name) ~= "string" or name == "" then
        error("levels.start needs a level name", 2)
    end
    pending = name
    watch()
end

--- Starts the level a tool asked for, once: reads and clears the mod's "autostart_level"
--- setting (the SDK's Build & Run writes it), and its "autostart_vars" ("Name=value;..."), console
--- variables set just before the level starts (e.g. UnlimitedHealth=true). Returns the level name
--- or nil.
function levels.autostart_from_settings()
    local name = settings.get(AUTOSTART_KEY)
    if type(name) ~= "string" or name == "" then
        return nil
    end
    settings.set(AUTOSTART_KEY, nil)
    local vars = settings.get(AUTOSTART_VARS_KEY)
    settings.set(AUTOSTART_VARS_KEY, nil)
    pending_vars = type(vars) == "string" and vars ~= "" and vars or nil
    levels.start(name)
    return name
end

return levels
