-- boz.engine.player: the local player in a Zombies match: health, place, stance, speed and perks.
--
--   local player = require("boz.engine.player")
--   player.give_all_perks()
--   player.health()  player.set_health(500, true)  player.set_god(true)
--   player.position()  player.teleport({x = 0, y = 250, z = 0})
--   player.downed()  player.stance()  player.set_speed("SprintSpeed", 1.5)
--
-- game: CHealth::SetHealth, CPlayerController::PlaceAt

local core = require("boz.engine.core")
local components = require("boz.engine.components")
local map = require("boz.engine.map")

local player = {}

--- True while a Zombies match with a local player is running.
function player.in_match()
    return map.player() ~= nil
end

--- The player's name hash (Entity_GetNameHash of its entity record): how scores, kills and
--- events name the player. nil outside a match.
function player.name_hash()
    local entity = map.player()
    return entity and require("boz.engine.entities").name_hash(entity) or nil
end

local HEALTH, MAX_HEALTH = core.offset("CHealth", "health"), core.offset("CHealth", "maxHealth")
local STANCE, STATE = core.offset("CPlayerController", "stance"), core.offset("CPlayerController", "state")
player.STANCES = {standing = 1, crouching = 2, prone = 4, downed = 8}
player.SPEEDS = {"WalkSpeed", "AimWalkSpeed", "SprintSpeed", "CrouchSpeed", "AimCrouchSpeed",
                 "ProneSpeed", "AimProneSpeed", "PerkedWalkSpeed", "PerkedAimWalkSpeed",
                 "PerkedSprintSpeed", "PerkedCrouchSpeed", "PerkedAimCrouchSpeed", "PerkedProneSpeed",
                 "PerkedAimProneSpeed", "LastStandSpeed"}
-- The HUD icon of each perk (player.PERKS order).
local PERK_ICONS = {"Perk_Deadshot_Image", "Perk_Double_Tap_Image", "Perk_Juggernog_Image",
                    "Perk_StaminUp_Image", "Perk_PHD_Flopper_Image", "Perk_Revival_Image",
                    "Perk_Speed_Cola_Image"}
local OWNED_PERKS, OWNED_BITS = core.offset("CPerkManager", "owned"), core.offset("CPerkManager", "ownedBits")
local JUGGERNOG = 3

local function component(name)
    local _, id = map.player()
    return id and components.find(name, id) or nil
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
        core.call("CHealth::SetMaxHealth", h, math.floor(value))
    end
    core.call("CHealth::SetHealth", h, hook.float_bits(value), 0, 0)
    -- The game ignores the change while the player is invulnerable (god mode, just hit): set it.
    game.write("f32", h + HEALTH, math.min(value, game.read("i32", h + MAX_HEALTH)))
    return true
end

--- Makes the player take no damage (true) or normal damage again (the UnlimitedHealth cvar).
function player.set_god(on)
    return require("boz.systems.console").register("UnlimitedHealth", on and "true" or "false", "bool")
end

--- True while the player takes no damage.
function player.god()
    return require("boz.systems.console").get("UnlimitedHealth") == "true"
end

--- The player's position {x, y, z} (game centimetres, y up: the camera, about 136 above the feet).
function player.position()
    local entity = map.player()
    return entity and require("boz.engine.entities").position(entity) or nil
end

