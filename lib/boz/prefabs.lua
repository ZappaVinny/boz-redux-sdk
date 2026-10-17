-- boz.prefabs: scripts for the map's prefabs, models, volumes and weapons, and the event bus
-- between them. Map scripts see this module as `boz`; docs/map-editor.md (Map scripting) is the guide.
--
--   function on_hit(volume, info)              -- in a script attached to a prefab
--       self:part("Door"):hide():set_collision(false):open_navmesh()
--       boz.send("vault_open", {by = self.name})
--   end
--
-- Each scripted object runs its script once with its own `self` and top-level variables. Script
-- globals and boz.globals are saved with the game. Handlers: start(), on_enter / on_exit /
-- on_hit / on_use(volume, info), on_event(name, data) (boz.send and boz.match_events' events;
-- "weapon_fired" only reaches boz.on); weapon scripts: on_given, on_equip, on_fire(data),
-- on_reload. Every volume event also reaches boz.on listeners as "<volume>.<event>".
--
-- How it works: the client's loadscript(name, env) loads a script with a fresh environment per
-- object (self and boz in it, the mod's globals behind it). Volumes are boz.objects events. Use
-- prompts: when a Use volume becomes the point of interest in reach (SUBJECT_POI_TRIGGER, handled
-- by CIngameStatePlaying::UpdatePoiPrompt, whose handling is skipped for it) its prompt is shown
-- with Poi_ShowPrompt. Saving: CSaveManager::SaveGame (autosave at each round start, pause) writes
-- the globals to the map mod's settings (globals.<level>); a level started from a save
-- (boz.map.resuming) runs start() once the save is applied. Hooks here are before hooks where
-- they can be: an after hook's return trap on a long, busy function crashed the game.

local core = require("boz.core")
local hash = require("boz.hash")
local map = require("boz.map")
local objects = require("boz.objects")
local weapons = require("boz.weapons")
local timers = require("boz.timers")
local saved = require("boz.saved")
local match_events = require("boz.match_events")

local prefabs = {}

local LOAD_WAIT = 20             -- seconds to wait for a save to load before starting anyway
local EXIT_DELAY = 0.25          -- seconds out of a Trigger volume before it counts as leaving
local POI_TRIGGER = hash.name("SUBJECT_POI_TRIGGER")

local function lower(name)
    return string.lower(name)
end

local function log_error(where, err)
    log("boz.prefabs: " .. where .. ": " .. tostring(err))
end

local Instance = {}
Instance.__index = Instance

local instances = {}     -- lower name -> instance
local volumes = {}       -- lower volume name -> its world_data entry
local listeners = {}     -- event name -> {fn, ...}
local hooked = {}        -- lower volume name .. event -> true

--- Values every script of the map shares, saved with the game.
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

--- Shows the object. Returns self.
function Instance:show() return self:set_visible(true) end
--- Hides the object. Returns self.
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

--- Lets zombies and players walk where the object blocked them. Returns self.
function Instance:open_navmesh() return self:set_navmesh(true) end
--- Blocks the walkable area under the object again. Returns self.
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
    core.safely("boz.prefabs: " .. instance.name .. ":" .. handler, fn, instance, ...)
end

--- The scripted object called *name* (its script instance), else its boz.objects handle when it
--- exists in the level, else nil.
function prefabs.find(name)
    return instances[lower(name)] or objects.find(name)
end

local function notify_listeners(name, data)
    for _, fn in ipairs(listeners[name] or {}) do
        core.safely("boz.prefabs: listener of " .. name, fn, data, name)
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

--- Runs fn() once, `seconds` of game time from now (boz.timers). Returns a timer with :cancel().
function prefabs.after(seconds, fn)
    return timers.after(seconds, fn)
end

--- Runs fn() every `seconds` of game time until the timer is cancelled (boz.timers).
function prefabs.every(seconds, fn)
    return timers.every(seconds, fn)
end

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

local function pay(cost)
    if not cost or cost <= 0 then
        return true
    end
    local score = require("boz.score")
    if not score.get() then
        log_error("use cost", "no score manager: the cost is not taken")
        return true
    end
    return score.spend(cost)
end

-- The game's collision reports enter/exit again and again while something stands in a ghost box
-- (and once per collision shape), so each Trigger volume counts what is inside: "enter" when
-- something comes in, "exit" once it has been out for EXIT_DELAY seconds.
local leaving = {}       -- {entry, entity, info, left} waiting to become "exit"

local function inside(entry, entity, delta)
    entry._inside = entry._inside or {}
    local count = math.max((entry._inside[entity] or 0) + delta, 0)
    entry._inside[entity] = count > 0 and count or nil
    return count
end

local function fire_volume(event, entry, info)
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
    notify_listeners(entry.name .. "." .. event, info)
end

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

local function watch_volume(entry)
    for _, event in ipairs(VOLUME_EVENTS[entry.volume] or {}) do
        local key = lower(entry.name) .. event
        if not hooked[key] then
            hooked[key] = true
            objects.on(entry.name, event, function(object, info) volume_event(event, object, info) end)
        end
    end
end

-- A Use volume's point of interest has a barricade's type but no barricade, so the game would
-- leave its prompt hidden: the volume's own prompt is shown instead.

local function prompt_of(entry)
    local text = entry.prompt ~= "" and entry.prompt or "Use"
    if entry.cost and entry.cost > 0 then
        text = text .. " [Cost: " .. entry.cost .. "]"
    end
    return text
end

local function show_prompt(entity)
    if entity == 0 then
        return false
    end
    for _, entry in pairs(volumes) do
        if entry.volume == "use" and not (entry.once and entry._fired)
                and objects.get(entry.name):entity_pointer() == entity then
            local element = core.call("Poi_FindPromptElement")
            if element ~= 0 then
                core.call("Poi_ShowPrompt", element, require("boz.text").cstring(prompt_of(entry)), 1, 1)
            end
            return true
        end
    end
    return false
end

-- Saved globals: each scripted object's global variables and prefabs.globals.

local function saved_key()
    local name = map.name()
    return name and "globals." .. name or nil
end

local function snapshot()
    local data = {objects = {}, globals = prefabs.globals}
    for _, instance in pairs(instances) do
        local vars = {}
        for k, v in pairs(instance._env or {}) do
            if type(k) == "string" and k ~= "self" and k ~= "boz" and type(v) ~= "function" then
                vars[k] = v
            end
        end
        data.objects[instance.name] = vars
    end
    return data
end

--- Writes the map's saved globals now (the game's saves call this).
function prefabs.save()
    local key = saved_key()
    if not key or not settings then
        return false
    end
    saved.write(key, snapshot())
    return true
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

