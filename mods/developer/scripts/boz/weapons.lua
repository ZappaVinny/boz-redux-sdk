-- boz.weapons: the local player's weapons during a match: the one in hand, ammo, live stats,
-- giving weapons, and events when weapons are equipped, given, fired and reloaded.
--
--   local weapons = require("boz.weapons")
--   local gun = weapons.current()               -- nil outside a match
--   if gun then gun:set_ammo(gun:clip_size(), 999) end
--   weapons.give("thundergun")    weapons.upgrade("mp40")    weapons.take("mp40")
--   weapons.listen(function(event, name) print(event .. " " .. name) end)
--
-- Weapons are named as in the editor's Weapons tab ("mp40", or "0x..." for an unnamed one).
-- Changes made here last for the match; the Weapons tab changes the weapons for good.
--
-- How it works (Ghidra names in the game definition): the player's CWeaponManager sits on a child
-- of the player entity (+0x48 = the player); its weapons are CPlayerWeapon components found by
-- name hash (WeaponManager_FindWeapon, map at +0x1d4), the one in hand at +0x1e0.
-- CWeaponManager::GiveWeapon(manager, hash, slot, refill) equips one; EquipWeapon sends
-- SUBJECT_WEAPON_EQUIPPED; CPlayerController::FireWeapon fires; CWeaponManager::SetReloading
-- starts a reload. A CPlayerWeapon keeps its rounds at +0x2c (clip) and +0x30 (reserve), its
-- clip size at +0x80, reserve size at +0x84, fire rate at +0x200 (rounds per minute) and
-- CWeaponDamage at +0x20c (head +4, torso +8, limbs +0xc).

local hash = require("boz.hash")
local components = require("boz.components")

local weapons = {}

local FALLBACK = {
    ["CWeaponManager::s_table"] = 0x4704d0,
    ["WeaponManager_FindWeapon"] = 0x21de72 + 1,
    ["CWeaponManager::GiveWeapon"] = 0x2205dc + 1,
    ["CWeaponManager::EquipWeapon"] = 0x2202fc + 1,
    ["CWeaponManager::SetReloading"] = 0x21e078 + 1,
    ["CPlayerController::FireWeapon"] = 0x1d4ecc + 1,
    ["WeaponManager_RefillAll"] = 0x21f018 + 1,
    ["WeaponManager_RefillWeapon"] = 0x21f068 + 1,
}
-- The slots: primary (in hand) +0x1e0, secondary +0x1e4, melee +0x1e8, grenade +0x1ec, tactical
-- (monkey bomb, Gersch, ...) +0x1f0; grenades left +0x1cc, tactical left +0x1d0.
weapons.SLOTS = {primary = 0x1e0, secondary = 0x1e4, melee = 0x1e8, grenade = 0x1ec, tactical = 0x1f0}
local GRENADES, TACTICALS = 0x1cc, 0x1d0
local MANAGER_PLAYER = 0x48
local MANAGER_IN_HAND = 0x1e0
local WEAPON_NAME = 0x5c
local WEAPON_UPGRADE = 0x60   -- CPlayerWeapon Upgrade: the Pack-a-Punched weapon's name hash
local CLIP, RESERVE = 0x2c, 0x30
local CLIP_SIZE, RESERVE_SIZE = 0x80, 0x84
local FIRE_RATE = 0x200
local DAMAGE = 0x20c

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local names = {}        -- hash -> name, for the weapons the map knows

