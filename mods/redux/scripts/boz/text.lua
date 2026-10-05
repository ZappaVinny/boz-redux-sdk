-- boz.text: adding text to the game's string table.
--
--   text.add("S_MYMOD_TITLE", "My setting")
--   iwui.set_text_id(label, "S_MYMOD_TITLE")
--
-- The game shows text by string id (like S_MENU_MUSIC) in the current language. text.add
-- registers an id of the mod's own; use it wherever the game takes a string id.
--
-- How it works: menus and labels hash the id and ask Localise_GetString for the text; a hook
-- answers for the mod's ids.

local hash = require("boz.hash")

local text = {}

local strings = {}   -- id hash -> address of the text (kept for the whole session)
local hooked = false

local function store(value)
    local address = game.alloc(#value + 1)
    for i = 1, #value do
        game.write("u8", address + i - 1, value:byte(i))
    end
    return address
end

--- Adds (or replaces) the text for a string id. Returns the id's hash.
function text.add(id, value)
    local h = hash.name(id)
    strings[h] = store(value)
    if not hooked then
        hooked = true
        hook.add("Localise_GetString", {before = function(call)
            local address = strings[call:arg(1)]
            if address then
                call:skip(address)
            end
        end})
    end
    return h
end

return text