-- start() runs at once in a new game; continuing a save, after the save is applied.
local starting = {pending = false, waited = 0}

local function run_start()
    starting.pending = false
    for _, instance in pairs(instances) do
        call(instance, "start")
    end
end

local function save_loaded()
    if starting.pending then
        local key = saved_key()
        restore(key and settings and saved.read(key))
        run_start()
    end
end

local WEAPON_HANDLERS = {given = "on_given", equipped = "on_equip", fired = "on_fire", reloaded = "on_reload"}

local bridged = false

local function bridge()
    if bridged then
        return
    end
    bridged = true
    match_events.on_any(function(name, data)
        if name == "game_loaded" then
            save_loaded()
        elseif name == "weapon_fired" then
            notify_listeners(name, data)
        else
            prefabs.send(name, data)
        end
    end)
    weapons.on_event(function(event, name, data)
        local instance = instances[lower(name)]
        if instance and instance.kind == "weapon" then
            call(instance, WEAPON_HANDLERS[event], data)
        end
    end)
    hook.add(core.sym("CSaveManager::SaveGame"), {before = function()
        core.safely("boz.prefabs: save", prefabs.save)
    end})
    hook.add(core.sym("CIngameStatePlaying::UpdatePoiPrompt"), {before = function(info)
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
    events.on("frame", function(dt)
        check_leaving(dt or 0)
        if starting.pending then
            starting.waited = starting.waited + (dt or 0)
            if starting.waited > LOAD_WAIT then
                log_error("save", "the save did not load; starting without it")
                run_start()
            end
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

-- Every function the script defines becomes a method of its object, called without self (self
-- is in the script's environment): handlers, and functions other scripts call.
local function bind(instance, env)
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
    require("boz.console").print(text)
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
    instances, volumes, leaving = {}, {}, {}
    timers.cancel_all()
    match_events.know_names(all_names)
    for k in pairs(prefabs.globals) do
        prefabs.globals[k] = nil
    end
    local text = require("boz.text")
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
    local member_names = {}
    for _, entry in ipairs(list or {}) do
        table.insert(member_names, entry.name)
        for _, member in ipairs(entry.members or {}) do
            table.insert(member_names, member)
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
    match_events.know_names(member_names)
    bridge()
    starting.pending = map.resuming()
    starting.waited = 0
    if not starting.pending then
        run_start()
    end
end

return prefabs
