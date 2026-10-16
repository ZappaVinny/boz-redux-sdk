-- boz.pieces: the map's interactive pieces: mystery boxes, perk machines, doors, traps, wall buys,
-- Pack-a-Punch, power switches, barricades, landers, turrets, flingers, teleporters, ...
--
--   for box in pieces.each("CMysteryBox") do log(box:get("m_Cost")) end
--   local box = pieces.active_box()                 -- the box that is out
--   box:set("m_Cost", 500)
--   pieces.perks()[1]:use()                         -- as if the player pressed use there
--   pieces.doors()                                  -- every door, with :get("m_DoorState")
--
-- A piece handle: piece.entity, piece.class, piece.component, piece:get(field), piece:set(field,
-- value), piece:fields() (every field and value), piece:position(), piece:use(), piece:name_hash(),
-- piece:send(event), piece:cost(), piece:use_free() (opens, buys, spins without points); boxes
-- :spawn_box() / :despawn_box() (pieces.move_box(to)), Pack-a-Punch
-- :spawn_pack_a_punch() / :despawn_pack_a_punch(), barricades :fix_barricade()
-- (pieces.fix_all_barricades()).
-- The fields are the game's (reflected): docs/toolkit-fields.md explains them; boz.reflect has the
-- rest.
--
-- How it works: each kind is a component class (its table lists them). "Use" is what the game does
-- when the player presses use at a point of interest (Poi_SendUse: the entity at CLevelManager
-- +0x214 broadcasts the interact event with the player's name hash); the piece reacts as if the
-- player used it (paying, opening, buying).

local pieces = {}

local reflect = require("boz.reflect")
local entities = require("boz.entities")
local components = require("boz.components")

pieces.CLASSES = {"CMysteryBox", "CPerk", "CDoor", "CTrap", "CTrapSwitch", "CWeaponChalkOutline",
                  "CPackAPunch", "CPowerSwitch", "CBarricade", "CLunarLander", "CLunarLanderStation",
                  "CTurret", "CFlinger", "CTeleporter", "CTeleportMainframe", "CCentrifuge", "CLighthouse",
                  "CRocketLauncher", "CMonkeyLander", "CZipLine", "CEasterEgg"}

local FALLBACK = {["Poi_SendUse"] = 0x19fd48 + 1}
local NEAREST_POI = 0x214

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local Piece = {}
Piece.__index = Piece

local function make(entity, class_name, component)
    return setmetatable({entity = entity, class = class_name, component = component}, Piece)
end

--- A field of its component (by name).
function Piece:get(field)
    return reflect.get(self.component, self.class, field)
end

--- Sets a field of its component. Returns true, or false and why.
function Piece:set(field, value)
    return reflect.set(self.component, self.class, field, value)
end

--- Every field and its value.
function Piece:fields()
    return reflect.dump(self.component, self.class)
end

--- Its position {x, y, z}.
function Piece:position()
    return entities.position(self.entity)
end

--- Its name hash (what the World tab named it, hashed).
function Piece:name_hash()
    return entities.name_hash(self.entity)
end

--- Uses it as the player would (the game charges the cost and does the rest). Returns true when
--- the use was sent.
function Piece:use()
    local level = game.read("ptr", "CLevelManager::s_instance")
    if level == 0 then
        return false
    end
    local before = game.read("u32", level + NEAREST_POI)
    game.write("u32", level + NEAREST_POI, self.entity)
    game.call(sym("Poi_SendUse"), 0, 0)
    game.write("u32", level + NEAREST_POI, before)
    return true
end

-- The fields that hold what using a piece costs (all zeroed for a free use).
local COSTS = {CDoor = {"m_Cost"}, CMysteryBox = {"m_Cost", "m_FireSaleCost"}, CPackAPunch = {"m_Cost"},
               CPerk = {"m_perkSinglePCost", "m_perkMultiPCost"}, CTurret = {"m_Cost"},
               CLunarLander = {"m_Cost"}, CWeaponChalkOutline = {"m_cost", "m_ammoCost", "m_upgradedAmmoCost"}}

--- What using it costs (points), or nil for a piece without a cost.
function Piece:cost()
    local fields = COSTS[self.class]
    return fields and self:get(fields[1]) or nil
end

local UNKNOWN_COST = 50000
local REFUND_TIME = 3            -- seconds a free use refunds charges for (traps charge late)

-- Free uses waiting for the credited points to count (the score updates on the next frame), and
-- the time left to refund their charges.
local pending, refunding, watching = {}, 0, false
local last_charge, frame = {}, 0

local function on_charge(event)
    if refunding <= 0 then
        return
    end
    local player = components.local_player()
    local id = player and entities.name_hash(player)
    if not id or (event.b or 0) & 0xffffffff ~= id & 0xffffffff then
        return
    end
    -- One charge reaches several subjects: refund it once.
    local key = tostring(event.a)
    if last_charge[key] and frame - last_charge[key] <= 1 then
        return
    end
    last_charge[key] = frame
    require("boz.score").add(event.a)
end

local function run_pending(dt)
    local score = require("boz.score")
    refunding = refunding - (dt or 0)
    frame = frame + 1
    for i = #pending, 1, -1 do
        local job = pending[i]
        job.frames = job.frames + 1
        if job.frames == 2 then
            refunding = REFUND_TIME
            job.piece:use()
        elseif job.frames >= 5 then
            score.add(-job.credit)                -- the credit goes; charges come back on their own
            table.remove(pending, i)
        end
    end
end

--- Uses it for free: opens a door, buys the perk, spins the box, buys the wall weapon, switches
--- a trap on, ... without the player losing points: the cost is credited (the game checks it a
--- frame later), the use happens on the next frame, every charge to the player for the next
--- few seconds is refunded and the credit is taken back. Returns true when queued.
function Piece:use_free()
    local score = require("boz.score")
    if not score.get() then
        return false
    end
    -- A piece whose cost is not a reflected field (trap switches, teleporters) gets plenty.
    local credit = self:cost() or UNKNOWN_COST
    score.add(credit)
    table.insert(pending, {piece = self, credit = credit, frames = 0})
    if not watching then
        watching = true
        events.on("frame", run_pending)
        require("boz.game_events").on("SUBJECT_CHARGE_POINTS", on_charge)
    end
    return true
end

--- Sends the piece's entity an event (boz.entities.send): "SUBJECT_MB_SPAWN", ...
function Piece:send(event, a, b)
    return entities.send(self.entity, event, a, b)
end

--- A mystery box: brings it out here (SUBJECT_MB_SPAWN) or puts it away (SUBJECT_MB_DESPAWN: it
--- leaves with its own animation once nobody is using it; m_IsDespawning).
function Piece:spawn_box() return self:send("SUBJECT_MB_SPAWN") end
function Piece:despawn_box() return self:send("SUBJECT_MB_DESPAWN") end

--- A mystery box's weapons (name hashes; m_Weapons).
function Piece:box_weapons()
    return self:get("m_Weapons") or {}
end

--- Adds a weapon (name or hash) to a mystery box's pool (SUBJECT_MB_ADD_WEAPON), or takes one out
--- (SUBJECT_MB_REMOVE_WEAPON). The map's own pool is the Weapons tab's; this lasts the match.
function Piece:add_box_weapon(weapon)
    local id = type(weapon) == "number" and weapon or require("boz.hash").name(weapon)
    return self:send("SUBJECT_MB_ADD_WEAPON", id)
end
function Piece:remove_box_weapon(weapon)
    local id = type(weapon) == "number" and weapon or require("boz.hash").name(weapon)
    return self:send("SUBJECT_MB_REMOVE_WEAPON", id)
end

--- Pack-a-Punch: brings it out (SUBJECT_PACKAPUNCH_SPAWN) or puts it away.
function Piece:spawn_pack_a_punch() return self:send("SUBJECT_PACKAPUNCH_SPAWN") end
function Piece:despawn_pack_a_punch() return self:send("SUBJECT_PACKAPUNCH_DESPAWN") end

--- A barricade: puts one board back (SUBJECT_BARRICADE_FIX).
function Piece:fix_barricade() return self:send("SUBJECT_BARRICADE_FIX") end

--- Moves the mystery box to another box spot (a piece of CMysteryBox, or the spot's entity name),
--- putting the current one away. Returns true when sent.
function pieces.move_box(to)
    local target = type(to) == "string" and pieces.of(to, "CMysteryBox") or to
    if not target then
        return false
    end
    local current = pieces.active_box()
    if current and current.entity ~= target.entity then
        current:despawn_box()
    end
    return target:spawn_box()
end

--- Fixes every barricade fully (like the carpenter, without the points).
function pieces.fix_all_barricades()
    for barricade in pieces.each("CBarricade") do
        for _ = 1, 6 do
            barricade:fix_barricade()
        end
    end
    return true
end

--- Iterates the pieces of a class: for piece in pieces.each("CPerk") do ... end
function pieces.each(class_name)
    local iterate = entities.each(class_name)
    return function()
        local entity, component = iterate()
        if entity then
            return make(entity, class_name, component)
        end
        return nil
    end
end

--- Every piece of a class, as a list.
function pieces.list(class_name)
    local out = {}
    for piece in pieces.each(class_name) do
        table.insert(out, piece)
    end
    return out
end

--- The piece of a class an entity has (or the entity called that name), or nil.
function pieces.of(target, class_name)
    local entity = type(target) == "string" and entities.find(target) or target
    if not entity then
        return nil
    end
    local component = entities.component(entity, class_name)
    return component and make(entity, class_name, component) or nil
end

function pieces.boxes() return pieces.list("CMysteryBox") end
function pieces.perks() return pieces.list("CPerk") end
function pieces.doors() return pieces.list("CDoor") end
function pieces.traps() return pieces.list("CTrap") end
function pieces.wall_buys() return pieces.list("CWeaponChalkOutline") end
function pieces.pack_a_punch() return pieces.list("CPackAPunch")[1] end
function pieces.power_switches() return pieces.list("CPowerSwitch") end

--- The mystery box that is out now (m_IsActive), or nil.
function pieces.active_box()
    for box in pieces.each("CMysteryBox") do
        if box:get("m_IsActive") then
            return box
        end
    end
    return nil
end

--- Every piece of every kind: {[class] = count} for the classes the map has.
function pieces.summary()
    local out = {}
    for _, class_name in ipairs(pieces.CLASSES) do
        local n = #pieces.list(class_name)
        if n > 0 then
            out[class_name] = n
        end
    end
    return out
end

return pieces
