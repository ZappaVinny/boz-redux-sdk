-- Developer: the game's developer console on screen, plus developer cheats.
--
-- The release build kept the console (commands, console variables, key bindings) but dropped
-- every way to see it. This mod gives it a window: a command line with history, a browser for all
-- console variables, cheats and the developer commands. Press ` or F1.
--
-- Game access goes through the standard library in scripts/boz (console, player, fly, rounds).

local console = require("boz.console")
local player = require("boz.player")
local fly = require("boz.fly")
local rounds = require("boz.rounds")

local MAX_LINES = 2000
local MAX_ROWS = 300          -- variable rows shown at once; type in the filter to narrow
local REFRESH_SECONDS = 0.5   -- how often shown values are read back from the game

local state = {
    open = false,
    lines = {},
    history = {},
    input = "",
    focus_input = false,
    at_bottom = true,
    scroll = false,
    var_filter = "",
    cmd_filter = "",
    cmd_args = "",
    round = 1,
    values = {},
    values_age = math.huge,
}

local vars = console.vars()
local commands = console.commands()
table.sort(vars, function(a, b) return a.name:lower() < b.name:lower() end)
table.sort(commands, function(a, b) return a.name:lower() < b.name:lower() end)

local COLORS = {
    input = {0.55, 0.8, 1.0},
    error = {1.0, 0.45, 0.4},
    info = {0.6, 0.9, 0.6},
}

local function add_line(text, kind)
    for line in (text .. "\n"):gmatch("(.-)\r?\n") do
        state.lines[#state.lines + 1] = {text = line, kind = kind}
    end
    while #state.lines > MAX_LINES do
        table.remove(state.lines, 1)
    end
    if state.at_bottom then
        state.scroll = true
    end
end

local function info(text)
    add_line(text, "info")
end

local function fail(text)
    add_line(text, "error")
end

local function set_open(open)
    state.open = open
    overlay.capture(open)
    if open then
        state.focus_input = true
        state.values_age = math.huge
    end
end

local function toggle()
    set_open(not state.open)
end

-- Everything the game's console prints shows in the log.
console.on_output(function(text)
    add_line(text)
end)

-- Commands --------------------------------------------------------------------------------------
-- The mod answers these itself; everything else goes to the game's console. The game's own
-- `cvar`, `bind` and `help` are registered but have no handler in the release build.

local commands_here = {}
local execute

function commands_here.clear()
    state.lines = {}
end

function commands_here.find(text)
    text = (text or ""):lower()
    if text == "" then
        fail("usage: find <text>  (searches variable and command names)")
        return
    end
    local found = 0
    for _, v in ipairs(vars) do
        if v.name:lower():find(text, 1, true) then
            info(string.format("  var  %-36s %-10s default %s", v.name, v.type, v.default))
            found = found + 1
        end
    end
    for _, c in ipairs(commands) do
        if c.name:lower():find(text, 1, true) then
            info("  cmd  " .. c.name)
            found = found + 1
        end
    end
    info(found .. " match" .. (found == 1 and "" or "es"))
end

function commands_here.help()
    info("Type a console variable name to see its value, or name and value to set it.")
    info("Type a command with its arguments to run it; separate several with ';'.")
    info("Mod commands: find <text>, clear, help, bind <key> <line>, unbind <key>, binds,")
    info("cvar <name> <value> [bool|int|float|string], fov <degrees|default>, perks, noclip.")
    info("The game also has listVars, listCommands, listAliases, alias, unbindAll.")
    info("Up/Down recall earlier lines.")
end

-- Key bindings are saved with the mod's settings and restored at start.
local key_binds = {}

local function save_binds()
    local list = {}
    for key, line in pairs(key_binds) do
        list[#list + 1] = key .. "\t" .. line
    end
    settings.set("binds", table.concat(list, "\n"))
end

local function bind(key, line)
    key_binds[key] = line
    input.bind(key, function()
        execute(line)
    end)
end

function commands_here.bind(rest)
    local key, line = (rest or ""):match("^(%S+)%s+(.+)$")
    if not key then
        fail("usage: bind <key> <console line>   e.g. bind F5 KillAllZombies")
        return
    end
    bind(key, line)
    save_binds()
    info("Bound " .. key .. " to: " .. line)
end

function commands_here.unbind(key)
    if not key or key == "" or not key_binds[key] then
        fail("usage: unbind <key>  (see binds)")
        return
    end
    key_binds[key] = nil
    input.unbind(key)
    save_binds()
    info("Unbound " .. key)
end

function commands_here.binds()
    local any = false
    for key, line in pairs(key_binds) do
        info(string.format("  %-12s %s", key, line))
        any = true
    end
    if not any then
        info("No bindings. bind <key> <console line> adds one.")
    end
end

function commands_here.cvar(rest)
    local name, value, kind = (rest or ""):match("^(%S+)%s+(%S+)%s*(%S*)$")
    if not name then
        fail("usage: cvar <name> <value> [bool|int|float|string]")
        return
    end
    local result, used = console.register(name, value, kind ~= "" and kind or nil)
    if result then
        info(string.format("%s = %s (%s)", name, result, used))
    else
        fail(used or ("cannot register " .. name))
    end
end

function commands_here.perks()
    local given = player.give_all_perks()
    if not given then
        fail("Start a Zombies match to get perks.")
    elseif #given == 0 then
        info("You already have every perk.")
    else
        info("Perks given: " .. table.concat(given, ", "))
    end
end

function commands_here.noclip()
    local on = fly.set()
    if on == nil then
        fail("Noclip needs a Zombies match (the player has no fly component here).")
    elseif on then
        info("Noclip on: move keys fly where you look, Space up, Left Ctrl down.")
    else
        info("Noclip off.")
    end
end

-- For quick tests only: the saved field of view is a Redux setting (Options > Settings).
local function apply_fov(degrees)
    player.set_fov(degrees)
end

function commands_here.fov(rest)
    local current, default = player.fov()
    if rest == "" then
        if current then
            info(string.format("fov = %.0f (map default %.0f)", current, default))
        else
            fail("Start a Zombies match to see the field of view.")
        end
        return
    end
    if rest == "default" then
        apply_fov(nil)
        info("Field of view back to the map default")
        return
    end
    local value = tonumber(rest)
    if not value or value < 20 or value > 140 then
        fail("usage: fov <20-140> | fov default")
        return
    end
    apply_fov(value)
    info(string.format("Field of view set to %.0f%s", value, current and "" or " (applies in a match)"))
end

execute = function(line)
    local name, rest = line:match("^(%S+)%s*(.*)$")
    local handler = commands_here[name]
    if handler then
        handler(rest)
        return
    end
    local _, err = console.exec(line)
    if err then
        fail(err)
    end
end

local function run(line)
    line = line:match("^%s*(.-)%s*$")
    if line == "" then
        return
    end
    if state.history[#state.history] ~= line then
        state.history[#state.history + 1] = line
    end
    add_line("> " .. line, "input")
    execute(line)
end

-- Restore saved settings.
local saved_binds = settings.get("binds")
for entry in ((type(saved_binds) == "string" and saved_binds or "") .. "\n"):gmatch("(.-)\n") do
    local key, line = entry:match("^([^\t]+)\t(.+)$")
    if key then
        bind(key, line)
    end
end

-- Keys ------------------------------------------------------------------------------------------

input.bind("`", toggle)
input.bind("F1", toggle)

