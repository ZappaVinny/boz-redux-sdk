-- boz.flash: debugging the game's Flash menus (gameswf).
--
-- flash.capture_log() makes ActionScript trace() output and gameswf's own warnings appear in
-- boz-log.txt as "[flash] ...".
--
-- How it works: the release build sets no gameswf log handler, so nothing is formatted. A hook on
-- gameswf_LogMsg formats each message with the game's vsnprintf.

local flash = {}

local hooked = false

--- Shows ActionScript trace() output and gameswf warnings in boz-log.txt as "[flash] ...".
function flash.capture_log()
    if hooked then
        return
    end
    hooked = true
    local buffer = game.alloc(4096)
    local args = game.alloc(32)
    hook.add("gameswf_LogMsg", {before = function(call)
        -- The variadic arguments: r1..r3 then the caller's stack words.
        for i = 2, 8 do
            game.write("u32", args + (i - 2) * 4, call:arg(i))
        end
        game.call("vsnprintf", buffer, 4096, call:arg(1), args)
        local text = game.read("string", buffer, 4096):gsub("%s+$", "")
        if text ~= "" then
            log("[flash] " .. text)
        end
    end})
end

return flash
