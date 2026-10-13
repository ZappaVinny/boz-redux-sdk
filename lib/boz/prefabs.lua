-- boz.prefabs: scripts for the map's prefabs, models and volumes, and the event bus between them.
--
-- A script is attached to an object in the editor (Properties → Object → Game → Script). It is
-- just the handlers; `self` is the object it is attached to:
--
--   function on_hit(volume, info)              -- a Hit volume of this prefab was shot
--       self:part("Door"):hide():set_collision(false):open_navmesh()
--       boz.send("vault_open", {by = self.name})
--   end
--
-- The script runs once per object using it, each with its own `self` and its own top-level
-- variables (a `local hits = 0` at the top counts per object). `boz` is this module.
--
-- Saved with the game: a script's global variables (`hits = 0`, not `local hits = 0`) and
-- boz.globals (one table every script of the map shares) are written when the game saves and
-- come back when the player continues that save, before start() runs. Numbers, strings,
-- booleans and tables of those are saved; functions and handles are not.
--
-- Timers: boz.after(seconds, fn) and boz.every(seconds, fn) run on game time (they wait while
-- the game is paused) and return a timer with :cancel().
--
-- On `self`: self.name, self.properties (the values set in the editor for the script's
-- ---@property lines), self:part(name) and self:parts() for a prefab's parts, and show/hide,
-- set_collision, open_navmesh/close_navmesh for the whole object.
--
-- Handlers a script may define (all optional):
--   start()                      the level started
--   on_enter(volume, who), on_exit(volume, who)   a Trigger volume (who.player, who.zombie)
--   on_hit(volume, info)         a Hit volume was shot
--   on_use(volume, who)          the player pressed use at a Use volume (its cost already paid)
--   on_event(name, data)         boz.send(name, data) from any script, and game events:
--                                "round_started" {round = n}, "power_on",
--                                "perk_bought" {perk = "Juggernog", player = true},
--                                "door_opened" {door = name, hash = n},
--                                "zombie_killed" {position = {x, y, z}, entity = e,
--                                                 by_player = true, headshot = true},
--                                "player_downed", "player_revived",
--                                "weapon_given", "weapon_equipped", "weapon_reloaded"
--                                {weapon = "mp40"} ("weapon_fired" only reaches boz.on)
--
-- Weapon scripts (Weapons tab → Add script): self is the weapon (self.name, and the boz.weapons
-- handle's methods on the live weapon: self:clip(), self:set_damage(...), ...). Handlers:
-- on_given(), on_equip(), on_fire(data), on_reload(), on_event(name, data).
-- volume is the volume's name inside the prefab (its own name for a volume with a script); only
-- volumes send these, and only volumes of the object (or its parts) the script is attached to.
-- Other functions a script defines can be called by other scripts: boz.find("Vault_1"):open().
-- Every volume event also goes to boz.on listeners as "<volume name>.<event>"
-- ("Vault_1.Skull.hit"); on_event does not get it (the script's own handler did).
-- Trigger volumes: on_enter when something comes in, on_exit once it has left (the game's own
-- enter/exit flicker while standing in it is smoothed out).
--
-- print shows in the Developer console as well as the log.
--
-- How it works: the client's loadscript(name, env) loads the script with a fresh environment for
-- each object (self and boz in it, the mod's globals behind it; print also goes through the
-- game's Console_Print, which boz.console passes to the Developer console). Volumes are boz.objects events
-- (enter/exit on ghost boxes, hit on easter egg skulls, use at points of interest). Use prompts:
-- when a Use volume becomes the point of interest in reach (SUBJECT_POI_TRIGGER, handled by
-- CIngameStatePlaying::UpdatePoiPrompt), its prompt is shown with Poi_ShowPrompt; its cost is
-- paid with CScoreManager::AddScore. Rounds:
-- CWaveManager::StartWave (round number at +0x78). Power: a power switch's on flag
-- (CPowerSwitch +0x88). Perks: CPerkManager::GainPerk(manager, perk, apply) for a perk not yet
-- owned (bits at +0x58). Doors: a CDoor whose m_DoorState (+0x9c) became 2 (open), checked each
-- frame. Hooks here are before hooks where they can be: an after hook swaps the return address
-- for the client's trap, and on a busy function that crashed the game.
-- Zombies: CAIControllerZombie::State_Dead entering (state event 1): its transform at +0xc4,
-- killer entity at +0x138, hit location at +0x124 (0 head), kill kind at +0x22c (0/1 knife,
-- 2 grenade). Downed: the local CPlayerController's stance (+0x1f4) is 8 (last stand) while its
-- state machine (state at +0x1d4) is not 0x14/0x15 (dead). Game time: frames in which
-- CPlayerController::FixedStep ran. Saving: CSaveManager::SaveGame (autosave at each round
-- start, pause); continuing a save: CLevelManager +0x298 set at level start, then
-- CSaveManager::NotifyLoad sends SUBJECT_LOAD from the resume-loading state. The values go in
-- the map mod's settings (globals.<level>.<n>, Lua table text in chunks).

local objects = require("boz.objects")
local hash = require("boz.hash")
local weapons = require("boz.weapons")
local text = require("boz.text")

local prefabs = {}

local FALLBACK = {
    ["CPerkManager::GainPerk"] = 0x1cc080 + 1,
    ["CDoor::OnEvent"] = 0x17c340 + 1,
    ["CAIControllerZombie::State_Dead"] = 0x1152e8 + 1,
    ["CPlayerController::s_table"] = 0x46c90c,
    ["CPlayerController::FixedStep"] = 0x1d8e3c + 1,
    ["CSaveManager::SaveGame"] = 0x1f4974 + 1,
    ["CSaveManager::NotifyLoad"] = 0x1f3240 + 1,
    ["CScoreManager::s_instance"] = 0x461080,
    ["CIsEntityDB::GetEntity"] = 0x0bd4c8 + 1,
    ["CDoor::s_table"] = 0x466798,
    ["CIngameStatePlaying::UpdatePoiPrompt"] = 0x1a1e68 + 1,
    ["Poi_FindPromptElement"] = 0x19f78c + 1,
    ["Poi_ShowPrompt"] = 0x19f9d0 + 1,
    ["CScoreManager::GetLocalScore"] = 0x1f6148 + 1,
    ["CScoreManager::AddScore"] = 0x1f73e0 + 1,
    ["CWaveManager::StartWave"] = 0x217c1c + 1,
    ["Entity_GetNameHash"] = 0x104218 + 1,
    ["CPowerSwitch::s_table"] = 0x46d188,
}
local LEVEL_PLAYER = 0x1a0
local WAVE_ROUND = 0x78
local POWER_ON = 0x88
local LEVEL_NAME = 0x55          -- CLevelManager: the level's name ("callofthedead")
local LEVEL_RESUMING = 0x298     -- CLevelManager: the level started from a save
local PERKS_OWNED = 0x58         -- CPerkManager
local COMPONENT_ENTITY = 0xc
local DOOR_STATE = 0x9c          -- CDoor m_DoorState: 2 = open
local DOOR_OPEN = 2
local ZOMBIE_TRANSFORM = 0xc4    -- CAIControllerZombie
local ZOMBIE_KILLER = 0x138
local ZOMBIE_HIT_LOCATION = 0x124
local ZOMBIE_KILL_KIND = 0x22c
local PLAYER_STATE = 0x1d4       -- CPlayerController: its state machine's state
local PLAYER_STANCE = 0x1f4
local STANCE_DOWNED = 8
local PERK_NAMES = {"Deadshot", "Double Tap", "Juggernog", "Stamin-Up", "PHD Flopper", "Quick Revive",
                    "Speed Cola"}
local SAVE_CHUNK = 3000          -- settings lines hold up to 4 KB
local LOAD_WAIT = 20             -- seconds to wait for a save to load before starting anyway

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

local function lower(name)
    return string.lower(name)
end

local function log_error(where, err)
    log("boz.prefabs: " .. where .. ": " .. tostring(err))
end

-- Instances: one per scripted object in the running level.

local Instance = {}
Instance.__index = Instance

local instances = {}     -- lower name -> instance
local volumes = {}       -- lower volume name -> its world_data entry
local listeners = {}     -- event name -> {fn, ...}
local hooked = {}        -- lower volume name .. event -> true
local names = {}         -- name hash -> object name, for game events about the map's objects
local loading = false    -- the game is applying a save (its own events then are not news)

--- Values every script of the map shares, saved with the game (see the top of this file).
prefabs.globals = {}

--- The boz.objects handle of a part of this prefab (by its name in the prefab).
function Instance:part(name)
    return objects.get(self._parts[name] or (self.name .. "." .. name))
end

--- {name, object} of every part of this prefab.
function Instance:parts()
    local out = {}
    for name, full in pairs(self._parts) do
        table.insert(out, {name = name, object = objects.get(full)})
    end
    table.sort(out, function(a, b) return a.name < b.name end)
    return out
end

local function each_member(self, fn)
    if #self._members == 0 then
        fn(objects.get(self.name))
        return
    end
    for _, full in ipairs(self._members) do
        fn(objects.get(full))
    end
end

--- Shows or hides the object (every part of a prefab). Returns self.
function Instance:set_visible(visible)
    each_member(self, function(object) object:set_visible(visible) end)
    return self
end

function Instance:show() return self:set_visible(true) end
function Instance:hide() return self:set_visible(false) end

--- Switches the collision of the object (every part of a prefab). Returns self.
function Instance:set_collision(enabled)
    each_member(self, function(object) object:set_collision(enabled) end)
    return self
end

--- Opens or closes the walkable area under the object (and its parts that block it). Returns self.
function Instance:set_navmesh(open)
    objects.set_navmesh(self.name, open)
    each_member(self, function(object) object:set_navmesh(open) end)
    return self
end

function Instance:open_navmesh() return self:set_navmesh(true) end
function Instance:close_navmesh() return self:set_navmesh(false) end

--- The object's world position {x, y, z} (game centimetres, y is up): a prefab's is the middle
--- of its parts. nil when it is not in the running level.
function Instance:position()
    local sum, count = {x = 0, y = 0, z = 0}, 0
    each_member(self, function(object)
        local p = object:position()
        if p then
            sum.x, sum.y, sum.z, count = sum.x + p.x, sum.y + p.y, sum.z + p.z, count + 1
        end
    end)
    if count == 0 then
        return nil
    end
    return {x = sum.x / count, y = sum.y / count, z = sum.z / count}
end

--- True when the object (any part of a prefab) is within `distance` centimetres of `target` (a
--- position such as zombie_killed's data.position, or another object).
function Instance:near(target, distance)
    local found = false
    each_member(self, function(object)
        found = found or object:near(target, distance)
    end)
    return found
end

--- boz.send from this object.
function Instance:send(name, data)
    prefabs.send(name, data)
end

local function call(instance, handler, ...)
    local fn = instance and instance[handler]
    if type(fn) ~= "function" then
        return
    end
    local ok, err = pcall(fn, instance, ...)
    if not ok then
        log_error(instance.name .. ":" .. handler, err)
    end
end

--- The scripted object called *name* (its script instance), else its boz.objects handle when it
--- exists in the level, else nil.
function prefabs.find(name)
    return instances[lower(name)] or objects.find(name)
end

local function notify_listeners(name, data)
    for _, fn in ipairs(listeners[name] or {}) do
        local ok, err = pcall(fn, data, name)
        if not ok then
            log_error("listener of " .. name, err)
        end
    end
end

--- Sends an event on the bus: every boz.on(name) listener and every script's on_event.
function prefabs.send(name, data)
    notify_listeners(name, data)
    for _, instance in pairs(instances) do
        call(instance, "on_event", name, data)
    end
end

--- Calls fn(data, name) on every boz.send(name, ...). Returns fn.
function prefabs.on(name, fn)
    listeners[name] = listeners[name] or {}
    table.insert(listeners[name], fn)
    return fn
end

-- Volumes

local HANDLERS = {enter = "on_enter", exit = "on_exit", hit = "on_hit", use = "on_use"}
local VOLUME_EVENTS = {trigger = {"enter", "exit"}, hit = {"hit"}, use = {"use"}}

local function allowed(entry, who)
    if entry.who == "zombies" then
        return who and who.zombie
    elseif entry.who == "anyone" then
        return true
    end
    return who == nil or who.player
end

-- The name hash scores and door tags are keyed by: the entity database's record for an entity
-- (CIsEntityDB::GetEntity, by the id at +4), then Entity_GetNameHash of that record, as the game
-- does (asking the entity pointer itself gives a wrong value).
local function name_hash(entity)
    local record = game.call(sym("CIsEntityDB::GetEntity"), entity)
    return record ~= 0 and game.call(sym("Entity_GetNameHash"), record) or 0
end

local function score_manager()
    local manager = game.read("ptr", sym("CScoreManager::s_instance"))
    return manager ~= 0 and manager or nil
end

local function pay(cost)
    if not cost or cost <= 0 then
        return true
    end
    local manager = score_manager()
    if not manager then
        log_error("use cost", "no score manager: the cost is not taken")
        return true
    end
    if game.call(sym("CScoreManager::GetLocalScore"), manager) < cost then
        return false
    end
    local level = game.read("ptr", "CLevelManager::s_instance")
    local player = level ~= 0 and game.read("ptr", level + LEVEL_PLAYER) or 0
    if player ~= 0 then
        local before = game.call(sym("CScoreManager::GetLocalScore"), manager)
        local id = name_hash(player)
        game.call(sym("CScoreManager::AddScore"), manager, id, -cost, 0)
        local after = game.call(sym("CScoreManager::GetLocalScore"), manager)
        if after ~= before - cost then
            log_error("use cost", string.format("points %d -> %d paying %d (player hash 0x%08x)",
                                                before, after, cost, id))
        end
    end
    return true
end

-- Trigger volumes: the game's collision reports enter/exit again and again while something
-- stands in a ghost box (and once per collision shape), so each volume counts what is inside:
-- "enter" when something comes in, "exit" once it has been out for EXIT_DELAY seconds.
local EXIT_DELAY = 0.25
local leaving = {}       -- {entry, entity, info, left} waiting to become "exit"

local function inside(entry, entity, delta)
    entry._inside = entry._inside or {}
    local count = math.max((entry._inside[entity] or 0) + delta, 0)
    entry._inside[entity] = count > 0 and count or nil
    return count
end

local fire_volume

local function volume_event(event, object, info)
    local entry = volumes[lower(object.name)]
    if not entry or not allowed(entry, info) then
        return
    end
    if entry.volume == "trigger" then
        local entity = info and info.entity or 0
        if event == "enter" then
            if inside(entry, entity, 1) ~= 1 then
                return
            end
            for i, pending in ipairs(leaving) do
                if pending.entry == entry and pending.entity == entity then
                    table.remove(leaving, i)   -- back before it counted as leaving
                    return
                end
            end
        else
            if inside(entry, entity, -1) ~= 0 then
                return
            end
            table.insert(leaving, {entry = entry, entity = entity, info = info, left = 0})
            return
        end
    end
    fire_volume(event, entry, info)
end

local function check_leaving(dt)
    local due = {}
    for i = #leaving, 1, -1 do
        local pending = leaving[i]
        pending.left = pending.left + dt
        if pending.left >= EXIT_DELAY then
            table.remove(leaving, i)
            table.insert(due, 1, pending)
        end
    end
    for _, pending in ipairs(due) do
        fire_volume("exit", pending.entry, pending.info)
    end
end

fire_volume = function(event, entry, info)
    if entry.once and entry._fired then
        return
    end
    if event == "use" and not pay(entry.cost) then
        return
    end
    entry._fired = true
    local owner_name = entry.owner ~= "" and entry.owner or (entry.script ~= "" and entry.name)
    local owner = owner_name and instances[lower(owner_name)]
    local part = entry.name
    if entry.owner ~= "" and string.sub(entry.name, 1, #entry.owner + 1) == entry.owner .. "." then
        part = string.sub(entry.name, #entry.owner + 2)
    end
    call(owner, HANDLERS[event], part, info)
    notify_listeners(entry.name .. "." .. event, info)   -- boz.on only: the script had its handler
end

local function watch_volume(entry)
    for _, event in ipairs(VOLUME_EVENTS[entry.volume] or {}) do
        local key = lower(entry.name) .. event
        if not hooked[key] then
            hooked[key] = true
            objects.on(entry.name, event, function(object, info) volume_event(event, object, info) end)
        end
    end
end

-- Use prompts: when the point of interest in reach changes (SUBJECT_POI_TRIGGER),
-- CIngameStatePlaying::UpdatePoiPrompt hides the prompt and builds the one for the POI's type; a
-- Use volume's type (a barricade's) has no barricade, so the game would leave it hidden. For a
-- Use volume the game's handling is skipped and the volume's own prompt shown instead.

local prompt_texts = {}   -- text -> game memory holding it (the label keeps the pointer)

local function text_pointer(text)
    local pointer = prompt_texts[text]
    if not pointer then
        pointer = game.alloc(#text + 1)
        for i = 1, #text do
            game.write("u8", pointer + i - 1, string.byte(text, i))
        end
        prompt_texts[text] = pointer
    end
    return pointer
end

local function prompt_of(entry)
    local text = entry.prompt ~= "" and entry.prompt or "Use"
    if entry.cost and entry.cost > 0 then
        text = text .. " [Cost: " .. entry.cost .. "]"
    end
    return text
end

local POI_TRIGGER = hash.name("SUBJECT_POI_TRIGGER")

local function show_prompt(entity)
    if entity == 0 then
        return false
    end
    for _, entry in pairs(volumes) do
        if entry.volume == "use" and not (entry.once and entry._fired)
                and objects.get(entry.name):entity_pointer() == entity then
            local element = game.call(sym("Poi_FindPromptElement"))
            if element ~= 0 then
                game.call(sym("Poi_ShowPrompt"), element, text_pointer(prompt_of(entry)), 1, 1)
            end
            return true
        end
    end
    return false
end

-- Game events on the bus

local power_was_on = false

local function power_on()
    local table_address = sym("CPowerSwitch::s_table")
    if not table_address then
        return false
    end
    local components = require("boz.components")
    for switch in components.each(table_address) do
        if game.read("u8", switch + POWER_ON) ~= 0 then
            return true
        end
    end
    return false
end

-- Timers on game time

local clock = {now = 0, stepped = false, timers = {}}

local Timer = {}
Timer.__index = Timer

--- Stops the timer.
function Timer:cancel()
    self.cancelled = true
end

local function add_timer(seconds, interval, fn)
    assert(type(fn) == "function", "boz timers need a function")
    local timer = setmetatable({due = clock.now + seconds, interval = interval, fn = fn}, Timer)
    table.insert(clock.timers, timer)
    return timer
end

--- Runs fn() once, `seconds` of game time from now (paused time does not count). Returns a timer
--- with :cancel().
function prefabs.after(seconds, fn)
    return add_timer(seconds, nil, fn)
end

--- Runs fn() every `seconds` of game time until the timer is cancelled. Returns the timer.
function prefabs.every(seconds, fn)
    assert(seconds > 0, "boz.every needs a positive interval")
    return add_timer(seconds, seconds, fn)
end

local function run_timers(dt)
    if clock.stepped then
        clock.now = clock.now + dt
    end
    clock.stepped = false
    local due = {}
    for _, timer in ipairs(clock.timers) do
        if not timer.cancelled and timer.due <= clock.now then
            table.insert(due, timer)
        end
    end
    for _, timer in ipairs(due) do
        local ok, err = pcall(timer.fn)
        if not ok then
            log_error("timer", err)
        end
        if timer.interval and not timer.cancelled then
            timer.due = timer.due + timer.interval
        else
            timer.cancelled = true
        end
    end
    if #due > 0 then
        local kept = {}
        for _, timer in ipairs(clock.timers) do
            if not timer.cancelled then
                table.insert(kept, timer)
            end
        end
        clock.timers = kept
    end
end

-- Saved globals: each scripted object's global variables and prefabs.globals, as Lua table text.

local function saveable(value, seen, depth)
    local kind = type(value)
    if kind == "number" or kind == "string" or kind == "boolean" then
        return value
    end
    if kind ~= "table" or getmetatable(value) ~= nil or seen[value] or depth > 16 then
        return nil   -- functions, handles, instances, loops
    end
    seen[value] = true
    local copy = {}
    for k, v in pairs(value) do
        local key_kind = type(k)
        if key_kind == "string" or key_kind == "number" then
            local saved = saveable(v, seen, depth + 1)
            if saved ~= nil then
                copy[k] = saved
            end
        end
    end
    seen[value] = nil
    return copy
end

local function encode(value)
    local kind = type(value)
    if kind == "table" then
        local keys = {}
        for k in pairs(value) do
            table.insert(keys, k)
        end
        table.sort(keys, function(a, b)
            if type(a) == type(b) then
                return a < b
            end
            return type(a) == "number"
        end)
        local out = {}
        for _, k in ipairs(keys) do
            table.insert(out, "[" .. encode(k) .. "]=" .. encode(value[k]))
        end
        return "{" .. table.concat(out, ",") .. "}"
    elseif kind == "string" then
        return (string.format("%q", value):gsub("\\\n", "\\n"))
    elseif kind == "number" then
        if value ~= value then
            return "(0/0)"
        elseif value == math.huge then
            return "1e999"
        elseif value == -math.huge then
            return "-1e999"
        elseif math.type(value) == "integer" then
            return tostring(value)
        end
        return string.format("%.17g", value)
    end
    return tostring(value)
end

local function decode(text)
    local chunk = load("return " .. text, "=saved globals", "t", {})
    if not chunk then
        return nil
    end
    local ok, value = pcall(chunk)
    return ok and type(value) == "table" and value or nil
end

local function level_name()
    local level = game.read("ptr", "CLevelManager::s_instance")
    return level ~= 0 and game.read("string", level + LEVEL_NAME, 64) or nil
end

local function snapshot()
    local data = {objects = {}, globals = saveable(prefabs.globals, {}, 0) or {}}
    for _, instance in pairs(instances) do
        local vars = {}
        for k, v in pairs(instance._env or {}) do
            if type(k) == "string" and k ~= "self" and k ~= "boz" and type(v) ~= "function" then
                local saved = saveable(v, {}, 0)
                if saved ~= nil then
                    vars[k] = saved
                end
            end
        end
        data.objects[instance.name] = vars
    end
    return data
end

--- Writes the map's saved globals now (the game's saves call this).
function prefabs.save()
    local name = level_name()
    if not name or not settings then
        return false
    end
    local text = encode(snapshot())
    local key = "globals." .. name
    local before = settings.get(key .. ".count", 0)
    local count = 0
    for at = 1, #text, SAVE_CHUNK do
        count = count + 1
        settings.set(key .. "." .. count, string.sub(text, at, at + SAVE_CHUNK - 1))
    end
    for i = count + 1, before do
        settings.set(key .. "." .. i, nil)
    end
    settings.set(key .. ".count", count)
    return true
end

local function read_saved()
    local name = level_name()
    if not name or not settings then
        return nil
    end
    local key = "globals." .. name
    local parts = {}
    for i = 1, settings.get(key .. ".count", 0) do
        local part = settings.get(key .. "." .. i)
        if type(part) ~= "string" then
            return nil
        end
        table.insert(parts, part)
    end
    return #parts > 0 and decode(table.concat(parts)) or nil
end

local function restore(data)
    if not data then
        return
    end
    for k in pairs(prefabs.globals) do
        prefabs.globals[k] = nil
    end
    for k, v in pairs(data.globals or {}) do
        prefabs.globals[k] = v
    end
    for name, vars in pairs(data.objects or {}) do
        local instance = instances[lower(name)]
        if instance and instance._env then
            for k, v in pairs(vars) do
                instance._env[k] = v
            end
        end
    end
end

-- Starting: start() runs at once in a new game; continuing a save, after the save is applied.

local starting = {pending = false, waited = 0}

local function run_start()
    starting.pending = false
    for _, instance in pairs(instances) do
        call(instance, "start")
    end
end

local function save_loaded()
    if starting.pending then
        restore(read_saved())
        run_start()
    end
end

-- Game events

local function local_player()
    local level = game.read("ptr", "CLevelManager::s_instance")
    return level ~= 0 and game.read("ptr", level + LEVEL_PLAYER) or 0
end

local function name_of(entity)
    if entity == 0 then
        return nil, 0
    end
    local h = name_hash(entity)
    return names[h] or string.format("0x%08x", h), h
end

local downed = false
local door_states = {}   -- CDoor component -> m_DoorState last frame

-- Doors: each frame, a door whose state became open (2). quiet: just remember the states.
local function watch_doors(quiet)
    local components = require("boz.components")
    local seen = {}
    for door in components.each(sym("CDoor::s_table")) do
        local state = game.read("u32", door + DOOR_STATE)
        seen[door] = state
        local was = door_states[door]
        if not quiet and was ~= nil and was ~= DOOR_OPEN and state == DOOR_OPEN then
            local name, h = name_of(game.read("ptr", door + COMPONENT_ENTITY))
            prefabs.send("door_opened", {door = name, hash = h})
        end
    end
    door_states = seen
end

local function watch_player()
    local player = local_player()
    local controller = player ~= 0 and game.call("CIsComponentTableBase::Find",
        sym("CPlayerController::s_table"), game.read("u32", player + 4)) or 0
    if controller == 0 then
        downed = false
        return
    end
    local state = game.read("u32", controller + PLAYER_STATE)
    local dead = state == 0x14 or state == 0x15
    local now = game.read("u32", controller + PLAYER_STANCE) == STANCE_DOWNED and not dead
    if now and not downed then
        prefabs.send("player_downed", {})
    elseif downed and not now and not dead then
        prefabs.send("player_revived", {})
    end
    downed = now
end

local function bridge_more_events()
    hook.add(sym("CPerkManager::GainPerk"), {before = function(info)
        local manager, perk = info:arg(1), info:arg(2)
        if loading or manager == 0 or game.read("u32", manager + PERKS_OWNED) & (1 << (perk & 31)) ~= 0 then
            return
        end
        local entity = game.read("ptr", manager + COMPONENT_ENTITY)
        prefabs.send("perk_bought", {perk = PERK_NAMES[perk + 1] or perk,
                                     player = entity ~= 0 and entity == local_player()})
    end})
    hook.add(sym("CAIControllerZombie::State_Dead"), {before = function(info)
        local controller, machine = info:arg(1), info:arg(2)
        if controller == 0 or machine == 0 then
            return
        end
        -- The state event's kind (vtable slot 6): 1 when the zombie enters the dead state.
        local kind = game.call(game.read("ptr", game.read("ptr", machine) + 0x18), machine)
        if kind ~= 1 then
            return
        end
        local killer = game.read("ptr", controller + ZOMBIE_KILLER)
        local how = game.read("i32", controller + ZOMBIE_KILL_KIND)
        prefabs.send("zombie_killed", {
            position = objects.transform_position(game.read("ptr", controller + ZOMBIE_TRANSFORM)),
            entity = game.read("ptr", controller + COMPONENT_ENTITY),
            by_player = killer ~= 0 and killer == local_player(),
            headshot = (how < 0 or how > 2) and game.read("u32", controller + ZOMBIE_HIT_LOCATION) == 0,
        })
    end})
    local WEAPON_HANDLERS = {given = "on_given", equipped = "on_equip", fired = "on_fire",
                             reloaded = "on_reload"}
    weapons.listen(function(event, name, data)
        local instance = instances[lower(name)]
        if instance and instance.kind == "weapon" then
            call(instance, WEAPON_HANDLERS[event], data)
        end
        local info = {weapon = name}
        for k, v in pairs(data or {}) do
            info[k] = v
        end
        if event == "fired" then
            notify_listeners("weapon_fired", info)
        else
            prefabs.send("weapon_" .. event, info)
        end
    end)
    local stepped = sym("CPlayerController::FixedStep")
    if stepped then
        hook.add(stepped, {before = function() clock.stepped = true end})
    end
    hook.add(sym("CSaveManager::SaveGame"), {before = function()
        local ok, err = pcall(prefabs.save)
        if not ok then
            log_error("save", err)
        end
    end})
    hook.add(sym("CSaveManager::NotifyLoad"), {
        before = function() loading = true end,
        after = function()
            loading = false
            watch_doors(true)    -- doors the save opened are not news
            save_loaded()
        end,
    })
end

local bridged = false

local function bridge_game_events()
    if bridged then
        return
    end
    bridged = true
    bridge_more_events()
    -- A before hook that replaces the game's handling for Use volumes (an after hook's return
    -- trap through this long function crashed the game).
    hook.add(sym("CIngameStatePlaying::UpdatePoiPrompt"), {before = function(info)
        if info:arg(3) ~= POI_TRIGGER or not next(volumes) then
            return
        end
        local ok, shown = pcall(show_prompt, info:arg(4))
        if not ok then
            log_error("prompt", shown)
        elseif shown then
            info:skip()
        end
    end})
    hook.add(sym("CWaveManager::StartWave"), {after = function(call_info)
        local manager = call_info:arg(1)
        prefabs.send("round_started", {round = manager ~= 0 and game.read("u32", manager + WAVE_ROUND) or 0})
    end})
    events.on("frame", function(dt)
        run_timers(dt or 0)
        check_leaving(dt or 0)
        if starting.pending then
            starting.waited = starting.waited + (dt or 0)
            if starting.waited > LOAD_WAIT then
                log_error("save", "the save did not load; starting without it")
                run_start()
            end
        end
        local watched, err = pcall(watch_player)
        if not watched then
            log_error("player", err)
        end
        local doors_ok, doors_err = pcall(watch_doors, loading)
        if not doors_ok then
            log_error("doors", doors_err)
        end
        local ok, on = pcall(power_on)
        if ok and on and not power_was_on then
            power_was_on = true
            prefabs.send("power_on", {})
        elseif ok and not on then
            power_was_on = false
        end
    end)
end

-- A weapon script's self: the instance, and the live weapon's methods (boz.weapons handles).
local function weapon_index(t, key)
    local method = Instance[key]
    if method ~= nil then
        return method
    end
    local live = weapons.get(rawget(t, "name"))
    local value = live and live[key]
    if type(value) == "function" then
        return function(_, ...) return value(live, ...) end
    end
    return value
end

local function new_instance(entry)
    local parts = {}
    for _, part in ipairs(entry.parts or {}) do
        parts[part.part] = part.name
    end
    local instance = {name = entry.name, kind = entry.kind, properties = entry.properties or {},
                      _parts = parts, _members = entry.members or {}}
    if entry.kind == "weapon" then
        return setmetatable(instance, {__index = weapon_index})
    end
    instance.object = objects.get(entry.name)
    return setmetatable(instance, Instance)
end

local function bind(instance, env)
    -- Every function the script defines becomes a method of its object, called without self
    -- (self is in the script's environment): handlers, and functions other scripts call.
    for name, value in pairs(env) do
        if type(value) == "function" then
            instance[name] = function(_, ...) return value(...) end
        end
    end
end

-- print in a map script: the mod's log, and the game console (the Developer console shows it).
local function script_print(...)
    local parts = {}
    for i = 1, select("#", ...) do
        parts[i] = tostring((select(i, ...)))
    end
    local text = table.concat(parts, "\t")
    print(text)
    local console = game.read("ptr", "g_console")
    if console ~= 0 then
        pcall(game.call, "Console_Print", console, (text:gsub("%%", "%%%%")))
    end
end

local script_globals = setmetatable({print = script_print}, {__index = _ENV})

local function load_script(entry)
    if not loadscript then
        log_error("script " .. entry.script, "this client is too old to run map scripts: update it")
        return nil
    end
    local instance = new_instance(entry)
    local env = setmetatable({self = instance, boz = prefabs}, {__index = script_globals})
    instance._env = env
    local ok, chunk = pcall(loadscript, entry.script, env)
    if not ok then
        log_error("script " .. entry.script, chunk)
        return nil
    end
    local ran, err = pcall(chunk)
    if not ran then
        log_error("script " .. entry.script, err)
        return nil
    end
    bind(instance, env)
    return instance
end

--- Starts the level's objects (boz.world calls this when a level has started, with the map's
--- world_data objects, the names of all its objects and its weapons).
function prefabs.start(list, all_names, weapon_list)
    instances, volumes, names = {}, {}, {}
    power_was_on, downed, loading = false, false, false
    door_states = {}
    clock.timers, leaving = {}, {}
    for _, name in ipairs(all_names or {}) do
        names[hash.name(name)] = name
    end
    for k in pairs(prefabs.globals) do
        prefabs.globals[k] = nil
    end
    local weapon_names = {}
    for _, weapon in ipairs(weapon_list or {}) do
        table.insert(weapon_names, weapon.name)
        if weapon.display and weapon.display ~= "" then
            -- Wall buy prompts ask the game's text for "<weapon>_S_WEAPON" (UpdatePoiPrompt).
            text.add(weapon.name .. "_S_WEAPON", weapon.display)
        end
        if weapon.script and weapon.script ~= "" then
            instances[lower(weapon.name)] = load_script({name = weapon.name, kind = "weapon",
                                                         script = weapon.script,
                                                         properties = weapon.properties})
        end
    end
    weapons.know(weapon_names)
    for _, entry in ipairs(list or {}) do
        names[hash.name(entry.name)] = entry.name
        for _, member in ipairs(entry.members or {}) do
            names[hash.name(member)] = member
        end
        if entry.kind == "volume" then
            volumes[lower(entry.name)] = {name = entry.name, volume = entry.volume, who = entry.who,
                                          once = entry.once, prompt = entry.prompt or "",
                                          cost = entry.cost or 0, owner = entry.owner or "",
                                          script = entry.script or ""}
            watch_volume(entry)
        end
        if entry.script and entry.script ~= "" then
            instances[lower(entry.name)] = load_script(entry)
        end
    end
    bridge_game_events()
    local level = game.read("ptr", "CLevelManager::s_instance")
    starting.pending = level ~= 0 and game.read("u8", level + LEVEL_RESUMING) ~= 0
    starting.waited = 0
    if not starting.pending then
        run_start()
    end
end

return prefabs
