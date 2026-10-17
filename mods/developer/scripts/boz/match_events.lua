-- boz.match_events: what happens in a Zombies match, as named events with plain data.
--
--   local match_events = require("boz.match_events")
--   match_events.on("zombie_killed", function(data) if data.headshot then log("headshot") end end)
--   match_events.on_any(function(name, data) log(name) end)
--
-- Events and their data:
--   "round_started" {round = n}, "round_ended" {round = n}, "power_on",
--   "perk_bought" {perk = "Juggernog", player = true}, "door_opened" {door = name, hash = n},
--   "zombie_killed" {position = {x, y, z}, entity = e, by_player = true, headshot = true},
--   "player_downed", "player_revived", "player_hit" {damage = n},
--   "weapon_given", "weapon_equipped", "weapon_fired", "weapon_reloaded" {weapon = "mp40"},
--   "points_earned" / "points_spent" {points = n, player = true},
--   "box_weapon" / "pack_a_punch" {weapon = "mp40"}, "powerup_grabbed" {powerup = "nuke",
--   player = true}, "nuke", "carpenter", "trap_activated", "teleporter_activated",
--   "game_loaded" (a continued save has been applied).
-- While the game applies a save its own events are not news: none are sent.
--
-- How it works: rounds start in CWaveManager::StartWave; perks with CPerkManager::GainPerk for a
-- perk not yet owned (bits at +0x58); zombies die entering CAIControllerZombie::State_Dead (state
-- event 1): its transform at +0xc4, killer entity at +0x138, hit location at +0x124 (0 head), kill
-- kind at +0x22c (0/1 knife, 2 grenade); points earned go through CScoreManager::AddScore; power-ups
-- through CPickupManager::ApplyPickup; continuing a save, CSaveManager::NotifyLoad. Doors (a CDoor
-- whose m_DoorState became open), the power and the player's downed state are checked each frame;
-- the rest are the game's own SUBJECT_* events (boz.game_events).

local match_events = {}

local core = require("boz.core")
local map = require("boz.map")

local ZOMBIE_TRANSFORM, ZOMBIE_KILLER, ZOMBIE_HIT_LOCATION, ZOMBIE_KILL_KIND = 0xc4, 0x138, 0x124, 0x22c
local COMPONENT_ENTITY = 0xc
local PERKS_OWNED = 0x58
local STATE_EVENT_KIND = 0x18     -- CIsStateMachine vtable: the state event's kind (1: entering)

local listeners = {}      -- name -> {fn = true}
local any = {}            -- {fn = true}
local started = false
local loading = false
local names = {}          -- name hash -> object name (door names)
local state = {downed = false, powered = false, doors = {}, level_starts = 0}

local function emit(name, data)
    if loading then
        return
    end
    data = data or {}
    for fn in pairs(listeners[name] or {}) do
        core.safely("boz.match_events: " .. name, fn, data, name)
    end
    for fn in pairs(any) do
        core.safely("boz.match_events: " .. name, fn, name, data)
    end
end

local function player_entity()
    return map.player() or 0
end

local function player_hash()
    local id = require("boz.player").name_hash()
    return id and id & 0xffffffff or nil
end

local function name_of(entity)
    if entity == 0 then
        return nil, 0
    end
    local h = require("boz.entities").name_hash(entity) or 0
    return names[h] or string.format("0x%08x", h), h
end

local function watch_doors(quiet)
    local seen = {}
    for door in require("boz.pieces").each("CDoor") do
        local open = door:is_open()
        seen[door.component] = open
        if not quiet and state.doors[door.component] == false and open then
            local name, h = name_of(door.entity)
            emit("door_opened", {door = name, hash = h})
        end
    end
    state.doors = seen
end

local function watch_player()
    local player = require("boz.player")
    local dead = player.dead()
    local downed = player.downed()
    if downed and not state.downed then
        emit("player_downed")
    elseif state.downed and not downed and not dead then
        emit("player_revived")
    end
    state.downed = downed
end

local function watch_power()
    local on = require("boz.rounds").powered()
    if on and not state.powered then
        emit("power_on")
    end
    state.powered = on
end

local function round()
    return require("boz.rounds").current() or 0
end

local function relay(event, name, data_of, options)
    require("boz.game_events").on(event, function(e)
        emit(name, data_of and data_of(e) or {})
    end, options or {dedupe_frames = 3})
end

