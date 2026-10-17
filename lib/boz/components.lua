-- boz.components: finding the game's entity components (helper for the other modules).
--
-- Most mods use boz.player and friends instead. components.local_player() gives the local
-- player's entity; components.on_player(table) or components.each(table) find components by the
-- gamedef name of their table (e.g. "CPerkManager::s_table").
--
-- How it works: component tables (T::s_table) keep components in a red-black tree keyed by entity
-- id: header node pointer at table +4 (header +8 = first node), nodes link parent +4, left +8,
-- right +0xc, key +0x10, component +0x14.

local components = {}

local core = require("boz.core")
local symbols = require("boz.symbol_data")

--- The local player's entity and its id, or nil outside a Zombies match (boz.map.player).
function components.local_player()
    return require("boz.map").player()
end

--- The address of a component table by its gamedef name ("CPerkManager::s_table") or class
--- ("CPerkManager"), or nil when the game has no such table.
function components.table(name)
    if type(name) == "number" then
        return name
    end
    local class_name = name:gsub("::s_table$", "")
    local address = core.sym(class_name .. "::s_table")
    if address then
        return address
    end
    local offset = symbols.tables[class_name]
    return offset and game.base() + offset or nil
end

--- The component of an entity id in a table (by gamedef name, e.g. "CPerkManager::s_table",
--- or class name).
function components.find(table_name, id)
    local address = components.table(table_name)
    if not address then
        return nil
    end
    local component = core.call("CIsComponentTableBase::Find", address, id)
    return component ~= 0 and component or nil
end

--- The component on the local player's entity, or nil.
function components.on_player(table_name)
    local _, id = components.local_player()
    return id and components.find(table_name, id)
end

local function next_node(node)
    local right = game.read("ptr", node + 0xc)
    if right ~= 0 then
        node = right
        while game.read("ptr", node + 8) ~= 0 do
            node = game.read("ptr", node + 8)
        end
        return node
    end
    local parent = game.read("ptr", node + 4)
    while node == game.read("ptr", parent + 0xc) do
        node = parent
        parent = game.read("ptr", parent + 4)
    end
    if game.read("ptr", node + 0xc) ~= parent then
        node = parent
    end
    return node
end

--- Iterates the components in a table (its gamedef name, or its address):
--- for component, id in components.each(name) do ... end
function components.each(table_name)
    local address = components.table(table_name)
    if not address then
        return function() return nil end
    end
    local header = game.read("ptr", address + 4)
    local node = header ~= 0 and game.read("ptr", header + 8) or 0
    local steps = 0
    return function()
        while node ~= header and node ~= 0 and steps < 1024 do
            local current = node
            node = next_node(node)
            steps = steps + 1
            local component = game.read("ptr", current + 0x14)
            if component ~= 0 then
                return component, game.read("u32", current + 0x10)
            end
        end
        return nil
    end
end

return components
