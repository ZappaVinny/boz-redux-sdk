# Standard library

The standard lib (`boz.*`) is the friendly layer for writing mods: plain functions for the
player, menus, the console and more, with the game's addresses, offsets and events hidden
inside. Mods should use it instead of the client's low-level `game`/`hook` functions
([client Lua API](lua-mods.md#client-lua-api)) wherever it covers what they need.

This page is generated from the comments in `lib/boz/*.lua` (`tools/stdlib/generate_doc.py`); see
[Lua mods](lua-mods.md) for how to use it in a mod.

Using it in a mod: an SDK project's build adds it to the mod as `scripts/boz`; then
`local player = require("boz.player")`. Each mod carries its own copy; copies in different
mods work together.

Functions that need a Zombies match return `nil` (or `false`) outside one instead of failing.

## Contents

- **Gameplay**: [boz.player](#bozplayer), [boz.camera](#bozcamera), [boz.rounds](#bozrounds), [boz.zombies](#bozzombies), [boz.weapons](#bozweapons), [boz.effects](#bozeffects), [boz.score](#bozscore), [boz.pickups](#bozpickups), [boz.pieces](#bozpieces), [boz.map](#bozmap), [boz.fly](#bozfly), [boz.deadops](#bozdeadops)
- **Map scripting**: [boz.world](#bozworld), [boz.prefabs](#bozprefabs), [boz.objects](#bozobjects), [boz.match_events](#bozmatch_events), [boz.timers](#boztimers), [boz.saved](#bozsaved), [boz.hooks](#bozhooks), [boz.game](#bozgame), [boz.levels](#bozlevels)
- **Engine access**: [boz.entities](#bozentities), [boz.components](#bozcomponents), [boz.reflect](#bozreflect), [boz.resources](#bozresources), [boz.physics](#bozphysics), [boz.game_events](#bozgame_events), [boz.spawns](#bozspawns), [boz.audio](#bozaudio), [boz.screen](#bozscreen), [boz.hud](#bozhud), [boz.stats](#bozstats), [boz.saves](#bozsaves), [boz.network](#boznetwork)
- **Controls**: [boz.input](#bozinput)
- **Console**: [boz.console](#bozconsole), [boz.cvars](#bozcvars)
- **Menus and text**: [boz.pause_settings](#bozpause_settings), [boz.text](#boztext)
- **Game UI building blocks**: [boz.iwui](#boziwui), [boz.frontend](#bozfrontend), [boz.flash](#bozflash), [boz.swf](#bozswf), [boz.avm1](#bozavm1)
- **Low-level helpers**: [boz.hash](#bozhash), [boz.enums](#bozenums)

## Gameplay

### boz.player

The local player in a Zombies match: health, place, stance, speed and perks.

```lua
local player = require("boz.player")
player.give_all_perks()
player.health()  player.set_health(500, true)  player.set_god(true)
player.position()  player.teleport({x = 0, y = 250, z = 0})
player.downed()  player.stance()  player.set_speed("SprintSpeed", 1.5)
```

<details><summary>How it works</summary>

the player's entity is CLevelManager +0x1a0; its CHealth keeps its health (+0x48 float, +0x44 the most it can be now; CHealth::SetHealth changes it the game's way); CPlayerController keeps the stance at +0x1f4 (1 standing, 2 crouching, 4 prone, 8 downed / last stand; SetStance changes it) and its state machine's state at +0x1d4 (0x14, 0x15: dead); movement speeds are console variables read every step (WalkSpeed, SprintSpeed, CrouchSpeed, ProneSpeed and their Aim* and Perked* (Stamin-Up) forms, LastStandSpeed); UnlimitedHealth makes it invulnerable.

</details>

| Function | Description |
| --- | --- |
| `player.in_match()` | True while a Zombies match with a local player is running. |
| `player.name_hash()` | The player's name hash (Entity_GetNameHash of its entity record): how scores, kills and events name the player. nil outside a match. |
| `player.health()` | The player's health and the most it can have, or nil outside a match. |
| `player.set_health(value, raise_max)` | Sets the player's health; raise_max also raises the most it can have to it. |
| `player.set_god(on)` | Makes the player take no damage (true) or normal damage again (the UnlimitedHealth cvar). |
| `player.god()` | True while the player takes no damage. |
| `player.position()` | The player's position {x, y, z} (game centimetres, y up: the camera, about 136 above the feet). |
| `player.teleport(position)` | Moves the player (a position like player.position()'s). |
| `player.stance()` | The stance name ("standing", "crouching", "prone", "downed"), or nil. |
| `player.set_stance(name)` | Sets the stance ("standing", "crouching" or "prone"; the camera height follows). |
| `player.downed()` | True while the player is down (last stand) and not dead. |
| `player.dead()` | True once the player died (the match is ending). |
| `player.kill()` | Kills the player (the game's KillPlayer). |
| `player.speed(name)` | A movement speed (one of player.SPEEDS) as the game reads it. |
| `player.set_speed(name, value)` | Sets a movement speed (one of player.SPEEDS; it applies at once). Returns the value kept. |
| `player.set_unlimited_stamina(on)` | Unlimited sprint (true) or the game's stamina again (the UnlimitedStamina cvar). |
| `player.unlimited_stamina()` | True while sprinting is unlimited. |
| `player.PERKS` | The perk names, in the game's order. |
| `player.perks()` | The perks the player owns, by name ({["Juggernog"] = true, ...}), or nil outside a match. |
| `player.give_perk(name)` | Gives a perk by name (with its effects, e.g. Juggernog's health). False if not possible. |
| `player.give_all_perks()` | Gives every perk the player is missing. Returns the names given, or nil outside a match. |
| `player.take_perk(name)` | Takes a perk away (as losing it when downed does: its icon goes, Juggernog's extra health too). False if the player does not have it. |
| `player.take_all_perks()` | Takes every perk away (the game's ResetAllPerks: icons and health back to normal). |

### boz.camera

The field of view and camera shakes.

```lua
camera.set_fov(90)                        kept across matches; aiming down sights still zooms
camera.fov()                              the field of view and the map's default
camera.shake("romero-transform-shake")    George's transform shake (every map: misc group)
camera.shake("explosion-large")           a Dead Ops shake (a map build bundles it by name)
camera.stop_shake()
```

The game's shakes (CCameraShakeConfig resources): romero-transform-shake (misc, so every map), explosion-large and explosion-lightning-bolt (Dead Ops). Fields: duration (ms, below 0: until stopped), limit (the most it moves, x y z), switchInterval and rollInterval (ms between new offsets), rollLimit.

<details><summary>How it works</summary>

CCameraShake (singleton) plays one config at a time (CameraShake_Play(shake, name): +0x20 the config, +0x24 endless, +0x28 time left); each frame it picks offsets (+0x34 x y z, +0x40 roll) that CCameraProcessorShake adds to the camera's matrix when the camera update event reaches it. Field of view: CWeaponManager::UpdateFov eases the current FOV (+0xc0) up toward the base FOV (+0xc4, copied from the map's camera at match start) or down to the weapon's sights; it never lowers the current FOV by itself and skips the camera write once it arrived, so changing the base and setting the current FOV just below it makes the next update land on the new value.

</details>

| Function | Description |
| --- | --- |
| `camera.FOV_RANGE` | The range of field of view the game handles well (degrees). |
| `camera.shake(name)` | Shakes the camera with a shake config by name. Returns false when it is not loaded. |
| `camera.stop_shake()` | Stops the shake. |
| `camera.shaking()` | True while a shake plays. |
| `camera.fov()` | The field of view in degrees and the map's default, or nil outside a match. |
| `camera.set_fov(degrees)` | Sets the field of view in degrees (aiming down sights still zooms); nil restores the map's default. The value is kept across matches. Returns false outside a match (it still applies when the next match starts). |

### boz.rounds

Rounds and the match (Zombies mode).

```lua
rounds.current()            the round number          rounds.zombies_left()
rounds.set(10)              rounds.start_next()       rounds.set_spawning(false)
rounds.wave()               the round's settings (zombies, health, speeds, ...)
rounds.on_start(fn)         rounds.on_end(fn)
```

<details><summary>How it works</summary>

CWaveManager (singleton) runs the rounds: +0x50 the round's CWave, +0x70 zombies alive, +0x78 the round number, +0x7c spawned and +0x84 killed this round (the round ends when killed reaches the wave's zombie count: vtable +0x50 GetZombieCount(round, powerOn)), +0x88 the next round's wave, timers +0x8c (next spawn), +0x90 (next round), +0x94 (spawning starts), +0xb8 power on. A round starts with SUBJECT_NEW_WAVE (CWaveManager::StartWave: the next wave, round + 1; WaveManager_FillNextWave picks the next wave or a special round) and ends with SUBJECT_WAVE_ENDED. The new-wave info SUBJECT_NEW_WAVE carries (a StartWaveInfo): +4 the wave, +8 / +0xc a special round's health and count, +0x10 the wave after it, +0x14 the round it follows. The Game tab sets a map's rounds (docs/map-editor.md, Game rules).

</details>

| Function | Description |
| --- | --- |
| `rounds.manager()` | The round manager (CWaveManager), or nil outside a match. |
| `rounds.current()` | The round number (0 before the first round), or nil outside a match. |
| `rounds.alive()` | Zombies alive now. |
| `rounds.spawned() return read(SPAWNED)` | Zombies spawned this round. |
| `rounds.killed() return read(KILLED)` | Zombies killed this round. |
| `rounds.powered()` | True once the power is on. |
| `rounds.wave_pointer()` | The round's wave (a CWave resource: boz.reflect fields of its class), or nil. |
| `rounds.wave_class()` | The round's wave class ("CWave", "CWaveRepeatable", "CWaveSpeciality", "CWaveMonkey"). |
| `rounds.special()` | True during a special round (dogs, monkeys). |
| `rounds.total()` | How many zombies the round has in all (as the game counts it, with the power's extra ones). |
| `rounds.zombies_left()` | Zombies still to kill this round. |
| `rounds.wave()` | The round's settings: every field of its wave class by name (boz.reflect), plus "class". |
| `rounds.set_wave(field, value)` | Changes a setting of the running round's wave (e.g. "m_ZombieHealth"); it lasts until the level loads again. Returns true, or false and why. |
| `rounds.timers()` | Milliseconds until the next spawn, until the next round starts, and until spawning starts. |
| `rounds.special_history()` | The round the last special round ran in, and how many have run. |
| `rounds.start_next()` | Starts the next round now, as the game does when the pause between rounds ends: the next wave of the chain (or a special round when one is due), round + 1; zombies left over go. Returns false outside a round. (The console's StartWave needs a wave name: without one it stops the rounds.) |
| `rounds.first_wave()` | The level's first wave (its name hash): the level's starting wave for the difficulty (CLevel m_StartingWavesSP: easy, normal, hard), else "wave1". |
| `rounds.wave_for(number)` | The wave round `number` plays (its name hash): the level's first wave, followed along each wave's next wave (a repeating wave stays, growing with the round number). Special rounds are not counted. |
| `rounds.set(number)` | Starts round `number` now (1 or more): its wave from the level's chain, zombie count and health as that round has them; zombies left over go. Returns false outside a match. |
| `rounds.go_to(number)` | Makes the next round started be round `number` (its wave stays the chain's next one; the repeating round's growth and the game's health use the number). |
| `rounds.queue(wave)` | Queues a wave by name or hash (one of the level's CWave resources: "wave1", "boz_normal_3", ...) as the next round. |
| `rounds.on_start(fn)` | Calls fn(round) when a round starts. Returns a handle (boz.game_events.off). |
| `rounds.on_end(fn)` | Calls fn(round) when a round's last zombie dies. |
| `rounds.set_spawning(on)` | Stops (false) or resumes (true) zombie spawning: no new zombie appears, the round waits (DisableZombieSpawning; CWaveManager::CreateZombie checks it). |
| `rounds.spawning()` | True while zombies spawn (rounds.set_spawning). |

### boz.zombies

The zombies (and dogs, monkeys, George) alive in the match.

```lua
for z in zombies.each() do if z:health() < 100 then z:kill() end end
zombies.count()          zombies.nearest(position)
zombies.on_death(fn)     fn(zombie_entity) when one dies
zombies.kill_all()       zombies.credit_kills("SUBJECT_ZOMBIE_GERSCH_DEATH")
zombies.spawn("zombie", spawns.nearest(pos):position(), {health = 500, speed = "sprint"})
zombies.spawn("zombie_dog", at)      zombies.spawn_george(at)      zombies.dogs()
```

Spawn on the navmesh (a spawn point's position is safe): an AI that cannot reach the navmesh dies within seconds.

A handle (zombies.each(kind), zombies.of(entity)): z.entity, z:kind(), z:get(field) / z:set(field, value) (its AI controller's reflected fields), z:position(), z:health(), z:max_health(), z:set_health(n), z:damage(n), z:kill(), z:alive(), z:teleport(position), z:component(class) (any of its components: CHealth, CIsCrowdAgent, ... for boz.reflect). Zombies also: z:set_speed(tier), z:crawler(), z:state(), z:dying(), the game's effects (z:freeze(), z:shatter(), z:burn(), z:explode(), z:lightning(), z:gersch(), z:shockwave()), z:frozen(), z:burning(), z:human(), z:send(event).

<details><summary>How it works</summary>

each kind has its AI controller class (zombies.KINDS); CWaveManager::OnSpawnZombie spawns one from a ZombieSpawnInfo (CreateZombie: the round's health and speed, a look, tracked for the round when it counts); a plain zombie's spec comes from its look (CZombieConfiguration +0x58). George spawns through the wave manager's boss spawn (+0xb4 holds him). Every zombie has a CAIControllerZombie (its table lists them; +0x9d crawler, +0xc4 its transform, +0xd4 its health, +0xec its broadcaster, +0x30 its subject: the weapons' and traps' effects arrive there as events (CAIControllerZombie::OnEvent), +0x150 its state machine; AIGodmode makes zombies ignore damage); CHealth keeps its health (+0x48 float, +0x44 the most it can be now, set by CreateZombie from the round; +0x40 m_MaxHealth the spec's) and takes damage with CHealth::Damage(health, amount, attacker name hash): it sends SUBJECT_HEALTH_DECREASE to itself and the zombie dies below 1 (SUBJECT_DIED, then SUBJECT_ZOMBIE_DEATH from the level manager with its name hash). SUBJECT_DIED adds a kill to the player's stats (STAT_ZOMBIESKILLED) only when the attacker is the local player's name hash; deaths the game deals itself (a black hole's SUBJECT_ZOMBIE_GERSCH_DEATH, chain lightning, traps) pass none.

</details>

| Function | Description |
| --- | --- |
| `zombies.KINDS` | The kinds of AI and their controller classes. |
| `Zombie:kind()` | Its kind: "zombie", "dog", "monkey" or "george". |
| `Zombie:alive()` | True while it is still in the match. |
| `Zombie:get(field)` | A field of its AI controller (reflected: dogs' attackingRadius, monkeys' m_damage, George's m_zombieModeDamageMultiplier, ...), and setting one. |
| `Zombie:set(field, value)` | Sets a field of its AI controller. Returns true, or false and why. |
| `Zombie:component(class_name)` | One of its components by class (CHealth, CPathWalker, ...), or nil. |
| `Zombie:health_component()` | Its CHealth component, or nil. |
| `Zombie:position()` | Its position {x, y, z}. |
| `Zombie:teleport(position)` | Moves it (on the navmesh: its crowd agent is placed there too, so it walks on from the new spot). Returns false when it has no crowd agent. |
| `Zombie:health()` | Its health and the most it can have. |
| `Zombie:max_health()` | The most health it can have now. |
| `Zombie:damage(amount)` | Hurts it (as if the player did, so the kill counts). Returns the zombie. |
| `Zombie:kill()` | Kills it. |
| `Zombie:set_health(value)` | Sets its health (up to its maximum, z:max_health(); zombies.spawn's health raises it). |
| `Zombie:set_speed(tier)` | Sets its speed tier: "walk", "walk_fast", "run" or "sprint" (or 0-3), as rounds pick them. |
| `Zombie:send(event, a, b, c)` | Sends the zombie's own subject an event (what the game's weapons and effects do to it). |
| `Zombie:freeze() return self:send("SUBJECT_ZOMBIE_SPAWN_ICE")` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:shatter() return self:send("SUBJECT_ZOMBIE_ICE_SHATTER")` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:burn() return self:send("SUBJECT_START_BURNING", 0, 1, 1)` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:explode() return self:send("SUBJECT_ZOMBIE_TRIGGER_FULL_BODY_EXPLOSION")` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:lightning() return self:send("SUBJECT_ZOMBIE_CHAIN_LIGHTNING_DEATH")` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:gersch() return self:send("SUBJECT_ZOMBIE_GERSCH_DEATH")` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:shockwave() return self:send("SUBJECT_ZOMBIE_SHOCKWAVE_DEATH")` | Effects the game has for zombies (each as its weapons and traps do it): freeze() encases it in ice (it shatters and dies after ZombieFreezeTimeMS), shatter() breaks a frozen one, burn() sets it on fire (looks only; the kill is damage's), explode() blows it apart (the human gun's death), lightning() (chain lightning death), gersch() (black hole death), shockwave() (Thundergun death). Not wrapped: SUBJECT_ZOMBIE_TURN_HUMAN crashes outside Call of the Dead (the human model is not set up), SUBJECT_FORCE_ZOMBIE_DEATH damages by a field that is usually 0 (use kill()). |
| `Zombie:human()` | True once the human gun turned it. |
| `Zombie:frozen()` | True while frozen in ice. |
| `Zombie:burning()` | True while on fire. |
| `Zombie:state()` | Its AI state number (CIsStateMachine at +0x150): 2 chasing, 13 frozen, 15 dying, 21 dead. |
| `Zombie:dying()` | True once it is dying (or dead). |
| `Zombie:crawler()` | True for a crawler (legs gone). |
| `zombies.of(entity)` | The AI handle of an entity (a zombie, dog, monkey or George), or nil. |
| `zombies.each(kind)` | Iterates the zombies: for z in zombies.each() do ... end. `kind` picks another kind ("dog", "monkey", "george") or "all". |
| `zombies.list(kind)` | Every one of a kind (default zombies), as a list. |
| `zombies.count(kind)` | How many of a kind (default zombies) are in the match. |
| `zombies.nearest(position)` | The zombie nearest a position, and its distance. |
| `zombies.dogs() return zombies.list("dog")` | Every hellhound, and every monkey, in the match. |
| `zombies.monkeys() return zombies.list("monkey")` | Every hellhound, and every monkey, in the match. |
| `zombies.george()` | George (Call of the Dead's boss) while he is in the match, or nil. |
| `zombies.spawn(spec, position, options)` | Spawns one AI the way rounds do (health from the round and difficulty, speed tier, look): `spec` is "zombie" (or nil: a zombie in one of the level's looks) or an entity spec ("zombie_dog", "zombie_dog_flaming", "zombie_monkey"), at a position. options: look (a CZombieConfiguration name or hash: zombies.looks()), health (instead of the round's), speed ("walk" .. "sprint"), counts (true: it is one of the round's zombies, so killing it counts toward the round), powered (a powered zombie: the round's powered health). Needs a round running. Returns its handle, or nil and why. |
| `zombies.spawn_at_point(point, counts)` | Spawns one of the round's own zombies at a spawn point (its entity name; nil: the game picks a spawn point near the player). counts: it is one of the round's (default false: an extra). |
| `zombies.looks()` | The level's zombie looks (CZombieConfiguration hashes; zombies spawn in one at random), from the level's CLevel. |
| `zombies.spawn_george(position)` | Spawns George (Call of the Dead's boss, entity spec george_romero) at a position, as the round does. Returns his handle, or nil and why (his spec must be loaded: a map built with zombies.spawn_george in its scripts bundles it). |
| `zombies.within(position, radius)` | Zombies within `radius` centimetres of a position. |
| `zombies.on_death(fn)` | Calls fn(entity, name_hash) when a zombie dies (SUBJECT_ZOMBIE_DEATH: its second argument is the zombie's name hash; the entity may already be gone, then nil). Returns a handle (boz.game_events.off). |
| `zombies.kill_all(kind)` | Kills every living AI of a kind (default "all"), each as if the player did (the kills count). Returns how many. |
| `zombies.spawn_one()` | Spawns one zombie the game's way (SpawnZombie: at a spawn point near the player). |
| `zombies.set_invulnerable(on)` | Makes zombies and the other AI unhurtable (true) or normal again (the AIGodmode cvar). |
| `zombies.credit_kills(event)` | Makes the kills a zombie deals itself while handling `event` count as the player's (stats, achievements), e.g. "SUBJECT_ZOMBIE_GERSCH_DEATH" for the zombies a black hole takes. The game kills them with CHealth::Damage and no attacker; that damage becomes the player's. |

### boz.weapons

The local player's weapons during a match: the one in hand, ammo, live stats,

giving weapons, and events when weapons are equipped, given, fired and reloaded.

```lua
local weapons = require("boz.weapons")
local gun = weapons.current()               -- nil outside a match
if gun then gun:set_ammo(gun:clip_size(), 999) end
weapons.give("thundergun")    weapons.upgrade("mp40")    weapons.take("mp40")
weapons.on_event(function(event, name) print(event .. " " .. name) end)
```

Weapons are named as in the editor's Weapons tab ("mp40", or "0x..." for an unnamed one). Changes made here last for the match; the Weapons tab changes the weapons for good.

<details><summary>How it works</summary>

the player's CWeaponManager sits on a child of the player entity (+0x48 = the player); its weapons are CPlayerWeapon components found by name hash (WeaponManager_FindWeapon, map at +0x1d4), the one in hand at +0x1e0. CWeaponManager::GiveWeapon(manager, hash, slot, refill) equips one; EquipWeapon sends SUBJECT_WEAPON_EQUIPPED; the fire button fires through CPlayerController::FireWeapon (hip), FireWeaponAimed (aiming down sights) or FireWeaponAlternate; CWeaponManager::SetReloading starts a reload. A CPlayerWeapon keeps its rounds at +0x2c (clip) and +0x30 (reserve), its clip size at +0x80, reserve size at +0x84, fire rate at +0x200 (rounds per minute) and CWeaponDamage at +0x20c (head +4, torso +8, limbs +0xc).

</details>

| Function | Description |
| --- | --- |
| `weapons.know(list)` | Tell boz.weapons the names of weapons (the map's world data does this for its weapons). |
| `weapons.name(name_hash)` | A weapon's name from its hash ("0x..." when boz.weapons does not know it: weapons.know). |
| `weapons.manager()` | The local player's weapon manager, or nil outside a match. |
| `Weapon:upgrade_name()` | The name of its Pack-a-Punched version, or nil when it has none. |
| `Weapon:clip() return game.read("u32", self.pointer + CLIP)` | Rounds in the clip and spare rounds; the most each can hold. |
| `Weapon:reserve() return game.read("u32", self.pointer + RESERVE)` | Rounds in the clip and spare rounds; the most each can hold. |
| `Weapon:clip_size() return game.read("u32", self.pointer + CLIP_SIZE)` | Rounds in the clip and spare rounds; the most each can hold. |
| `Weapon:reserve_size() return game.read("u32", self.pointer + RESERVE_SIZE)` | Rounds in the clip and spare rounds; the most each can hold. |
| `Weapon:set_ammo(clip, reserve)` | Sets the rounds in the clip and in reserve (nil keeps one). Returns the weapon. |
| `Weapon:fire_rate() return game.read("u32", self.pointer + FIRE_RATE)` | Fire rate in rounds per minute (automatic fire modes). |
| `Weapon:set_fire_rate(rounds_per_minute)` | Sets the fire rate for this match. Returns the weapon. |
| `Weapon:damage()` | Damage per hit: head, torso, limbs. |
| `Weapon:set_damage(head, torso, limbs)` | Sets the damage per hit for this match (nil keeps one). Returns the weapon. |
| `Weapon:in_hand()` | True while this is the weapon in hand. |
| `weapons.current()` | The weapon in the player's hands, or nil. |
| `weapons.get(name)` | The player's weapon called *name* (every weapon of the map is there, owned or not), or nil. |
| `weapons.guard_missing_animations()` | Makes equipping a weapon whose animations are not loaded (another map's: the AllWeapons command, weapons.give) safe: the game looks its animation ids up in a missing state machine (Anim_FindId through a null pointer); this answers "not found" (0xffff) instead. weapons.give calls it. |
| `weapons.give(name)` | Gives the player *name* and puts it in hand, with full ammo. Returns false outside a match or when the map has no such weapon. |
| `weapons.slot_of(name)` | The slot a weapon the player holds is in ("primary", "secondary", ...), or nil. |
| `weapons.take(name)` | Takes a weapon away from the player. The one in hand: the other gun comes up (false when it is the only gun); grenades and tactical: none left (the slot keeps the kind, with 0). Returns true when taken. |
| `weapons.upgrade(name)` | Pack-a-Punches a weapon the player holds (the upgraded version replaces it in its slot, full ammo), as the machine does but free and at once. Returns false when it has no upgrade. |
| `weapons.slot(name)` | The weapon in a slot ("primary" = in hand, "secondary", "melee", "grenade", "tactical"), or nil. |
| `weapons.owned()` | The player's weapons by slot: {primary = weapon, secondary = ..., ...} (empty slots left out). |
| `weapons.grenades()` | Grenades and tactical grenades (monkey bombs, Gersch devices, ...) the player has. |
| `weapons.set_grenades(grenades, tacticals)` | Sets the grenades (and tactical grenades; nil keeps one). |
| `weapons.refill(name)` | Refills every weapon and the grenades (what max ammo does), or one weapon by name. |
| `Weapon:get(field)` | A field of the weapon's CPlayerWeapon by name (boz.reflect: m_clipSize, m_spreadMin, ...). |
| `Weapon:set(field, value)` | Sets a field of the weapon's CPlayerWeapon for this match. Returns true, or false and why. |
| `Weapon:fields()` | Every field of the weapon's CPlayerWeapon. |
| `weapons.on_event(fn)` | Calls fn(event, weapon name, data) on "equipped", "given", "fired" (data.clip: rounds left before the shot) and "reloaded" of the local player's weapons. Returns a handle for off(). |
| `weapons.off(handle)` | Stops a handler on_event() returned. |

### boz.effects

Spawning the game's effects and projectiles anywhere, for as long as you want.

```lua
local effects = require("boz.effects")
effects.spawn("impactRayGun", {x = 0, y = 50, z = 0})            -- a one-off effect
local hole = effects.projectile("gersch", effects.aim(), {trigger = "open", lifetime = 6})
hole:remove()                                                    -- close it early
effects.explode(position, {radius = 400, damage = 2000})          -- a grenade's blast
```

Names are the game's effect and projectile names ("gersch_Effect", "impactRayGun", "iceShatter", ...; any map's: the build bundles what scripts name, and the editor's Effects tab lists them and can give them your own names), or "0x..." hashes.

Effects are visual (particles); projectiles bring the game's behaviour with them: a Gersch device opens a black hole that pulls zombies in and kills them, a monkey bomb lures them, a bolt explodes where it hits. What a projectile answers to (its triggers, effects.TRIGGERS) depends on what it is: "open" (black hole), "explode" (grenades, bolts). The game kills zombies a black hole takes without naming the player: boz.zombies.credit_kills makes those kills count as the player's.

<details><summary>How it works</summary>

Spawn_ByHash creates any entity spec a loaded group holds (boz.entities.spawn); a projectile's CProjectileEntity keeps its live lifetime (ms) at +0xc0 (m_bHasLifeTime turns it on), its open state at +0xc7, its owner at +0x88, its rigid body at +0x80 (Bullet body +0x34); events go to its subject at +0x28 (SUBJECT_SPAWN_GERSCH_EFFECT opens a Gersch device and restarts its lifetime a frame later, SUBJECT_EXPLODE, SUBJECT_TERMINATE ends it with its own sounds). The crosshair point is the weapon manager's +0xcc (WeaponManager_UpdateAim ray-casts it every frame; +0xf0: a live zombie). A spawned entity's components are set up by the game a little later (CProjectileEntity::Init links its transform at +0x7c, subscribes to its events and finds its rigid body): a projectile gets its trigger and lifetime once that has happened; its owner (+0x88) right away, as the game's own launcher does (zombies turning to a device read it).

</details>

| Function | Description |
| --- | --- |
| `effects.EXPLOSIONS` | Projectiles that explode (every map's weapon projectiles group has them). |
| `effects.TRIGGERS` | What a projectile answers to: the event it is sent, and whether the game restarts its lifetime when it arrives (a Gersch device's lifetime starts again once it has opened). |
| `effects.know(list)` | Tell boz.effects the map's effects: {name, hash, kind, behaviour, triggers} each (the map's world data does this at level start). |
| `effects.known()` | The map's effects by name ({hash, kind, behaviour, triggers}). |
| `Effect:alive()` | True while it is still in the world. |
| `Effect:projectile()` | Its CProjectileEntity component, or 0 for a plain effect. |
| `Effect:ready()` | True once the game has set it up (a projectile takes a frame or so after spawning; scripts need not wait: what was asked for happens then). |
| `Effect:position()` | Its position {x, y, z} (game centimetres, y up), or nil once it is gone. |
| `Effect:move(position)` | Moves it to a position. |
| `Effect:trigger(name)` | Sends a trigger (effects.TRIGGERS: "open", "explode"). A projectile still being set up gets it as soon as it is. Returns false when it does not answer that trigger or is gone. |
| `Effect:set_visible(visible)` | Shows or hides its own model (a projectile's behaviour and the effects it spawns stay). |
| `Effect:hide() return self:set_visible(false)` | Hides or shows its own model. |
| `Effect:show() return self:set_visible(true)` | Hides or shows its own model. |
| `Effect:freeze()` | Stops a projectile where it is (it no longer falls or rolls), once the game has set it up. |
| `Effect:lifetime(seconds)` | Removes it after this many seconds from now. A projectile ends the game's way (a black hole closes with its own sound and effect). |
| `Effect:remove()` | Removes it now (a projectile ends the game's way). |
| `effects.spawn(name, position, options)` | Spawns an effect at a position {x, y, z}. Options: rotation {x, y, z, w}, lifetime (seconds, then it is removed). Returns the effect, or nil and why. |
| `effects.projectile(name, position, options)` | Spawns a projectile at a position and lets the game run it. Options: trigger (e.g. "open"), lifetime (seconds; after a trigger), raise (centimetres: it floats that far above the position, and its proximity reach grows to match, so zombies walking under a black hole still die; for one that "Stays where spawned"), hidden (its own model is not drawn), freeze (stay where spawned instead of settling on the floor), lift (centimetres up, default 10; raise replaces it), rotation. It is the player's (zombies turning to a device ask for its owner, so it always has one). What it was asked for happens once the game has set it up (a frame or so). Returns the projectile, or nil and why. |
| `effects.explode(position, options)` | An explosion at a position, the player's (its kills count; it hurts the player too, at OwnExplosionDamageModifier percent, like their own grenade). Options: radius (centimetres; default the grenade's), inner (full damage within it), damage (the most, at the centre), min_damage (at the edge), kind (effects.EXPLOSIONS: "frag", the default, "raygun", "claymore", "monkey"), quiet (no explosion effect). Returns the explosion's projectile, or nil and why. |
| `effects.aim()` | The point the player's crosshair is on {x, y, z} (where a shot lands; up to 100 m away) and whether it is a live zombie; nil outside a match. |

### boz.score

Points (Zombies mode).

```lua
score.get()          the player's points        score.add(500)   score.spend(950)
score.set(10000)     score.points_for("SUBJECT_ZOMBIE_SCORE_KILL_HEAD")
score.on_change(fn)  fn(points, delta) after every change
score.free_purchases(3)   purchases cost nothing for 3 seconds
```

<details><summary>How it works</summary>

CScoreManager (singleton) keeps each player's points in a map keyed by the player's name hash (Entity_GetNameHash of its entity record; +0x40; earned points for stats at +0x4c): GetLocalScore(manager) reads the local player's, AddScore(manager, player, delta, countForStats) changes them (clamped at 0; purchases cost nothing with the UnlimitedScore cvar) and calls OnScoreChanged(manager, score, player, delta) for the HUD. Points for actions come from the score table (CScoreConfig, the ScoreConfigName cvar; the Game tab's economy changes a map's own): ScoreConfig_GetScore.

</details>

| Function | Description |
| --- | --- |
| `score.manager()` | The score manager (CScoreManager), or nil outside a match. |
| `score.get()` | The local player's points, or nil outside a match. |
| `score.add(points, counts)` | Gives the player points (negative takes them, never below 0). counts: also count them as earned (stats, power-up drops). Returns the new points. |
| `score.spend(points)` | Takes points for a purchase; false (and nothing taken) when the player has too few. |
| `score.set(points)` | Sets the player's points. |
| `score.points_for(action)` | Points the map's score table gives for an action ("SUBJECT_ZOMBIE_SCORE_HIT", ...). |
| `score.on_change(fn)` | Calls fn(points, delta) after every change of the local player's points. Returns fn. |
| `score.free_purchases(seconds)` | Makes purchases cost nothing for `seconds` from now (the UnlimitedScore cvar: the score manager skips every charge), then restores the cvar. Calling it again extends the time. |

### boz.pickups

Power-ups (Zombies mode).

```lua
pickups.spawn("max_ammo", position)    drops one there for the player to collect
pickups.give("insta_kill")             as if the player collected it
pickups.active()                       {insta_kill = ms left, double_points = ..., ...}
pickups.on_collect(fn)                 fn(name) when the player collects one
```

Names: double_points, insta_kill, max_ammo, nuke, carpenter, firesale, deathmachine, perkbottle, lightningbolt (the game's order). How often they drop is the Game tab's economy (docs/map-editor.md, Game rules).

<details><summary>How it works</summary>

CPickupManager (singleton) spawns them with SpawnPickupAt(manager, type, transform, offset) (the spec <name>_pickup at the transform's position +0xa8 plus the offset) and applies a collected one with ApplyPickup(manager, player, type, sound): it sets the timers (+0xb8 insta-kill, +0xbc double points, +0xc0 fire sale, +0xc4 death machine, +0xc8 carpenter points; milliseconds, from the InstaKillTime / DoublePointsTime / FireSaleTime / DeathMachineTime / CarpenterScoreTime cvars), refills ammo, sends the nuke or carpenter, gives the death machine or lightning bolt weapon or a perk.

</details>

| Function | Description |
| --- | --- |
| `pickups.manager()` | The pickup manager (CPickupManager), or nil outside a match. |
| `pickups.spawn(name, position)` | Drops a power-up at a position {x, y, z} for the player to collect. Returns true, or false and why. |
| `pickups.give(name)` | Applies a power-up as if the local player collected it. Returns true, or false and why. |
| `pickups.active()` | The timed power-ups running now: {insta_kill = ms, double_points = ms, firesale = ms, deathmachine = ms, carpenter = ms} (only those with time left). |
| `pickups.set_time(name, ms)` | Sets how long a running timed power-up lasts from now (ms; 0 ends it). |
| `pickups.on_collect(fn)` | Calls fn(name, player_entity) whenever a power-up is collected (SUBJECT_ON_PICKUP: its first argument points at {?, player id +4, type +8, sound +0xc}). Returns a handle (boz.game_events.off). |

### boz.pieces

The map's interactive pieces: mystery boxes, perk machines, doors, traps, wall buys,

Pack-a-Punch, power switches, barricades, landers, turrets, flingers, teleporters, ...

```lua
for box in pieces.each("CMysteryBox") do log(box:get("m_Cost")) end
local box = pieces.active_box()                 -- the box that is out
box:set("m_Cost", 500)
pieces.perks()[1]:use()                         -- as if the player pressed use there
pieces.doors()                                  -- every door, with :get("m_DoorState")
```

A piece handle: piece.entity, piece.class, piece.component, piece:get(field), piece:set(field, value), piece:fields() (every field and value), piece:position(), piece:use(), piece:name_hash(), piece:send(event), piece:cost(), piece:use_free() (opens, buys, spins without points); boxes :spawn_box() / :despawn_box() (pieces.move_box(to)), Pack-a-Punch :spawn_pack_a_punch() / :despawn_pack_a_punch(), barricades :fix_barricade() (pieces.fix_all_barricades()), doors :is_open() (pieces.open_all_doors()). The fields are the game's (reflected): docs/map-editor.md (Game prefab fields) explains them; boz.reflect has the rest.

<details><summary>How it works</summary>

each kind is a component class (its table lists them). "Use" is what the game does when the player presses use at a point of interest (Poi_SendUse: the point of interest in reach, boz.map.nearest_poi, broadcasts the interact event with the player's name hash); the piece reacts as if the player used it (checking the points, paying, opening, buying). A free use credits the cost first (the piece checks the points a frame before it charges them), uses it a frame later with purchases free (boz.score.free_purchases) and takes the credit back.

</details>

| Function | Description |
| --- | --- |
| `pieces.DOOR_OPEN` | A door's m_DoorState when it is open. |
| `Piece:get(field)` | A field of its component (by name). |
| `Piece:set(field, value)` | Sets a field of its component. Returns true, or false and why. |
| `Piece:fields()` | Every field and its value. |
| `Piece:position()` | Its position {x, y, z}. |
| `Piece:name_hash()` | Its name hash (what the World tab named it, hashed). |
| `Piece:use()` | Uses it as the player would (the game charges the cost and does the rest). Returns true when the use was sent. |
| `Piece:cost()` | What using it costs (points), or nil for a piece without a cost. |
| `Piece:use_free()` | Uses it for free: opens a door, buys the perk, spins the box, buys the wall weapon, switches a trap on, ... without the player losing points (purchases are free for a few seconds around the use). Returns true when queued. |
| `Piece:send(event, a, b)` | Sends the piece's entity an event (boz.entities.send): "SUBJECT_MB_SPAWN", ... |
| `Piece:spawn_box() return self:send("SUBJECT_MB_SPAWN")` | A mystery box: brings it out here (SUBJECT_MB_SPAWN) or puts it away (SUBJECT_MB_DESPAWN: it leaves with its own animation once nobody is using it; m_IsDespawning). |
| `Piece:despawn_box() return self:send("SUBJECT_MB_DESPAWN")` | A mystery box: brings it out here (SUBJECT_MB_SPAWN) or puts it away (SUBJECT_MB_DESPAWN: it leaves with its own animation once nobody is using it; m_IsDespawning). |
| `Piece:box_weapons()` | A mystery box's weapons (name hashes; m_Weapons). |
| `Piece:add_box_weapon(weapon)` | Adds a weapon (name or hash) to a mystery box's pool (SUBJECT_MB_ADD_WEAPON), or takes one out (SUBJECT_MB_REMOVE_WEAPON). The map's own pool is the Weapons tab's; this lasts the match. |
| `Piece:remove_box_weapon(weapon)` | Takes a weapon out of a mystery box's pool (SUBJECT_MB_REMOVE_WEAPON). |
| `Piece:spawn_pack_a_punch() return self:send("SUBJECT_PACKAPUNCH_SPAWN")` | Pack-a-Punch: brings it out (SUBJECT_PACKAPUNCH_SPAWN) or puts it away. |
| `Piece:despawn_pack_a_punch() return self:send("SUBJECT_PACKAPUNCH_DESPAWN")` | Pack-a-Punch: brings it out (SUBJECT_PACKAPUNCH_SPAWN) or puts it away. |
| `Piece:fix_barricade() return self:send("SUBJECT_BARRICADE_FIX")` | A barricade: puts one board back (SUBJECT_BARRICADE_FIX). |
| `Piece:is_open()` | A door: true once it is open. |
| `pieces.open_all_doors()` | Opens every closed door for free. Returns how many were opened. |
| `pieces.move_box(to)` | Moves the mystery box to another box spot (a piece of CMysteryBox, or the spot's entity name; nil: a random other spot), putting the current one away. Returns true when sent, or false and why. |
| `pieces.fix_all_barricades()` | Fixes every barricade fully (like the carpenter, without the points). |
| `pieces.each(class_name)` | Iterates the pieces of a class: for piece in pieces.each("CPerk") do ... end |
| `pieces.list(class_name)` | Every piece of a class, as a list. |
| `pieces.of(target, class_name)` | The piece of a class an entity has (or the entity called that name), or nil. |
| `pieces.boxes() return pieces.list("CMysteryBox")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.perks() return pieces.list("CPerk")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.doors() return pieces.list("CDoor")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.traps() return pieces.list("CTrap")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.wall_buys() return pieces.list("CWeaponChalkOutline")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.pack_a_punch() return pieces.list("CPackAPunch")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.power_switches() return pieces.list("CPowerSwitch")` | Every piece of a kind: mystery boxes, perk machines, doors, traps, wall buys, power switches; pack_a_punch() is the map's Pack-a-Punch machine (nil without one). |
| `pieces.active_box()` | The mystery box that is out now (m_IsActive), or nil. |
| `pieces.summary()` | Every piece of every kind: {[class] = count} for the classes the map has. |

### boz.map

The level being played, and the map systems the game has commands for.

```lua
map.name()            "kino", "ascension", "callofthedead", "tutorial" or a map project's
map.difficulty()      "easy", "normal" or "hard"        map.dead_ops()
map.player()          the local player's entity and id
map.on_level_start(fn)                                   fn() each time a level has started
map.restart()         map.power_on()                    map.fog("fog_name")
map.toggle_pause()    map.set_time_scale(0.5)
map.kino.teleport("lobby")      map.ascension.gersch_teleport()      map.ascension.launch_rocket()
map.callofthedead.lighthouse(state)
```

<details><summary>How it works</summary>

CLevelManager (singleton) keeps the level's name at +0x55, the local player's entity at +0x1a0, the level's CLevel resource at +0x204, Dead Ops Arcade at +0x208, the difficulty at +0x20c (0 easy, 1 normal, 2 hard: the single-player starting wave and the zombies' health multiplier), the point of interest in reach at +0x214 (an entity) and whether the level started from a save at +0x298. The map systems are the game's developer commands (StartTeleportLobby, GerschTeleportRandom, RocketLaunch, LighthouseState, SwitchFog, RestartLevel, SwitchPowerOn, TimeTogglePause, TimeFactor) run through boz.console; docs/console-reference.md lists every command.

</details>

| Function | Description |
| --- | --- |
| `map.level_manager()` | The level manager (CLevelManager), or nil outside a level. |
| `map.name()` | The level's name (lower case), or nil. |
| `map.name_address()` | The address of the level manager's name text (what the game's own name checks compare). |
| `map.player()` | The local player's entity and its id, or nil outside a Zombies match. |
| `map.level_info()` | The level's CLevel resource (its starting waves, zombie looks, ...), or nil. |
| `map.difficulty_index()` | The difficulty's index (0 easy, 1 normal, 2 hard), or nil. |
| `map.difficulty()` | "easy", "normal" or "hard" (single player), or nil. |
| `map.dead_ops()` | True in Dead Ops Arcade. |
| `map.playing()` | True while a level with a player is running. |
| `map.resuming()` | True when the running level was started from a save (continuing a game). |
| `map.nearest_poi()` | The point of interest in reach (an entity: the box, a perk, a door the player can use), or 0. |
| `map.set_nearest_poi(entity)` | Makes an entity the point of interest in reach (what the use button acts on). Returns the previous one. |
| `map.level_key()` | A number that changes when another level starts (0 outside a match). |
| `map.on_level_start(fn)` | Calls fn() every time a level has started (its player exists), and at once when one is running. Returns fn. |
| `map.restart()` | Restarts the level. |
| `map.power_on()` | Turns the power on. |
| `map.fog(name)` | Switches to a fog config by name (the level's CIwFogConfig resources, as rounds use them). |
| `map.toggle_pause()` | Pauses or resumes game time. |
| `map.set_time_scale(factor)` | Game speed multiplier (1 = normal). |
| `map.kino` | Kino der Toten. |
| `map.kino.teleport(kind)` | Starts a teleport ("lobby": back to the lobby, "projector": to the projector room, "random": to a random room). |
| `map.ascension` | Ascension. |
| `map.ascension.gersch_teleport()` | Sends the player to a random Gersch teleport point. |
| `map.ascension.launch_rocket()` | Authenticates and launches the rocket. |
| `map.callofthedead` | Call of the Dead. |
| `map.callofthedead.lighthouse(state)` | Sets the lighthouse's state (its beam searching for the Pack-a-Punch). |

### boz.fly

Noclip, using the game's developer fly mode.

```lua
local fly = require("boz.fly")
fly.set(true)                       -- fly through walls; movement keys fly where you look
fly.move_vertical(1, dt)            -- call each frame while an "up" key is held
```

<details><summary>How it works</summary>

CPlayerFreeFly toggles on SUBJECT_PLAYER_FREE_MODE (sent to CInputManager's subject); while flying, movement moves the player along the view at FreeFlySpeed and SUBJECT_PLAYER_ASCEND raises it by FreeFlySpeed (sent here with the speed scaled and signed).

</details>

| Function | Description |
| --- | --- |
| `fly.available()` | True if fly mode can be used now (a Zombies match whose player has the fly component). |
| `fly.active()` | True while flying. |
| `fly.set(on)` | Turns fly mode on or off (nil toggles). Returns the new state, or nil if unavailable. |
| `fly.speed()` | Fly speed (FreeFlySpeed): distance per frame at full speed. |
| `fly.set_speed(speed)` | Sets the fly speed (FreeFlySpeed). |
| `fly.move_vertical(direction, dt)` | Moves up (direction 1) or down (-1) for dt seconds at fly speed. Call it every frame while a key is held. |

### boz.deadops

Dead Ops Arcade (the top-down mode).

```lua
deadops.active()            deadops.set_round(12)        deadops.set_god(true)
deadops.score()             deadops.set_score(100000)    deadops.health()
deadops.spawn_enemy()       deadops.toggle_spawning()    deadops.spawn_pickup()
deadops.horde()             every field of the horde manager (spawn timers, horde size, ...)
deadops.storage()           the persistent storage: stats and power timers
```

<details><summary>How it works</summary>

Dead Ops runs in the same level manager with CLevelManager +0x208 set. Its systems are singletons (CDORoundManager, CDOHordeManager, CDOPickupManager, CDOPersistentStorage, CDOPlayerInput, CDOGoreManager) and components (CDOPlayer: m_Score; CDOHealth: maxHealth, m_Health; CDOPlayerController: walking body, helicopter, tank; CDOAIController for enemies), all reflected (boz.reflect). The rounds are 42 CDORound resources (arena, lighting, music, hordes). The developer commands (SetRound, GodMode, ManyLives, InfiniteBombBoost, spawnEnemy, toggleEnemySpawn, spawnPickup, SpawnDeathGems, AutoAim) run through boz.console.

</details>

| Function | Description |
| --- | --- |
| `deadops.active()` | True in Dead Ops Arcade. |
| `deadops.set_round(number)` | Jumps to a round (the SetRound command). |
| `deadops.set_god(on)` | God mode on or off (the GodMode command toggles it; this asks for a state). Returns the state. |
| `deadops.many_lives()` | Many lives (the ManyLives command). |
| `deadops.infinite_bombs()` | Unlimited bombs and speed boosts (InfiniteBombBoost). |
| `deadops.spawn_enemy() return exec("spawnEnemy")` | Spawns an enemy (spawnEnemy). |
| `deadops.toggle_spawning() return exec("toggleEnemySpawn")` | Switches enemy spawning on or off (toggleEnemySpawn). |
| `deadops.spawn_pickup() return exec("spawnPickup")` | Spawns a pickup (spawnPickup). |
| `deadops.spawn_gems() return exec("SpawnDeathGems")` | Spawns death gems (SpawnDeathGems). |
| `deadops.auto_aim() return exec("AutoAim")` | Switches auto aim (AutoAim). |
| `deadops.score()` | The local player's score (CDOPlayer m_Score), or nil. |
| `deadops.set_score(points)` | Sets the local player's score. |
| `deadops.health()` | The local player's health and maximum (CDOHealth), or nil. |
| `deadops.horde()` | The horde manager's fields (spawn timers, horde size, pickups this round, ...), or nil. |
| `deadops.storage()` | The persistent storage's fields (stats, the player body / shield / speed shoes timers), or nil. |
| `deadops.enemies()` | The enemies alive: {entity, health component} for each CDOAIController. |

## Map scripting

### boz.world

Game behaviour a map project's world asks for that the game's data cannot express.

```lua
require("boz.world").start()   (map projects call this from main.lua; the SDK adds it)
```

The map's objects: the editor writes each map's start state and scripted objects into boz/world_data.lua (hidden objects, objects without collision, walkable areas that start blocked, scripts and their property values); as soon as each level has started this applies the start state with boz.objects and starts the scripts with boz.prefabs.

Perk machines that work without power: the editor's "Needs power" off writes the power switch name "boz_no_power". The game only powers a machine when its power switch is turned on (Quick Revive in solo is the exception), so when such a machine starts this powers it the same way (CPerk +0x7c powered, +0x7d lit, and the machine's own "power_switch_on" event for its lights and jingle).

| Function | Description |
| --- | --- |
| `world.start()` | Turns on what map projects need from the standard library (call once, from main.lua), and starts the mod's map when the launcher asked for it (its "autostart_level" setting). |

### boz.prefabs

Scripts for the map's prefabs, models, volumes and weapons, and the event bus

between them. Map scripts see this module as `boz`; docs/map-editor.md (Map scripting) is the guide.

```lua
function on_hit(volume, info)              -- in a script attached to a prefab
    self:part("Door"):hide():set_collision(false):open_navmesh()
    boz.send("vault_open", {by = self.name})
end
```

Each scripted object runs its script once with its own `self` and top-level variables. Script globals and boz.globals are saved with the game. Handlers: start(), on_enter / on_exit / on_hit / on_use(volume, info), on_event(name, data) (boz.send and boz.match_events' events; "weapon_fired" only reaches boz.on); weapon scripts: on_given, on_equip, on_fire(data), on_reload. Every volume event also reaches boz.on listeners as "<volume>.<event>".

<details><summary>How it works</summary>

the client's loadscript(name, env) loads a script with a fresh environment per object (self and boz in it, the mod's globals behind it). Volumes are boz.objects events. Use prompts: when a Use volume becomes the point of interest in reach (SUBJECT_POI_TRIGGER, handled by CIngameStatePlaying::UpdatePoiPrompt, whose handling is skipped for it) its prompt is shown with Poi_ShowPrompt. Saving: CSaveManager::SaveGame (autosave at each round start, pause) writes the globals to the map mod's settings (globals.<level>); a level started from a save (boz.map.resuming) runs start() once the save is applied. Hooks here are before hooks where they can be: an after hook's return trap on a long, busy function crashed the game.

</details>

| Function | Description |
| --- | --- |
| `prefabs.globals` | Values every script of the map shares, saved with the game. |
| `Instance:part(name)` | The boz.objects handle of a part of this prefab (by its name in the prefab). |
| `Instance:parts()` | {name, object} of every part of this prefab. |
| `Instance:set_visible(visible)` | Shows or hides the object (every part of a prefab). Returns self. |
| `Instance:show() return self:set_visible(true)` | Shows the object. Returns self. |
| `Instance:hide() return self:set_visible(false)` | Hides the object. Returns self. |
| `Instance:set_collision(enabled)` | Switches the collision of the object (every part of a prefab). Returns self. |
| `Instance:set_navmesh(open)` | Opens or closes the walkable area under the object (and its parts that block it). Returns self. |
| `Instance:open_navmesh() return self:set_navmesh(true)` | Lets zombies and players walk where the object blocked them. Returns self. |
| `Instance:close_navmesh() return self:set_navmesh(false)` | Blocks the walkable area under the object again. Returns self. |
| `Instance:position()` | The object's world position {x, y, z} (game centimetres, y is up): a prefab's is the middle of its parts. nil when it is not in the running level. |
| `Instance:near(target, distance)` | True when the object (any part of a prefab) is within `distance` centimetres of `target` (a position such as zombie_killed's data.position, or another object). |
| `Instance:send(name, data)` | boz.send from this object. |
| `prefabs.find(name)` | The scripted object called *name* (its script instance), else its boz.objects handle when it exists in the level, else nil. |
| `prefabs.send(name, data)` | Sends an event on the bus: every boz.on(name) listener and every script's on_event. |
| `prefabs.on(name, fn)` | Calls fn(data, name) on every boz.send(name, ...). Returns fn. |
| `prefabs.after(seconds, fn)` | Runs fn() once, `seconds` of game time from now (boz.timers). Returns a timer with :cancel(). |
| `prefabs.every(seconds, fn)` | Runs fn() every `seconds` of game time until the timer is cancelled (boz.timers). |
| `prefabs.save()` | Writes the map's saved globals now (the game's saves call this). |
| `prefabs.start(list, all_names, weapon_list)` | Starts the level's objects (boz.world calls this when a level has started, with the map's world_data objects, the names of all its objects and its weapons). |

### boz.objects

The map's objects by name: show and hide them, switch their collision, open and

close the walkable area under them, and react when players walk into them, use them or shoot them. The building blocks for triggers and easter eggs.

```lua
local objects = require("boz.objects")
local skull = objects.get("Skull_1")
skull:on("use", function(object) object:hide() end)
objects.on("Secret_Room_Trigger", "enter", function(object, who)
    if who.player then objects.get("Secret_Wall"):hide():set_collision(false):open_navmesh() end
end)
```

Names are the script names the editor shows for each object (Properties → Object → Game → Scripts): turn on "Scripts can change it" there. Shipped entities use their own names.

<details><summary>How it works</summary>

- CIsEntityDB::FindEntity(name hash) gives the entity (a pointer; its id is at +4). A

</details>

```lua
component's entity pointer is at component +0xc; children hang off CIsHierarchy +0x24.
```

- Visibility: CIsRenderableModel::SetVisible (doors hide this way after opening). - Collision: CIsCollisionObject::Enable / Disable on the entity's collision box, sphere,

```lua
capsule or mesh (what SUBJECT_ENABLE/DISABLE_COLLISION do).
```

- Walkable area: navmesh polygons carry a tag (a name hash); NavMesh_SetTagOpen(navmesh, tag,

```lua
open) opens or closes them, as doors do with their own name. The editor tags the polygons
under objects set to block the walkable area with the object's name.
```

- "enter"/"exit": CIsCollisionObject::OnCollisionEnter/OnCollisionExit (this, other) run

```lua
when two collision objects start or stop touching; ghost volumes (triggers) get them too.
```

- "use": Poi_SendUse runs when the player presses use at the point of interest in reach

```lua
(boz.map.nearest_poi).
```

- "damage": CHealth::Damage(health, amount, attacker name hash) on objects with health. - "hit": CEasterEgg::OnEvent runs when a weapon hits a skull (Hit volumes are made from the

```lua
musical easter egg's skulls); for objects with "hit" handlers the game's handling is skipped,
so they stay out of the level's own easter egg.
```

- Positions: the entity's CIsTransform keeps its world matrix at +0x38, the position at

```lua
+0x5c/+0x60/+0x64 (game centimetres, y up); CIsTransform::UpdateWorld refreshes it when the
transform moved.
```

| Function | Description |
| --- | --- |
| `objects.level()` | A key that changes when another level loads (0 outside a match). |
| `objects.get(name)` | The object called `name` (a handle: it finds the entity when used, so it can be made before the level loads). Names are not case-sensitive. |
| `objects.find(name)` | The object called `name` if it exists in the running level, else nil. |
| `Object:entity_pointer()` | The entity pointer, or 0 when the object is not in the running level. |
| `Object:exists()` | True when the object is in the running level. |
| `Object:set_visible(visible)` | Shows or hides the object's models (its collision and behaviour stay). Returns the object. |
| `Object:show()` | Shows the object. Returns the object. |
| `Object:hide()` | Hides the object. Returns the object. |
| `Object:set_collision(enabled)` | Switches the object's collision on or off (players and bullets pass through it when off). Returns the object. |
| `objects.set_navmesh(tag, open)` | Opens (true) or closes (false) the walkable area tagged `tag` (a name: an object set to block the walkable area, or a door). Returns true when the level has a navmesh. |
| `Object:set_navmesh(open)` | Opens or closes the walkable area under the object (it must be set to block the walkable area in the editor). Returns the object. |
| `Object:open_navmesh()` | Lets zombies and players walk where the object blocked them. Returns the object. |
| `Object:close_navmesh()` | Blocks the walkable area under the object again. Returns the object. |
| `objects.transform_position(transform)` | The world position of a CIsTransform component: {x, y, z} in game centimetres (y is up). |
| `objects.position_of(entity)` | The world position of an entity (pointer), or nil when it has no transform. |
| `objects.distance(a, b)` | The distance in centimetres between two positions or objects (anything with :position()), or nil when either has no position. |
| `Object:position()` | The object's world position {x, y, z} (game centimetres, y is up), or nil when it is not in the running level. |
| `Object:near(target, distance)` | True when the object is within `distance` centimetres of `target` (a position such as zombie_killed's data.position, or another object). |
| `Object:on(event, fn)` | Calls `fn(object, info)` on the object's `event`: "enter" / "exit" (something starts or stops touching it; info.player, info.zombie, info.entity), "use" (the player pressed use at it), "hit" (a weapon hit it: Hit volumes), "damage" (it was hurt; info.amount, info.attacker). Returns the object. |
| `objects.on(name, event, fn)` | objects.on(name, event, fn): the same as objects.get(name):on(event, fn). |

### boz.match_events

What happens in a Zombies match, as named events with plain data.

```lua
local match_events = require("boz.match_events")
match_events.on("zombie_killed", function(data) if data.headshot then log("headshot") end end)
match_events.on_any(function(name, data) log(name) end)
```

Events and their data:

```lua
"round_started" {round = n}, "round_ended" {round = n}, "power_on",
"perk_bought" {perk = "Juggernog", player = true}, "door_opened" {door = name, hash = n},
"zombie_killed" {position = {x, y, z}, entity = e, by_player = true, headshot = true},
"player_downed", "player_revived", "player_hit" {damage = n},
"weapon_given", "weapon_equipped", "weapon_fired", "weapon_reloaded" {weapon = "mp40"},
"points_earned" / "points_spent" {points = n, player = true},
"box_weapon" / "pack_a_punch" {weapon = "mp40"}, "powerup_grabbed" {powerup = "nuke",
player = true}, "nuke", "carpenter", "trap_activated", "teleporter_activated",
"game_loaded" (a continued save has been applied).
```

While the game applies a save its own events are not news: none are sent.

<details><summary>How it works</summary>

rounds start in CWaveManager::StartWave; perks with CPerkManager::GainPerk for a perk not yet owned (bits at +0x58); zombies die entering CAIControllerZombie::State_Dead (state event 1): its transform at +0xc4, killer entity at +0x138, hit location at +0x124 (0 head), kill kind at +0x22c (0/1 knife, 2 grenade); points earned go through CScoreManager::AddScore; power-ups through CPickupManager::ApplyPickup; continuing a save, CSaveManager::NotifyLoad. Doors (a CDoor whose m_DoorState became open), the power and the player's downed state are checked each frame; the rest are the game's own SUBJECT_* events (boz.game_events).

</details>

| Function | Description |
| --- | --- |
| `match_events.on(name, fn)` | Calls fn(data, name) every time the event happens. Returns a handle for off(). |
| `match_events.on_any(fn)` | Calls fn(name, data) on every event. Returns a handle for off(). |
| `match_events.off(handle)` | Stops a handler on() or on_any() returned. |
| `match_events.know_names(list)` | Tells it the names of the map's objects, so door_opened names its door. |
| `match_events.loading()` | True while the game applies a continued save. |

### boz.timers

Run code later, on game time (paused time does not count).

```lua
local timers = require("boz.timers")
local t = timers.after(5, function() log("five seconds of play later") end)
timers.every(1, function() log("tick") end)
t:cancel()
```

<details><summary>How it works</summary>

game time advances by the frame's time in frames where CPlayerController::FixedStep ran (the game's simulation step, which stops while paused).

</details>

| Function | Description |
| --- | --- |
| `Timer:cancel()` | Stops the timer. |
| `timers.after(seconds, fn)` | Runs fn() once, `seconds` of game time from now. Returns a timer with :cancel(). |
| `timers.every(seconds, fn)` | Runs fn() every `seconds` of game time until the timer is cancelled. Returns the timer. |
| `timers.now()` | Seconds of game time since the first timer was made. |
| `timers.cancel_all()` | Cancels every timer (a new level starts fresh). |

### boz.saved

Lua tables kept in the mod's settings (saves/mods/<id>.cfg).

```lua
local saved = require("boz.saved")
saved.write("progress.kino", {round = 12, parts = {"plug", "fuse"}})
local progress = saved.read("progress.kino")
```

Numbers, strings, booleans and tables of those are kept; functions, handles and loops are left out. Tables are stored as Lua table text in chunks (a settings line holds up to 4 KB).

| Function | Description |
| --- | --- |
| `saved.saveable(value, seen, depth)` | A copy of a value with only what can be saved (nil when nothing can). |
| `saved.encode(value)` | A saveable value as Lua text (keys sorted, so the same table gives the same text). |
| `saved.decode(text)` | The table a text from saved.encode holds, or nil. |
| `saved.write(key, value)` | Writes a table under a key of the mod's settings. |
| `saved.read(key)` | The table written under a key, or nil. |

### boz.hooks

A map's hook scripts (the Game tab's Hooks list).

```lua
scripts/hooks/<event>.lua returns a function; it runs every time the event happens, with
the event's data (see the Game tab or boz.prefabs for each event's data):
```

```lua
  return function(data)
      log("round " .. data.round)
  end
```

boz.world starts the hooks the build found (world_data.hooks: their event names).

| Function | Description |
| --- | --- |
| `hooks.start(names)` | Starts the hook scripts for these event names (each scripts/hooks/<event>.lua). Returns how many started; a script that fails to load is logged and skipped. |

### boz.game

The Game tab's rules a map needs at run time.

```lua
require("boz.game").start(data)   (boz.world calls it with the map's world_data.game)
```

Console variables (points at start, power-up drops and times, the score table, ...) are set just before the map's level loads (Level_Load, when the level manager has the level's name), and the game's own values come back when another level loads, so the map mod can stay enabled. Power on at start runs the game's SwitchPowerOn once the level has started. Repeating rounds' health: the game hard-codes 10 x round^2 - 150 (CWaveRepeatable::GetZombieHealth); with grow_health the round's own data is used instead: health x health multiplier ^ (round - m_StartingWave).

| Function | Description |
| --- | --- |
| `game_rules.active()` | True while the map's own level is loaded (after start()). |
| `game_rules.start(data)` | Applies the map's rules (world_data.game: {cvars, power_on, grow_health, behaves_like, level}). |

### boz.levels

Start levels (Zombies maps) without going through the menus.

```lua
levels.start("kino")      levels.autostart_from_settings()
```

<details><summary>How it works</summary>

the front end's StartLevel console command starts a single-player match on a level by name (it sends the game's own start-game event). The command only works once the front end is running, so levels.start waits for the Flash menu's first ActionScript call and a short settling time. levels.autostart_from_settings reads a one-shot request from the mod's settings: the editor's Build & Run writes it to start the level just saved.

</details>

| Function | Description |
| --- | --- |
| `levels.start(name)` | Starts a single-player match on the level (e.g. "kino") once the front end is up. Call it while the mod's script starts; the match starts after the main menu appears. |
| `levels.autostart_from_settings()` | Starts the level a tool asked for, once: reads and clears the mod's "autostart_level" setting (the SDK's Build & Run writes it), and its "autostart_vars" ("Name=value;..."), console variables set just before the level starts (e.g. UnlimitedHealth=true). Returns the level name or nil. |

## Engine access

### boz.entities

Any entity of the game: find, spawn, move, inspect and remove.

```lua
local entities = require("boz.entities")
local box = entities.find("MysteryBox_Lobby")
print(entities.position(box).x, table.concat(entities.components(box), ", "))
local zombie = entities.spawn("zombie_dog", {x = 0, y = 220, z = 0})
for entity, health in entities.each("CHealth") do ... end
entities.remove(zombie)
```

An entity is the game's object: an id (+4), a name, and components (one per class: CIsTransform for its place, CHealth, CAIControllerZombie, CPerk, ...) kept in one table per class (T::s_table, keyed by the entity id). boz.reflect reads and writes any component's fields by name.

<details><summary>How it works</summary>

CIsEntityDB::FindEntity(name hash) finds one by name (a global map); Spawn_ByHash creates one from any loaded entity spec (CIsEntitySpec, by name or hash) at a position and rotation; EntityDB_Destroy removes one (with its children, at the end of the frame); a component's entity is at component +0xc; a transform keeps its local position at +0xa8, rotation +0x98 (s x y z: the scalar first) and world position at +0x5c (CIsTransform::UpdateWorld refreshes it, Transform_SetDirty marks a change).

</details>

| Function | Description |
| --- | --- |
| `entities.find(name)` | The entity called `name` (or with that name hash) in the running level, or nil. |
| `entities.id(entity)` | An entity's id (+4). |
| `entities.record(entity)` | The entity's record in the entity database (what Entity_GetNameHash and the managers use), or nil once the entity is gone. |
| `entities.alive(id)` | True while the entity with this id is in the world (CIsEntityDB::GetEntity only reads the id at +4, so a removed entity's memory is never touched). |
| `entities.name_hash(entity)` | The hash of an entity's name (the key the score manager and navmesh tags use). |
| `entities.of_component(component)` | The entity a component belongs to. |
| `entities.spec_loaded(spec)` | True when an entity spec (name or hash) is in a loaded group, so it can spawn (Spawn_FindSpec). |
| `entities.spawn(spec, position, rotation)` | Spawns an entity spec (its name, "0x..." hash or hash) at a position {x, y, z} with a rotation {x, y, z, w} (default none). Returns the entity, or nil and why (the spec must be in a loaded group: a map project's build brings every spec its scripts name). |
| `entities.remove(entity)` | Removes an entity (and its children) at the end of the frame. |
| `entities.position(entity)` | The entity's world position {x, y, z} (game centimetres, y up), or nil without a transform. |
| `entities.set_position(entity, position)` | Moves the entity (its local position: the world position for an entity without a parent). |
| `entities.rotation(entity)` | The entity's rotation {x, y, z, w} (a quaternion), or nil. |
| `entities.set_rotation(entity, rotation)` | Turns the entity: a quaternion {x, y, z, w}, or a number (degrees about the vertical axis). |
| `entities.set_visible(entity, visible)` | Shows or hides the entity's own model (CIsRenderableModel::SetVisible: its collision and behaviour stay). Returns false when it has no model. |
| `entities.component(entity, class_name)` | The entity's component of a class ("CHealth", "CPerk", ...), or nil. |
| `entities.components(entity)` | The classes of the components an entity has (that the library knows a table for). |
| `entities.each(class_name)` | Iterates the entities with a component of a class: for entity, component in each("CHealth"). |
| `entities.send(entity, event, a, b)` | Sends an event (a name such as "SUBJECT_SPAWNPOINT_ACTIVATE", or an id) to one entity, the way hits and uses reach it (CIsBroadcaster::Send on its broadcaster). Returns false when the entity has no broadcaster. |
| `entities.nearest(class_name, position)` | The nearest entity with a component of a class to a position, its component and distance. |

### boz.components

Finding the game's entity components (helper for the other modules).

Most mods use boz.player and friends instead. components.local_player() gives the local player's entity; components.on_player(table) or components.each(table) find components by the gamedef name of their table (e.g. "CPerkManager::s_table").

<details><summary>How it works</summary>

component tables (T::s_table) keep components in a red-black tree keyed by entity id: header node pointer at table +4 (header +8 = first node), nodes link parent +4, left +8, right +0xc, key +0x10, component +0x14.

</details>

| Function | Description |
| --- | --- |
| `components.local_player()` | The local player's entity and its id, or nil outside a Zombies match (boz.map.player). |
| `components.table(name)` | The address of a component table by its gamedef name ("CPerkManager::s_table") or class ("CPerkManager"), or nil when the game has no such table. |
| `components.find(table_name, id)` | The component of an entity id in a table (by gamedef name, e.g. "CPerkManager::s_table", or class name). |
| `components.on_player(table_name)` | The component on the local player's entity, or nil. |
| `components.each(table_name)` | Iterates the components in a table (its gamedef name, or its address): for component, id in components.each(name) do ... end |

### boz.reflect

Every reflected field of the game, by name.

```lua
local reflect = require("boz.reflect")
local perk = reflect.component(entity, "CPerk")       -- or an entity id, or an object handle
print(reflect.get(perk, "CPerk", "m_perkSinglePCost"))
reflect.set(perk, "CPerk", "m_perkSinglePCost", 500)
local waves = reflect.singleton("CWaveManager")      -- managers by class name
for name, value in pairs(reflect.dump(perk, "CPerk")) do print(name, value) end
```

The game describes its components and resources to its own reflection system (CIsClassInfo: 359 classes, their bases and fields with offset, size and type); boz/reflection_data.lua holds that description (tools/stdlib/generate_data.py, from the game definition). docs/map-editor.md (Game prefab fields) explains what the fields do.

Types read: unsigned int, int, short, char, unsigned char, bool, float, CIwFVec3 {x, y, z}, CIwFQuat {x, y, z, w}, CIwColour {r, g, b, a}, string (std::string: its characters' pointer first), NetworkProperty<T> (the value at +4; writing marks it changed at +8), vector<T> (begin, end), list<T> (header pointer; nodes: next, previous, value at +8), enums (unsigned int), CIsTimer, bitset (raw bits). Containers and strings are read-only.

| Function | Description |
| --- | --- |
| `reflect.class(name)` | The class description {bases = {{name, offset}}, fields = {[name] = {offset, size, type}}}, or nil. |
| `reflect.classes()` | Every reflected class name, sorted. |
| `reflect.fields(class_name)` | Every field of a class with its bases' fields: {[name] = {offset, size, type, class}}. |
| `reflect.get(object, class_name, field)` | A field's value on an object (a pointer to an instance of the class or a subclass), or nil and why. |
| `reflect.set(object, class_name, field, value)` | Sets a field (numbers, booleans, {x, y, z} vectors, NetworkProperty values). Returns true, or false and why. |
| `reflect.dump(object, class_name)` | Every field's value: {[field] = value}. |
| `reflect.component(target, class_name)` | The component of class `class_name` on an entity (its pointer, {id = entity id}, or a boz.objects / boz.effects handle), or nil. |
| `reflect.singleton(class_name)` | A manager by class name ("CWaveManager", "CPickupManager", ...): its singleton, or nil. |
| `reflect.singletons()` | Every singleton class name the library knows, sorted. |

### boz.resources

The game's loaded resources (anything in the loaded .group files) by name.

```lua
local wave = resources.find("wave1", "CWave")           -- a round's settings
require("boz.reflect").get(wave, "CWave", "m_ZombieCount")
resources.find("BOGravity", "CAchievement")              -- an achievement
resources.group("ingame")                                -- a loaded group
```

Types are the game's resource class names: CWave, CLevel, CZombieConfiguration, CIsEntitySpec, CIwModel, CIwTexture, CIwMaterial, CIwSoundSpec, CIwSoundData, CSoundSequence, CAchievement, CScoreConfig, ... Reflected ones (CIsReflectedResource: waves, levels, zombie configurations, score tables, ...) are readable and writable with boz.reflect by their class; a change lasts until the group loads again.

<details><summary>How it works</summary>

the Marmalade resource manager (its pointer at image +0x492b10) finds resources in every loaded group: CIwResManager_GetResNamed(manager, name, type, flags) and CIwResManager_GetResHashed(manager, hash, type, flags); CIwResManager_GetGroupNamed(manager, name) a loaded group.

</details>

| Function | Description |
| --- | --- |
| `resources.manager()` | The resource manager, or nil before the game set it up. |
| `resources.find(name, type_name)` | A loaded resource by name (or hash, or "0x..." hash) and type, or nil. |
| `resources.loaded(name, type_name)` | True when a resource of that name and type is loaded. |
| `resources.group(name)` | A loaded group by name ("ingame", "kino_statics", ...), or nil. |
| `resources.hash(name)` | The hash the game names resources by (IwHashString). |

### boz.physics

Ray casts against the world and everything in it.

```lua
local hit = physics.raycast(from, to)          -- {position, normal, entity} or nil
physics.ground(position)                       -- the floor under a position (its y), or nil
physics.line_of_sight(a, b)                    -- true when nothing is between two points
```

Positions are {x, y, z} in game centimetres (y up). `filter` chooses what the ray can hit (collision groups as bits; default 0xffffffef: everything but triggers, like bullets).

<details><summary>How it works</summary>

Physics_RayCastAll(from, to, outList, filter, mask) casts through the Bullet world (CIsBulletWorld) and fills a list (STLport: the list object points at a sentinel node; nodes link next +0, previous +4) with every hit: node +8 position, +0x14 normal, +0x20 entity, +0x24 shape, +0x28 distance squared, +0x2c material, sorted nearest first. Nodes and the sentinel come from the game's operator new and go back to its operator delete (list::sort swaps sentinels, so the list's own must be the game's). Physics_RayCast (nine arguments) is what the game's own code uses for the first hit.

</details>

| Function | Description |
| --- | --- |
| `physics.raycast_all(from, to, filter)` | Every hit of a ray from `from` to `to`, nearest first: {{position, normal, entity}, ...}. |
| `physics.raycast(from, to, filter)` | Casts a ray from `from` to `to`. Returns {position, normal, entity} of the first hit, or nil. |
| `physics.ground(position, depth)` | The floor's height (y) under a position, looking down `depth` centimetres (default 2000). |
| `physics.line_of_sight(a, b)` | True when the world blocks nothing between two points. |

### boz.game_events

Every event the game sends itself (its SUBJECT_* observer events).

```lua
local game_events = require("boz.game_events")
game_events.on("SUBJECT_ZOMBIE_DEATH", function(e) log("a zombie died") end)
game_events.on("power_switch_on", function(e) ... end)      -- the SUBJECT_ prefix is optional
game_events.send(subject, "SUBJECT_NUKE_NOW")               -- send one yourself
```

Handlers get {name, id, subject, sender, a, b}: the subject that sent it (a CIsSubject inside a manager or component), the object it is on behalf of, and the event's two arguments (their meaning is per event: docs/game-events.md). A handler that returns true stops the event (no observer gets it): use with care. Most events reach several subjects (the sender's, then the managers' that pass it on); on()'s dedupe options call a handler once per event.

<details><summary>How it works</summary>

every event passes through CIsSubject::Dispatch(subject, event, a, b, sender), which calls the observers subscribed to it; this hooks Dispatch while anything listens (a hook costs nothing while no handler is set). Names: boz/event_names.lua (the game definition's 337 events); ids are the name's IwHashString.

</details>

| Function | Description |
| --- | --- |
| `game_events.id(name)` | The id of an event name ("SUBJECT_ZOMBIE_DEATH", or without the SUBJECT_ prefix). |
| `game_events.name(id)` | The name of an event id, or its id as "0x..." when the game definition does not name it. |
| `game_events.list()` | Every event name the library knows, sorted. |
| `game_events.on(name, fn, options)` | Calls fn(event) every time the game sends the event (a name, or "*" for every event: slow, for exploring). Options: dedupe_frames (call fn once for an event that reaches several subjects: the same event within this many frames is skipped; math.huge: once ever), dedupe_key (fn(event) -> what makes two events the same; default its two arguments). Returns a handle for off(). |
| `game_events.off(handle)` | Stops a handler on() returned. |
| `game_events.send(subject, name, a, b, c)` | Sends an event from a subject (a CIsSubject address: a manager's or component's subject) with its two arguments, the way the game does (CIsSubject::NotifyVirtual). |

### boz.spawns

The zombies' spawn points (Zombies mode).

```lua
for point in spawns.each() do log(point:position().x) end
spawns.set_active(point, false)          zombies stop coming out there
spawns.nearest(position)
```

A spawn point handle: point.entity, point.component, point:position(), point:get(field) (CSpawnPoint: m_StartActive, spawntype, users), point:active(), point:set_active(on).

<details><summary>How it works</summary>

every spawn point is an entity with a CSpawnPoint; opening an area's door sends its spawn points SUBJECT_SPAWNPOINT_ACTIVATE (DEACTIVATE closes them), which CSpawnPoint::OnEvent turns into the active flag at +0x34; CWaveManager spawns zombies at active points.

</details>

| Function | Description |
| --- | --- |
| `Point:position()` | Its position {x, y, z}. |
| `Point:get(field)` | A field of its CSpawnPoint. |
| `Point:active()` | True while zombies can come out here. |
| `Point:set_active(on)` | Lets zombies come out here (true) or not (false). |
| `spawns.each()` | Iterates the spawn points: for point in spawns.each() do ... end |
| `spawns.active()` | The spawn points zombies can come out of now. |
| `spawns.list()` | Every spawn point, as a list. |
| `spawns.set_active(point, on)` | Switches a spawn point (a handle or entity) on or off. |
| `spawns.nearest(position)` | The spawn point nearest a position and its distance. |

### boz.audio

Sounds, sound sequences and music.

```lua
audio.play("gersch_opens", position)       a sound (spec) by name, at a place or everywhere
audio.sequence("dog_wave_start")           a sequence (voice lines, stings, wave starts)
audio.music("115.mp3", {loop = true})      a music track from blackops-music
audio.pause_music()  audio.resume_music()  audio.music_volume(0.5)
```

Music tracks (assets/blackops-music): 115.mp3, a7x.mp3, abracadavre.mp3, mus_theatre_underscore.mp3, mus_gameover.mp3, mus_game_over_element_115.mp3 and the perk and Pack-a-Punch stings (mus_jugganog_sting.mp3, mus_revive_sting.mp3, ...). A map ships its own music by putting an .mp3 in its mod's assets (it replaces one of the same name).

<details><summary>How it works</summary>

CIwSoundManager::Play(manager, spec hash, position, 0, 0) plays a sound spec (positioned when a position {x, y, z} in whole centimetres is given); CSoundSequenceManager::Play (manager, hash, 0x1000, 0) runs a CSoundSequence; Music_Play(CMusicManager, path, repeat, now, volume, lock) streams an mp3 (now: switch at once instead of fading; lock: nothing else may change the music until it ends), Music_Pause / Music_Resume (s3eAudio), Music_SetVolume (+0xb0, 0-256). The music's current track hash is at +4.

</details>

| Function | Description |
| --- | --- |
| `audio.play(name, position)` | Plays a sound spec by name or hash; at a position {x, y, z} when given. Returns true. |
| `audio.sequence(name)` | Runs a sound sequence by name or hash (wave starts, announcer lines, stings). |
| `audio.music(file, options)` | Plays a music track (a file of blackops-music, e.g. "115.mp3"). Options: loop (repeat it), fade (fade from the current track instead of switching at once), volume (0-1, default 1), lock (nothing else changes the music until it ends). |
| `audio.music_track()` | The hash of the music track playing (IwHashString of its path), or 0. |
| `audio.pause_music()` | Pauses the music. |
| `audio.resume_music()` | Resumes the music. |
| `audio.music_volume(volume)` | Sets the music volume (0-1). |

### boz.screen

Full-screen effects and fog.

```lua
screen.effect("nuke")                     the nuke's white flash
screen.effect("shockEffect", 2000)        Kino's electric shock, for 2 seconds
screen.fog("Monkeys")                     a fog config (the level's or one a round uses)
```

Full-screen effects (CFullscreenFXConfig resources): nuke (every map), shockEffect and crawler_gas (Kino), lazarus and romeroElectricutionEffect (Call of the Dead). Fogs (CIwFogConfig, misc group): KINO, Ascension, Monkeys, callofthedead and the level's others. A map project's build brings any effect or fog its scripts name from another map.

<details><summary>How it works</summary>

CFullscreenFXManager (singleton) plays one when it gets its play event (id kept at image +0x4672f0) with the config's name hash and a display time (0: the config's own): materials fade in, show and fade out (m_FadeTime, m_DurationTime, m_InitialDelay). Fog: the SwitchFog command (CVFXManager, CIwFogManager).

</details>

| Function | Description |
| --- | --- |
| `screen.effect(name, ms)` | Plays a full-screen effect by name (or hash) for `ms` milliseconds (default: its own time). Returns false when the effect is not loaded. |
| `screen.fog(name)` | Switches the fog to a fog config by name. |

### boz.hud

The in-game HUD's elements.

```lua
hud.set_visible("Insta_Kill_Image", true)       hud.hide("Clip_Label")
hud.ELEMENTS                                    the HUD's named elements
hud.message("The power is on", 3)               a line of text for 3 seconds
```

Elements (IwUI, found by name): the power-up icons and labels (Insta_Kill_Image, Double_Points, Fire_Sale, Death_Machine; _Image and _Label), the perk icons (Perk_Juggernog_Image, ...), Clip_Label, Grenade_Label, Low_Ammo_Label, No_Ammo_Label, Headshot_Image/Label, Being_Revived_Label. Text on the screen: boz.text (strings) and boz.iwui (any element).

<details><summary>How it works</summary>

HUD_SetElementVisible(name, visible) finds the element in the current page (CUIPageManager::FindElement), shows or hides it (CIwUIElement::SetVisible) and makes it opaque; the power-up code calls it with the icon names.

</details>

| Function | Description |
| --- | --- |
| `hud.set_visible(name, visible)` | Shows or hides a HUD element by name (the game shows and hides its own as things happen). |
| `hud.show(name)` | Shows a HUD element. |
| `hud.hide(name)` | Hides a HUD element. |
| `hud.message(text, seconds, x, y)` | Shows a line of text in the HUD's font for `seconds` (default 3; a new message replaces the last), where the game writes "Reviving" (left of the crosshair), or at `x, y` (screen pixels, its left edge). Returns false outside a match. |
| `hud.clear_message()` | Hides the message now. |

### boz.stats

The player's statistics and achievements.

```lua
stats.get("STAT_ZOMBIESKILLED")     stats.add("STAT_HEADSHOTS", 1)
stats.unlock("BOGravity")           stats.progress("BOWhackAZombie")  -> current, target
```

Stats: STAT_ZOMBIESKILLED, STAT_HEADSHOTS, STAT_REVIVED, STAT_COMRADESREVIVED, STAT_PLAYERDEATHS, STAT_POINTSSPENT, STAT_WAVES (this match) and their _TOTAL forms (all time). Achievements are CAchievement resources by name (BOGravity, BOWhackAZombie, BOEagleLanded, ...).

<details><summary>How it works</summary>

CStatsManager (singleton) keeps a map per mode (Stats_GetMode: 1 Zombies, 2 Dead Ops) from a stat's name hash to its value: Stats_Get(manager, name), Stats_Add(manager, mode, hash, delta). Achievements are CAchievement resources (boz.resources): target at +0x24, progress +0x28, enabled +0x36; Achievement_SetProgress clamps, unlocks at the target and saves (CAchievementDB).

</details>

| Function | Description |
| --- | --- |
| `stats.get(name)` | A stat's value (this mode's), or nil when the game has no stats manager. |
| `stats.add(name, amount)` | Adds to a stat. Returns the new value. |
| `stats.all()` | Every stat: {[name] = value}. |
| `stats.progress(name)` | An achievement's progress and target, or nil when the game has no such achievement. |
| `stats.set_progress(name, value)` | Sets an achievement's progress (the target unlocks it, and the game saves). |
| `stats.unlock(name)` | Unlocks an achievement. |
| `stats.unlocked(name)` | True once an achievement is unlocked. |

### boz.saves

The game's saves.

```lua
saves.save()                 saves the match now (as the round-start autosave does)
saves.on_save(fn)            fn() when the game writes its save (every system adds its part)
saves.on_load(fn)            fn() when a saved match is continued
```

A script's own state: boz.globals / script globals are saved with the game (boz.prefabs). Saving on pause and on suspend: the SaveOnPause and SaveOnSuspend variables (boz.cvars).

<details><summary>How it works</summary>

CSaveManager::AutoSave writes the in-game save (SaveGame: SUBJECT_SAVE to every system, then <slot>_save_game.i3d) and the profile and stats; a continued match sends SUBJECT_LOAD (CSaveManager::NotifyLoad) and every system reads its section back.

</details>

| Function | Description |
| --- | --- |
| `saves.save()` | Saves the match now (single player). Returns false outside a match. |
| `saves.on_save(fn)` | Calls fn() whenever the game writes its save. Returns a handle (boz.game_events.off). |
| `saves.on_load(fn)` | Calls fn() when a saved match is continued. |

### boz.network

Co-op state.

```lua
network.host()          true when this game runs the match (single player too)
network.wifi()          true for local Wi-Fi co-op
network.players()       the other players in the match: {entity, ...}
```

<details><summary>How it works</summary>

CGameNetwork (singleton) +0x54 is the host flag the gameplay code checks (only the host spawns zombies, counts kills, drops power-ups; the others follow its NetworkProperty fields and network events); CGameNetwork::IsWifiMode is the Bonjour TCP configuration; other players are entities with a CRemotePlayer (their weapons CRemotePlayerWeapon, perks CRemotePerkManager). The online services (DemonWare) are not used by BOZ Redux.

</details>

| Function | Description |
| --- | --- |
| `network.host()` | True when this game runs the match. |
| `network.wifi()` | True for local Wi-Fi co-op. |
| `network.players()` | The other players: a list of their entities. |

## Controls

### boz.input

The player's controls during a Zombies match: watch, change or send the game's actions.

```lua
local input = require("boz.input")
input.on_action("melee", function(down)
    log("knife " .. (down and "pressed" or "released"))
end)
input.send("reload")
```

Actions: shoot, aim, reload, use, melee, grenade, tactical, crouch, fire_mode, switch_weapon. They are the game's own actions, whatever keys the player bound to them.

<details><summary>How it works</summary>

the client sends the player's key presses straight to the game's input (native controls) and raises the "action" event first; a handler that returns true keeps the action from the game. Dead Ops Arcade still uses the touchpad path and raises no actions.

</details>

| Function | Description |
| --- | --- |
| `M.ACTIONS` | The action names. |
| `M.on_action(name, fn)` | Calls fn(down) when the player presses (true) or releases (false) the action. If fn returns true the game does not get it. Several handlers may watch one action; any one returning true keeps it from the game. |
| `M.send(name, down)` | Sends an action to the game as if its button was pressed (down = true, the default) or released. Handlers from on_action do not see it. |
| `M.held(name)` | True while the player holds the action's key or button. |
| `M.aiming()` | True while the player is aiming down sights (approximate: it can miss aiming in some states). |
| `M.native()` | True when the client sends controls straight to the game (actions work); false with the old touchpad controls. |

## Console

### boz.console

The game's developer console.

```lua
local console = require("boz.console")
console.set("WeaponsUnlimitedAmmo", true)
print(console.exec("listVars Unlimited"))
```

Runs console lines, reads and sets console variables (cvars), registers new ones, and passes on everything the console prints. Every variable and command is listed in docs/console-reference.md.

<details><summary>How it works</summary>

the release build kept the console (CIwConsole, g_console) but no display, so Console_Print has nowhere to send text. This module hooks Console_Print and wraps the console's own functions (Console_Execute, Console_FindVar, Cvar_Register*).

</details>

| Function | Description |
| --- | --- |
| `console.ready()` | True once the game created its console (from the first frame on, in practice). |
| `console.print(text)` | Prints a line on the game's console (the Developer console shows it). |
| `console.on_output(fn)` | Calls fn(text) for every line the console prints. |
| `console.exec(line)` | Runs a console line as if typed. Returns what it printed, or nil and an error. |
| `console.get(name)` | A console variable's value as text, or nil when the game has not registered it. |
| `console.set(name, value)` | Sets a registered variable from text (numbers and booleans are converted). Returns the value the game kept, or nil and an error. |
| `console.register(name, value, kind)` | Registers a variable with the game (if it does not exist yet) and sets it. kind: bool, int, float or string; guessed from the value when omitted. Makes values the game only reads, like StartingScore, take effect. Returns the value and the kind used. |
| `console.vars()` | Every known variable: {name, type, default, used_by, lookup_only}. |
| `console.commands()` | Every known command: {name, id, owner}. |

### boz.cvars

Every console variable of the game, typed, with its default and what it does.

```lua
cvars.get("SprintSpeed")            -> 1.85 (a number, boolean or string by its type)
cvars.set("SprintSpeed", 3)         registers it when the game has not yet, then sets it
cvars.reset("SprintSpeed")          back to the game's default
cvars.info("SprintSpeed")           {type, default, note}
cvars.find("Zombie")                every variable whose name has "Zombie" in it
cvars.commands()                    every command {name, args, note}
```

664 variables: the player (WalkSpeed, SprintSpeed, PlayerStartWeapon, ...), zombies (AI*, Zombie*), rounds (StartWaveOnStart, StaggerStartingZombies, ...), power-ups (Pickup*, *Time), the HUD (HUD*), Dead Ops (do*), the camera, sound, saves and debug. docs/console-reference.md lists them all. Changes last for the session; the Game tab sets a map's own (only on that map).

<details><summary>How it works</summary>

boz.console registers and sets them (CIwConsole); boz/cvar_data.lua is the game definition's catalog (tools/stdlib/generate_data.py) with the notes of tools/symbols/console_notes.toml.

</details>

| Function | Description |
| --- | --- |
| `cvars.info(name)` | What the library knows of a variable: {type, default, note}, or nil. |
| `cvars.get(name)` | A variable's value (by its type), or nil when the game has not registered it. |
| `cvars.set(name, value)` | Sets a variable (registering it first when the game has not: values the game only reads, like StartingScore, then take effect). Returns the value kept. |
| `cvars.reset(name)` | Sets a variable back to the game's default. |
| `cvars.find(text)` | Every variable whose name contains `text` (any case), sorted: {name, ...}. |
| `cvars.all()` | Every variable name, sorted. |
| `cvars.commands()` | Every command: {{name, args, note}, ...}, sorted by name. |
| `cvars.run(name, ...)` | Runs a command with arguments (as typed in the console). Returns what it printed. |

## Menus and text

### boz.pause_settings

Settings in the game's pause menu (Settings page, CIngameStateOptions).

```lua
local pause_settings = require("boz.pause_settings")
pause_settings.add_slider{id = "fov", label = "Field of view", min = 50, max = 120, step = 1,
                          get = function() return value end, set = function(v) ... end}
pause_settings.add_checkbox{id = "aim_toggle", label = "Toggle aim",
                            get = function() return on end, set = function(on) ... end}
```

Call these when the mod's script starts. Each time the page opens, the rows are added in the order they were registered, stacked in the free column right of the game's sliders, styled exactly like the game's own (they are copies of its widgets).

<details><summary>How it works</summary>

the page is one flat IwUI panel. A slider row is copied from the detail level row (bar image, slider, title label), a checkbox row from the auto aim row (label, box, cross, button). Copies keep the original's slot (OnLODChanged, OnAutoAim); hooks on those slots take the events that come from a copy and leave the game's own alone. Labels show a string id registered with boz.text.

</details>

| Function | Description |
| --- | --- |
| `pause_settings.add_slider(spec)` | Adds a slider. spec: id, label, min, max, step (optional), get() -> number, set(number). |
| `pause_settings.add_checkbox(spec)` | Adds a checkbox. spec: id, label, get() -> boolean, set(boolean). |

### boz.text

Adding text to the game's string table.

```lua
text.add("S_MYMOD_TITLE", "My setting")
iwui.set_text_id(label, "S_MYMOD_TITLE")
```

The game shows text by string id (like S_MENU_MUSIC) in the current language. text.add registers an id of the mod's own; use it wherever the game takes a string id.

<details><summary>How it works</summary>

menus and labels hash the id and ask Localise_GetString for the text; a hook answers for the mod's ids.

</details>

| Function | Description |
| --- | --- |
| `text.cstring(value)` | The address of a zero-terminated copy of a text in game memory, for game functions that keep the pointer (labels, prompts). The same text gives the same address; it is never freed. |
| `text.add(id, value)` | Adds (or replaces) the text for a string id. Returns the id's hash. |

## Game UI building blocks

### boz.iwui

The in-game menus (Marmalade IwUI pages, e.g. the pause menu).

```lua
local slider = iwui.find("musicSlider")
local copy = iwui.clone(slider)
iwui.add_child(iwui.parent(slider), copy)
iwui.set_position(copy, 800, 300)
```

Find elements by name, walk and dump a page, copy and place widgets, set labels, slider values and visibility. boz.pause_settings is built on it; use that for settings rows.

<details><summary>How it works</summary>

pages are trees of elements shown by CUIPageManager. Element layout: +4 name hash, +0x18 parent, +0x1c children (data, +0x20 count), +0x34 event handlers, +0x48/+0x4c slots, +0x5c position, +0x64 size, +0x8c layout, +0xa0 properties. Widgets call named slots on their page's event handler (a slider's OnSliderChanged calls e.g. CIngameStateOptions::OnMusicChanged with itself as the element).

</details>

| Function | Description |
| --- | --- |
| `iwui.find(name)` | The element with this name on the current page, or nil. |
| `iwui.parent(element)` | The element's parent, or nil. |
| `iwui.children(element)` | The element's children (list of addresses). |
| `iwui.class_name(element)` | The element's C++ class (from its RTTI), e.g. "CIwUISlider". |
| `iwui.name_hash(element)` | The hash of the element's name (compare with boz.hash.name). |
| `iwui.rect(element)` | Position and size in the parent (pixels): +0x5c/+0x60 position, +0x64/+0x68 size. |
| `iwui.set_position(element, x, y)` | Moves an element within its parent. |
| `iwui.is_named(element, name)` | True if the element's name is name. |
| `iwui.clone(element)` | A deep copy of an element (not yet on any page; add it with add_child). |
| `iwui.add_child(parent, child)` | Adds an element to a parent (and to the parent's layout, if it has one). |
| `iwui.set_name(element, name)` | Renames an element (CIwManaged::SetName, vtable slot 9) so FindElement finds it. |
| `iwui.set_visible(element, visible)` | Shows or hides an element. |
| `iwui.set_caption(label, text)` | Sets a label's text. SetCaption only stores the "caption" property and skips the redraw in some states, so the label is also told the property changed (vtable +0xb8). |
| `iwui.set_text_id(label, id)` | Points a label at a string id (boz.text.add, or one of the game's like S_MENU_MUSIC). The game's labels show their localiseCaption string id rather than their caption. Changes only the label's own property (not one shared through its style). Returns false if it has none. |
| `iwui.set_value(slider, value)` | Sets a slider's value (0..4096 on the game's sliders); calls its OnSliderChanged slot. |
| `iwui.find_in(element, test, depth)` | The first descendant (depth first) for which test(element) is true. |
| `iwui.dump(element, names, depth)` | Logs the element tree under element (class, name, children); names resolves known names. |

### boz.frontend

Changing the main menu (front end), one Flash movie played by gameswf.

Building blocks for mods that change main-menu screens; higher-level helpers (adding widgets to a screen) will grow here. frontend.patch_screen adds ActionScript (built with boz.avm1) to a screen; frontend.call runs one of the movie's ActionScript functions.

<details><summary>How it works</summary>

ActionScript talks to the game with _root.sendMsg(name, a, b), which the native IsSendMessage turns into the active CFlashMenuState's OnEvent(IwHashString(name), a, b) (numbers arrive as integers); screens pass events they do not know to CFlashMenuState::OnEvent, so hooks can add new ones. The game calls ActionScript with CFlashMenuState::CallActionScript(state, function, format, ...) (gameswf format: "%d", "%f", "%s", comma separated). The movie is patched as it loads (assets.patch), so no game file is changed or shipped.

</details>

| Function | Description |
| --- | --- |
| `frontend.patch_screen(names, build)` | Adds a frame script to the screen (sprite) whose scripts use all of names (e.g. {"initialise", "SUBJECT_OPTIONS_VOLUME"} is the Options screen). build(b) fills an avm1 builder; the script runs after the screen's own first-frame script. Call while the mod's script starts (before the menu loads). |
| `frontend.call(state, fn, format, ...)` | Calls an ActionScript function on a Flash menu state (CFlashMenuState) with gameswf's format, e.g. frontend.call(state, "setMusicVol", "%d", 50). |
| `frontend.capture_log` | Shows ActionScript trace() output and gameswf warnings in the log (boz.flash.capture_log). |

### boz.flash

Debugging the game's Flash menus (gameswf).

flash.capture_log() makes ActionScript trace() output and gameswf's own warnings appear in boz-log.txt as "[flash] ...".

<details><summary>How it works</summary>

the release build sets no gameswf log handler, so nothing is formatted. A hook on gameswf_LogMsg formats each message with the game's vsnprintf.

</details>

| Function | Description |
| --- | --- |
| `flash.capture_log()` | Shows ActionScript trace() output and gameswf warnings in boz-log.txt as "[flash] ...". |

### boz.swf

Reading and changing Flash movies (SWF), for patching the game's menus.

Most mods use boz.frontend instead. swf.parse(bytes) gives a movie whose sprites can be found by the names their scripts use and given extra frame scripts; movie:serialize() writes it back.

<details><summary>How it works</summary>

works on the uncompressed movies the game ships (FWS). Tags keep their original bytes unless changed, so an untouched movie serializes back byte for byte.

</details>

| Function | Description |
| --- | --- |
| `Sprite:actions()` | The frame scripts (DoAction bodies) of the sprite's tags, in order. |
| `Sprite:uses(text)` | True if any frame script of the sprite contains text (a name used in its code). |
| `Sprite:add_first_frame_action(action_bytes)` | Adds a frame script to the sprite's first frame, after the scripts already there. |
| `Sprite:serialize()` | The sprite's tag bytes (used by Movie:serialize). |
| `swf.parse(bytes)` | Parses a movie. Returns the movie, or nil and an error. |
| `Movie:sprites()` | Every sprite (DefineSprite) in the movie, parsed. |
| `Movie:sprite(id)` | The sprite with this character id, or nil. |
| `Movie:find_sprite_using(...)` | The first sprite whose frame scripts use all the given names, or nil. |
| `Movie:serialize()` | The movie as bytes, with changed sprites rebuilt. |

### boz.avm1

Building ActionScript 2 bytecode (AVM1) for the game's Flash menus.

```lua
local b = avm1.builder()
b:push("hello from a mod"):op("Trace")
local bytes = b:bytes()   -- a frame script for boz.swf / boz.frontend.patch_screen
```

A builder collects actions. Values are pushed with :push(...) (strings, numbers, booleans, avm1.NULL, avm1.UNDEFINED); :get("a.b.c") pushes a path; functions are built with :func(name, params, body_fn); jumps use labels. Used by boz.frontend.

| Function | Description |
| --- | --- |
| `avm1.builder()` | A new ActionScript (AVM1) bytecode builder. |
| `Builder:push(...)` | Pushes values onto the stack (one Push action). |
| `Builder:op(name)` | Emits a simple action by name (GetVariable, SetMember, CallMethod, ...). |
| `Builder:label(name)` | Marks a jump target. |
| `Builder:if_true(name)` | Jumps to a label if the value on the stack is true. |
| `Builder:jump(name)` | Jumps to a label. |
| `Builder:func(name, params, body)` | Defines a function: name ("" for an anonymous one, left on the stack), parameter names, and body(b) which fills a builder for the function body. |
| `Builder:bytes(inner)` | The finished bytecode; frame scripts end with an End action unless inner is set. |
| `Builder:get(path)` | Pushes the value of a dotted path, e.g. b:get("_root.Options.settings"). |
| `Builder:call_method(push_obj, method, ...)` | Calls obj.method(args...) where obj is pushed by push_obj(b); leaves the result on the stack. |
| `Builder:trace(text, path)` | trace(text .. value-of-path): writes a line to the Flash log (see boz.flash.capture_log). |

## Low-level helpers

### boz.hash

The game's name hash.

Event ids (SUBJECT_*), element names, resource names, string ids and console names are all hashed this way: hash.name("musicSlider").

<details><summary>How it works</summary>

IwHashString is djb2 (h = h * 33 + c from 5381) over the name with A-Z lower-cased.

</details>

| Function | Description |
| --- | --- |
| `hash.name(text)` | The game's hash of a name (IwHashString). |
| `hash.of(value)` | A hash from a name, a "0x..." hash or a number (returned as it is). |

### boz.enums

The names of the game's enumerations (the values reflected fields hold).

```lua
enums.name("WeaponBehaviourType", 10)   -> "eDeathMachine"
enums.value("PerkType", "ePerkJuggernog") -> 2
enums.WeaponBehaviourType[3]            -> "eAutomatic" (lists are 1-based: value + 1)
```

<details><summary>How it works</summary>

CParsableEnumManager registers each enum from a null-terminated table of names in the game's data (value = position): these are those tables, read from the 1.0.11 image.

</details>

| Function | Description |
| --- | --- |
| `enums.name(enum, value)` | The name of an enum's value (the game's number), or nil. |
| `enums.value(enum, name)` | The game's number for an enum value's name, or nil. |
