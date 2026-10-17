-- boz.network: co-op state.
--
--   network.host()          true when this game runs the match (single player too)
--   network.wifi()          true for local Wi-Fi co-op
--   network.players()       the other players in the match: {entity, ...}
--
-- How it works: CGameNetwork (singleton) +0x54 is the host flag the gameplay code checks (only
-- the host spawns zombies, counts kills, drops power-ups; the others follow its NetworkProperty
-- fields and network events); CGameNetwork::IsWifiMode is the Bonjour TCP configuration; other
-- players are entities with a CRemotePlayer (their weapons CRemotePlayerWeapon, perks
-- CRemotePerkManager). The online services (DemonWare) are not used by BOZ Redux.

local network = {}

local core = require("boz.core")

local HOST = 0x54

local function instance()
    return core.singleton("CGameNetwork")
end

--- True when this game runs the match.
function network.host()
    local n = instance()
    return n ~= nil and game.read("u8", n + HOST) ~= 0
end

--- True for local Wi-Fi co-op.
function network.wifi()
    local n = instance()
    return n ~= nil and ((core.call("CGameNetwork::IsWifiMode", n) or 0) & 0xff) ~= 0
end

--- The other players: a list of their entities.
function network.players()
    local out = {}
    for entity in require("boz.entities").each("CRemotePlayer") do
        table.insert(out, entity)
    end
    return out
end

return network
