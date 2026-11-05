-- boz.class: classes with inheritance.
--
--   local Door = boz.Prefab:extend("Door")
--   function Door:on_use(player) boz.Prefab.on_use(self, player) end   -- call the parent
--   Door:new(...)  door:is_a(boz.Prefab)

local Class = {__name = "Class"}
Class.__index = Class

--- A new class that inherits this one's methods (name: for error messages).
function Class:extend(name)
    local class = setmetatable({}, {__index = self})
    class.__index = class
    class.__name = name or self.__name
    class.super = self
    return class
end

--- A new object of this class; init(...) sets it up.
function Class:new(...)
    local object = setmetatable({}, self)
    object:init(...)
    return object
end

--- Sets up a new object (override it; call the parent's init too).
function Class:init() end

--- True when the object is of this class or one that extends it.
function Class:is_a(other)
    local class = getmetatable(self)
    while class do
        if class == other then
            return true
        end
        class = class.super
    end
    return false
end

--- The class's name.
function Class:class_name()
    return getmetatable(self).__name
end

return Class
