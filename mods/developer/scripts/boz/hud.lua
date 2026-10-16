-- boz.hud: the in-game HUD's elements.
--
--   hud.set_visible("Insta_Kill_Image", true)       hud.hide("Clip_Label")
--   hud.ELEMENTS                                    the HUD's named elements
--   hud.message("The power is on", 3)               a line of text for 3 seconds
--
-- Elements (IwUI, found by name): the power-up icons and labels (Insta_Kill_Image, Double_Points,
-- Fire_Sale, Death_Machine; _Image and _Label), the perk icons (Perk_Juggernog_Image, ...),
-- Clip_Label, Grenade_Label, Low_Ammo_Label, No_Ammo_Label, Headshot_Image/Label,
-- Being_Revived_Label. Text on the screen: boz.text (strings) and boz.iwui (any element).
--
-- How it works: HUD_SetElementVisible(name, visible) finds the element in the current page
-- (CUIPageManager::FindElement), shows or hides it (CIwUIElement::SetVisible) and makes it opaque;
-- the power-up code calls it with the icon names.

local hud = {}

hud.ELEMENTS = {"Insta_Kill_Image", "Insta_Kill_Label", "Double_Points_Image", "Double_Points_Label",
                "Fire_Sale_Image", "Fire_Sale_Label", "Death_Machine_Image", "Death_Machine_Label",
                "Perk_Deadshot_Image", "Perk_Double_Tap_Image", "Perk_Juggernog_Image",
                "Perk_PHD_Flopper_Image", "Perk_Revival_Image", "Perk_Speed_Cola_Image",
                "Perk_StaminUp_Image", "Clip_Label", "Grenade_Label", "Low_Ammo_Label", "No_Ammo_Label",
                "Headshot_Image", "Headshot_Label", "Being_Revived_Label"}

local FALLBACK = {["HUD_SetElementVisible"] = 0x1cffe4 + 1}

local function sym(name)
    return game.symbol(name) or (FALLBACK[name] and game.base() + FALLBACK[name])
end

--- Shows or hides a HUD element by name (the game shows and hides its own as things happen).
function hud.set_visible(name, visible)
    game.call(sym("HUD_SetElementVisible"), name, visible and 1 or 0)
    return true
end

--- Shows a HUD element.
function hud.show(name)
    return hud.set_visible(name, true)
end

--- Hides a HUD element.
function hud.hide(name)
    return hud.set_visible(name, false)
end

-- Messages: a copy of the HUD's "Being revived" label (the game's font), showing a string id of
-- our own (boz.text).
local MESSAGE_LIKE, MESSAGE_NAME = "Being_Revived_Label", "boz_message"
local message = {element = nil, left = 0, watching = false, turn = 0}

local function message_label()
    local iwui = require("boz.iwui")
    local found = iwui.find(MESSAGE_NAME)
    if found then
        return found
    end
    local like = iwui.find(MESSAGE_LIKE)
    if not like then
        return nil
    end
    local copy = iwui.clone(like)
    if not copy then
        return nil
    end
    iwui.set_name(copy, MESSAGE_NAME)
    iwui.add_child(iwui.parent(like), copy)
    return copy
end

--- Shows a line of text in the HUD's font for `seconds` (default 3; a new message replaces the
--- last), where the game writes "Reviving" (left of the crosshair), or at `x, y` (screen pixels,
--- its left edge). Returns false outside a match.
function hud.message(text, seconds, x, y)
    local label = message_label()
    if not label then
        return false
    end
    -- The label shows a string id: the text goes in as one of two ids of our own, in turn, so the
    -- label sees a new id and redraws.
    message.turn = 3 - (message.turn == 1 and 1 or 2)
    local id = "S_BOZ_MESSAGE_" .. message.turn
    require("boz.text").add(id, tostring(text))
    require("boz.iwui").set_text_id(label, id)
    if x and y then
        require("boz.iwui").set_position(label, x, y)
    end
    hud.set_visible(MESSAGE_NAME, true)     -- the game's way: visible and opaque
    message.element, message.left = label, seconds or 3
    if not message.watching then
        message.watching = true
        events.on("frame", function(dt)
            if message.left > 0 then
                message.left = message.left - (dt or 0)
                if message.left <= 0 and require("boz.iwui").find(MESSAGE_NAME) == message.element then
                    hud.set_visible(MESSAGE_NAME, false)
                end
            end
        end)
    end
    return true
end

--- Hides the message now.
function hud.clear_message()
    if require("boz.iwui").find(MESSAGE_NAME) then
        hud.set_visible(MESSAGE_NAME, false)
    end
    message.left = 0
end

return hud
