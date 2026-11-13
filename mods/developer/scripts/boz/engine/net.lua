-- boz.engine.net: scripts in co-op. Every game in a match that runs BOZ Redux talks to the others
-- through a network subject of its own (other games drop what is sent to it), on the game's own
-- connection: any server, LAN or online, carries it as part of the match.
--
-- The host decides. While shared scripts are on (every player runs BOZ Redux with the same
-- scripted mods: the handshake), a guest's use, hit and enter events go to the host, the host
-- runs the scripts, and what they change (shown, hidden, moved, lured, ended) is sent to every
-- game. Otherwise each game runs its scripts for itself, as in single player.
--
--   net.shared()           true while shared scripts are on
--   net.host()             true on the game that runs the match (single player too)
--   net.send(name, data)   data (numbers, strings, booleans, tables of them) to every other game
--   net.on(name, fn)       fn(data, from) for what the others send
--   net.route(op, ...)     the standard library's changes: see below
--
-- game: CIsNetworkSubject::CIsNetworkSubject, ::SetId, ::Notify, ::Dispatch

local net = {}

local core = require("boz.engine.core")

local PROTOCOL = 1
local ID_HIGH, ID_LOW = 0x626f7a21, 0x6e657431    -- "boz!" "net1": the subject other games address
local MAGIC = 11                  -- top four bits of every BOZ packet
local BEGIN, DATA = 1, 2
local MAX_BYTES = 8192
local HELLO_EVERY = 2.0          -- seconds between hellos until everyone has answered
local GIVE_UP = 12.0             -- seconds after the match starts: who has not answered lacks Redux
local POSITION_EVERY = 0.5       -- seconds between a game's player position reports

-- One channel per game: every mod carries its own standard library, they share this.
shared.boz_net = shared.boz_net or {handlers = {}, ops = {}, mods = {}, queue = {}, peers = {},
                                    partial = {}, context = {}}
local state = shared.boz_net

--- Adds this mod to what the handshake compares (mods with scripts must match in co-op).
function net.add_mod(id, version)
    if type(id) == "string" and not (state.private and state.private[id]) then
        state.mods[id] = tostring(version or "")
    end
end

--- Leaves this mod out of the handshake: a tool each player may or may not have (it changes
--- nothing the others see).
function net.private(id)
    if type(id) == "string" then
        state.mods[id] = nil
        state.private = state.private or {}
        state.private[id] = true
    end
end

