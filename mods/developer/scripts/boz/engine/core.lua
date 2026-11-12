-- boz.engine.core: internals the standard library's modules share. Mods use the modules instead.

local core = {}

local symbols = require("boz.engine.symbol_data")

--- The address of a game function or global by its gamedef name, or nil. Names the client's
--- own game definition does not know yet come from boz.symbol_data.
function core.sym(name)
    local address = game.symbol(name)
    if address then
        return address
    end
    local offset = symbols.functions[name] or symbols.globals[name]
    return offset and game.base() + offset or nil
end

--- A field's byte offset in a game struct, by its gamedef name: core.offset("CLevelManager",
--- "player"). The game definition's structs first, then the reflected fields (with bases).
--- An unknown name is an error: it is the library's bug, found when the module loads.
function core.offset(struct, field)
    local known = symbols.structs and symbols.structs[struct]
    if known and known[field] then
        return known[field]
    end
    local reflection = require("boz.engine.reflection_data")
    local function find(name, base)
        local info = reflection[name]
        if not info then
            return nil
        end
        local f = info.fields[field]
        if f then
            return base + f[1]
        end
        for _, b in ipairs(info.bases) do
            local at = find(b[1], base + b[2])
            if at then
                return at
            end
        end
        return nil
    end
    local at = find(struct, 0)
    if not at then
        error("boz: the game definition has no field " .. struct .. "." .. field, 2)
    end
    return at
end

--- A game struct's size in bytes (gamedef), for buffers passed to the game.
function core.size(struct)
    local known = symbols.structs and symbols.structs[struct]
    if not known or not known._size then
        error("boz: the game definition has no size for " .. struct, 2)
    end
    return known._size
end

--- A singleton's instance ("CWaveManager"), or nil while the game has none.
function core.singleton(class_name)
    local at = core.sym(class_name .. "::s_instance")
    local instance = at and game.read("ptr", at) or 0
    return instance ~= 0 and instance or nil
end

-- game.call returns signed numbers, game.read("u32") unsigned ones, and heap addresses are often
-- above 0x80000000: results are compared as unsigned.

--- Calls a game function (gamedef name or address); the result as an unsigned number.
function core.call(target, ...)
    if type(target) == "string" then
        target = core.sym(target) or error("boz: the game has no function " .. target, 2)
    end
    return (game.call(target, ...) or 0) & 0xffffffff
end

--- Calls the virtual function at byte `offset` of a C++ object's vtable.
function core.virtual(object, offset, ...)
    local method = game.read("ptr", game.read("ptr", object) + offset)
    return (game.call(method, object, ...) or 0) & 0xffffffff
end

local buffers = {}

--- A buffer of game memory for passing to game functions, kept per key and reused.
function core.scratch(key, size)
    local buffer = buffers[key]
    if not buffer or buffer.size < size then
        if buffer then
            game.free(buffer.address)
        end
        buffer = {address = game.alloc(size), size = size}
        buffers[key] = buffer
    end
    return buffer.address
end

--- x, y, z of a position given as {x =, y =, z =} or {x, y, z}.
function core.xyz(p)
    return p.x or p[1] or 0, p.y or p[2] or 0, p.z or p[3] or 0
end

function core.write_vec3(at, p)
    local x, y, z = core.xyz(p)
    game.write("f32", at, x)
    game.write("f32", at + 4, y)
    game.write("f32", at + 8, z)
end

function core.read_vec3(at)
    return {x = game.read("f32", at), y = game.read("f32", at + 4), z = game.read("f32", at + 8)}
end

--- Writes a quaternion {x, y, z, w} (or a list in that order) the way the game keeps one
--- (CIwFQuat): the scalar first.
function core.write_quat(at, q)
    q = q or {}
    local values = {q.w or q[4] or 1, q.x or q[1] or 0, q.y or q[2] or 0, q.z or q[3] or 0}
    for i, value in ipairs(values) do
        game.write("f32", at + 4 * (i - 1), value)
    end
end

function core.read_quat(at)
    return {w = game.read("f32", at), x = game.read("f32", at + 4), y = game.read("f32", at + 8),
            z = game.read("f32", at + 12)}
end

local logged = {}   -- errors already logged (where .. error), at most 256

--- Calls fn(...) through pcall; an error is logged with the module's name (each one once: a
--- handler that fails every frame keeps the log readable) and swallowed.
function core.safely(where, fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then
        local key = where .. ": " .. tostring(err)
        if not logged[key] then
            if next(logged) == nil or #logged < 256 then
                logged[key] = true
                logged[#logged + 1] = key
            end
            log(key)
        end
    end
    return ok, err
end

return core
