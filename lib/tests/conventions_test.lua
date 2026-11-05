-- No old conventions left in the standard library or the Developer mod (block 3: no
-- compatibility): lua5.4 lib/tests/conventions_test.lua (from the SDK root).
local OLD = {
    {'---@property', 'script settings are ---@setting'},
    {'self%.properties', 'script settings are self.settings'},
    {'require%("boz%.prefabs"%)', 'the runtime is boz.objects.runtime (scripts use require("boz"))'},
    {'prefabs%.globals', 'shared values are boz.saved'},
}
local FLAT = {"core", "hash", "reflect", "components", "entities", "game_events", "hooks", "map",
              "pieces", "spawns", "timers", "score", "weapons", "match_events", "objects", "player",
              "zombies", "rounds", "pickups", "effects", "world", "audio", "camera", "hud", "input",
              "console", "cvars", "pause_settings", "text", "screen"}
local failures = {}
local handle = io.popen("find lib/boz mods/developer/scripts/main.lua -name '*.lua'")
for path in handle:lines() do
    local file = assert(io.open(path))
    local text = file:read("a")
    file:close()
    for _, rule in ipairs(OLD) do
        if text:find(rule[1]) then
            table.insert(failures, path .. ": " .. rule[2])
        end
    end
    for _, name in ipairs(FLAT) do
        if text:find('require%("boz%.' .. name .. '"%)') then
            table.insert(failures, path .. ': require("boz.' .. name .. '") moved (engine/game/systems)')
        end
    end
end
handle:close()
if #failures > 0 then
    error("FAILED:\n" .. table.concat(failures, "\n"))
end
print("conventions_test: OK")
