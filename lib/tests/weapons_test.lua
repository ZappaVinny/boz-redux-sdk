-- boz.weapons and weapon scripts against a fake game: lua5.4 lib/tests/weapons_test.lua (from the
-- SDK root).
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
local fake = require("fake_game").install({strict = true})
local memory, symbols, functions, hooks, calls, frames = fake.memory, fake.symbols, fake.functions, fake.hooks,
    fake.calls, fake.frames
local address, run_hook, frame, check, called = fake.address, fake.run_hook, fake.frame, fake.check, fake.called

local hash = require("boz.hash")
local LEVEL, PLAYER, MANAGER = 0x8000, 0x8100, 0xa000
local MP40, HEAVY = 0xb000, 0xb400
memory[address("CLevelManager::s_instance")] = LEVEL
memory[LEVEL + 0x1a0] = PLAYER
memory[PLAYER + 4] = 1
memory[MANAGER + 0x48] = PLAYER
memory[MANAGER + 0x1e0] = MP40
memory[MP40 + 0x5c], memory[HEAVY + 0x5c] = hash.name("mp40"), hash.name("mp40_heavy")
memory[MP40 + 0x2c], memory[MP40 + 0x30], memory[MP40 + 0x80] = 12, 64, 32
memory[MP40 + 0x20c + 4] = 400

local components = require("boz.components")
components.each = function(tbl)
    local done = false
    return function()
        if not done and (tbl == "CWeaponManager" or tbl == address("CWeaponManager::s_table")) then done = true; return MANAGER end
    end
end
components.local_player = function() return PLAYER, 1 end
local by_hash = {[hash.name("mp40")] = MP40, [hash.name("mp40_heavy")] = HEAVY}
functions["WeaponManager_FindWeapon"] = function(_, h) return by_hash[h] or 0 end
functions["CWeaponManager::GiveWeapon"] = function(manager, h)
    memory[manager + 0x1e0] = by_hash[h]
end
functions["CIsComponentTableBase::Find"] = function() return 0 end

local weapons = require("boz.weapons")
weapons.know({"mp40", "mp40_heavy"})
local gun = weapons.current()
check(gun and gun.name == "mp40" and gun:clip() == 12 and gun:reserve() == 64, "the weapon in hand")
gun:set_ammo(gun:clip_size(), 999)
check(memory[MP40 + 0x2c] == 32 and memory[MP40 + 0x30] == 999, "set_ammo")
gun:set_damage(900)
check(select(1, gun:damage()) == 900, "set_damage")
check(weapons.give("mp40_heavy") and weapons.current().name == "mp40_heavy", "give")
check(not weapons.give("nothing"), "giving an unknown weapon fails")

-- Upgrading and taking.
memory[HEAVY + 0x60] = hash.name("mp40")              -- the heavy one "upgrades" to the mp40
functions["CWeaponManager::EquipWeapon"] = function(manager, weapon, slot)
    memory[manager + 0x1e0 + 4 * slot] = weapon
end
check(weapons.current():upgrade_name() == "mp40" and weapons.slot_of("mp40_heavy") == "primary", "its upgrade and slot")
check(weapons.upgrade("mp40_heavy") and weapons.current().name == "mp40", "upgrade replaces it")
check(not weapons.upgrade("mp40"), "no upgrade")
check(not weapons.take("mp40"), "the only gun stays")
memory[MANAGER + 0x1e4] = HEAVY
check(weapons.take("mp40") and weapons.current().name == "mp40_heavy" and memory[MANAGER + 0x1e4] == 0, "take: the other gun comes up")
memory[MANAGER + 0x1e0] = MP40

-- Weapon scripts through boz.prefabs.
local dir = os.tmpname()
os.remove(dir)
os.execute("mkdir -p " .. dir .. "/weapons")
local file = assert(io.open(dir .. "/weapons/Heavy.lua", "w"))
file:write([[
shots = 0
function on_fire(data) shots = shots + 1; seen.fire = data.clip end
function on_equip() seen.equip = self.name .. ":" .. self:clip() end
function on_given() seen.given = true end
function on_reload() seen.reload = true end
]])
file:close()
function loadscript(name, env)
    return assert(loadfile(dir .. "/" .. name:gsub("%.", "/") .. ".lua", "t", env))
end
seen = {}
local prefabs = require("boz.prefabs")
local bus = {}
prefabs.on("weapon_fired", function(data) table.insert(bus, "fired:" .. data.weapon) end)
prefabs.on("weapon_equipped", function(data) table.insert(bus, "equipped:" .. data.weapon) end)
prefabs.start({}, {}, {{name = "mp40_heavy", script = "weapons.Heavy"}, {name = "mp40", script = ""}})
memory[MANAGER + 0x1e0] = MP40
memory[HEAVY + 0x2c] = 7
run_hook("CWeaponManager::GiveWeapon", {MANAGER, hash.name("mp40_heavy"), 0, 1})
run_hook("CWeaponManager::EquipWeapon", {MANAGER, HEAVY, 0, 1})
check(seen.given and seen.equip == "mp40_heavy:7", "on_given, on_equip with self as the weapon")
memory[MANAGER + 0x1e0] = HEAVY
run_hook("CPlayerController::FireWeapon", {})
run_hook("CWeaponManager::SetReloading", {MANAGER, 1, 1})
check(seen.fire == 7 and seen.reload, "on_fire (clip) and on_reload")
check(table.concat(bus, " ") == "equipped:mp40_heavy fired:mp40_heavy", "bus events (" .. table.concat(bus, " ") .. ")")
memory[HEAVY + 0x2c] = 6
run_hook("CPlayerController::FireWeaponAimed", {})
check(seen.fire == 6, "an aimed shot fires too")
memory[MANAGER + 0x1e0] = MP40
run_hook("CPlayerController::FireWeapon", {})
check(seen.fire == 6, "another weapon's shots do not reach this script")
os.execute("rm -rf " .. dir)

-- The starting weapon: set right before the game gives it, on this map only.
local registered = {}
package.loaded["boz.console"] = {register = function(name, value) registered[name] = value end}
package.loaded["boz.world_data"] = {start_weapon = {name = "mp40", reserve = 99, level = "my_map"}}
functions["CPerk::Init"] = function() return 0 end
require("boz.world").start()
memory[LEVEL + 0x55] = "my_map"
run_hook("WeaponManager_GiveStartWeapons", {MANAGER})
check(registered.PlayerStartWeapon == "mp40" and registered.PlayerStartAmmo == "99",
      "the map's starting weapon")
memory[LEVEL + 0x55] = "kino"
run_hook("WeaponManager_GiveStartWeapons", {MANAGER})
check(registered.PlayerStartWeapon == "colt45" and registered.PlayerStartAmmo == "40",
      "other maps get the Colt back")
print("weapons_test: OK")
