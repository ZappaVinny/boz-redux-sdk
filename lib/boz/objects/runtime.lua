-- The runtime behind boz.get and object scripts: makes every object of the map an object of its
-- class, runs scripts (each returns its class), routes volume, use and game events to them, and
-- saves boz.saved and objects' own fields with the game.
--
-- game: volumes are boz.objects events; uses are Poi_SendUse (caught for classes that change
-- on_use); a Use volume's prompt is shown from CIngameStatePlaying::UpdatePoiPrompt; saves are
-- CSaveManager::SaveGame (saved to the map mod's settings as globals.<level>).

local core = require("boz.engine.core")
local hash = require("boz.engine.hash")
local map = require("boz.engine.map")
local engine = require("boz.engine.objects")
local weapons = require("boz.engine.weapons")
local timers = require("boz.engine.timers")
local saved_store = require("boz.engine.saved")
local match_events = require("boz.engine.match_events")
local pieces = require("boz.engine.pieces")
local Object = require("boz.objects.object")
local Prefab = require("boz.objects.prefab")
local native = require("boz.objects.native")
local Weapon = require("boz.game.weapon")
local Player = require("boz.game.player")

local runtime = {}

local LOAD_WAIT = 20             -- seconds to wait for a save to load before starting anyway
local EXIT_DELAY = 0.25          -- seconds out of a Trigger volume before it counts as leaving
local POI_TRIGGER = hash.name("SUBJECT_POI_TRIGGER")

local function lower(name) return string.lower(name) end

local function log_error(where, err)
    log("boz: " .. where .. ": " .. tostring(err))
end

local Debris = require("boz.objects.debris")

local CLASSES = {Object = Object, Prefab = Prefab, Volume = require("boz.objects.volume"), Debris = Debris}
for name, class in pairs(native) do
    if name ~= "Native" then
        CLASSES[name] = class
    end
end

local objects = {}       -- lower name -> object (made on first boz.get, or at start)
local started = false    -- a level's objects are known
local entries = {}       -- lower name -> the map's entry for it (world_data objects)
local volumes = {}       -- lower volume name -> its entry
local by_hash = {}       -- name hash -> name
local listeners = {}     -- bus event -> {fn, ...}
local hooked = {}
local weapon_objects = {}

--- Values every script of the map shares, kept in saves.
runtime.saved = {}

--- The object called name, as its class (nil for a name the map does not have).
function runtime.get(name)
    if type(name) ~= "string" then
        return nil
    end
    local key = lower(name)
    local object = objects[key]
    if object then
        return object
    end
    if not started then
        -- A map script runs before any level: a stand-in its :on() listeners attach to by name.
        return Object:new(name)
    end
    local entry = entries[key]
    if not entry and not by_hash[hash.name(name)] then
        return nil
    end
    local class = CLASSES[entry and entry.class or "Object"] or Object
    object = class:new((entry and entry.name) or name, entry)
    objects[key] = object
    return object
end

--- A volume's entry by name (boz.Volume reads and changes it), or nil.
function runtime.volume(name)
    return volumes[lower(name)]
end

--- The object whose entity this is (a pointer), or nil.
function runtime.of_entity(entity)
    local name = entity and entity ~= 0 and by_hash[require("boz.engine.entities").name_hash(entity)]
    return name and runtime.get(name) or nil
end

--- Every object of a class (boz.Perk, ...).
function runtime.each(class)
    local out = {}
    for _, entry in pairs(entries) do
        local object = runtime.get(entry.name)
        if object and object:is_a(class) then
            out[#out + 1] = object
        end
    end
    table.sort(out, function(a, b) return a.name < b.name end)
    return out
end

local function notify(name, data)
    for _, fn in ipairs(listeners[name] or {}) do
        core.safely("boz.on " .. name, fn, data, name)
    end
end

--- Sends an event to every boz.on(name) listener and every object's on_event.
function runtime.send(name, data)
    notify(name, data)
    for _, object in pairs(objects) do
        if type(object.on_event) == "function" then
            core.safely(object.name .. ":on_event", object.on_event, object, name, data)
        end
    end
end

--- Calls fn(data, name) on every boz.send(name) and game event of that name ("round_started").
function runtime.on(name, fn)
    listeners[name] = listeners[name] or {}
    table.insert(listeners[name], fn)
    return fn
end

-- Who set a volume off: the player (a boz.Player) or the zombie's info table.
local function who_of(info)
    if info == nil or info.player then
        return runtime.player()
    end
    return info
end

--- You (the local player).
function runtime.player()
    runtime._player = runtime._player or Player:new()
    return runtime._player
end

--- Every player in the match.
function runtime.players()
    return {runtime.player()}
end

-- Volumes

local VOLUME_EVENTS = {trigger = {"enter", "exit"}, hit = {"hit"}, use = {"use"}}

local function allowed(entry, info)
    if entry.who == "zombies" then
        return info and info.zombie
    elseif entry.who == "anyone" then
        return true
    end
    return info == nil or info.player
end

local function pay(cost)
    if not cost or cost <= 0 then
        return true
    end
    local score = require("boz.engine.score")
    if not score.get() then
        return true
    end
    return score.spend(cost)
end

-- Trigger volumes report enter/exit again and again while something stands in them: count
-- what is inside; "exit" once it has been out for EXIT_DELAY seconds.
local leaving = {}

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
    local who = who_of(info)
    local volume = runtime.get(entry.name)
    local owner = entry.owner ~= "" and runtime.get(entry.owner) or nil
    if owner then
        owner:_emit(event, who, string.sub(entry.name, #entry.owner + 2))
    end
    if volume and volume ~= owner then
        volume:_emit(event, who)
    end
end

local function volume_event(event, handle, info)
    local entry = volumes[lower(handle.name)]
    if not entry or engine.is_hidden(entry.name) or not allowed(entry, info) then
        return
    end
    if info and info.zombie then      -- check_zombies has them
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
                    table.remove(leaving, i)
                    return
                end
            end
        else
            if inside(entry, entity, -1) == 0 then
                table.insert(leaving, {entry = entry, entity = entity, info = info, left = 0})
            end
            return
        end
    end
    fire_volume(event, entry, info)
end

-- Zombies have no body a volume can feel (theirs is for bullets), so the volumes they may set
-- off look for them. A zombie that dies inside leaves.
local ZOMBIE_CHECK = 0.1     -- seconds between looks
local ZOMBIE_CHEST = 100     -- centimetres above its feet: a volume in the air still sees it

local zombie_volumes, zombie_wait = {}, 0

local function zombies_alive()
    local alive = {}
    for zombie in require("boz.game.zombies").each("all") do
        if (zombie:health() or 0) > 0 then
            alive[zombie.entity] = zombie
        end
    end
    return alive
end

local function zombie_in(volume, zombie)
    local p = zombie:position()
    return p ~= nil and (volume:contains(p) or volume:contains({x = p.x, y = p.y + ZOMBIE_CHEST, z = p.z}))
end

local function check_zombies(dt)
    zombie_wait = zombie_wait - dt
    if zombie_wait > 0 or #zombie_volumes == 0 then
        return
    end
    zombie_wait = ZOMBIE_CHECK
    local alive = zombies_alive()
    for _, entry in ipairs(zombie_volumes) do
        local volume = engine.get(entry.name)
        local open = volume:exists() and not engine.is_hidden(entry.name)
        for entity, zombie in pairs(entry._zombies) do
            if not (open and alive[entity] and zombie_in(volume, zombie)) then
                entry._zombies[entity] = nil
                fire_volume("exit", entry, zombie)
            end
        end
        for entity, zombie in pairs(open and alive or {}) do
            if not entry._zombies[entity] and zombie_in(volume, zombie) then
                entry._zombies[entity] = zombie
                fire_volume("enter", entry, zombie)
            end
        end
    end
end

local function check_leaving(dt)
    for i = #leaving, 1, -1 do
        local pending = leaving[i]
        pending.left = pending.left + dt
        if pending.left >= EXIT_DELAY then
            table.remove(leaving, i)
            fire_volume("exit", pending.entry, pending.info)
        end
    end
end

local function watch_volume(entry)
    for _, event in ipairs(VOLUME_EVENTS[entry.volume] or {}) do
        local key = lower(entry.name) .. event
        if not hooked[key] then
            hooked[key] = true
            engine.on(entry.name, event, function(handle, info) volume_event(event, handle, info) end)
        end
    end
end

-- A Use volume's point of interest would show no prompt: its own is shown instead.
local function show_prompt(entity)
    if entity == 0 then
        return false
    end
    for _, entry in pairs(volumes) do
        if entry.volume == "use" and not (entry.once and entry._fired)
                and not engine.is_hidden(entry.name)
                and engine.get(entry.name):entity_pointer() == entity then
            local text = entry.prompt ~= "" and entry.prompt or "Use"
            if entry.cost and entry.cost > 0 then
                text = text .. " [Cost: " .. entry.cost .. "]"
            end
            local element = core.call("Poi_FindPromptElement")
            if element ~= 0 then
                core.call("Poi_ShowPrompt", element, require("boz.systems.text").cstring(text), 1, 1)
            end
            return true
        end
    end
    return false
end

-- Uses of the game's own prefabs: a class that changes on_use decides; others only tell their
-- listeners. pass_use lets the parent's on_use run the game's purchase without coming back here.
local passing = false
local REMEMBERED = {native.Perk, native.MysteryBox, native.PackAPunch, native.TrapSwitch,
                    native.WallBuy, native.Barricade}
local IN_USE = 3                 -- seconds
local USE_MEMORY = 20            -- seconds a use counts (a perk's drink, the box's spin)
local used = {}                  -- class -> {object, at}: what the player used last
local clock = 0

--- Runs fn (which uses a piece) without the use reaching scripts again.
function runtime.pass_use(fn)
    passing = true
    local ok, err = pcall(fn)
    passing = false
    if not ok then
        log_error("use", err)
    end
end

local function on_game_use(info)
    if pieces.trap_switch_busy(map.nearest_poi()) then
        info:skip()
        return
    end
    local object = runtime.of_entity(map.nearest_poi())
    if not object or not object:is_a(native.Native) then
        return
    end
    for _, class in ipairs(REMEMBERED) do
        if object:is_a(class) then
            used[class] = {object = object, at = clock}
        end
    end
    if passing then
        return
    end
    if object.on_use ~= native.Native.on_use then   -- its class changes what a use does
        info:skip()
        object:_emit("use", runtime.player())
    else
        object:_notify("use", runtime.player())
    end
end

-- Saves: boz.saved and each object's own fields (self.count = 3 is kept).
local function saved_key()
    local name = map.name()
    return name and "globals." .. name or nil
end

local function snapshot()
    local data = {objects = {}, saved = runtime.saved}
    for key, object in pairs(objects) do
        local fields = {}
        for k, v in pairs(object) do
            local t = type(v)
            if type(k) == "string" and k:sub(1, 1) ~= "_" and k ~= "name" and k ~= "settings"
                    and k ~= "entity" and (t == "number" or t == "string" or t == "boolean"
                    or t == "table") then
                fields[k] = v
            end
        end
        if next(fields) then
            data.objects[key] = fields
        end
    end
    return data
end

--- Writes the map's saved values now (the game's saves call this).
function runtime.save()
    local key = saved_key()
    if not key or not settings then
        return false
    end
    saved_store.write(key, snapshot())
    return true
end

local function restore(data)
    if not data then
        return
    end
    for k in pairs(runtime.saved) do
        runtime.saved[k] = nil
    end
    for k, v in pairs(data.saved or data.globals or {}) do
        runtime.saved[k] = v
    end
    for key, fields in pairs(data.objects or {}) do
        local object = runtime.get(key)
        if object then
            for k, v in pairs(fields) do
                object[k] = v
            end
        end
    end
end

local starting = {pending = false, waited = 0}

local function run_start()
    starting.pending = false
    Object._in_level = true
    for _, object in pairs(objects) do
        if type(object.start) == "function" then
            core.safely(object.name .. ":start", object.start, object)
        end
    end
    Object._in_level = false
end

local function save_loaded()
    if starting.pending then
        local key = saved_key()
        restore(key and settings and saved_store.read(key))
        run_start()
    end
end

-- The game's event does not say which machine sold the perk or spun the box: it is the one the
-- player used last. Nothing used lately (a script gave the perk): no machine hears of it.
local function just_used(class)
    local use = used[class]
    used[class] = nil
    return use and clock - use.at <= USE_MEMORY and use.object or nil
end

-- What the player used a moment ago: for what follows a use at once, and may not (no points).
local function in_use(class)
    local use = used[class]
    return use and clock - use.at <= IN_USE and use.object or nil
end

local function route(name, data)
    local player = runtime.player()
    if name == "door_opened" then
        local door = data and data.door and runtime.get(data.door)
        if door then
            door:_emit("opened", player)
            for _, other in ipairs(door:links("siblings")) do   -- debris it opens with
                if other:is_a(Debris) then other:open(player) end
            end
        end
    elseif name == "perk_bought" then
        local perk = just_used(native.Perk)
        if perk then perk:_emit("bought", player, data and data.perk) end
    elseif name == "box_weapon" then
        local box = just_used(native.MysteryBox)
        if box then
            box:_emit("spun", player)
            box:_emit("weapon", player, data and data.weapon)
        end
    elseif name == "points_spent" then
        local wall = in_use(native.WallBuy)
        if wall then
            used[native.WallBuy] = nil
            wall:_emit("bought", player, wall.settings.weapon)
        end
    elseif name == "barricade_repaired" then
        local barricade = in_use(native.Barricade)     -- stays: a hold repairs board after board
        if barricade then
            used[native.Barricade].at = clock
            barricade:_emit("repaired", player)
        end
    elseif name == "pack_a_punch" then
        local machine = just_used(native.PackAPunch)
        if machine then machine:_emit("upgraded", player, data and data.weapon) end
    elseif name == "power_on" then
        for _, switch in ipairs(runtime.each(native.PowerSwitch)) do
            switch:_emit("on", player)
        end
    elseif name == "trap_activated" then
        local switch = just_used(native.TrapSwitch)
        if switch then switch:_emit("activated", player) end
    elseif name == "trap_cooled" then
        local trap = data and data.trap and runtime.get(data.trap)
        if trap then
            trap:_emit("cooled")
            for _, switch in ipairs(trap:linked_from("traps")) do
                switch:_emit("cooled")
            end
        end
    end
end

local bridged = false

local function bridge()
    if bridged then
        return
    end
    bridged = true
    match_events.on_any(function(name, data)
        if name == "game_loaded" then
            save_loaded()
            return
        end
        core.safely("boz: " .. name, route, name, data)
        runtime.send(name, data)
    end)
    weapons.on_event(function(event, name, data)
        local object = weapon_objects[lower(name)]
        if object then
            object:_emit(({given = "given", equipped = "equip", fired = "fire",
                          reloaded = "reload"})[event] or event, data)
        end
    end)
    hook.add(core.sym("CSaveManager::SaveGame"), {before = function()
        core.safely("boz: save", runtime.save)
    end})
    hook.add(core.sym("Poi_SendUse"), {before = function(info)
        core.safely("boz: use", on_game_use, info)
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
        clock = clock + (dt or 0)
        check_leaving(dt or 0)
        check_zombies(dt or 0)
        if starting.pending then
            starting.waited = starting.waited + (dt or 0)
            if starting.waited > LOAD_WAIT then
                log_error("save", "the save did not load; starting without it")
                run_start()
            end
        end
    end)
end

-- print in a script: the mod's log and the game console.
local function script_print(...)
    local parts = {}
    for i = 1, select("#", ...) do
        parts[i] = tostring((select(i, ...)))
    end
    local text = table.concat(parts, "\t")
    print(text)
    require("boz.systems.console").print(text)
end

local script_globals = setmetatable({print = script_print}, {__index = _ENV})

-- A script returns its class (usually an extend() of the object's own class).
local function load_class(script)
    if not loadscript then
        log_error("script " .. script, "this client is too old to run map scripts: update it")
        return nil
    end
    local env = setmetatable({boz = require("boz")}, {__index = script_globals})
    local ok, chunk = pcall(loadscript, script, env)
    if not ok then
        log_error("script " .. script, chunk)
        return nil
    end
    local ran, class = pcall(chunk)
    if not ran then
        log_error("script " .. script, class)
        return nil
    end
    if type(class) ~= "table" or type(class.new) ~= "function" then
        log_error("script " .. script, "it must end with `return <its class>` (e.g. "
                  .. "local Door = boz.Door:extend() ... return Door)")
        return nil
    end
    return class
end

--- Starts the level's objects (boz.world calls this when a level starts: the map's objects,
--- the names of all of them and its weapons).
function runtime.start(list, all_names, weapon_list)
    objects, entries, volumes, leaving, weapon_objects, by_hash = {}, {}, {}, {}, {}, {}
    runtime._player = nil
    used, zombie_volumes = {}, {}
    started = true
    Object.forget_level_listeners()
    Object._in_level = true
    timers.cancel_all()
    for k in pairs(runtime.saved) do
        runtime.saved[k] = nil
    end
    for _, name in ipairs(all_names or {}) do
        by_hash[hash.name(name)] = name
    end
    match_events.know_names(all_names)
    local text = require("boz.systems.text")
    local weapon_names = {}
    for _, weapon in ipairs(weapon_list or {}) do
        table.insert(weapon_names, weapon.name)
        if weapon.display and weapon.display ~= "" then
            text.add(weapon.name .. "_S_WEAPON", weapon.display)
        end
        local class = Weapon
        if weapon.script and weapon.script ~= "" then
            class = load_class(weapon.script) or Weapon
        end
        weapon_objects[lower(weapon.name)] = class:new(weapon.name, weapon)
    end
    weapons.know(weapon_names)
    local member_names = {}
    for _, entry in ipairs(list or {}) do
        entries[lower(entry.name)] = entry
        by_hash[hash.name(entry.name)] = entry.name
        table.insert(member_names, entry.name)
        for _, member in ipairs(entry.members or {}) do
            table.insert(member_names, member)
        end
        if entry.kind == "volume" then
            volumes[lower(entry.name)] = {name = entry.name, volume = entry.volume, who = entry.who,
                                          once = entry.once, prompt = entry.prompt or "",
                                          cost = entry.cost or 0, owner = entry.owner or ""}
            watch_volume(entry)
            if entry.volume == "trigger" and entry.who ~= "players" then
                local volume = volumes[lower(entry.name)]
                volume._zombies = {}
                table.insert(zombie_volumes, volume)
            end
        end
        if entry.script and entry.script ~= "" then
            local class = load_class(entry.script)
            if class then
                objects[lower(entry.name)] = class:new(entry.name, entry)
            end
        end
    end
    match_events.know_names(member_names)
    -- A name the entity has in the game is another name of the world's object (PowerSwitch).
    local ok, data = pcall(require, "boz.world_data")
    for world_name, game_name in pairs(ok and type(data) == "table" and data.aliases or {}) do
        by_hash[hash.name(game_name)] = world_name
    end
    bridge()
    Object._in_level = false
    starting.pending = map.resuming()
    starting.waited = 0
    if not starting.pending then
        run_start()
    end
end

return runtime
