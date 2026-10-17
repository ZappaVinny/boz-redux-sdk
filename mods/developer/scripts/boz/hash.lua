-- boz.hash: the game's name hash.
--
-- Event ids (SUBJECT_*), element names, resource names, string ids and console names are all
-- hashed this way: hash.name("musicSlider").
--
-- How it works: IwHashString is djb2 (h = h * 33 + c from 5381) over the name with A-Z
-- lower-cased.

local hash = {}

--- The game's hash of a name (IwHashString).
function hash.name(text)
    local h = 5381
    for i = 1, #text do
        local c = text:byte(i)
        if c >= 65 and c <= 90 then
            c = c + 32
        end
        h = (h * 33 + c) & 0xffffffff
    end
    return h
end

--- A hash from a name, a "0x..." hash or a number (returned as it is).
function hash.of(value)
    if type(value) == "number" then
        return value
    end
    if value:sub(1, 2):lower() == "0x" then
        return tonumber(value:sub(3), 16)
    end
    return hash.name(value)
end

return hash
