-- boz.game_events: every event the game sends itself (its SUBJECT_* observer events).
--
--   local game_events = require("boz.game_events")
--   game_events.on("SUBJECT_ZOMBIE_DEATH", function(e) log("a zombie died") end)
--   game_events.on("power_switch_on", function(e) ... end)      -- the SUBJECT_ prefix is optional
--   game_events.send(subject, "SUBJECT_NUKE_NOW")               -- send one yourself
--
-- Handlers get {name, id, subject, sender, a, b}: the subject that sent it (a CIsSubject inside
-- a manager or component), the object it is on behalf of, and the event's two arguments (their
-- meaning is per event: docs/game-events.md). A handler that returns true stops the event (no
-- observer gets it): use with care.
--
-- How it works: every event passes through CIsSubject::Dispatch(subject, event, a, b, sender),
-- which calls the observers subscribed to it; this hooks Dispatch while anything listens (a hook
-- costs nothing while no handler is set). Names: boz/event_names.lua (the game definition's 337
-- events); ids are the name's IwHashString.

local game_events = {}

local hash = require("boz.hash")

local DISPATCH = 0x0c1194 + 1           -- CIsSubject::Dispatch (Thumb), for older game definitions
local NOTIFY_VIRTUAL = 0x0c12f8 + 1     -- CIsSubject::NotifyVirtual

local names_by_id = nil
local listeners = {}        -- id -> {fn = true}; 0 -> every event
local count = 0
local hook_handle = nil

local function load_names()
    if names_by_id == nil then
        names_by_id = {}
        local ok, list = pcall(require, "boz.event_names")
        for _, name in ipairs(ok and list or {}) do
            names_by_id[hash.name(name)] = name
        end
    end
    return names_by_id
end

--- The id of an event name ("SUBJECT_ZOMBIE_DEATH", or without the SUBJECT_ prefix).
function game_events.id(name)
    if type(name) == "number" then
        return name
    end
    local upper = string.upper(name)
    if not upper:find("^SUBJECT_") and not upper:find("^NETWORK_") and not load_names()[hash.name(upper)] then
        upper = "SUBJECT_" .. upper
    end
    return hash.name(upper)
end

--- The name of an event id, or its id as "0x..." when the game definition does not name it.
function game_events.name(id)
    return load_names()[id] or string.format("0x%08x", id)
end

--- Every event name the library knows, sorted.
function game_events.list()
    local out = {}
    for _, name in pairs(load_names()) do
        table.insert(out, name)
    end
    table.sort(out)
    return out
end

local function on_dispatch(call)
    local id = call:arg(2)
    local wanted, every = listeners[id], listeners[0]
    if not wanted and not every then
        return
    end
    local event = {name = game_events.name(id), id = id, subject = call:arg(1), a = call:arg(3),
                   b = call:arg(4), sender = call:arg(5)}
    for _, set in ipairs({wanted or {}, every or {}}) do
        for fn in pairs(set) do
            if fn(event) == true then
                call:skip()
                return
            end
        end
    end
end

local function ensure_hook()
    if hook_handle == nil and count > 0 then
        hook_handle = hook.add(game.symbol("CIsSubject::Dispatch") or (game.base() + DISPATCH),
                               {before = on_dispatch})
    elseif hook_handle ~= nil and count == 0 then
        hook.remove(hook_handle)
        hook_handle = nil
    end
end

--- Calls fn(event) every time the game sends the event (a name, or "*" for every event: slow,
--- for exploring). Returns a handle for off().
function game_events.on(name, fn)
    local id = name == "*" and 0 or game_events.id(name)
    listeners[id] = listeners[id] or {}
    listeners[id][fn] = true
    count = count + 1
    ensure_hook()
    return {id = id, fn = fn}
end

--- Stops a handler on() returned.
function game_events.off(handle)
    local set = handle and listeners[handle.id]
    if set and set[handle.fn] then
        set[handle.fn] = nil
        count = count - 1
        if next(set) == nil then
            listeners[handle.id] = nil
        end
        ensure_hook()
    end
end

--- Sends an event from a subject (a CIsSubject address: a manager's or component's subject)
--- with its two arguments, the way the game does (CIsSubject::NotifyVirtual).
function game_events.send(subject, name, a, b, c)
    if not subject or subject == 0 then
        return false
    end
    game.call(game.symbol("CIsSubject::NotifyVirtual") or (game.base() + NOTIFY_VIRTUAL),
              subject, game_events.id(name), a or 0, b or 0, c or 0)
    return true
end

return game_events