--- Tell boz.weapons the names of weapons (the map's world data does this for its weapons).
function weapons.know(list)
    for _, name in ipairs(list or {}) do
        names[hash.name(name)] = name
    end
end

local function name_of(name_hash)
    return names[name_hash] or string.format("0x%08x", name_hash)
end

--- A weapon's name from its hash ("0x..." when boz.weapons does not know it: weapons.know).
function weapons.name(name_hash)
    return name_of(name_hash)
end

local function hash_of(name)
    if type(name) == "number" then
        return name
    end
    if string.sub(name, 1, 2) == "0x" then
        return tonumber(string.sub(name, 3), 16)
    end
    return hash.name(name)
end

--- The local player's weapon manager, or nil outside a match.
function weapons.manager()
    local player = components.local_player()
    if not player then
        return nil
    end
    local only, count = nil, 0
    for manager in components.each(sym("CWeaponManager::s_table")) do
        if game.read("ptr", manager + MANAGER_PLAYER) == player then
            return manager
        end
        only, count = manager, count + 1
    end
    return count == 1 and only or nil
end

-- A weapon handle: a CPlayerWeapon of the player.

local Weapon = {}
Weapon.__index = Weapon

local function handle(pointer)
    if not pointer or pointer == 0 then
        return nil
    end
    local name_hash = game.read("u32", pointer + WEAPON_NAME)
    return setmetatable({pointer = pointer, hash = name_hash, name = name_of(name_hash)}, Weapon)
end

--- The name of its Pack-a-Punched version, or nil when it has none.
function Weapon:upgrade_name()
    local up = game.read("u32", self.pointer + WEAPON_UPGRADE)
    return up ~= 0 and name_of(up) or nil
end

--- Rounds in the clip.
function Weapon:clip() return game.read("u32", self.pointer + CLIP) end
--- Spare rounds.
function Weapon:reserve() return game.read("u32", self.pointer + RESERVE) end
--- Clip size.
function Weapon:clip_size() return game.read("u32", self.pointer + CLIP_SIZE) end
--- Reserve size.
function Weapon:reserve_size() return game.read("u32", self.pointer + RESERVE_SIZE) end

--- Sets the rounds in the clip and in reserve (nil keeps one). Returns the weapon.
function Weapon:set_ammo(clip, reserve)
    if clip then game.write("u32", self.pointer + CLIP, clip) end
    if reserve then game.write("u32", self.pointer + RESERVE, reserve) end
    return self
end

--- Fire rate in rounds per minute (automatic fire modes).
function Weapon:fire_rate() return game.read("u32", self.pointer + FIRE_RATE) end

--- Sets the fire rate for this match. Returns the weapon.
function Weapon:set_fire_rate(rounds_per_minute)
    game.write("u32", self.pointer + FIRE_RATE, rounds_per_minute)
    return self
end

--- Damage per hit: head, torso, limbs.
function Weapon:damage()
    return game.read("u32", self.pointer + DAMAGE + 4), game.read("u32", self.pointer + DAMAGE + 8),
        game.read("u32", self.pointer + DAMAGE + 0xc)
end

--- Sets the damage per hit for this match (nil keeps one). Returns the weapon.
function Weapon:set_damage(head, torso, limbs)
    if head then game.write("u32", self.pointer + DAMAGE + 4, head) end
    if torso then game.write("u32", self.pointer + DAMAGE + 8, torso) end
    if limbs then game.write("u32", self.pointer + DAMAGE + 0xc, limbs) end
    return self
end

--- True while this is the weapon in hand.
function Weapon:in_hand()
    local manager = weapons.manager()
    return manager ~= nil and game.read("ptr", manager + MANAGER_IN_HAND) == self.pointer
end

--- The weapon in the player's hands, or nil.
function weapons.current()
    local manager = weapons.manager()
    return manager and handle(game.read("ptr", manager + MANAGER_IN_HAND)) or nil
end

--- The player's weapon called *name* (every weapon of the map is there, owned or not), or nil.
function weapons.get(name)
    local manager = weapons.manager()
    if not manager then
        return nil
    end
    return handle(game.call(sym("WeaponManager_FindWeapon"), manager, hash_of(name)))
end

--- Gives the player *name* and puts it in hand, with full ammo. Returns false outside a match
--- or when the map has no such weapon.
function weapons.give(name)
    local manager = weapons.manager()
    if not manager or not weapons.get(name) then
        return false
    end
    game.call(sym("CWeaponManager::GiveWeapon"), manager, hash_of(name), 0, 1)
    return true
end

--- The slot a weapon the player holds is in ("primary", "secondary", ...), or nil.
function weapons.slot_of(name)
    local manager = weapons.manager()
    if not manager then
        return nil
    end
    local wanted = hash_of(name)
    for slot, offset in pairs(weapons.SLOTS) do
        local pointer = game.read("ptr", manager + offset)
        if pointer ~= 0 and game.read("u32", pointer + WEAPON_NAME) == wanted then
            return slot
        end
    end
    return nil
end

local SLOT_INDEX = {primary = 0, secondary = 1, melee = 2, grenade = 3, tactical = 4}

--- Takes a weapon away from the player. The one in hand: the other gun comes up (false when it
--- is the only gun); grenades and tactical: none left (the slot keeps the kind, with 0). Returns
--- true when taken.
function weapons.take(name)
    local manager, slot = weapons.manager(), weapons.slot_of(name)
    if not manager or not slot or slot == "melee" then
        return false
    end
    local equip = sym("CWeaponManager::EquipWeapon")
    if slot == "primary" then
        local other = game.read("ptr", manager + weapons.SLOTS.secondary)
        if other == 0 then
            return false
        end
        game.call(equip, manager, other, 0, 0)     -- the other gun into the hand ...
    end
    game.call(equip, manager, 0, slot == "primary" and 1 or SLOT_INDEX[slot], 0)   -- ... and its slot emptied
    return true
end

--- Pack-a-Punches a weapon the player holds (the upgraded version replaces it in its slot, full
--- ammo), as the machine does but free and at once. Returns false when it has no upgrade.
function weapons.upgrade(name)
    local manager, slot = weapons.manager(), weapons.slot_of(name)
    local gun = slot and weapons.slot(slot)
    local up = gun and game.read("u32", gun.pointer + WEAPON_UPGRADE) or 0
    if not manager or up == 0 or (slot ~= "primary" and slot ~= "secondary") then
        return false
    end
    game.call(sym("CWeaponManager::GiveWeapon"), manager, up, SLOT_INDEX[slot], 1)
    -- Into the hand, the replaced gun drops to an empty secondary slot: the upgrade replaces it.
    if slot == "primary" and game.read("ptr", manager + weapons.SLOTS.secondary) == gun.pointer then
        game.call(sym("CWeaponManager::EquipWeapon"), manager, 0, 1, 0)
    end
    return true
end

--- The weapon in a slot ("primary" = in hand, "secondary", "melee", "grenade", "tactical"), or nil.
function weapons.slot(name)
    local manager, offset = weapons.manager(), weapons.SLOTS[name]
    if not manager or not offset then
        return nil
    end
    return handle(game.read("ptr", manager + offset))
end

--- The player's weapons by slot: {primary = weapon, secondary = ..., ...} (empty slots left out).
function weapons.owned()
    local out = {}
    for name in pairs(weapons.SLOTS) do
        out[name] = weapons.slot(name)
    end
    return out
end

--- Grenades and tactical grenades (monkey bombs, Gersch devices, ...) the player has.
function weapons.grenades()
    local manager = weapons.manager()
    if not manager then
        return nil
    end
    return game.read("u32", manager + GRENADES), game.read("u32", manager + TACTICALS)
end

--- Sets the grenades (and tactical grenades; nil keeps one).
function weapons.set_grenades(grenades, tacticals)
    local manager = weapons.manager()
    if not manager then
        return false
    end
    if grenades then game.write("u32", manager + GRENADES, grenades) end
    if tacticals then game.write("u32", manager + TACTICALS, tacticals) end
    return true
end

--- Refills every weapon and the grenades (what max ammo does), or one weapon by name.
function weapons.refill(name)
    local manager = weapons.manager()
    if not manager then
        return false
    end
    if name then
        game.call(sym("WeaponManager_RefillWeapon"), manager, hash_of(name))
    else
        game.call(sym("WeaponManager_RefillAll"), manager)
    end
    return true
end

--- A field of the weapon's CPlayerWeapon by name (boz.reflect: m_clipSize, m_spreadMin, ...).
function Weapon:get(field)
    return require("boz.reflect").get(self.pointer, "CPlayerWeapon", field)
end

--- Sets a field of the weapon's CPlayerWeapon for this match. Returns true, or false and why.
function Weapon:set(field, value)
    return require("boz.reflect").set(self.pointer, "CPlayerWeapon", field, value)
end

--- Every field of the weapon's CPlayerWeapon.
function Weapon:fields()
    return require("boz.reflect").dump(self.pointer, "CPlayerWeapon")
end

-- Events: fn(event, weapon name, data) for "equipped", "given", "fired", "reloaded".

local listeners = {}
local hooked = false

local function emit(event, name, data)
    for _, fn in ipairs(listeners) do
        local ok, err = pcall(fn, event, name, data or {})
        if not ok then
            log("boz.weapons: " .. event .. " listener: " .. tostring(err))
        end
    end
end

local function is_players(manager)
    return manager ~= 0 and manager == weapons.manager()
end

local function install()
    hooked = true
    hook.add(sym("CWeaponManager::GiveWeapon"), {before = function(call)
        if is_players(call:arg(1)) then
            emit("given", name_of(call:arg(2)))
        end
    end})
    hook.add(sym("CWeaponManager::EquipWeapon"), {before = function(call)
        local manager, weapon, slot = call:arg(1), call:arg(2), call:arg(3)
        if slot == 0 and weapon ~= 0 and is_players(manager)
                and game.read("ptr", manager + MANAGER_IN_HAND) ~= weapon then
            emit("equipped", name_of(game.read("u32", weapon + WEAPON_NAME)))
        end
    end})
    hook.add(sym("CPlayerController::FireWeapon"), {before = function()
        local gun = weapons.current()
        if gun then
            emit("fired", gun.name, {clip = gun:clip()})
        end
    end})
    hook.add(sym("CWeaponManager::SetReloading"), {before = function(call)
        if call:arg(2) ~= 0 and is_players(call:arg(1)) then
            local gun = weapons.current()
            if gun then
                emit("reloaded", gun.name)
            end
        end
    end})
end

--- Calls fn(event, weapon name, data) on "equipped", "given", "fired" and "reloaded" of the
--- local player's weapons. Returns fn.
function weapons.listen(fn)
    if not hooked then
        install()
    end
    table.insert(listeners, fn)
    return fn
end

return weapons
