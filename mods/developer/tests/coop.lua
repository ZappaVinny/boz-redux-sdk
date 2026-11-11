--! players: 2
--! timeout: 240
-- Wi-Fi co-op on one machine: the host opens a Kino room, the guest finds and joins it, the
-- lobby counts down and both play the match, each seeing the other.
local network = require("boz.engine.network")

test.coop_map("kino", {UnlimitedHealth = true, MultiplayerLobbyTimeWifiMs = 5000})

test.step("both players are in the match", function()
    test.wait_until(test.in_match, 180, "the co-op match")
    test.wait_until(function() return #network.players() == 1 end, 60, "the other player")
    test.wait(5)
    test.screenshot("coop")
end)

test.step("the host runs the match", function()
    test.expect(network.wifi(), "the match is Wi-Fi co-op")
    test.expect(network.host() == (test.role == "host"),
                test.role .. ": network.host() is " .. tostring(network.host()))
end)

test.step("no Lua errors", function()
    test.expect(test.errors() == 0, test.errors() .. " Lua errors in mods")
end)
