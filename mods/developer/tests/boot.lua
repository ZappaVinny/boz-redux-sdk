--! timeout: 240
-- The game boots with the Developer mod, a Kino match starts and the console works.
local console = require("boz.systems.console")

test.start_map("kino", {UnlimitedHealth = true})

test.step("the match starts", function()
    test.wait_until(test.in_match, 150, "the Kino match")
    test.wait(5)
    test.screenshot("kino")
end)

test.step("the console runs commands", function()
    test.expect(console.ready(), "the console is ready")
    local kept = console.register("BozTestValue", "7")
    test.expect(kept ~= nil, "a console variable can be registered")
end)

test.step("no Lua errors", function()
    test.expect(test.errors() == 0, test.errors() .. " Lua errors in mods")
end)