local held = {}

events.on("key", function(name, down)
    held[name] = down
    if state.open and down and name == "Escape" then
        set_open(false)
        return true
    end
end)

-- Noclip up/down while Space / Left Ctrl are held.
events.on("frame", function(dt)
    local up, down = held["Space"], held["Left Ctrl"]
    if up ~= down then
        fly.move_vertical(up and 1 or -1, dt)
    end
end)

-- AllWeapons gives weapons from other maps whose animations are not loaded; equipping one makes
-- the game look up animation ids in a missing state machine. Answer "not found" (0xffff) instead
-- of letting the lookup read through a null pointer.
hook.add("Anim_FindId", {before = function(call)
    if call:arg(3) == 0 then
        game.write("u16", call:arg(1), 0xffff)
        call:skip()
    end
end})

-- Tabs ------------------------------------------------------------------------------------------

local function value_of(name)
    return state.values[name]
end

local function refresh_values(names, dt)
    state.values_age = state.values_age + dt
    if state.values_age < REFRESH_SECONDS then
        return
    end
    state.values_age = 0
    for _, name in ipairs(names) do
        state.values[name] = console.get(name) or false
    end
end

local function set_var(name, value)
    local result, err = console.set(name, value)
    if not result then
        fail(err)
    end
    state.values[name] = result or state.values[name]
