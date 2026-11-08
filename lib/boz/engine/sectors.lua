-- boz.engine.sectors: the level's sectors (rooms the game draws only when the camera can see
-- them through portals).
--
--   sectors.find("mymap_sector_lobby")   the CIsSector of a sector group, or nil
--   sectors.drawn(sector)                 drawn this frame
--   sectors.set_culling(false)            draw every sector in view (no portals), for comparisons
--
-- game: SectorManager_Render, SectorManager_DrawThroughPortals (CIsSectorManager, CIsSector)

local sectors = {}

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")

local MAP, DRAW_ALL = 0x28, 0x53            -- CIsSectorManager: sectors by name hash; no culling
local NODE_LEFT, NODE_RIGHT, NODE_KEY, NODE_VALUE = 0x8, 0xc, 0x10, 0x14
local VISITED = 0xd4                        -- CIsSector: drawn this frame

local function manager()
    return core.singleton("CIsSectorManager")
end

-- Every (name hash, CIsSector) of the map's red-black tree, in order.
local function each(node, out, depth)
    if node == 0 or depth > 64 then
        return out
    end
    each(game.read("ptr", node + NODE_LEFT), out, depth + 1)
    out[#out + 1] = {game.read("u32", node + NODE_KEY), game.read("ptr", node + NODE_VALUE)}
    each(game.read("ptr", node + NODE_RIGHT), out, depth + 1)
    return out
end

--- Every sector of the level: a list of {hash, sector}.
function sectors.list()
    local m = manager()
    if not m then
        return {}
    end
    local header = game.read("ptr", m + MAP)
    return header ~= 0 and each(game.read("ptr", header + 4), {}, 0) or {}
end

--- The CIsSector of a sector group by its name, or nil.
function sectors.find(group_name)
    local wanted = hash.name(group_name)
    for _, item in ipairs(sectors.list()) do
        if item[1] == wanted then
            return item[2]
        end
    end
    return nil
end

--- True when the game drew the sector this frame.
function sectors.drawn(sector)
    return sector ~= nil and sector ~= 0 and game.read("u8", sector + VISITED) ~= 0
end

--- Portal culling on (true, the game's way) or off (every sector in view is drawn).
function sectors.set_culling(on)
    local m = manager()
    if m then
        game.write("u8", m + DRAW_ALL, on and 0 or 1)
    end
    return m ~= nil
end

--- True while portal culling is on.
function sectors.culling()
    local m = manager()
    return m ~= nil and game.read("u8", m + DRAW_ALL) == 0
end

return sectors
