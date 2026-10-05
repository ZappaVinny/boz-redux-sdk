-- boz.player: the local player in a Zombies match: perks and field of view.
--
--   local player = require("boz.player")
--   player.give_all_perks()
--   player.set_fov(90)                  -- kept across matches; aiming down sights still zooms

local components = require("boz.components")

local player = {}

--- True while a Zombies match with a local player is running.
function player.in_match()
    return components.local_player() ~= nil
end

-- Perks ---------------------------------------------------------------------------------------

--- The perk names, in the game's order.
player.PERKS = {"Deadshot", "Double Tap", "Juggernog", "Stamin-Up", "PHD Flopper", "Quick Revive", "Speed Cola"}

local function perk_manager()
    return components.on_player("CPerkManager::s_table")
end

--- The perks the player owns, by name ({["Juggernog"] = true, ...}), or nil outside a match.
function player.perks()
    local manager = perk_manager()
    if not manager then
        return nil
    end
    local owned, result = game.read("u32", manager + 0x58), {}
    for i, name in ipairs(player.PERKS) do
        if owned & (1 << (i - 1)) ~= 0 then
            result[name] = true
        end
    end
    return result
end

--- Gives a perk by name (with its effects, e.g. Juggernog's health). False if not possible.
function player.give_perk(name)
    local manager = perk_manager()
    if not manager then
        return false
    end
    for i, perk in ipairs(player.PERKS) do
        if perk == name then
            if game.read("u32", manager + 0x58) & (1 << (i - 1)) == 0 then
                game.call("CPerkManager::GainPerk", manager, i - 1, 1)
            end
            return true
        end
    end
    return false
end

--- Gives every perk the player is missing. Returns the names given, or nil outside a match.
function player.give_all_perks()
    local owned = player.perks()
    if not owned then
        return nil
    end
    local given = {}
    for _, name in ipairs(player.PERKS) do
        if not owned[name] then
            player.give_perk(name)
            given[#given + 1] = name
        end
    end
    return given
end

-- Field of view -------------------------------------------------------------------------------
-- CWeaponManager::UpdateFov eases the current FOV (+0xc0) up toward the base FOV (+0xc4, copied
-- from the map's camera at match start) or down to the weapon's sights; it never lowers the
-- current FOV by itself and skips the camera write once it arrived. Changing the base and setting
-- the current FOV just below it makes the next update land on the new value.

local BASE_FOV, CURRENT_FOV, AIMING, PLAYER_ENTITY = 0xc4, 0xc0, 0xbc, 0x48
local fov = {manager = nil, default = nil, wanted = nil}

local function weapon_manager()
    local entity = components.local_player()
    if not entity then
        return nil
    end
    -- The weapon manager sits on a child of the player entity; +0x48 points back at the player.
    local only, count = nil, 0
    for manager in components.each("CWeaponManager::s_table") do
        if game.read("ptr", manager + PLAYER_ENTITY) == entity then
            return manager
        end
        only, count = manager, count + 1
    end
    return count == 1 and only or nil
end

local function apply(manager, degrees, now)
    game.write("f32", manager + BASE_FOV, degrees)
    if now and not game.read("bool", manager + AIMING) then
        game.write("f32", manager + CURRENT_FOV, degrees - 0.01)
    end
end

events.on("frame", function()
    local manager = weapon_manager()
    if manager ~= fov.manager then
        fov.manager = manager
        fov.default = manager and game.read("f32", manager + BASE_FOV)
        if manager and fov.wanted then
            apply(manager, fov.wanted, true)
        end
    elseif manager and fov.wanted then
        game.write("f32", manager + BASE_FOV, fov.wanted)   -- keep it (the game resets it per match)
    end
end)

--- The field of view in degrees and the map's default, or nil outside a match.
function player.fov()
    if not fov.manager then
        return nil
    end
    return fov.wanted or fov.default, fov.default
end

--- Sets the field of view in degrees (aiming down sights still zooms); nil restores the map's
--- default. The value is kept across matches. Returns false outside a match (it still applies
--- when the next match starts).
function player.set_fov(degrees)
    fov.wanted = degrees
    if not fov.manager then
        return false
    end
    apply(fov.manager, degrees or fov.default, true)
    return true
end

return player