end

local function console_tab()
    ui.child("log", 0, -40, function()
        for _, line in ipairs(state.lines) do
            local color = COLORS[line.kind]
            if color then
                ui.text_colored(line.text, color[1], color[2], color[3])
            else
                ui.text(line.text)
            end
        end
        if state.scroll then
            ui.scroll_to_bottom()
            state.scroll = false
        end
        state.at_bottom = ui.at_bottom()
    end)
    local submitted, text = ui.input("##command", state.input, {
        submit = true,
        history = state.history,
        hint = "command or variable  (help, find <text>, clear)",
        width = -1,
        focus = state.focus_input,
    })
    state.focus_input = false
    state.input = text
    if submitted then
        run(text)
        state.input = ""
        state.focus_input = true
        state.scroll = true
    end
end

local CHEATS = {
    {"UnlimitedHealth", "God mode (no damage)"},
    {"WeaponsUnlimitedAmmo", "Unlimited ammo"},
    {"UnlimitedScore", "Free purchases (unlimited points)"},
    {"UnlimitedStamina", "Unlimited sprint"},
    {"HealthIgnoreBleedOutTime", "Never bleed out when downed"},
    {"AIGodmode", "Zombies can't be hurt"},
    {"UnlimitedWaterMove", "Unlimited water movement"},
}

