-- boz.player: the local player in a Zombies match: health, place, stance, speed, perks and field
-- of view.
--
--   local player = require("boz.player")
--   player.give_all_perks()
--   player.set_fov(90)                  -- kept across matches; aiming down sights still zooms
--   player.health()  player.set_health(500, true)  player.god(true)
--   player.position()  player.teleport({x = 0, y = 250, z = 0})
--   player.downed()  player.stance()  player.set_speed("SprintSpeed", 1.5)
--
-- How it works: the player's entity is CLevelManager +0x1a0; its CHealth keeps its health (+0x48
-- float, +0x44 the most it can be now; CHealth::SetHealth changes it the game's way); CPlayerController keeps the
-- stance at +0x1f4 (1 standing, 2 crouching, 4 prone, 8 downed / last stand; SetStance changes it)
-- and its state machine's state at +0x1d4 (0x14, 0x15: dead); movement speeds are console
-- variables read every step (WalkSpeed, SprintSpeed, CrouchSpeed, ProneSpeed and their Aim* and
-- Perked* (Stamin-Up) forms, LastStandSpeed); UnlimitedHealth makes it invulnerable.

local components = require("boz.components")

local player = {}

--- True while a Zombies match with a local player is running.
function player.in_match()
    return components.local_player() ~= nil
end

-- Health, place, stance, speed -----------------------------------------------------------------

local HEALTH, MAX_HEALTH = 0x48, 0x44   -- CHealth: health; the most it can be now (Juggernog doubles it)
local STANCE, STATE = 0x1f4, 0x1d4
player.STANCES = {standing = 1, crouching = 2, prone = 4, downed = 8}
player.SPEEDS = {"WalkSpeed", "AimWalkSpeed", "SprintSpeed", "CrouchSpeed", "AimCrouchSpeed",
                 "ProneSpeed", "AimProneSpeed", "PerkedWalkSpeed", "PerkedAimWalkSpeed",
                 "PerkedSprintSpeed", "PerkedCrouchSpeed", "PerkedAimCrouchSpeed", "PerkedProneSpeed",
                 "PerkedAimProneSpeed", "LastStandSpeed"}
local FALLBACK = {["CHealth::SetHealth"] = 0x19a20c + 1, ["CPlayerController::SetStance"] = 0x1db634 + 1,
                  ["PerkManager_SetOwned"] = 0x1cbac4 + 1, ["PerkManager_ShowIcon"] = 0x1cbeb8 + 1,
                  ["PerkManager_LayoutIcons"] = 0x1cc028 + 1, ["PerkManager_ResetAll"] = 0x1cbff4 + 1,
                  ["CHealth::SetMaxHealth"] = 0x19972c + 1}
-- The HUD icon of each perk (player.PERKS order).
local PERK_ICONS = {"Perk_Deadshot_Image", "Perk_Double_Tap_Image", "Perk_Juggernog_Image",
                    "Perk_StaminUp_Image", "Perk_PHD_Flopper_Image", "Perk_Revival_Image",
                    "Perk_Speed_Cola_Image"}
local OWNED_PERKS = 0x4c     -- CPerkManager: the owned perks (a network bool array; bits at +0x58)

local function component(name)
    local _, id = components.local_player()
    return id and components.find(name, id) or nil
end

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

--- The player's health and the most it can have, or nil outside a match.
function player.health()
    local h = component("CHealth")
    if not h then
        return nil
    end
    return game.read("f32", h + HEALTH), game.read("i32", h + MAX_HEALTH)
end

--- Sets the player's health; raise_max also raises the most it can have to it.
function player.set_health(value, raise_max)
    local h = component("CHealth")
    if not h then
        return false
    end
    if raise_max and value > game.read("i32", h + MAX_HEALTH) then
        game.call(sym("CHealth::SetMaxHealth"), h, math.floor(value))
    end
    game.call(sym("CHealth::SetHealth"), h, hook.float_bits(value), 0, 0)
    -- The game ignores the change while the player is invulnerable (god mode, just hit): set it.
    game.write("f32", h + HEALTH, math.min(value, game.read("i32", h + MAX_HEALTH)))
    return true
