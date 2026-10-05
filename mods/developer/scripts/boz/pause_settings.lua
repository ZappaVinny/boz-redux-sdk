-- boz.pause_settings: settings in the game's pause menu (Settings page, CIngameStateOptions).
--
--   local pause_settings = require("boz.pause_settings")
--   pause_settings.add_slider{id = "fov", label = "Field of view", min = 50, max = 120, step = 1,
--                             get = function() return value end, set = function(v) ... end}
--   pause_settings.add_checkbox{id = "aim_toggle", label = "Toggle aim",
--                               get = function() return on end, set = function(on) ... end}
--
-- Call these when the mod's script starts. Each time the page opens, the rows are added in the
-- order they were registered, stacked in the free column right of the game's sliders, styled
-- exactly like the game's own (they are copies of its widgets).
--
-- How it works: the page is one flat IwUI panel. A slider row is copied from the detail level row
-- (bar image, slider, title label), a checkbox row from the auto aim row (label, box, cross,
-- button). Copies keep the original's slot (OnLODChanged, OnAutoAim); hooks on those slots take
-- the events that come from a copy and leave the game's own alone. Labels show a string id
-- registered with boz.text.

local iwui = require("boz.iwui")
local text = require("boz.text")
local hash = require("boz.hash")

local pause_settings = {}

local FULL = 4096              -- the page's sliders run 0..4096
local COLUMN_GAP = 1.15        -- the new column starts this many slider widths right of the game's
local entries = {}             -- registered rows, in order
local live = {}                -- copies on the open page: element address -> entry
local installed = false
local built_panel = nil        -- the page this copy of the module last added its rows to

local function class_has(element, kind)
    return iwui.class_name(element):find(kind, 1, true) ~= nil
end

-- The child of a kind nearest to (x, y); above = only ones higher up.
local function nearest(panel, kind, x, y, above)
    local best, best_distance
    for _, child in ipairs(iwui.children(panel)) do
        if class_has(child, kind) then
            local cx, cy = iwui.rect(child)
            if not above or cy < y then
                local distance = math.abs(cx - x) + math.abs(cy - y) * 2
                if not best or distance < best_distance then
                    best, best_distance = child, distance
                end
            end
        end
    end
    return best
end

local function find_child(panel, name)
    for _, child in ipairs(iwui.children(panel)) do
        if iwui.is_named(child, name) then
            return child
        end
    end
end

-- Copies element into panel, moved by (dx, dy); prepare(copy) runs before it joins the panel.
local function copy(panel, element, dx, dy, prepare)
    local c = iwui.clone(element)
    if not c then
        return nil
    end
    if prepare then
        prepare(c)
    end
    iwui.add_child(panel, c)
    local x, y = iwui.rect(element)
    iwui.set_position(c, x + dx, y + dy)
    return c
end

local function labelled(entry)
    return function(label)
        if not iwui.set_text_id(label, entry.text_id) then
            iwui.set_caption(label, entry.label)
        end
    end
end

-- Templates on the page: the detail level row and the auto aim row, with their extents.
local function templates(panel)
    local slider = iwui.find("lodSlider")
    if not slider then
        return nil
    end
    local sx, sy, sw = iwui.rect(slider)
    local t = {
        slider = slider,
        slider_bar = nearest(panel, "Image", sx, sy),
        slider_label = nearest(panel, "Label", sx, sy, true),
        checkbox_label = find_child(panel, "AutoAim"),
        checkbox_box = find_child(panel, "autoaimbox"),
        checkbox_cross = find_child(panel, "autoAimCross"),
        checkbox_button = find_child(panel, "autoaimbutton"),
    }
    t.slider_top = t.slider_label and select(2, iwui.rect(t.slider_label)) or sy
    t.column_x = sx + math.floor(sw * COLUMN_GAP)
    local music = iwui.find("musicSlider")
    t.slider_step = music and (select(2, iwui.rect(music)) - sy) or 249
    local invert = find_child(panel, "invertybutton")
    if t.checkbox_button then
        local bx, by = iwui.rect(t.checkbox_button)
        local lx = t.checkbox_label and iwui.rect(t.checkbox_label) or bx
        t.checkbox_left = math.min(lx, bx)
        t.checkbox_top = by
        t.checkbox_step = invert and (select(2, iwui.rect(invert)) - by) or 131
    end
    return t
end

local function add_slider_row(panel, t, entry, top)
    local dx, dy = t.column_x - select(1, iwui.rect(t.slider)), top - t.slider_top
    if t.slider_bar then
        copy(panel, t.slider_bar, dx, dy)
    end
    if t.slider_label then
        copy(panel, t.slider_label, dx, dy, labelled(entry))
    end
    local slider = copy(panel, t.slider, dx, dy)
    if not slider then
        return
    end
    iwui.set_name(slider, "boz_" .. entry.id)
    live[slider] = entry
    local ok, value = pcall(entry.get)
    if ok and type(value) == "number" then
        local fraction = (value - entry.min) / (entry.max - entry.min)
        iwui.set_value(slider, math.floor(math.max(0, math.min(1, fraction)) * FULL + 0.5))
    end
