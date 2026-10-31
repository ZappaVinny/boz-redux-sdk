-- boz.levels against a fake game: lua5.4 lib/tests/levels_test.lua (from the SDK root).
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path

local stored = {autostart_level = "apothicon_reborn", autostart_mode = "coop"}
settings = {
    get = function(key, default)
        if stored[key] == nil then
            return default
        end
        return stored[key]
    end,
    set = function(key, value) stored[key] = value end,
}
local fake = require("fake_game").install({strict = true})
local executed = {}
package.loaded["boz.console"] = {
    ready = function() return true end,
    register = function() return true end,
    exec = function(line) table.insert(executed, line) return "" end,
}
local LEVEL_MANAGER, MENU = 0x5000, 0x7000
fake.memory[fake.address("CLevelManager::s_instance")] = LEVEL_MANAGER
for _, name in ipairs({"strcpy", "FrontEnd_SetMapVote", "FrontEnd_SetLobbyLevel",
                       "CFlashMenuState::TransitionState"}) do
    fake.functions[name] = function() return 0 end
end

local levels = require("boz.levels")
local check = fake.check

-- The launcher's co-op request: read once, then the room opens after the menu settles.
check(levels.autostart_from_settings() == "apothicon_reborn", "the level asked for")
check(stored.autostart_level == nil and stored.autostart_mode == nil,
      "the one-shot request is cleared")
fake.run_hook("CFlashMenuState::CallActionScript", {MENU}, "after")
for _ = 1, 59 do
    fake.frame()
end
check(not fake.last("CFlashMenuState::TransitionState"), "waits for the menu to settle")
fake.frame()
local copy = fake.last("strcpy")
check(copy and copy[2] == LEVEL_MANAGER + 0x55 and copy[3] == "apothicon_reborn",
      "the map is the level the match plays")
check(fake.last("FrontEnd_SetMapVote")[2] == 0, "map vote off")
local lobby = fake.last("FrontEnd_SetLobbyLevel")
check(lobby[2] == "" and lobby[3] == "apothicon_reborn", "the map is the lobby's level")
local page = fake.last("CFlashMenuState::TransitionState")
check(page[2] == MENU and page[3] == "ConnectWifi" and page[4] == "multi_lobby"
      and page[5] == "lobby", "the Wi-Fi lobby page, from the menu that called last")
check(#executed == 0, "no single-player start")

-- A solo request still starts the level through the console.
stored.autostart_level = "kino"
check(levels.autostart_from_settings() == "kino", "the solo level")
fake.run_hook("CFlashMenuState::CallActionScript", {MENU}, "after")
for _ = 1, 60 do
    fake.frame()
end
check(executed[1] == "StartLevel kino", "single-player start")
check(#fake.called("CFlashMenuState::TransitionState") == 1, "no second room")

print("levels_test: ok")
