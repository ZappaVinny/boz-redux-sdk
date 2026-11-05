-- The game's own prefabs as classes: Perk, Door, MysteryBox, PackAPunch, PowerSwitch, Trap,
-- TrapSwitch, WallBuy, Barricade, ZombieSpawn. Their methods are the game's behaviour; a script
-- extends one to change it and calls the parent to keep it.
--
--   local SealedDoor = boz.Door:extend("SealedDoor")
--   function SealedDoor:on_use(player)
--       if not boz.saved.egg_done then return end      -- stays shut
--       boz.Door.on_use(self, player)                  -- pay and open as normal
--   end
--   return SealedDoor
--
-- game: a use is Poi_SendUse on the point of interest in reach; boz.prefabs catches it for
-- objects whose class changes on_use.

local Prefab = require("boz.objects.prefab")
local pieces = require("boz.engine.pieces")

local native = {}

-- The game class a prefab is built on, and its piece handle (boz.pieces).
local Native = Prefab:extend("Native")
Native.game_class = nil

function Native:_piece()
    local entity = self._handle:entity_pointer()
    return entity ~= 0 and pieces.of(entity, self.game_class) or nil
end

--- What happens when a player uses it: the game's own purchase (pays and runs it).
function Native:on_use(player)
    local piece = self:_piece()
    if piece then
        require("boz.objects.runtime").pass_use(function() piece:use() end)
    end
end

--- Runs it without the player paying (opens, buys, spins, switches on).
function Native:use_free()
    local piece = self:_piece()
    return piece ~= nil and piece:use_free()
end

--- A field of the game's component by its game name ("m_Cost"); see self.settings first.
function Native:field(name)
    local piece = self:_piece()
    return piece and piece:get(name)
end

--- Sets a field of the game's component by its game name.
function Native:set_field(name, value)
    local piece = self:_piece()
    return piece ~= nil and piece:set(name, value)
end

local function define(name, game_class)
    local class = Native:extend(name)
    class.game_class = game_class
    native[name] = class
    return class
end

--- Perk machine. Events: bought.
local Perk = define("Perk", "CPerk")
--- Gives its perk to the player for free.
function Perk:give() return self:use_free() end

--- Door or debris. Events: opened.
local Door = define("Door", "CDoor")
--- Opens it without paying.
function Door:open() return self:use_free() end
--- True once it is open.
function Door:is_open()
    local piece = self:_piece()
    return piece ~= nil and piece:is_open()
end

--- Mystery box. Events: spun, weapon.
local MysteryBox = define("MysteryBox", "CMysteryBox")
--- Brings the box out here.
function MysteryBox:bring_out() local p = self:_piece() return p ~= nil and p:spawn_box() end
--- Sends the box away (it leaves with its animation).
function MysteryBox:send_away() local p = self:_piece() return p ~= nil and p:despawn_box() end

--- Pack-a-Punch. Events: upgraded.
local PackAPunch = define("PackAPunch", "CPackAPunch")
function PackAPunch:bring_out() local p = self:_piece() return p ~= nil and p:spawn_pack_a_punch() end
function PackAPunch:send_away() local p = self:_piece() return p ~= nil and p:despawn_pack_a_punch() end

--- Power switch. Events: on.
local PowerSwitch = define("PowerSwitch", "CPowerSwitch")
--- Turns the power on.
function PowerSwitch:turn_on() return self:use_free() end

--- Trap switch. Events: activated.
local TrapSwitch = define("TrapSwitch", "CTrapSwitch")
--- Runs its traps without paying.
function TrapSwitch:activate() return self:use_free() end

--- Trap. Events: activated.
local Trap = define("Trap", "CTrap")
--- Runs the trap for seconds (default: its own time).
function Trap:activate(seconds)
    local piece = self:_piece()
    if not piece then
        return false
    end
    local core = require("boz.engine.core")
    local active = math.floor((seconds or (piece:get("m_ActivePeriodMS") or 30000) / 1000) * 1000)
    -- game: CTrap::OnEvent changes state on SUBJECT_TRAP_TRANSITION_STATE (1 = on, b = ms)
    core.call("CIsSubject::NotifyVirtual", require("boz.engine.reflect").object(piece.component, "CTrap") + 8,
              require("boz.engine.game_events").id("SUBJECT_TRAP_TRANSITION_STATE"), 1, active, 0)
    return true
end

--- Wall buy. Events: bought.
define("WallBuy", "CWeaponChalkOutline")

--- Window barricade. Events: repaired.
local Barricade = define("Barricade", "CBarricade")
--- Puts one board back.
function Barricade:repair() local p = self:_piece() return p ~= nil and p:fix_barricade() end

--- Zombie spawn.
local ZombieSpawn = define("ZombieSpawn", "CSpawnPoint")
--- Lets zombies come out of it (true) or not (false).
function ZombieSpawn:set_active(on)
    local entity = self._handle:entity_pointer()
    return entity ~= 0 and require("boz.engine.spawns").set_active(entity, on)
end

native.Native = Native
return native