local cheat_names = {}
for _, cheat in ipairs(CHEATS) do
    cheat_names[#cheat_names + 1] = cheat[1]
end

local function cheats_tab(dt)
    refresh_values(cheat_names, dt)
    ui.separator("Cheats (console variables)")
    for _, cheat in ipairs(CHEATS) do
        local changed, on = ui.checkbox(cheat[2] .. "##" .. cheat[1], value_of(cheat[1]) == "true")
        ui.tooltip(cheat[1])
        if changed then
            set_var(cheat[1], on and "true" or "false")
        end
    end

    ui.separator("Field of view (Zombies match)")
    local current, default = player.fov()
    if current then
        local submitted, text = ui.input("Degrees##fov", state.fov_text or string.format("%.0f", current),
            {submit = true, width = 80})
        state.fov_text = text
        ui.same_line()
        if ui.button("Apply##fov") or submitted then
            run("fov " .. text)
            state.fov_text = nil
        end
        ui.same_line()
        if ui.button("Default##fov") then
            run("fov default")
            state.fov_text = nil
        end
        ui.text_disabled(string.format("Now %.0f, map default %.0f. Aiming down sights still zooms.", current, default))
    else
        ui.text_disabled("Start a Zombies match to change the field of view.")
    end

    ui.separator("Player (Zombies match)")
    if ui.button("Give all perks") then
        run("perks")
    end
    ui.same_line()
    if ui.button(fly.active() and "Noclip: on" or "Noclip: off") then
        run("noclip")
    end
    local speed = fly.speed()
    if speed then
        ui.same_line()
        local submitted, text = ui.input("Fly speed##flyspeed", state.fly_text or string.format("%.0f", speed),
            {submit = true, width = 80})
        state.fly_text = text
        if submitted then
            local value = tonumber(text)
            if value and value > 0 then
                fly.set_speed(value)
            end
            state.fly_text = nil
        end
    end
    ui.text_disabled("Noclip: move keys fly where you look, Space up, Left Ctrl down.")

    ui.separator("Zombies match")
    if ui.button("Start next round") then
        rounds.start_next()
    end
    ui.same_line()
    if ui.button("Spawn a zombie") then
        rounds.spawn_zombie()
    end
    ui.same_line()
    if ui.button("Kill all zombies") then
        rounds.kill_all()
    end
    ui.same_line()
    if ui.button("Power on") then
        rounds.power_on()
    end
    if ui.button("Pause / resume time") then
        rounds.toggle_pause()
    end
    ui.same_line()
    if ui.button("Wireframe") then
        run("wireframe")
    end

    ui.separator("Dead Ops Arcade")
    local round_changed, round = ui.slider("Round##round", state.round, 1, 100, true)
    if round_changed then
        state.round = round
    end
    ui.same_line()
    if ui.button("Set round") then
        run("SetRound " .. state.round)
    end
    if ui.button("Zombie spawning on / off") then
        run("toggleEnemySpawn")
    end
    ui.same_line()
    if ui.button("Spawn an enemy") then
        run("spawnEnemy")
    end
    ui.text_disabled("Commands answer only in the mode they belong to. Results show in the Console tab.")
end

local function variables_tab(dt)
    local _, filter = ui.input("##varfilter", state.var_filter, {hint = "filter variables", width = -1})
    if filter ~= state.var_filter then
        state.var_filter = filter
        state.values_age = math.huge
    end
    local needle = filter:lower()
    local shown, names = {}, {}
    for _, v in ipairs(vars) do
        if needle == "" or v.name:lower():find(needle, 1, true) then
            shown[#shown + 1] = v
            names[#names + 1] = v.name
            if #shown >= MAX_ROWS then
                break
            end
        end
    end
    refresh_values(names, dt)
    ui.text_disabled(string.format("%d variables shown%s. Values not registered yet appear once the game creates them.",
        #shown, #shown >= MAX_ROWS and " (narrow the filter for more)" or ""))
    ui.child("vars", 0, 0, function()
        ui.table("vartable", 4, function()
            for _, v in ipairs(shown) do
                local value = value_of(v.name)
                ui.next_column()
                ui.text(v.name)
                ui.next_column()
                ui.text_disabled(v.type)
                ui.next_column()
                if v.lookup_only and not value then
                    ui.text_disabled("(lookup only)")
                elseif not value then
                    ui.text_disabled("(not registered)")
                elseif v.type == "bool" then
                    local changed, on = ui.checkbox("##" .. v.name, value == "true")
                    if changed then
                        set_var(v.name, on and "true" or "false")
                    end
                else
                    local submitted, text = ui.input("##" .. v.name, value, {submit = true, width = -1})
                    if submitted then
                        set_var(v.name, text)
                    end
                end
                ui.next_column()
                ui.text_disabled(v.default)
            end
        end)
    end)
end

local function commands_tab()
    local _, filter = ui.input("##cmdfilter", state.cmd_filter, {hint = "filter commands", width = 300})
    state.cmd_filter = filter
    ui.same_line()
    local _, args = ui.input("##cmdargs", state.cmd_args, {hint = "arguments for Run", width = -1})
    state.cmd_args = args
    ui.text_disabled("Commands belong to game systems and only answer while that system exists " ..
        "(many need a match). +name / -name pairs are key presses and releases.")
    local needle = filter:lower()
    ui.child("cmds", 0, 0, function()
        ui.table("cmdtable", 3, function()
            for _, c in ipairs(commands) do
                if needle == "" or c.name:lower():find(needle, 1, true) then
                    ui.next_column()
                    ui.text(c.name)
                    ui.next_column()
                    ui.text_disabled(c.owner or "")
                    ui.next_column()
                    if ui.button("Run##" .. c.name .. c.id) then
                        run(state.cmd_args ~= "" and (c.name .. " " .. state.cmd_args) or c.name)
                    end
                end
            end
        end)
    end)
end

-- A mistake inside a tab shows in the log instead of switching the window off (the runtime turns
-- off handlers that raise errors). Repeated errors are reported once.
local last_error

events.on("frame", function(dt)
    if not state.open then
        return
    end
    local ok, still_open = pcall(ui.window, "Developer console",
        {x = 40, y = 40, w = 980, h = 580, closable = true},
        function()
            ui.tab_bar("developer", function()
                ui.tab("Console", console_tab)
                ui.tab("Cheats", function() cheats_tab(dt) end)
                ui.tab("Variables", function() variables_tab(dt) end)
                ui.tab("Commands", commands_tab)
            end)
        end)
    if not ok then
        if still_open ~= last_error then
            last_error = still_open
            fail("Developer console error: " .. tostring(still_open))
            log(tostring(still_open))
        end
        return
    end
    if not still_open then
        set_open(false)
    end
end)

info("BOZ Redux developer console. Type help for help.")
if not console.ready() then
    info("The game console is starting up; commands work once the game has loaded.")
end
