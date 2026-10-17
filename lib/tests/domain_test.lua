-- The domain modules (rounds, score, pickups, zombies, pieces, audio, stats, hud, map, cvars,
-- resources, deadops, player additions) against a fake game: lua5.4 lib/tests/domain_test.lua.
package.path = "lib/?.lua;lib/tests/?.lua;" .. package.path
local fake = require("fake_game").install()
local memory, strings, calls, functions = fake.memory, fake.strings, fake.calls, fake.functions
local address, check, last = fake.address, fake.check, fake.last
local cvar_values, executed = {}, {}
package.loaded["boz.console"] = {
    get = function(n) return cvar_values[n] end,
    register = function(n, v) cvar_values[n] = v return v end,
    exec = function(line) table.insert(executed, line) return "" end,
}

-- The world: the level manager, a player (entity 0x5000, id 7) with health and a controller.
local LEVEL, PLAYER = 0x6000, 0x5000
memory[address("CLevelManager::s_instance")] = LEVEL
memory[LEVEL + 0x1a0] = PLAYER
memory[PLAYER + 4] = 7
local tables = {}
functions[address("CIsComponentTableBase::Find")] = function(t, id) return (tables[t] or {})[id] or 0 end
local function give(class_name, id, component) tables[address(class_name .. "::s_table")] = tables[address(class_name .. "::s_table")] or {} tables[address(class_name .. "::s_table")][id] = component end
give("CHealth", 7, 0x7000)
give("CPlayerController", 7, 0x7100)
memory[0x7000 + 0x48], memory[0x7000 + 0x44] = 230.0, 230
functions[address("CHealth::SetMaxHealth")] = function(h, v) memory[h + 0x44] = v end
memory[0x7100 + 0x1f4], memory[0x7100 + 0x1d4] = 8, 3

-- boz.rounds
local rounds = require("boz.rounds")
local WM, WAVE = 0x8000, 0x8100
memory[address("CWaveManager::s_instance")] = WM
memory[WM + 0x78], memory[WM + 0x84], memory[WM + 0x70], memory[WM + 0x50], memory[WM + 0xb8] = 5, 3, 4, WAVE, 1
local VTABLE = 0x8200
memory[WAVE] = VTABLE
memory[VTABLE + 0x50] = address("fake::GetZombieCount")
functions[address("fake::GetZombieCount")] = function(wave, round, powered) return round == 5 and powered == 1 and 20 or 0 end
memory[VTABLE + 0x4c] = address("fake::GetClassName")
strings[0x8300] = "CWaveRepeatable"
functions[address("fake::GetClassName")] = function() return 0x8300 end
memory[VTABLE + 0x88] = address("fake::IsSpecial")
check(rounds.current() == 5 and rounds.killed() == 3 and rounds.alive() == 4 and rounds.powered(), "round state")
check(rounds.total() == 20 and rounds.zombies_left() == 17, "zombies left from the wave's count")
check(rounds.wave_class() == "CWaveRepeatable" and not rounds.special(), "the wave's class")
check(rounds.go_to(10) and memory[WM + 0x78] == 9, "go to a round")
-- rounds.set: the level's first wave (normal difficulty), followed to round 3 along m_NextWave.
memory[LEVEL + 0x204] = 0x8a00
local h = require("boz.hash").name
local W1, W2, W3 = 0x8d00, 0x8e00, 0x8f00
local by_hash = {[h("w1")] = W1, [h("w2")] = W2, [h("w3")] = W3}
functions[address("Wave_Find")] = function(x) return by_hash[x] or 0 end
memory[W1 + 0x84], memory[W2 + 0x84], memory[W3 + 0x84] = h("w2"), h("w3"), h("w3")
local reflect, real_get = require("boz.reflect"), require("boz.reflect").get
reflect.get = function(at, class_name, field)
    if class_name == "CLevel" and field == "m_StartingWavesSP" then return {h("w0"), h("w1"), h("w0")} end
    return real_get(at, class_name, field)