local function start()
    started = true
    local player = require("boz.player")
    local weapons = require("boz.weapons")
    hook.add(core.sym("CWaveManager::StartWave"), {after = function(call)
        local manager = call:arg(1)
        emit("round_started", {round = manager ~= 0 and round() or 0})
    end})
    hook.add(core.sym("CPerkManager::GainPerk"), {before = function(call)
        local manager, perk = call:arg(1), call:arg(2)
        if manager == 0 or game.read("u32", manager + PERKS_OWNED) & (1 << (perk & 31)) ~= 0 then
            return
        end
        local entity = game.read("ptr", manager + COMPONENT_ENTITY)
        emit("perk_bought", {perk = player.PERKS[perk + 1] or perk,
                             player = entity ~= 0 and entity == player_entity()})
    end})
    hook.add(core.sym("CAIControllerZombie::State_Dead"), {before = function(call)
        local controller, machine = call:arg(1), call:arg(2)
        if controller == 0 or machine == 0 or core.virtual(machine, STATE_EVENT_KIND) ~= 1 then
            return
        end
        local killer = game.read("ptr", controller + ZOMBIE_KILLER)
        local how = game.read("i32", controller + ZOMBIE_KILL_KIND)
        emit("zombie_killed", {
            position = require("boz.objects").transform_position(game.read("ptr", controller + ZOMBIE_TRANSFORM)),
            entity = game.read("ptr", controller + COMPONENT_ENTITY),
            by_player = killer ~= 0 and killer == player_entity(),
            headshot = (how < 0 or how > 2) and game.read("u32", controller + ZOMBIE_HIT_LOCATION) == 0,
        })
    end})
    local function points(e) return {points = e.a, player = (e.b or 0) & 0xffffffff == player_hash()} end
    -- Once per round: the wave manager and the level manager both pass it on.
    relay("SUBJECT_WAVE_ENDED", "round_ended", function() return {round = round()} end,
          {dedupe_key = function() return state.level_starts .. ":" .. round() end, dedupe_frames = math.huge})
    relay("SUBJECT_CHARGE_POINTS", "points_spent", points)
    relay("SUBJECT_ENEMY_ATTACK_DAMAGE", "player_hit", function(e) return {damage = e.a} end)
    relay("SUBJECT_MB_CHOOSE_WEAPON", "box_weapon", function(e) return {weapon = weapons.name(e.a)} end)
    relay("SUBJECT_PACKAPUNCH_START", "pack_a_punch", function(e) return {weapon = weapons.name(e.a)} end)
    relay("SUBJECT_NUKE_NOW", "nuke")
    relay("SUBJECT_CARPENTER_ACTIVATED", "carpenter")
    relay("SUBJECT_ON_TRAP_ACTIVATED", "trap_activated")
    relay("SUBJECT_ON_TELEPORTER_ACTIVATED", "teleporter_activated")
    hook.add(core.sym("CScoreManager::AddScore"), {before = function(call)
        local delta = call:arg(3) & 0xffffffff
        if delta == 0 or delta >= 0x80000000 then
            return
        end
        emit("points_earned", {points = delta, player = call:arg(2) & 0xffffffff == player_hash()})
    end})
    hook.add(core.sym("CPickupManager::ApplyPickup"), {before = function(call)
        local who = call:arg(2)
        emit("powerup_grabbed", {powerup = require("boz.pickups").TYPES[call:arg(3) + 1] or call:arg(3),
                                 player = who ~= 0 and who == player_entity()})
    end})
    weapons.on_event(function(event, name, data)
        local info = {weapon = name}
        for k, v in pairs(data or {}) do
            info[k] = v
        end
        emit("weapon_" .. event, info)
    end)
    hook.add(core.sym("CSaveManager::NotifyLoad"), {
        before = function() loading = true end,
        after = function()
            loading = false
            watch_doors(true)    -- doors the save opened are not news
            emit("game_loaded")
        end,
    })
    map.on_level_start(function()
        state.level_starts = state.level_starts + 1
        state.downed, state.powered, state.doors, loading = false, false, {}, false
    end)
    events.on("frame", function()
        if not map.playing() then
            return
        end
        core.safely("boz.match_events: player", watch_player)
        core.safely("boz.match_events: doors", watch_doors, loading)
        core.safely("boz.match_events: power", watch_power)
    end)
end

--- Calls fn(data, name) every time the event happens. Returns a handle for off().
function match_events.on(name, fn)
    if not started then
        start()
    end
    listeners[name] = listeners[name] or {}
    listeners[name][fn] = true
    return {name = name, fn = fn}
end

--- Calls fn(name, data) on every event. Returns a handle for off().
function match_events.on_any(fn)
    if not started then
        start()
    end
    any[fn] = true
    return {fn = fn}
end

--- Stops a handler on() or on_any() returned.
function match_events.off(handle)
    if handle.name then
        (listeners[handle.name] or {})[handle.fn] = nil
    else
        any[handle.fn] = nil
    end
end

--- Tells it the names of the map's objects, so door_opened names its door.
function match_events.know_names(list)
    for _, name in ipairs(list or {}) do
        names[require("boz.hash").name(name)] = name
    end
end

--- True while the game applies a continued save.
function match_events.loading()
    return loading
end

return match_events
