-- boz.engine.timers: run code later, on game time (paused time does not count).
--
--   local timers = require("boz.engine.timers")
--   local t = timers.after(5, function() log("five seconds of play later") end)
--   timers.every(1, function() log("tick") end)
--   t:cancel()
--
-- game: CIsBulletWorld::FixedStep

local timers = {}

local core = require("boz.engine.core")

local STEP = 1 / 30   -- seconds of game time per simulation step (the physics step's timeStep)

local clock = {now = 0, list = {}, running = false}

local Timer = {}
Timer.__index = Timer

--- Stops the timer.
function Timer:cancel()
    self.cancelled = true
end

local function run()
    local due = {}
    for _, timer in ipairs(clock.list) do
        if not timer.cancelled and timer.due <= clock.now then
            table.insert(due, timer)
        end
    end
    for _, timer in ipairs(due) do
        core.safely("boz.timers", timer.fn)
        if timer.interval and not timer.cancelled then
            timer.due = timer.due + timer.interval
        else
            timer.cancelled = true
        end
    end
    if #due > 0 then
        local kept = {}
        for _, timer in ipairs(clock.list) do
            if not timer.cancelled then
                table.insert(kept, timer)
            end
        end
        clock.list = kept
    end
end

local function start()
    if clock.running then
        return
    end
    clock.running = true
    -- The player's step is the fallback for a client whose game definition lacks the physics step.
    local at = core.sym("CIsBulletWorld::FixedStep") or core.sym("CPlayerController::FixedStep")
    hook.add(at, {before = function() clock.now = clock.now + STEP end})
    events.on("frame", run)
end

local function add(seconds, interval, fn, what)
    local check = require("boz.engine.check")
    seconds = check.number(seconds, what, 2)
    if not seconds or not check.fn(fn, what, 2) then
        return setmetatable({cancelled = true}, Timer)   -- nothing runs; :cancel() still works
    end
    start()
    local timer = setmetatable({due = clock.now + seconds, interval = interval, fn = fn}, Timer)
    table.insert(clock.list, timer)
    return timer
end

start()

--- Runs fn() once, `seconds` of game time from now. Returns a timer with :cancel().
function timers.after(seconds, fn)
    return add(seconds, nil, fn, "boz.after")
end

--- Runs fn() every `seconds` of game time until the timer is cancelled. Returns the timer.
function timers.every(seconds, fn)
    local n = tonumber(seconds)
    if n and n <= 0 then
        require("boz.engine.check").warn("boz.every needs more than 0 seconds, got " .. n, 2)
        return setmetatable({cancelled = true}, Timer)
    end
    return add(seconds, seconds, fn, "boz.every")
end

--- Seconds of game time since the first timer was made.
function timers.now()
    return clock.now
end

--- Cancels every timer (a new level starts fresh).
function timers.cancel_all()
    for _, timer in ipairs(clock.list) do
        timer.cancelled = true
    end
    clock.list = {}
end

return timers