--- Moves the player (a position like player.position()'s).
function player.teleport(position)
    local entity = map.player()
    return entity ~= nil and require("boz.engine.entities").set_position(entity, position)
end

local MAY_MOVE, MAY_LOOK = core.offset("CPlayerController", "mayMove"), core.offset("CPlayerController", "mayLook")
local WORLD_MATRIX = core.offset("CIsTransform", "worldAxes")   -- world rotation rows, then position

--- Stands the player on an entity, facing its way (the game's own teleport).
function player.place_on(entity)
    local controller = component("CPlayerController")
    local t = entity and entity ~= 0 and core.call("CIsTransform::FromEntity", entity)
    if not controller or not t or t == 0 then
        return false
    end
    core.call("CIsTransform::UpdateWorld", t)
    core.call("CPlayerController::PlaceAt", controller, t + WORLD_MATRIX)
    return true
end

--- Stands the player at a position (feet, like an entity's) facing a rotation {x, y, z, w}.
function player.place_at(position, rotation)
    local controller = component("CPlayerController")
    if not controller then
        return false
    end
    local q = rotation or {0, 0, 0, 1}
    local function turn(v)   -- v turned by q
        local x, y, z, w = q[1], q[2], q[3], q[4]
        local tx, ty, tz = 2 * (y * v[3] - z * v[2]), 2 * (z * v[1] - x * v[3]), 2 * (x * v[2] - y * v[1])
        return {v[1] + w * tx + (y * tz - z * ty), v[2] + w * ty + (z * tx - x * tz),
                v[3] + w * tz + (x * ty - y * tx)}
    end
    -- A world matrix as CIsTransform keeps it: each row an axis turned, then the position.
    local matrix = core.scratch("player.place_at", 48)
    local values = {}
    for _, axis in ipairs({{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}) do
        for _, v in ipairs(turn(axis)) do values[#values + 1] = v end
    end
    values[10], values[11], values[12] = position.x, position.y, position.z
    for i, v in ipairs(values) do
        game.write("f32", matrix + 4 * (i - 1), v)
    end
    core.call("CPlayerController::PlaceAt", controller, matrix)
    return true
end

--- Lets the player walk (true) or holds them where they stand (false). With look false, their
--- view is held too (as in the game's wormhole); looking is left alone when look is nil.
function player.set_movement(on, look)
    local controller = component("CPlayerController")
    if controller then
        game.write("u8", controller + MAY_MOVE, on and 1 or 0)
        if look ~= nil then
            game.write("u8", controller + MAY_LOOK, look and 1 or 0)
        end
    end
    return controller ~= nil
end

--- True while the player may walk.
function player.movement()
    local controller = component("CPlayerController")
    return controller ~= nil and game.read("u8", controller + MAY_MOVE) ~= 0
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
    core.call("CPlayerController::SetStance", controller, value)
    return true
end

--- True while the player is down (last stand) and not dead.
function player.downed()
    local controller = component("CPlayerController")
    if not controller then
        return false
    end
    local state = game.read("u32", controller + STATE)
    return game.read("u32", controller + STANCE) == 8 and state ~= 20 and state ~= 21
end

--- True once the player died (the match is ending).
function player.dead()
    local controller = component("CPlayerController")
    local state = controller and game.read("u32", controller + STATE)
    return state == 20 or state == 21
end

--- Kills the player (the game's KillPlayer).
function player.kill()
    return require("boz.systems.console").exec("KillPlayer")
end

--- A movement speed (one of player.SPEEDS) as the game reads it.
function player.speed(name)
    return tonumber(require("boz.systems.console").get(name))
end

--- Sets a movement speed (one of player.SPEEDS; it applies at once). Returns the value kept.
function player.set_speed(name, value)
    return require("boz.systems.console").register(name, tostring(value), "float")
end

--- Unlimited sprint (true) or the game's stamina again (the UnlimitedStamina cvar).
function player.set_unlimited_stamina(on)
    return require("boz.systems.console").register("UnlimitedStamina", on and "true" or "false", "bool")
end

--- True while sprinting is unlimited.
function player.unlimited_stamina()
    return require("boz.systems.console").get("UnlimitedStamina") == "true"
end

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
    local owned, result = game.read("u32", manager + OWNED_BITS), {}
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
            if game.read("u32", manager + OWNED_BITS) & (1 << (i - 1)) == 0 then
                core.call("CPerkManager::GainPerk", manager, i - 1, 1)
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
        local owned = game.read("u32", manager + OWNED_BITS)
        if perk == name and owned & bit ~= 0 then
            core.call("PerkManager_SetOwned", manager + OWNED_PERKS, owned & ~bit)
            core.call("PerkManager_ShowIcon", manager, PERK_ICONS[i], 0)
            core.call("PerkManager_LayoutIcons", manager)
            if i == JUGGERNOG then
                local health = component("CHealth")
                if health then
                    local max = game.read("i32", health + MAX_HEALTH) // 2
                    core.call("CHealth::SetMaxHealth", health, max)
                    if game.read("f32", health + HEALTH) > max then
                        core.call("CHealth::SetHealth", health, hook.float_bits(max), 0, 0)
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
    core.call("PerkManager_ResetAll", manager)
    return true
end

return player