local function mod_list()
    local out = {}
    for id, version in pairs(state.mods) do
        out[#out + 1] = id .. "@" .. version
    end
    table.sort(out)
    return table.concat(out, ",")
end

-- Values to bytes and back (string.pack): nil, booleans, numbers, strings and tables of them.
local function encode(value, out, depth)
    local kind = type(value)
    if kind == "nil" then
        out[#out + 1] = "n"
    elseif kind == "boolean" then
        out[#out + 1] = value and "T" or "F"
    elseif math.type(value) == "integer" then
        out[#out + 1] = string.pack("<c1j", "i", value)
    elseif kind == "number" then
        out[#out + 1] = string.pack("<c1d", "d", value)
    elseif kind == "string" then
        out[#out + 1] = string.pack("<c1s4", "s", value)
    elseif kind == "table" and depth < 8 then
        local count = 0
        for _ in pairs(value) do count = count + 1 end
        out[#out + 1] = string.pack("<c1I4", "t", count)
        for k, v in pairs(value) do
            encode(k, out, depth + 1)
            encode(v, out, depth + 1)
        end
    else
        out[#out + 1] = "n"      -- functions, objects: not sent
    end
end

local function decode(bytes, at, depth)
    local tag = bytes:sub(at, at)
    if tag == "n" then return nil, at + 1 end
    if tag == "T" then return true, at + 1 end
    if tag == "F" then return false, at + 1 end
    if tag == "i" then return string.unpack("<j", bytes, at + 1) end
    if tag == "d" then return string.unpack("<d", bytes, at + 1) end
    if tag == "s" then return string.unpack("<s4", bytes, at + 1) end
    if tag == "t" and depth < 8 then
        local count, next_at = string.unpack("<I4", bytes, at + 1)
        local out = {}
        for _ = 1, count do
            local k, v
            k, next_at = decode(bytes, next_at, depth + 1)
            v, next_at = decode(bytes, next_at, depth + 1)
            if k ~= nil then out[k] = v end
        end
        return out, next_at
    end
    error("boz.net: bad message")
end

local function event_of(kind, seq)
    return (MAGIC << 28) | ((state.tag & 0xfff) << 16) | ((kind & 0xf) << 12) | (seq & 0xfff)
end

-- Sends a message (to = a game's tag, or 0 for all of them).
local function send_raw(message, to)
    if not state.subject then
        return false
    end
    local parts = {}
    encode(message, parts, 0)
    local bytes = table.concat(parts)
    if #bytes > MAX_BYTES then
        log("boz.net: a message of " .. #bytes .. " bytes is too big (most " .. MAX_BYTES .. ")")
        return false
    end
    state.seq = ((state.seq or 0) + 1) & 0xfff
    local notify = core.sym("CIsNetworkSubject::Notify")
    game.call(notify, state.subject, event_of(BEGIN, state.seq), #bytes, to or 0)
    bytes = bytes .. string.rep("\0", (8 - #bytes % 8) % 8)
    for at = 1, #bytes, 8 do
        local a, b = string.unpack("<I4I4", bytes, at)
        game.call(notify, state.subject, event_of(DATA, state.seq), a, b)
    end
    return true
end

-- A packet arrived (on the game thread, inside the game's network update): reassembled, then
-- queued for the next frame.
local function received(event, a, b)
    if event >> 28 ~= MAGIC then
        return
    end
    local tag, kind, seq = (event >> 16) & 0xfff, (event >> 12) & 0xf, event & 0xfff
    if tag == state.tag then
        return                         -- our own, sent back to us
    end
    if kind == BEGIN then
        state.partial[tag] = {seq = seq, size = a, to = b, chunks = {}, have = 0}
    elseif kind == DATA then
        local part = state.partial[tag]
        if not part or part.seq ~= seq then
            return
        end
        part.chunks[#part.chunks + 1] = string.pack("<I4I4", a & 0xffffffff, b & 0xffffffff)
        part.have = part.have + 8
        if part.have >= part.size then
            state.partial[tag] = nil
            if part.to == 0 or part.to == state.tag then
                local bytes = table.concat(part.chunks):sub(1, part.size)
                local ok, message = pcall(decode, bytes, 1, 0)
                if ok and type(message) == "table" then
                    table.insert(state.queue, {message = message, from = tag})
                end
            end
        end
    end
end

-- The channel: made once per game, registered again each match (the game may clear it).
local function open()
    if not state.subject then
        local subject = game.alloc(core.size("CIsNetworkSubject") + 32)   -- with room to spare
        core.call("CIsNetworkSubject::CIsNetworkSubject", subject)
        state.subject = subject
        math.randomseed(os.time() + (require("boz.engine.player").name_hash() or 0))
        state.tag = math.random(1, 0xffe)
        hook.add(core.sym("CIsNetworkSubject::Dispatch"), {before = function(call)
            if call:arg(1) == state.subject then
                received(call:arg(2) & 0xffffffff, call:arg(3), call:arg(4))
            end
        end})
    end
    core.call("CIsNetworkSubject::SetId", state.subject, ID_HIGH, ID_LOW)
end

-- Other players and the handshake --------------------------------------------------------

-- Counted once per frame: the scan reads game memory and runs_logic asks often.
local counted_at, counted = nil, 0
local function others()
    local now = require("boz.engine.timers").now()
    if counted_at ~= now then
        counted_at, counted = now, #require("boz.engine.network").players()
    end
    return counted
end

--- True on the game that runs the match (single player too).
function net.host()
    local network = require("boz.engine.network")
    return others() == 0 or network.host()
end

--- True while shared scripts are on: every player in the match runs BOZ Redux with the same
--- scripted mods, so the host runs the scripts for everyone.
function net.shared()
    return state.shared == true
end

--- The other games that answered the handshake: tag -> {name, mods, position}.
function net.peers()
    return state.peers
end

--- This game's tag (what the others call it).
function net.tag()
    return state.tag
end

local function hello()
    send_raw({kind = "boz.hello", protocol = PROTOCOL, mods = mod_list(),
              name = require("boz.engine.player").name_hash() or 0}, 0)
end

local function decide(now)
    local count, missing = others(), {}
    local known = 0
    for _, peer in pairs(state.peers) do
        known = known + 1
        if peer.protocol ~= PROTOCOL then
            missing[#missing + 1] = "a player has another BOZ Redux version"
        elseif peer.mods ~= mod_list() then
            local theirs, mine = {}, {}
            for item in string.gmatch(peer.mods, "[^,]+") do theirs[item] = true end
            for item in string.gmatch(mod_list(), "[^,]+") do mine[item] = true end
            local lacks, extra = {}, {}
            for item in pairs(mine) do if not theirs[item] then lacks[#lacks + 1] = item end end
            for item in pairs(theirs) do if not mine[item] then extra[#extra + 1] = item end end
            table.sort(lacks)
            table.sort(extra)
            missing[#missing + 1] = "a player " .. table.concat({
                #lacks > 0 and ("lacks " .. table.concat(lacks, ", ")) or nil,
                #extra > 0 and ("has " .. table.concat(extra, ", ") .. " that this game lacks") or nil}, " and ")
        end
    end
    if known >= count and #missing == 0 and count > 0 then
        if not state.shared then
            state.shared = true
            log("boz.net: shared scripts on (" .. count + 1 .. " players, the host runs them)")
        end
        return
    end
    if now - state.started > GIVE_UP and not state.decided then
        state.decided = true
        if known < count then
            missing[#missing + 1] = (count - known) .. " player(s) without BOZ Redux"
        end
        local text = "Shared scripts are off: " .. table.concat(missing, "; ")
        log("boz.net: " .. text .. ". Each game runs its scripts for itself.")
        if net.host() then
            pcall(function() require("boz.systems.hud").message(text, 6) end)
        end
    end
end

local function handle(item)
    local message, from = item.message, item.from
    if message.kind == "boz.hello" then
        local peer = state.peers[from]
        state.peers[from] = {protocol = message.protocol, mods = message.mods, name = message.name,
                             position = peer and peer.position}
        if not peer then
            hello()                    -- a new player: tell it about us
        end
        return
    end
    if message.kind == "boz.where" then
        local peer = state.peers[from]
        if peer then peer.position = message.position end
        return
    end
    if message.kind == "boz.op" or message.kind == "boz.request" then
        if message.kind == "boz.request" and not net.host() then
            return
        end
        net.apply(message.op, message.args or {}, from, message.kind == "boz.request")
        return
    end
    for _, fn in ipairs(state.handlers[message.kind] or {}) do
        core.safely("boz.net " .. tostring(message.kind), fn, message.data, from)
    end
end

local function tick()
    if not require("boz.engine.map").player() then
        if state.in_match then          -- the match ended: start over next time
            state.in_match, state.shared, state.decided, state.peers = false, false, false, {}
        end
        return
    end
    local now = require("boz.engine.timers").now()
    if not state.in_match then
        state.in_match, state.started, state.next_hello, state.next_where = true, now, 0, 0
    end
    if others() == 0 then
        return                           -- single player: nothing to share
    end
    open()
    while #state.queue > 0 do
        handle(table.remove(state.queue, 1))
    end
    if not state.shared and now >= state.next_hello then
        state.next_hello = now + HELLO_EVERY
        hello()
    end
    if state.shared and now >= state.next_where then
        state.next_where = now + POSITION_EVERY
        send_raw({kind = "boz.where", position = require("boz.engine.player").position()}, 0)
    end
    decide(now)
end

--- Starts watching for co-op matches (the standard library does, once per game).
function net.start()
    if state.started_ticking then
        return
    end
    state.started_ticking = true
    -- Key bindings are a player's own input: in co-op a guest's go to the host.
    local bind = input.bind
    input.bind = function(key, fn)
        if type(fn) ~= "function" then
            return bind(key, fn)
        end
        return bind(key, function(...) return net.as_input(fn, ...) end)
    end
    events.on("frame", function() core.safely("boz.net", tick) end)
end

--- Sends data to every other game (shared scripts or not): their net.on(name) handlers get it.
function net.send(name, data, to)
    return send_raw({kind = name, data = data}, to or 0)
end

--- Calls fn(data, from) when another game sends name.
function net.on(name, fn)
    state.handlers[name] = state.handlers[name] or {}
    table.insert(state.handlers[name], fn)
end

-- Routing the standard library's changes --------------------------------------------------

--- An operation the standard library replays on other games: fn(args, from); knows(args) says
--- whether this copy of the library can apply it (the map's objects live in the map's copy).
function net.op(name, fn, knows)
    -- By default the copy that runs the map applies it (it knows the map's effects, sounds, ...).
    knows = knows or function() return require("boz.objects.runtime").running_map() end
    state.ops[name] = state.ops[name] or {}
    table.insert(state.ops[name], {fn = fn, knows = knows})
end

local function context(key)
    return state.context[key]
end

--- Runs fn with this game's own changes (no sharing): what one player alone should see.
function net.local_only(fn, ...)
    local saved = state.context.local_only
    state.context.local_only = true
    local results = table.pack(pcall(fn, ...))
    state.context.local_only = saved
    if not results[1] then
        error(results[2], 2)
    end
    return table.unpack(results, 2, results.n)
end

--- Runs fn as this player's own input (a key binding): a guest's changes go to the host.
function net.as_input(fn, ...)
    local saved = state.context.input
    state.context.input = true
    local results = table.pack(pcall(fn, ...))
    state.context.input = saved
    if not results[1] then
        error(results[2], 2)
    end
    return table.unpack(results, 2, results.n)
end

--- Applies an operation from another game (or the host's answer to a request).
function net.apply(op, args, from, request)
    local list = state.ops[op]
    if not list then
        return
    end
    local chosen = list[1]
    for _, entry in ipairs(list) do
        if entry.knows and entry.knows(args) then
            chosen = entry
            break
        end
    end
    local saved = state.context.remote
    state.context.remote = not request      -- a request runs on the host as its own change
    state.context.from = from
    core.safely("boz.net " .. op, chosen.fn, args, from)
    state.context.remote, state.context.from = saved, nil
end

--- What a change of the standard library should do now: "apply" here (and, on the host, also
--- sent to every game), or "skip" (a guest: the host runs the same scripts and sends it; or
--- its player's own input, sent to the host as a request). host_only: only the host applies it
--- (zombies, lures: the host runs them), nothing is sent to the guests.
function net.route(op, args, host_only)
    if not state.shared or context("local_only") or context("remote") then
        return "apply"
    end
    if net.host() then
        if not host_only then
            send_raw({kind = "boz.op", op = op, args = args}, 0)
        end
        return "apply"
    end
    if context("input") then
        send_raw({kind = "boz.request", op = op, args = args}, 0)
    end
    return "skip"
end

--- A guest's own event (its player used, shot or walked into something): sent to the host, whose
--- scripts run it as that player's.
function net.request(op, args)
    if state.shared and not net.host() then
        send_raw({kind = "boz.request", op = op, args = args}, 0)
    end
end

--- Runs an operation on one other game (tag): what a script does to that game's player.
function net.tell(tag, op, args)
    return send_raw({kind = "boz.op", op = op, args = args}, tag)
end

--- True while scripts run on this game for everyone (the host, or no sharing): guests leave
--- game-logic events to the host.
function net.runs_logic()
    return not state.shared or net.host() or context("local_only")
end

--- What one game shows (a message, a sound): this player's own input and boz.local stay on
--- this screen; the host's scripts show it to everyone; a guest's scripts leave it to the host.
--- Returns "apply" or "skip" like route.
function net.route_view(op, args)
    if not state.shared or context("local_only") or context("remote") or context("input") then
        return "apply"
    end
    if net.host() then
        send_raw({kind = "boz.op", op = op, args = args}, 0)
        return "apply"
    end
    return "skip"
end

--- The game (tag) whose request is being applied, or nil.
function net.from()
    return state.context.from
end

return net
