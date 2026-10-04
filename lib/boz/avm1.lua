-- boz.avm1: building ActionScript 2 bytecode (AVM1) for the game's Flash menus.
--
--   local b = avm1.builder()
--   b:push("hello from a mod"):op("Trace")
--   local bytes = b:bytes()   -- a frame script for boz.swf / boz.frontend.patch_screen
--
-- A builder collects actions. Values are pushed with :push(...) (strings, numbers, booleans,
-- avm1.NULL, avm1.UNDEFINED); :get("a.b.c") pushes a path; functions are built with
-- :func(name, params, body_fn); jumps use labels. Used by boz.frontend.

local avm1 = {}

avm1.NULL = setmetatable({}, {__tostring = function() return "null" end})
avm1.UNDEFINED = setmetatable({}, {__tostring = function() return "undefined" end})

local OPS = {
    GetVariable = 0x1C, SetVariable = 0x1D, GetMember = 0x4E, SetMember = 0x4F,
    CallFunction = 0x3D, CallMethod = 0x52, Pop = 0x17, Return = 0x3E, DefineLocal = 0x3C,
    Add2 = 0x47, Subtract = 0x0B, Multiply = 0x0C, Divide = 0x0D, Less2 = 0x48, Greater = 0x67,
    Equals2 = 0x49, Not = 0x12, PushDuplicate = 0x4C, NewObject = 0x40, InitObject = 0x43,
    Trace = 0x26, ToNumber = 0x4A, ToString = 0x4B, StringAdd = 0x21, TypeOf = 0x44,
}

local Builder = {}
Builder.__index = Builder

function avm1.builder()
    return setmetatable({parts = {}, size = 0, labels = {}, fixups = {}}, Builder)
end

local function emit(self, bytes)
    self.parts[#self.parts + 1] = bytes
    self.size = self.size + #bytes
end

local function action(self, code, payload)
    if payload then
        emit(self, string.pack("<BI2", code, #payload) .. payload)
    else
        emit(self, string.char(code))
    end
    return self
end

--- Pushes values onto the stack (one Push action).
function Builder:push(...)
    local payload = {}
    for i = 1, select("#", ...) do
        local v = select(i, ...)
        if v == avm1.NULL then
            payload[#payload + 1] = "\2"
        elseif v == avm1.UNDEFINED or v == nil then
            payload[#payload + 1] = "\3"
        elseif type(v) == "boolean" then
            payload[#payload + 1] = string.pack("<BB", 5, v and 1 or 0)
        elseif math.type(v) == "integer" and v >= -0x80000000 and v <= 0x7fffffff then
            payload[#payload + 1] = string.pack("<Bi4", 7, v)
        elseif type(v) == "number" then
            local d = string.pack("<d", v)  -- AVM1 doubles store the high word first
            payload[#payload + 1] = "\6" .. d:sub(5, 8) .. d:sub(1, 4)
        else
            payload[#payload + 1] = "\0" .. tostring(v) .. "\0"
        end
    end
    return action(self, 0x96, table.concat(payload))
end

--- Emits a simple action by name (GetVariable, SetMember, CallMethod, ...).
function Builder:op(name)
    local code = OPS[name]
    assert(code, "unknown AVM1 action " .. tostring(name))
    return action(self, code)
end

--- Marks a jump target.
function Builder:label(name)
    self.labels[name] = self.size
    return self
end

local function branch(self, code, name)
    emit(self, string.pack("<BI2i2", code, 2, 0))
    self.fixups[#self.fixups + 1] = {at = #self.parts, after = self.size, label = name}
    return self
end

--- Jumps to a label if the value on the stack is true.
function Builder:if_true(name)
    return branch(self, 0x9D, name)
end

--- Jumps to a label.
function Builder:jump(name)
    return branch(self, 0x99, name)
end

--- Defines a function: name ("" for an anonymous one, left on the stack), parameter names, and
--- body(b) which fills a builder for the function body.
function Builder:func(name, params, body)
    local inner = avm1.builder()
    body(inner)
    local code = inner:bytes(true)
    local header = name .. "\0" .. string.pack("<I2", #params)
    for _, p in ipairs(params) do
        header = header .. p .. "\0"
    end
    header = header .. string.pack("<I2", #code)
    emit(self, string.pack("<BI2", 0x9B, #header) .. header)
    emit(self, code)
    return self
end

--- The finished bytecode; frame scripts end with an End action unless inner is set.
function Builder:bytes(inner)
    for _, fix in ipairs(self.fixups) do
        local target = self.labels[fix.label]
        assert(target, "undefined label " .. fix.label)
        local part = self.parts[fix.at]
        self.parts[fix.at] = part:sub(1, 3) .. string.pack("<i2", target - fix.after)
    end
    local code = table.concat(self.parts)
    return inner and code or code .. "\0"
end

-- Convenience for common patterns ------------------------------------------------------------

--- Pushes the value of a dotted path, e.g. b:get("_root.Options.settings").
function Builder:get(path)
    local first, rest = path:match("^([^%.]+)%.?(.*)$")
    self:push(first):op("GetVariable")
    for part in rest:gmatch("[^%.]+") do
        self:push(part):op("GetMember")
    end
    return self
end

--- Calls obj.method(args...) where obj is pushed by push_obj(b); leaves the result on the stack.
function Builder:call_method(push_obj, method, ...)
    local args = {...}
    for i = #args, 1, -1 do
        self:push(args[i])
    end
    self:push(#args)
    push_obj(self)
    return self:push(method):op("CallMethod")
end

--- trace(text .. value-of-path): writes a line to the Flash log (see boz.flash.capture_log).
function Builder:trace(text, path)
    self:push(text)
    if path then
        self:get(path):op("Add2")
    end
    return self:op("Trace")
end

return avm1
