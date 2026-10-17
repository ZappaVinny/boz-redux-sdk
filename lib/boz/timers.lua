-- boz.timers: run code later, on game time (paused time does not count).
--
--   local timers = require("boz.timers")
--   local t = timers.after(5, function() log("five seconds of play later") end)
--   timers.every(1, function() log("tick") end)
--   t:cancel()
--
-- How it works: game time advances by the frame's time in frames where
-- CPlayerController::FixedStep ran (the game's simulation step, which stops while paused).

local timers = {}

local core = require("boz.core")

local clock = {now = 0, stepped = false, list = {}, running = false}

local Timer = {}
Timer.__index = Timer

--- Stops the timer.
function Timer:cancel()
    self.cancelled = true
end

local function run(dt)
    if clock.stepped then
        clock.now = clock.now + (dt or 0)
    end
    clock.stepped = false
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
    hook.add(core.sym("CPlayerController::FixedStep"), {before = function() clock.stepped = true end})
    events.on("frame", run)
end

local function add(seconds, interval, fn)
    assert(type(fn) == "function", "boz timers need a function")
    start()
    local timer = setmetatable({due = clock.now + seconds, interval = interval, fn = fn}, Timer)
    table.insert(clock.list, timer)
    return timer
end

--- Runs fn() once, `seconds` of game time from now. Returns a timer with :cancel().
function timers.after(seconds, fn)
    return add(seconds, nil, fn)
end

--- Runs fn() every `seconds` of game time until the timer is cancelled. Returns the timer.
function timers.every(seconds, fn)
    assert(seconds > 0, "boz timers need a positive interval")
    return add(seconds, seconds, fn)
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