end

--- Makes the player take no damage (true) or normal damage again (the UnlimitedHealth cvar).
function player.god(on)
    return require("boz.console").register("UnlimitedHealth", on and "true" or "false", "bool")
end

--- The player's position {x, y, z} (game centimetres, y up: the camera, about 136 above the feet).
function player.position()
    local entity = components.local_player()
    return entity and require("boz.entities").position(entity) or nil
end

--- Moves the player (a position like player.position()'s).
function player.teleport(position)
    local entity = components.local_player()
    return entity ~= nil and require("boz.entities").set_position(entity, position)
end

--- The stance name ("standing", "crouching", "prone", "downed"), or nil.
function player.stance()
    local controller = component("CPlayerController")
    if not controller then
        return nil
    end
    local value = game.read("u32", controller + STANCE)
    for name, number in pairs(player.STANCES) do
        if number == value then
            return name
        end
    end
    return tostring(value)
end

--- Sets the stance ("standing", "crouching" or "prone"; the camera height follows).
function player.set_stance(name)
    local controller = component("CPlayerController")
    local value = player.STANCES[name]
    if not controller or not value or value == 8 then
        return false
    end
    game.call(sym("CPlayerController::SetStance"), controller, value)
    return true
end

--- True while the player is down (last stand) and not dead.
function player.downed()
    local controller = component("CPlayerController")
    if not controller then
        return false
    end
    local state = game.read("u32", controller + STATE)
    return game.read("u32", controller + STANCE) == 8 and state ~= 0x14 and state ~= 0x15
end

--- True once the player died (the match is ending).
function player.dead()
    local controller = component("CPlayerController")
    local state = controller and game.read("u32", controller + STATE)
    return state == 0x14 or state == 0x15
end

--- Kills the player (the game's KillPlayer).
function player.kill()
    return require("boz.console").exec("KillPlayer")
end

--- A movement speed (one of player.SPEEDS) as the game reads it.
function player.speed(name)
    return tonumber(require("boz.console").get(name))
end

--- Sets a movement speed (one of player.SPEEDS; it applies at once). Returns the value kept.
function player.set_speed(name, value)
    return require("boz.console").register(name, tostring(value), "float")
end

--- Unlimited sprint (true) or the game's stamina again (the UnlimitedStamina cvar).
function player.unlimited_stamina(on)
    return require("boz.console").register("UnlimitedStamina", on and "true" or "false", "bool")
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

--- Takes a perk away (as losing it when downed does: its icon goes, Juggernog's extra health
--- too). False if the player does not have it.
function player.take_perk(name)
    local manager = perk_manager()
    if not manager then
        return false
    end
    for i, perk in ipairs(player.PERKS) do
        local bit = 1 << (i - 1)
        local owned = game.read("u32", manager + 0x58)
        if perk == name and owned & bit ~= 0 then
            game.call(sym("PerkManager_SetOwned"), manager + OWNED_PERKS, owned & ~bit)
            game.call(sym("PerkManager_ShowIcon"), manager, PERK_ICONS[i], 0)
            game.call(sym("PerkManager_LayoutIcons"), manager)
            if i == 3 then
                local health = component("CHealth")
                if health then
                    local max = game.read("i32", health + MAX_HEALTH) // 2
                    game.call(sym("CHealth::SetMaxHealth"), health, max)
                    if game.read("f32", health + 0x48) > max then
                        game.call(sym("CHealth::SetHealth"), health, hook.float_bits(max), 0, 0)
                    end
                end
            end
            return true
        end
    end
    return false
end

--- Takes every perk away (the game's ResetAllPerks: icons and health back to normal).
function player.take_all_perks()
    local manager = perk_manager()
    if not manager then
        return false
    end
    game.call(sym("PerkManager_ResetAll"), manager)
    return true
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
