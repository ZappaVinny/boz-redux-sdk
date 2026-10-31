-- boz.levels: start levels (Zombies maps) without going through the menus.
--
--   levels.start("kino")      levels.coop("kino")      levels.autostart_from_settings()
--
-- How it works: the front end's StartLevel console command starts a single-player match on a
-- level by name (it sends the game's own start-game event). The command only works once the
-- front end is running, so levels.start waits for the Flash menu's first ActionScript call and a
-- short settling time. levels.autostart_from_settings reads a one-shot request from the mod's
-- settings: the editor's Build & Run and the launcher write it. levels.coop does what the
-- multiplayer screen does on its Wi-Fi button with one map chosen: map vote off, the map as the
-- lobby's level (CLevelManager+0x55 and FrontEnd_SetLobbyLevel), then the Flash page change to
-- the Wi-Fi lobby. The lobby searches for a room whose name starts with the level, joins it, or
-- else publishes its own; the host's start event carries the level to every player (each needs
-- the map's mod).

local levels = {}

local AUTOSTART_KEY = "autostart_level"
local AUTOSTART_VARS_KEY = "autostart_vars"   -- "Name=value;Name=value", set before the level starts
local AUTOSTART_MODE_KEY = "autostart_mode"   -- "coop": the Wi-Fi co-op room for the level
local LEVEL_NAME_OFFSET = 0x55                -- CLevelManager: the level the next match plays
local SETTLE_FRAMES = 60

local pending = nil      -- level waiting for the front end
local pending_coop = false -- open the co-op room for it instead of starting it
local menu_state = nil   -- the Flash menu state that called ActionScript last
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

local function open_coop_room(name)
    local core = require("boz.core")
    local levels_manager = core.singleton("CLevelManager")
    if not levels_manager or not menu_state then
        log("boz.levels: the front end is not ready; open the co-op room for " .. name ..
            " from the menu")
        return false
    end
    core.call("strcpy", levels_manager + LEVEL_NAME_OFFSET, name)
    core.call("FrontEnd_SetMapVote", 0)
    core.call("FrontEnd_SetLobbyLevel", "", name)
    log("boz.levels: co-op room for " .. name)
    core.call("CFlashMenuState::TransitionState", menu_state, "ConnectWifi", "multi_lobby",
              "lobby", 0)
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
    if pending_coop then
        pending_coop = false
        open_coop_room(name)
    else
        start_now(name)
    end
end

local function watch()
    if watching then
        return
    end
    watching = true
    hook.add(require("boz.core").sym("CFlashMenuState::CallActionScript"), {after = function(call)
        menu_state = call:arg(1)
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
    pending_coop = false
    watch()
end

--- Opens the Wi-Fi co-op room for the level once the front end is up, as the multiplayer screen
--- does with one map chosen: it joins a room on the same level when it finds one, else hosts.
--- Every player needs the level (the map's mod). Call it while the mod's script starts.
function levels.coop(name)
    if type(name) ~= "string" or name == "" then
        error("levels.coop needs a level name", 2)
    end
    pending = name
    pending_coop = true
    watch()
end

--- Starts the level a tool asked for, once: reads and clears the mod's "autostart_level"
--- setting (the SDK's Build & Run and the launcher write it), its "autostart_mode" ("coop": the
--- co-op room instead of a single-player match) and its "autostart_vars" ("Name=value;..."),
--- console variables set just before the level starts (e.g. UnlimitedHealth=true). Returns the
--- level name or nil.
function levels.autostart_from_settings()
    local name = settings.get(AUTOSTART_KEY)
    if type(name) ~= "string" or name == "" then
        return nil
    end
    settings.set(AUTOSTART_KEY, nil)
    local vars = settings.get(AUTOSTART_VARS_KEY)
    settings.set(AUTOSTART_VARS_KEY, nil)
    pending_vars = type(vars) == "string" and vars ~= "" and vars or nil
    local mode = settings.get(AUTOSTART_MODE_KEY)
    settings.set(AUTOSTART_MODE_KEY, nil)
    if mode == "coop" then
        levels.coop(name)
    else
        levels.start(name)
    end
    return name
end

return levels