end

local function add_checkbox_row(panel, t, entry, top)
    if not t.checkbox_button then
        return
    end
    local dx, dy = t.column_x - t.checkbox_left, top - t.checkbox_top
    if t.checkbox_label then
        copy(panel, t.checkbox_label, dx, dy, labelled(entry))
    end
    if t.checkbox_box then
        copy(panel, t.checkbox_box, dx, dy)
    end
    local cross = t.checkbox_cross and copy(panel, t.checkbox_cross, dx, dy)
    local button = copy(panel, t.checkbox_button, dx, dy)
    if not button then
        return
    end
    iwui.set_name(button, "boz_" .. entry.id)
    entry.cross = cross
    live[button] = entry
    local ok, on = pcall(entry.get)
    if cross then
        iwui.set_visible(cross, ok and on == true)
    end
end

local function build_page()
    live = {}
    local detail = iwui.find("lodSlider")
    local panel = detail and iwui.parent(detail)
    local t = panel and templates(panel)
    if not t then
        log("boz.pause_settings: the pause menu's Settings page was not found")
        return
    end
    if built_panel == panel then
        return
    end
    built_panel = panel
    -- Rows from all mods share one column: each mod's copy of this module continues where the
    -- previous one (in mod load order) stopped, tracked in the client's shared table per page.
    local column = shared.boz_pause_settings
    if not column or column.panel ~= panel then
        column = {panel = panel, top = t.slider_top}
        shared.boz_pause_settings = column
    end
    local top = column.top
    for _, entry in ipairs(entries) do
        if entry.kind == "slider" then
            add_slider_row(panel, t, entry, top)
            top = top + t.slider_step
        else
            add_checkbox_row(panel, t, entry, top)
            top = top + (t.checkbox_step or 131)
        end
    end
    column.top = top
end

local function call_set(entry, value)
    local ok, err = pcall(entry.set, value)
    if not ok then
        log("boz.pause_settings: " .. entry.id .. ".set: " .. tostring(err))
    end
end

local function play_click()
    local sound = game.read("ptr", "CIwSoundManager::s_instance")
    if sound ~= 0 then
        game.call("CIwSoundManager::Play", sound, hash.name("menu_press"), 0, 0, 0)
    end
end

local function install()
    installed = true
    hook.add("CIngameStateOptions::Enter", {after = build_page})
    hook.add("CIngameStateOptions::Exit", {before = function()
        live = {}
        built_panel = nil
    end})
    hook.add("CIngameStateOptions::OnLODChanged", {before = function(call)
        local entry = live[call:arg(2)]
        if entry then
            local fraction = math.max(0, math.min(1, call:arg_signed(3) / FULL))
            local value = entry.min + fraction * (entry.max - entry.min)
            if entry.step then
                value = entry.min + math.floor((value - entry.min) / entry.step + 0.5) * entry.step
            end
            call_set(entry, value)
            call:skip()
        end
    end})
    hook.add("CIngameStateOptions::OnAutoAim", {before = function(call)
        local entry = live[call:arg(2)]
        if entry then
            local ok, on = pcall(entry.get)
            local value = not (ok and on == true)
            call_set(entry, value)
            if entry.cross then
                iwui.set_visible(entry.cross, value)
            end
            play_click()
            call:skip()
        end
    end})
end

local function register(kind, spec)
    assert(type(spec.id) == "string" and spec.id:match("^[%w_]+$"), "pause_settings: id must be letters, digits or _")
    assert(type(spec.label) == "string", "pause_settings: label is required")
    assert(type(spec.get) == "function" and type(spec.set) == "function", "pause_settings: get and set are required")
    local entry = {kind = kind, id = spec.id, label = spec.label, min = spec.min, max = spec.max,
                   step = spec.step, get = spec.get, set = spec.set}
    entry.text_id = "S_BOZ_" .. spec.id:upper()
    text.add(entry.text_id, spec.label)
    entries[#entries + 1] = entry
    if not installed then
        install()
    end
end

--- Adds a slider. spec: id, label, min, max, step (optional), get() -> number, set(number).
function pause_settings.add_slider(spec)
    assert(type(spec.min) == "number" and type(spec.max) == "number" and spec.max > spec.min,
        "pause_settings.add_slider: min < max required")
    register("slider", spec)
end

--- Adds a checkbox. spec: id, label, get() -> boolean, set(boolean).
function pause_settings.add_checkbox(spec)
    register("checkbox", spec)
end

return pause_settings
