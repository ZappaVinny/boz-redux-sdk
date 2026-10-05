-- boz.swf: reading and changing Flash movies (SWF), for patching the game's menus.
--
-- Most mods use boz.frontend instead. swf.parse(bytes) gives a movie whose sprites can be found
-- by the names their scripts use and given extra frame scripts; movie:serialize() writes it back.
--
-- How it works: works on the uncompressed movies the game ships (FWS). Tags keep their original
-- bytes unless changed, so an untouched movie serializes back byte for byte.

local swf = {}

local DEFINE_SPRITE, DO_ACTION, SHOW_FRAME, END = 39, 12, 1, 0

local function read_tags(bytes, pos, limit)
    local tags = {}
    while pos <= limit do
        local start = pos
        local code_length = string.unpack("<I2", bytes, pos)
        pos = pos + 2
        local code, length = code_length >> 6, code_length & 0x3f
        if length == 0x3f then
            length = string.unpack("<I4", bytes, pos)
            pos = pos + 4
        end
        local body = bytes:sub(pos, pos + length - 1)
        pos = pos + length
        tags[#tags + 1] = {code = code, body = body, raw = bytes:sub(start, pos - 1)}
        if code == END then
            break
        end
    end
    return tags
end

local function write_tag(tag)
    if tag.raw and not tag.changed then
        return tag.raw
    end
    local body = tag.body
    if #body < 0x3f then
        return string.pack("<I2", (tag.code << 6) | #body) .. body
    end
    return string.pack("<I2I4", (tag.code << 6) | 0x3f, #body) .. body
end

local Sprite = {}
Sprite.__index = Sprite

local function parse_sprite(tag)
    local id, frames = string.unpack("<I2I2", tag.body)
    local sprite = setmetatable({id = id, frames = frames, tag = tag}, Sprite)
    sprite.tags = read_tags(tag.body, 5, #tag.body)
    return sprite
end

--- The frame scripts (DoAction bodies) of the sprite's tags, in order.
function Sprite:actions()
    local list = {}
    for _, tag in ipairs(self.tags) do
        if tag.code == DO_ACTION then
            list[#list + 1] = tag.body
        end
    end
    return list
end

--- True if any frame script of the sprite contains text (a name used in its code).
function Sprite:uses(text)
    for _, body in ipairs(self:actions()) do
        if body:find(text, 1, true) then
            return true
        end
    end
    return false
end

--- Adds a frame script to the sprite's first frame, after the scripts already there.
function Sprite:add_first_frame_action(action_bytes)
    for i, tag in ipairs(self.tags) do
        if tag.code == SHOW_FRAME then
            table.insert(self.tags, i, {code = DO_ACTION, body = action_bytes, changed = true})
            self.changed = true
            return true
        end
    end
    return false
end

--- The sprite's tag bytes (used by Movie:serialize).
function Sprite:serialize()
    local parts = {string.pack("<I2I2", self.id, self.frames)}
    for _, tag in ipairs(self.tags) do
        parts[#parts + 1] = write_tag(tag)
    end
    return table.concat(parts)
end

local Movie = {}
Movie.__index = Movie

--- Parses a movie. Returns the movie, or nil and an error.
function swf.parse(bytes)
    local signature, version = bytes:sub(1, 3), bytes:byte(4)
    if signature ~= "FWS" then
        return nil, "not an uncompressed SWF (signature " .. signature .. ")"
    end
    local bits = bytes:byte(9) >> 3
    local rect_bytes = (5 + 4 * bits + 7) // 8
    local header_end = 8 + rect_bytes + 4
    local movie = setmetatable({
        version = version,
        header = bytes:sub(9, header_end),
        tags = read_tags(bytes, header_end + 1, #bytes),
    }, Movie)
    return movie
end

--- Every sprite (DefineSprite) in the movie, parsed.
function Movie:sprites()
    if not self.sprite_list then
        self.sprite_list = {}
        for _, tag in ipairs(self.tags) do
            if tag.code == DEFINE_SPRITE then
                self.sprite_list[#self.sprite_list + 1] = parse_sprite(tag)
            end
        end
    end
    return self.sprite_list
end

--- The sprite with this character id, or nil.
function Movie:sprite(id)
    for _, sprite in ipairs(self:sprites()) do
        if sprite.id == id then
            return sprite
        end
    end
end

--- The first sprite whose frame scripts use all the given names, or nil.
function Movie:find_sprite_using(...)
    local names = {...}
    for _, sprite in ipairs(self:sprites()) do
        local all = true
        for _, name in ipairs(names) do
            if not sprite:uses(name) then
                all = false
                break
            end
        end
        if all then
            return sprite
        end
    end
end

--- The movie as bytes, with changed sprites rebuilt.
function Movie:serialize()
    local parts = {}
    for _, sprite in ipairs(self.sprite_list or {}) do
        if sprite.changed then
            sprite.tag.body = sprite:serialize()
            sprite.tag.changed = true
        end
    end
    for _, tag in ipairs(self.tags) do
        parts[#parts + 1] = write_tag(tag)
    end
    local body = self.header .. table.concat(parts)
    return "FWS" .. string.char(self.version) .. string.pack("<I4", 8 + #body) .. body
end

return swf
