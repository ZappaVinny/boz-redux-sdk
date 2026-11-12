-- boz.online: Play Online through a server the player chooses (the client's network module).
-- The game's own online service is gone; a server that speaks its protocol can take its place.
-- Matches run between the players' games; the server signs them in and lists rooms.
--
--   online.available()          false on clients without online servers (before BOZ Redux 0.4.0)
--   online.server()             the server Play Online uses, "" when it is off
--   online.set_server(host)     call it while the mod starts; needs mod.toml [network] connects
--   online.check(host, fn)      fn(ok, message): whether the server answers
--   online.connected()          logged in to the server now
--   online.on_screen(fn)        fn(true) when the Multiplayer screen opens, fn(false) when it closes
--
-- game: CFlashMenuState::Enter, CFrontendStateMultiConnectionType::Enter, IwDemonware::Get,
--       IwDemonware::IsConnected

local online = {}

local core = require("boz.engine.core")

local function client_network()
    return type(network) == "table" and network.set_server ~= nil
end

--- Whether this client can use online servers.
function online.available()
    return client_network()
end

--- The server Play Online goes to, or "" when online play is off.
function online.server()
    return client_network() and network.server() or ""
end

--- Sends Play Online to host ("" or nil: off). Call it while the mod starts: the game signs in
--- once per run, when the Multiplayer screen opens, and a failed sign-in (online was off) does
--- not recover, so a later change is for the next start. Returns false on clients without
--- online servers. The mod's mod.toml must list the host under [network] connects.
function online.set_server(host)
    if not client_network() then
        return false
    end
    network.set_server(host or "")
    return true
end

--- Tries to reach a server's login port; fn(ok, message) runs on a later frame.
function online.check(host, fn)
    if not client_network() then
        fn(false, "This version of BOZ Redux cannot use online servers.")
        return
    end
    network.check(host, fn)
end

-- The game's network layer exists once the game has started (not while mods start).
local function game_network()
    return core.singleton("CGameNetwork")
end

--- True while the game is logged in to the online server (false before the game has started).
function online.connected()
    if not game_network() then
        return false
    end
    local dw = core.call("IwDemonware::Get")
    return dw ~= 0 and (core.call("IwDemonware::IsConnected", dw) & 0xff) ~= 0
end

local listeners = {}
local current, screen = nil, nil
local was_on = false
local watching = false

local function update()
    local on = current ~= nil and current == screen
    if on == was_on then
        return
    end
    was_on = on
    for _, fn in ipairs(listeners) do
        fn(on)
    end
end

--- Calls fn(true) when the game's Multiplayer screen (Online or Wi-Fi) opens and fn(false) when
--- another screen replaces it.
function online.on_screen(fn)
    table.insert(listeners, fn)
    if watching then
        return
    end
    watching = true
    -- Every menu screen's Enter calls CFlashMenuState::Enter first; the Multiplayer screen's own
    -- Enter returns after it, so it marks its screen last.
    hook.add(core.sym("CFlashMenuState::Enter"), {after = function(call)
        current = call:arg(1)
        update()
    end})
    hook.add(core.sym("CFrontendStateMultiConnectionType::Enter"), {after = function(call)
        screen = call:arg(1)
        current = screen
        update()
    end})
end

return online