end
memory[LEVEL + 0x20c] = 1
check(rounds.first_wave() == h("w1") and rounds.wave_for(3) == h("w3") and rounds.wave_for(9) == h("w3"), "the wave chain")
check(rounds.set(3) and memory[WM + 0x78] == 2, "set round")
local sent = last("CIsSubject::NotifyVirtual")
check(sent[2] == WM + 0x20 and memory[sent[4] + 4] == h("w3") and memory[sent[4] + 0x14] == 2, "starts it as round 3")
memory[LEVEL + 0x20c] = 2
reflect.get = real_get
rounds.set_spawning(false)
check(executed[#executed] == "DisableZombieSpawning true", "stop spawning")
rounds.queue("wave1")
check(last("CWaveManager::QueueWave")[3] == require("boz.hash").name("wave1"), "queue a wave")

-- boz.score
local score = require("boz.score")
memory[address("CScoreManager::s_instance")] = 0x8400
functions[address("CIsEntityDB::GetEntity")] = function(e) return e == PLAYER and 0x5800 or 0 end
functions[address("Entity_GetNameHash")] = function(r) return r == 0x5800 and 0xabcdef or 0 end
local points = 2500
functions[address("CScoreManager::GetLocalScore")] = function() return points end
functions[address("CScoreManager::AddScore")] = function(m, id, delta) if id == 0xabcdef then points = points + (delta >= 0x80000000 and delta - 0x100000000 or delta) end end
check(score.add(500) == 3000, "add points to the player's record hash")
check(score.spend(1000) and points == 2000 and not score.spend(5000), "spend")
check(score.set(100) == 100, "set")

-- boz.pickups
local pickups = require("boz.pickups")
memory[address("CPickupManager::s_instance")] = 0x8500
memory[0x8500 + 0xb8], memory[0x8500 + 0xbc] = 1000, 0
check(pickups.spawn("max_ammo", {x = 1, y = 2, z = 3}) and last("CPickupManager::SpawnPickupAt")[3] == 2, "spawn by name")
check(memory[last("CPickupManager::SpawnPickupAt")[4] + 0xac] == 2, "at the position")
check(pickups.give("insta_kill") and last("CPickupManager::ApplyPickup")[3] == PLAYER and last("CPickupManager::ApplyPickup")[4] == 1, "give")
local active = pickups.active()
check(active.insta_kill == 1000 and active.double_points == nil, "active timers")
check(not pickups.spawn("nothing", {0, 0, 0}), "an unknown power-up says so")

-- boz.zombies
local zombies = require("boz.zombies")
check(zombies.count() == 0, "no zombies")
give("CAIControllerZombie", 9, 0x7400)
memory[0x5100 + 4] = 9
local z = zombies.of(0x5100)
check(z and z:freeze() and last("CIsSubject::NotifyVirtual")[2] == 0x7430, "an effect goes to the controller's subject")
memory[0x7400 + 0x158] = 15
check(z:dying() and z:state() == 15, "dying state")
memory[0x7400 + 0xb7] = 1
check(z:frozen() and not z:burning(), "frozen flag")
check(zombies.of(PLAYER) == nil, "the player is no zombie")
give("CIsCrowdAgent", 9, 0x7500)
check(z:teleport({x = 10, y = 20, z = 30}) and last("CrowdAgent_Place")[2] == 0x7500
      and last("CrowdAgent_Place")[3] == hook.float_bits(10), "teleport places its crowd agent")
check(z:kind() == "zombie" and zombies.count("all") == 0, "kinds")
memory[LEVEL + 0x204] = 0x8a00
memory[0x8a00 + 0x68], memory[0x8a00 + 0x6c], memory[0x8b00] = 0x8b00, 0x8b04, 0xc0ffee
memory[address("g_game")] = 0x8c00
memory[0x8c00 + 0xd4], memory[0x8c00 + 0xd8] = 0x1000, 5
check(#zombies.looks() == 1 and zombies.looks()[1] == 0xc0ffee, "the level's looks")
check(select(2, zombies.spawn("zombie", {1, 2, 3})) == "not spawned", "spawn reports a failed spawn")
local info = last("CWaveManager::OnSpawnZombie")[3]
check(memory[info + 8] == 0x1005 and memory[info + 0x14] == 0xc0ffee and memory[info + 0x1c] == 1
      and memory[info + 0x28] == 1.0 and memory[0x8c00 + 0xd8] == 6, "the spawn info: a new name, a look, the position")

-- boz.player
local player = require("boz.player")
local hp, max = player.health()
check(hp == 230.0 and max == 230, "player health")
check(player.set_health(500, true) and memory[0x7000 + 0x44] == 500 and memory[0x7000 + 0x48] == 500, "set health raising the max")
check(player.stance() == "downed" and player.downed(), "downed")
memory[0x7100 + 0x1d4] = 0x14
check(not player.downed() and player.dead(), "dead is not downed")
player.set_speed("SprintSpeed", 3)
check(cvar_values.SprintSpeed == "3", "speed")
give("CPerkManager", 7, 0x7200)
memory[0x7200 + 0x58] = 0x4         -- Juggernog
check(player.take_perk("Juggernog") and last("PerkManager_SetOwned")[2] == 0x7200 + 0x4c and last("PerkManager_SetOwned")[3] == 0
      and memory[0x7000 + 0x44] == 250, "take a perk: its bit, Juggernog's health")
check(not player.take_perk("Deadshot"), "a perk the player lacks")

-- boz.map
local map = require("boz.map")
strings[LEVEL + 0x55] = "Kino"
memory[LEVEL + 0x20c] = 2
check(map.name() == "kino" and map.difficulty() == "hard" and not map.dead_ops(), "level info")
map.kino.teleport("lobby")
check(executed[#executed] == "StartTeleportLobby", "Kino teleport")

-- boz.audio
local audio = require("boz.audio")
memory[address("CMusicManager::s_instance")] = 0x8600
memory[address("CIwSoundManager::s_instance")] = 0x8700
check(audio.music("115.mp3", {loop = true}) and last("Music_Play")[3] == "blackops-music/115.mp3" and last("Music_Play")[4] == 1, "music by file")
check(audio.play("begin_wave", {x = 1.5, y = 2, z = 3}) and memory[last("CIwSoundManager::Play")[4]] == 1, "a positioned sound (whole centimetres)")

-- boz.stats and boz.resources
local stats = require("boz.stats")
memory[address("g_iwResManager")] = 0x8800
functions[address("CIwResManager_GetResNamed")] = function(m, name, kind) return name == "BOGravity" and kind == "CAchievement" and 0x8900 or 0 end
memory[0x8900 + 0x24], memory[0x8900 + 0x28] = 10, 3
local progress, target = stats.progress("BOGravity")
check(progress == 3 and target == 10 and not stats.unlocked("BOGravity"), "achievement progress")
check(stats.unlock("BOGravity") and last("Achievement_SetProgress")[3] == 10, "unlock")
check(require("boz.resources").find("BOGravity", "CAchievement") == 0x8900, "a resource by name")

-- boz.cvars
local cvars = require("boz.cvars")
check(cvars.info("SprintSpeed").type ~= nil, "a variable's info")
cvars.set("UnlimitedScore", true)
check(cvar_values.UnlimitedScore == "true", "set a bool")
check(#cvars.find("zombie") > 10 and #cvars.commands() > 50, "find and commands")

-- boz.hud, boz.pieces, boz.deadops load
require("boz.hud").show("Insta_Kill_Image")
check(last("HUD_SetElementVisible")[2] == "Insta_Kill_Image" and last("HUD_SetElementVisible")[3] == 1, "hud element")
check(#require("boz.pieces").perks() == 0, "pieces")
require("boz.deadops").set_round(7)
check(executed[#executed] == "SetRound 7", "Dead Ops round")
print("domain_test: OK")
