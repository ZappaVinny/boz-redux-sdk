-- boz.iwui: the in-game menus (Marmalade IwUI pages, e.g. the pause menu).
--
--   local slider = iwui.find("musicSlider")
--   local copy = iwui.clone(slider)
--   iwui.add_child(iwui.parent(slider), copy)
--   iwui.set_position(copy, 800, 300)
--
-- Find elements by name, walk and dump a page, copy and place widgets, set labels, slider
-- values and visibility. boz.pause_settings is built on it; use that for settings rows.
--
-- How it works: pages are trees of elements shown by CUIPageManager. Element layout: +4 name
-- hash, +0x18 parent, +0x1c children (data, +0x20 count), +0x34 event handlers, +0x48/+0x4c
-- slots, +0x5c position, +0x64 size, +0x8c layout, +0xa0 properties. Widgets call named slots on
-- their page's event handler (a slider's OnSliderChanged calls e.g.
-- CIngameStateOptions::OnMusicChanged with itself as the element).

local hash = require("boz.hash")

local iwui = {}

local function ptr(address)
    return game.read("ptr", address)
end

--- The element with this name on the current page, or nil.
function iwui.find(name)
    local manager = ptr("CUIPageManager::s_instance")
    if manager == 0 then
        return nil
    end
    local element = game.call("CUIPageManager::FindElement", manager, name, 0)
    return element ~= 0 and element or nil
end

--- The element's parent, or nil.
function iwui.parent(element)
    local parent = ptr(element + 0x18)
    return parent ~= 0 and parent or nil
end

--- The element's children (list of addresses).
function iwui.children(element)
    local data, count = ptr(element + 0x1c), game.read("u32", element + 0x20)
    local list = {}
    if data ~= 0 and count < 256 then
        for i = 0, count - 1 do
            list[#list + 1] = ptr(data + i * 4)
        end
    end
    return list
end

--- The element's C++ class (from its RTTI), e.g. "CIwUISlider".
function iwui.class_name(element)
    local vtable = ptr(element)
    if vtable == 0 then
        return "?"
    end
    local typeinfo = ptr(vtable - 4)
    if typeinfo == 0 then
        return "?"
    end
    local mangled = game.read("string", ptr(typeinfo + 4), 96)
    return mangled:gsub("^%d+", "")
end

--- The hash of the element's name (compare with boz.hash.name).
function iwui.name_hash(element)
    return game.read("u32", element + 4)
end

--- Position and size in the parent (pixels): +0x5c/+0x60 position, +0x64/+0x68 size.
function iwui.rect(element)
    return game.read("i32", element + 0x5c), game.read("i32", element + 0x60),
           game.read("i32", element + 0x64), game.read("i32", element + 0x68)
end

--- Moves an element within its parent.
function iwui.set_position(element, x, y)
    game.write("i32", element + 0x5c, x)
    game.write("i32", element + 0x60, y)
end

--- True if the element's name is name.
function iwui.is_named(element, name)
    return iwui.name_hash(element) == hash.name(name)
end

--- A deep copy of an element (not yet on any page; add it with add_child).
function iwui.clone(element)
    local copy = game.call("CIwUIElement::Clone", element)
    return copy ~= 0 and copy or nil
end

--- Adds an element to a parent (and to the parent's layout, if it has one).
function iwui.add_child(parent, child)
    game.call("CIwUIElement::AddChild", parent, child)
end

--- Renames an element (CIwManaged::SetName, vtable slot 9) so FindElement finds it.
function iwui.set_name(element, name)
    game.call(ptr(ptr(element) + 0x24), element, name)
end

--- Shows or hides an element.
function iwui.set_visible(element, visible)
    game.call("CIwUIElement::SetVisible", element, visible and 1 or 0)
end

--- Sets a label's text. SetCaption only stores the "caption" property and skips the redraw in
--- some states, so the label is also told the property changed (vtable +0xb8).
function iwui.set_caption(label, text)
    game.call("CIwUILabel::SetCaption", label, text)
    game.call(ptr(ptr(label) + 0xb8), label, hash.name("caption"))
end

--- Points a label at a string id (boz.text.add, or one of the game's like S_MENU_MUSIC). The
--- game's labels show their localiseCaption string id rather than their caption. Changes only
--- the label's own property (not one shared through its style). Returns false if it has none.
function iwui.set_text_id(label, id)
    local property = game.call("IwPropertySet_Find", label + 0xa0, hash.name("localiseCaption"), 0)
    if property == 0 then
        return false
    end
    game.write("u32", property + 0x14, hash.name(id))
    game.call(ptr(ptr(label) + 0xb8), label, hash.name("localiseCaption"))
    return true
end

--- Sets a slider's value (0..4096 on the game's sliders); calls its OnSliderChanged slot.
function iwui.set_value(slider, value)
    game.call("CIwUISlider::SetValue", slider, value)
end

--- The first descendant (depth first) for which test(element) is true.
function iwui.find_in(element, test, depth)
    depth = depth or 0
    for _, child in ipairs(iwui.children(element)) do
        if test(child) then
            return child
        end
        if depth < 12 then
            local found = iwui.find_in(child, test, depth + 1)
            if found then
                return found
            end
        end
    end
end

--- Logs the element tree under element (class, name, children); names resolves known names.
function iwui.dump(element, names, depth)
    depth = depth or 0
    local known = {}
    for _, name in ipairs(names or {}) do
        known[hash.name(name)] = name
    end
    local function walk(e, d)
        local h = iwui.name_hash(e)
        log(string.format("%s%s %s (0x%08x) @%x children=%d", string.rep("  ", d), iwui.class_name(e),
            known[h] or "?", h, e, #iwui.children(e)))
        if d < 8 then
            for _, child in ipairs(iwui.children(e)) do
                walk(child, d + 1)
            end
        end
    end
    walk(element, depth)
end

return iwui
