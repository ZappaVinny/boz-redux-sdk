-- boz.engine.network: co-op state.
--
--   network.host()          true when this game runs the match (single player too)
--   network.wifi()          true for local Wi-Fi co-op
--   network.players()       the other players in the match: {entity, ...}
--
-- game: CGameNetwork::IsWifiMode

local network = {}

local core = require("boz.engine.core")

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
    for entity in require("boz.engine.entities").each("CRemotePlayer") do
        table.insert(out, entity)
    end
    return out
end

return network
