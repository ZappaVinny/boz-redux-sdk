-- boz.timers: run code later, on game time (paused time does not count).
--
--   local timers = require("boz.timers")
--   local t = timers.after(5, function() log("five seconds of play later") end)
--   timers.every(1, function() log("tick") end)
--   t:cancel()
--
-- How it works: game time advances by one simulation step (1/30 s) every time the physics world
-- steps (CIsBulletWorld::FixedStep: the game simulates at a fixed 30 steps a second whatever the
-- frame rate, and not at all while paused); timers run from the frame event. Counting a frame's
-- time only in frames that stepped lost the frames the client draws between steps, so timers ran
-- slower the higher the frame rate. The clock starts when the module loads, not with the first
-- timer, which can be made inside a game callback (a volume's on_enter).

local timers = {}

local core = require("boz.core")

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

local function add(seconds, interval, fn)
    assert(type(fn) == "function", "boz timers need a function")
    start()
    local timer = setmetatable({due = clock.now + seconds, interval = interval, fn = fn}, Timer)
    table.insert(clock.list, timer)
    return timer
end

start()

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
