-- Runs every standard library test: lua5.4 lib/tests/run.lua (from the SDK root).
local failed = 0
local handle = io.popen("ls lib/tests/*_test.lua")
for path in handle:lines() do
    local ok = os.execute("lua5.4 " .. path .. " > /tmp/boz_lua_test.log 2>&1")
    local name = path:match("([%w_]+)_test%.lua$")
    if ok then
        print("ok    " .. name)
    else
        failed = failed + 1
        print("FAIL  " .. name)
        for line in io.lines("/tmp/boz_lua_test.log") do
            print("      " .. line)
        end
    end
end
handle:close()
os.remove("/tmp/boz_lua_test.log")
os.exit(failed == 0 and 0 or 1)
