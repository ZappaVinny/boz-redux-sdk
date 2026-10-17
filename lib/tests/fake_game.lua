-- A fake game for the standard library's tests: the client's game, hook and events APIs over a
-- table of memory. Every symbol name gets a made-up address; functions are Lua functions keyed by
-- symbol name (or address).
--
--   package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
--   local fake = require("fake_game").install({strict = true})
--   fake.functions["Spawn_ByHash"] = function(manager, hash, ...) return 0x5000 end
--   fake.run_hook("CHealth::Damage", {health, 100, 0})

local fake = {memory = {}, strings = {}, symbols = {}, functions = {}, hooks = {}, calls = {}, frames = {}}

local next_symbol, next_alloc = 0x1000, 0x900000

function fake.address(name)
    if not fake.symbols[name] then
        next_symbol = next_symbol + 0x10
        fake.symbols[name] = next_symbol
    end
    return fake.symbols[name]
end

local function name_at(target)
    for name, at in pairs(fake.symbols) do
        if at == target then
            return name
        end
    end
    return nil
end

--- Installs the fake as the globals game, hook, events, log and settings. Options: strict (a
--- call to a function without a fake errors; otherwise it returns 0), signed (results at or above
--- 0x80000000 come back negative, as the real game.call returns them).
function fake.install(options)
    options = options or {}
    local memory, strings = fake.memory, fake.strings
    game = {
        base = function() return 0x4a000000 end,
        symbol = fake.address,
        read = function(kind, at)
            if type(at) == "string" then
                at = fake.address(at)
            end
            if kind == "string" then
                return strings[at] or memory[at] or ""
            end
            return memory[at] or 0
        end,
        write = function(_, at, value) memory[at] = value end,
        alloc = function(size)
            next_alloc = next_alloc + (size or 0) + 16
            return next_alloc
        end,
        free = function() end,
        call = function(target, ...)
            if type(target) == "string" then
                target = fake.address(target)
            end
            local name = name_at(target)
            local fn = fake.functions[name] or fake.functions[target]
            table.insert(fake.calls, {name or target, ...})
            if not fn then
                if options.strict then
                    error("unexpected call " .. tostring(name or target))
                end
                return 0
            end
            local result = fn(...)
            if options.signed and type(result) == "number" and result >= 0x80000000 then
                result = result - 0x100000000
            end
            return result
        end,
    }
    hook = {
        add = function(target, handlers)
            fake.hooks[target] = fake.hooks[target] or {}
            table.insert(fake.hooks[target], handlers)
            return target
        end,
        remove = function() end,
        float_bits = function(x) return string.unpack("<I4", string.pack("<f", x)) end,
    }
    events = {on = function(name, fn) if name == "frame" then table.insert(fake.frames, fn) end end,
              off = function() end}
    log = function(message) print("log: " .. message) end
    settings = settings or {get = function(_, default) return default end, set = function() end}
    return fake
end

--- Runs the hooks on a function as the client would: `args` are its arguments, `when` "before"
--- (default) or "after". Returns true when a handler skipped the function.
function fake.run_hook(name, args, when)
    local skipped = false
    for _, handlers in ipairs(fake.hooks[fake.address(name)] or {}) do
        local fn = handlers[when or "before"]
        if fn then
            fn({arg = function(_, i) return args[i] or 0 end,
                arg_signed = function(_, i) return args[i] or 0 end,
                set_arg = function(_, i, value) args[i] = value end,
                skip = function() skipped = true end})
        end
    end
    return skipped
end

--- Runs the frame handlers once.
function fake.frame(dt)
    for _, fn in ipairs(fake.frames) do
        fn(dt or 0.016)
    end
end

--- The calls made to a function, oldest first.
function fake.called(name)
    local out = {}
    for _, c in ipairs(fake.calls) do
        if c[1] == name then
            table.insert(out, c)
        end
    end
    return out
end

--- The last call made to a function, or nil.
function fake.last(name)
    local list = fake.called(name)
    return list[#list]
end

function fake.check(condition, message)
    if not condition then
        error("FAILED: " .. message, 2)
    end
end

return fake
