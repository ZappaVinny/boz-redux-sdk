# Modding platform design

How BOZ Redux becomes moddable: how the game is reverse-engineered, how that knowledge is stored,
and how mods use it. The Lua API reference is in [lua-api.md](lua-api.md) as it lands.

**Where each part lives.**

- **[boz-redux](https://github.com/ZappaVinny/boz-redux) (the client):** everything that runs
  inside the game: file overrides, the mod loader, the Lua runtime and hooks, the Mods tab, and
  networking (DemonWare stubs, LAN co-op).
- **This SDK:** everything that makes mods: reverse engineering, bozkit, mod templates and
  packaging, the Redux mod.
- **[boz-redux-gamedef](https://github.com/ZappaVinny/boz-redux-gamedef):** the game definition
  (symbols, reflection, events, console). The SDK generates it, and both repos pin it as the
  `gamedef/` submodule.

## Ground rule: commit knowledge, never game code

A Ghidra project, a disassembly or a converted binary contains Activision's code, so none of it
is committed (the same rule as for the APK and data packs). What is committed is what we learn
about the code:

- **The symbol database** (`gamedef/symbols/boz-1.0.11.toml`): names, addresses, function signatures,
  struct layouts and notes.
- **Tools** (`tools/ghidra/`) that turn anyone's own copy of the game into a fully annotated
  Ghidra project, and export Ghidra's annotations back into the symbol database.

The symbol database is the source of truth: plain text, diffable, reviewable in pull requests.
A Ghidra project is a local, rebuildable view of it.

## Getting the game into Ghidra

1. `tools/ghidra/s3e_to_elf.py assets/boz.s3e.unpacked re/boz-1.0.11.elf` converts the game's
   S3E image into a standard ARM ELF:
   - code (`0x4a000000`-`0x4a3dc000`) and data (to `0x4a4a7dc8`) at the address the client
     loads them, so addresses in client logs, crash reports and traces match Ghidra exactly;
   - each of the 391 engine imports (`s3eFileOpen`, `glFrustumf`, ...) as a named stub in an
     `.imports` segment at `0x4a500000`, with the image's import slots pointing at the stubs, so
     the decompiler shows real call names.
2. Import the ELF into a Ghidra project in `re/ghidra/` (gitignored) and run auto-analysis.
3. `ApplySymbols` (planned) loads the symbol database: names, signatures, structs, comments.

Anyone with the APK can rebuild the same annotated project in minutes. `re/` is gitignored.

## Reverse-engineering method

The goal is a **broad map of the game first**: the subsystems a modder needs, named and
understood well enough to hook. Specific features (FOV, turn rate, ...) come out of that map
instead of driving it.

### Structural map first

Two things in the game give a map of the whole code base before any single subsystem is studied:

- **C++ run-time type information.** The game keeps RTTI, so `tools/ghidra/rtti_classes.py`
  recovers about 2,400 classes with their real names, inheritance and vtables, and names
  about 17,400 virtual functions by class (`CMysteryBox::vf24`). Classes split by library: game
  code (`CDO*`, `CMysteryBox`, `CAIControllerZombie`, ...), the Ideaworks studio layer (`CIs*`),
  Marmalade (`CIw*`), Bullet physics (`bt*`), gameswf (the Flash player used for UI) and
  DemonWare (online services).
- **Console variables.** About 600 named tuning values (`baseZombieHealth`, `AimTurnSpeed`,
  `DoublePointsTime`, `HUDPointsPosX`, ...) registered through `CIwConsole`, listed by
  `ExportBozCvars.java` with their defaults. They span every subsystem and are a ready-made
  modding surface: the client can find and set any of them by name at runtime.

### Subsystem map (the order of work)

1. **Engine boundary**: every call into the 391 imports, grouped by subsystem (file, memory,
   input, sound, GL, timer, device, network). Wrappers around them are the first functions named.
2. **Runtime structure**: main loop, frame update and render entry points, the "director"
   (fixed-step update and interpolation, partly known from the client), allocators, the
   resource manager (`.group.bin` loading).
3. **Game state**: game modes and screens (menus, loading, in-match), map loading, rounds, the
   player object, the camera.
4. **Entities**: zombies and AI, spawners, pathing, barriers, power-ups, perks, the mystery box,
   Pack-a-Punch.
5. **Weapons**: the weapon table (stats, ammo, damage), fire/reload/switch logic, grenades.
6. **Rendering**: scene graph, models, materials, the camera and projection, HUD and 2D UI.
7. **UI and text**: menu screens, fonts, localisation lookups.
8. **Audio**: sound and music triggers.
9. **Save data and settings**: profile, unlocks, the game's own options.
10. **Network**: multiplayer/zeroconf, lowest priority.

Each pass names functions and globals, types the main structs (player, zombie, weapon, camera),
and writes a short note in the symbol database. Coverage is tracked per subsystem in the symbol
database so it is clear what is mapped and what is not.

### Techniques

- **Anchors**: imports (input, GL, file and sound calls lead into their subsystems), strings
  (asset names, debug text), offsets the client already knows (crash sites, the director).
- **Live tracing** (our main advantage): the client *is* the CPU, so it can log every call to a
  function, or every read and write of an address, while someone plays. Watching which values
  change when you buy a perk or a round starts finds them in minutes.
- **Static analysis** in Ghidra: decompile around an anchor, name what is clear, build structs
  from field accesses, follow cross-references outward.

### Confidence

Every symbol has a confidence: `confirmed` (proven at runtime or unambiguous in code) or
`likely` (a reading not yet proven). The mod API only exposes `confirmed` symbols by default.

### How the Ghidra MCP is used

The [Ghidra MCP](https://github.com/bethington/ghidra-mcp) plugin lets the assistant work in the
user's open Ghidra: decompile and disassemble, list cross-references, search strings and bytes,
rename functions, variables and labels, set comments, and create and apply types and function
signatures. Changes appear live in the project, where they can be read and corrected by hand.
At the end of a piece of work, annotations are exported to the symbol database and committed.

## Symbol database

```toml
[game]
version = "1.0.11"
image_sha256 = "f458c15a..."   # boz.s3e; the client refuses mismatched symbol files

[[function]]
name = "Camera_SetFov"
offset = 0x1a2b3c              # from the image base (0x4a000000)
thumb = true
signature = "void Camera_SetFov(Camera *self, float fov)"
subsystem = "rendering"
confidence = "confirmed"
notes = "Called on aim and spawn."

[[global]]
name = "g_player"
offset = 0x45f2b0
type = "Player *"

[[struct]]
name = "Camera"
size = 0x80
fields = [ { name = "fov", offset = 0x24, type = "float" } ]
```

Names use `Subsystem_Function` for functions, `g_` for globals and `PascalCase` for types. The
build turns the database into the table the Lua runtime uses; mods refer to symbols by name,
never by address.

### Reflection schema

The game describes its own data. 369 classes register their fields by name with the studio
engine's reflection system (`CIsClassInfo`). `gamedef/reflection/boz-1.0.11.toml` is generated from
those registrations and lists each class's bases and fields (name, offset, size, type, and
whether it is network-synced). It covers most gameplay types:

- **player and health:** `CPlayerController`, `CHealth`;
- **weapons:** `CPlayerWeapon`, `CWeaponDamage`, `CWeaponAccuracy`;
- **rounds and spawns:** `CWave`, `CWaveSpeciality`, `CDORound`, `CLevel`, `CArea`;
- **zombie AI:** `CAIControllerZombie`;
- **map objects:** `CMysteryBox`, `CPackAPunch`, `CPerk`, `CDoor`, `CTrap`;
- **camera:** `CIsCamera`;
- **Dead Ops:** the `CDO*` classes.

It serves three purposes:

- **Lua:** components and resources are read and written by field name
  (`entity:component("CHealth").m_MaxHealth`), resolved through the schema, so mods never use
  raw offsets.
- **Data mods:** reflected resources are stored in `.group.bin` as property blobs keyed by the
  same field names, so the schema is the format of gameplay data such as wave sizes, zombie
  speeds and weapon damage.
- **Ghidra:** a structure per class, used automatically for `this` in its methods, turns
  `*(float *)(this + 0x40)` into `this->m_fov`.

## Mods

A mod is a folder (or a zip of one) in `mods/`:

```
mods/example/
  mod.toml          id, name, version, authors, game = "1.0.11", api, depends, load_after,
                    and [settings] the launcher shows
  assets/           files replacing the game's own, by the same relative path
  scripts/main.lua  entry point
```

- The launcher's **Mods** tab enables, disables and orders mods, and shows their settings.
- **Asset overrides**: the client's file layer checks enabled mods (highest priority first)
  before `assets/` and the `.dz` packs. Game files are never modified.
- **Lua**: Lua 5.4 embedded in the client; one Lua state, a separate global environment per mod,
  run only on the game thread.

### How the game finds its files (asset pipeline)

Mapped in Ghidra; the names are in the symbol database.

1. **Pick and mount the pack.** `Game_InitEngine` creates `CIsArchiveManager` (`g_resManager`). It
   takes the first pack that exists from `blackops_{gles1,dxt,atitc,etc}.dz`, then
   `AddArchive` (slot 2) and `MountAll` (slot 5) attach it with Marmalade's derbh library
   (`dzArchiveAttach`). Derbh registers itself as a filesystem with `s3eFileAddUserFileSys`.
   Our runtime ignores that registration and serves pack members from its own index
   (`s3e_file.c`, `dtrz_*`).
2. **Choose the data folder.** `CIwResManager_SetBuildStyle` sets `g_resBuildStylePath` to
   `data-<style>` (for example `data-etc`) and makes it the search prefix.
3. **Load a group.** `LoadGroup("bootstrap/bootstrap")` (slot 10) adds `.group`.
   `CIwResManager_LoadGroup` then builds the path: `debug_patches/` + name when the manager's
   debug-patch flag is set (it isn't in release), plus `.bin`.
4. **Resolve and open.** `IwFileOpen` → `IwPath_Resolve` tries `data-etc/bootstrap/bootstrap.group.bin`,
   then the bare name, checking each with `s3eFileCheckExists`, then calls `s3eFileOpen`.
   `CIwResManager_ReadGroupFile` checks the version header and deserialises every resource.
5. **Everything else** is opened by name the same way: localisation (`localisation/<lang>.dat`),
   cvar defaults (`console.bin`), the Flash front end (`fe_v4_cs4_swf.bin`, played by the
   embedded gameswf), shader binaries and music (`blackops-music/*.mp3`, loose files).

**What this means for mods:**

- Every read reaches the client's `s3eFileOpen` and `s3eFileCheckExists`. The override layer
  goes there: strip a leading `data-<style>/` and check each enabled mod's `assets/` for that
  path (or the bare file name, since the packs store names flat), before the packs.
- Whole-file replacement needs no game patching: groups, localisation, `console.bin`, the
  front-end movie and music.
- Packs store flat names (`lv1_island.group.bin`), so mods should mirror the logical path
  (`deadops-environments/lv1_island/lv1_island.group.bin`) and the client also matches by name.
- Group contents are decoded: `tools/bozkit` reads and writes reflected resources (waves,
  rounds, levels, zombie and score configs) and entity specs (weapons, pickups, map objects) by
  field name, byte for byte. See [asset-formats.md](asset-formats.md). Data mods can change wave
  sizes, zombie speeds and health, weapon clips and damage, and costs without code.

### Lua API outline

| Call | Purpose | Mechanism |
| --- | --- | --- |
| `boz.hook(name, {before=, after=})` | Run code when a game function runs; change arguments or result | Emulator breakpoint on the exact address, so game code is never patched |
| `boz.call(name, ...)` | Call a game function | `arm_emu_call` |
| `boz.struct(type, address)` | Typed field access from the symbol database | Direct memory access |
| `boz.read_*` / `boz.write_*` | Raw memory access | Direct memory access |
| `boz.patch(address, bytes)` | Code patch, undone when the mod unloads | Writes into the image |
| `boz.on(event, fn)` | `frame`, `input`, later `map_loaded`, `round_start`, ... | Client events |
| `boz.settings.get(key)` | The mod's launcher settings | `mod.toml` + saved values |

Safety: every callback runs protected; an error disables that mod and is logged instead of
crashing the game. Mods get no `os.execute` and file access only inside their own folder.

### Game events

The game's systems talk through an observer bus: `CIsSubject::NotifyVirtual` / `Dispatch`
send an event id to every `CIsObserver` that called `CIsSubject::Subscribe` for it, and the
observer's `OnEvent` reacts. `gamedef/events/boz-1.0.11.toml` lists all 337 events (`SUBJECT_*`),
each with its id (`IwHashString` of the name) and the classes that send and handle it.

Some examples:

- **rounds:** `SUBJECT_NEW_WAVE` and `SUBJECT_WAVE_ENDED`, sent by `CWaveManager`;
- **zombies:** `SUBJECT_ZOMBIE_DEATH`, and the `SUBJECT_ZOMBIE_SCORE_KILL_*` family (head,
  torso, limb, knife, grenade);
- **weapons:** `SUBJECT_WEAPON_SHOOT` and `SUBJECT_WEAPON_RELOAD`;
- **score and purchases:** `SUBJECT_ADD_SCORE`, and `SUBJECT_CHARGE_POINTS`, which every
  purchase sends: doors, the mystery box, Pack-a-Punch, perks, traps and turrets;
- **perks:** `SUBJECT_ON_PERK_GAINED` and `SUBJECT_ON_PERK_LOST`.

For Lua this is the natural event API. One hook on the send functions gives
`boz.on("SUBJECT_NEW_WAVE", fn)` for every event, with the event's two arguments, and lets a mod
cancel or change an event before the game sees it, for example a purchase's cost.

### Rounds and points

**Rounds** are run by `CWaveManager` from `CWave` definitions: data resources chained by
`m_NextWave`, starting at the level's `m_StartingWavesSP`.

- **Each frame:** while fewer zombies have spawned than `GetZombieCount(round, powerOn)` and
  fewer are alive than `GetMaxActive(round)`, it waits `GetSpawnTimeOut(round)` milliseconds and
  spawns one.
- **End of a round:** every `SUBJECT_DIED` raises the kill count; when it reaches the zombie
  count, the manager sends `SUBJECT_WAVE_ENDED`.
- **Next round:** after `GetWaveTimeout`, `StartWave` loads the next wave, raises the round
  number and resets the counters.
- **Scaling:** `CWaveRepeatable` waves grow each round as
  `base * multiplier ^ (round - m_StartingWave)`, applied to zombie count, powered count, max
  active and spawn timeout. Speciality waves (dogs, monkeys) slot in between.

Wave sizes, speeds, health and timing are all wave data, so a data mod can rebalance rounds, and a
Lua hook on the `CWave` getters can change them at run time.

**Points** live in `CScoreManager`, one score per player:

- `SUBJECT_ADD_SCORE` adds points;
- every purchase sends `SUBJECT_CHARGE_POINTS` (cost, player), which subtracts them;
- `SUBJECT_POINTS_PENALTY` subtracts without counting for stats.

In single player, a purchase the player can't afford is paid with COD Points (the store
currency) when they have enough.

### Combat, perks, pickups and input

**Hits and damage.**

- **Firing:** the weapon's shoot animation triggers `Weapon_FireBullets`. For each pellet it
  applies spread, raycasts 10,000 units and sends `SUBJECT_WEAPON_HIT` (with the body part hit) to
  the target entity's `CIsBroadcaster`. The knife (`CWeaponManager::MeleeAttack`) does the same
  for a target in a cone in front of the player.
- **Zombies:** they subscribe to every damage source when activated (weapon hits, explosions,
  traps, fire, shockwaves, dismemberment) and turn hits into `CHealth::Damage`.
- **`CHealth`:** clamps health to its maximum and ignores damage while invulnerable. After a hit
  it regenerates (`m_HealDelay`, `m_HealingTime`); below 1 health it sends `SUBJECT_DIED`.
- **Kill score:** a zombie's dead state sends `SUBJECT_ZOMBIE_DEATH`, then a kill-score event to
  the killer by how it died (head, torso, limb, knife, grenade). Headshots add
  `zombieHeadshotBonus`. The killer's `CScoreHandler` looks up the points in the score table,
  doubles them during Double Points and sends `SUBJECT_ADD_SCORE`.

**Weapons.** `CPlayerWeapon` holds the definition and live ammo (clip +0x2c, reserve +0x30). A
weapon behaviour (automatic, semi-auto, shotgun, revolver, launcher, Thunder Gun, Wunderwaffe,
Death Machine) is a small state machine: idle, firing, reloading. Firing takes a round unless
`WeaponsUnlimitedAmmo` is set; reloading moves rounds from the reserve to the clip.

**Points of interest.** Every usable object (perk machines, the box, Pack-a-Punch, doors,
barricades, traps, turrets) has an `Interact` method (slot 24). It checks the cost (COD Points as a
single-player fallback), sends `SUBJECT_CHARGE_POINTS` and acts.

- **The box:** state 0 buys and rolls a weapon; state 1 hands it over through
  `CWeaponManager::GiveWeapon`.
- **Power-ups:** the pickup manager tries a drop on each zombie death, based on points earned
  since the last drop. The last dog or monkey of a round drops Max Ammo.

**Input.**

- `CInputManager::OnInputAction(id)` is the game's button layer: melee, use, reload, grenades,
  aim, fire, crouch and prone, fire mode and weapon switch. It sends `ON_*_BUTTON` events. The
  desktop client could call it directly instead of emulating touch.
- The console also has **key-binding contexts** (`Console_PushBindContext`): `GameStateIngame`
  while playing, plus `BOPlayerControlsWin` (a Windows control set) or `XperiaPlayBO`. Each binds
  keys to console commands.

### Console commands

`gamedef/console/boz-1.0.11.toml` lists all 597 cvars and 148 developer console commands. Some
useful ones:

- **rounds and zombies:** `StartWave`, `KillAllZombies`, `SpawnZombie` (`CWaveManager`);
- **level:** `SwitchPowerOn`, `RestartLevel`, `PlayerDie` (`CLevelManager`), `EnablePerk` and
  `ResetAllPerks` (`CPerkManager`), `spawnEntity` (`CSpawnManager`);
- **free camera:** the `+FreeCam*` / `-FreeCam*` pairs;
- **rendering and time:** `TimeFactor`, `TimeTogglePause`, `wireframe`, `ReloadShaders`;
- **Dead Ops:** `GodMode`, `ManyLives`, `SetRound`.

Lua can expose them as `boz.console("StartWave")`, which makes them useful for testing mods and
as building blocks.

### Networking (and the plan to drop online services)

The game uses Marmalade's IwNetwork. Its backends are interchangeable, and a named
configuration from `iwnetworkconfigs.group` picks them
(`CIwNetworkConfigurationManager::SetConfiguration`):

| Configuration | Finding games | Connection | Status |
| --- | --- | --- | --- |
| `Bonjour_Tcp` | Bonjour / mDNS, service `_PROJECT_KIWI._tcp` (override: ICF `[NETWORK] DiscoveryServiceNameBonjour`) | plain TCP | the game's own local Wi-Fi co-op; the desktop runtime already implements zeroconf (`s3e_zeroconf.c`) and sockets |
| `OnlineDemonware` | DemonWare rooms | STUN through DemonWare | Activision's online service |

The front end switches between them with `SUBJECT_SWITCHED_CONNECT_TYPE` (1 = Wi-Fi). Co-op is
**host-authoritative**: the host (`CGameNetwork` `isHost`, +0x54) runs spawning, damage, deaths
and rounds. Clients follow through `NetworkProperty` fields (reflected fields flagged
`network = true`) and `CIsNetworkSubject` events, which travel as network events.

Every DemonWare use goes through one singleton, `IwDemonware::Get`:

- online rooms (create, list, join, destroy);
- account login and creation;
- telemetry (`RecordEvent`, from the metrics manager);
- server time (`GetServerTimestamp`, used by the store);
- the online key archive.

Server addresses come from the app config (ICF `[Demonware]`).

**Plan (client work, after the reverse-engineering milestone).** Keep the game's network calls,
but never talk to Activision or DemonWare:

1. **Stub DemonWare:** `IwDemonware` commands complete as "offline", and no DNS or connections
   are made.
2. **Lock co-op to `Bonjour_Tcp`:** hide or redirect the online option.
3. **LAN and mesh-VPN co-op:** Bonjour discovery works on a LAN and on virtual LANs that pass
   multicast (ZeroTier, and Radmin VPN or Hamachi depending on setup).
4. **Direct-IP join** in the launcher, for networks where discovery doesn't reach. This mirrors
   offline CoD clients: no accounts, no servers.

### Saves and menus

- **Saves:** `<home>/data-etc/` holds:
  - `profile_N.i3d`, `save_stats_N.i3d`, `save_settings.i3d`, `save_achievement.i3d` and
    `mm.i3d`;
  - `N_save_game.i3d`, the mid-game save. `CSaveManager::AutoSave` writes it at each round start
    in single player.

  Each system stores a section keyed by the hash of its class name
  (`CSaveManager::GetSection`). The file starts with a version (`0x0493e1`) and a 4-byte value;
  decoding the rest is a later tool (save editor).
- **Menus** are a Flash movie (`fe_v4_cs4_swf.bin`) played by gameswf:
  - C++ calls ActionScript with `CFlashMenuState::CallActionScript` (for example
    `transitionState`, `setWifiMode`);
  - ActionScript calls back with `SUBJECT_*` events into the front-end state's `OnEvent`.

  Menu mods can either replace the movie (assets) or call these functions from Lua.

### Dead Ops and pathing

**Dead Ops Arcade** is a separate top-level game state (`CDOGameStateIngame`) with its own
systems:

- `CDORoundManager` runs the rounds (states, `ROUND_COMPLETED`, the round indicator);
- `CDOHordeManager` spawns enemies;
- `CDOPickupManager` handles power-ups;
- `CDOPersistentStorage` holds unlocks and has the console cheats `GodMode` and `ManyLives`.

The player is `CDOPlayerController`, which can switch body (walking, helicopter, tank).
Everything about a run is data:

- 42 `CDORound` entries pick the arena, lighting and music;
- `CDOZombieSpawner` hordes say which enemy unlocks at which round and how spawn rates grow.

**Zombie movement** uses Recast/Detour crowds:

- each map has a standard Detour navmesh;
- zombies are crowd agents whose speed, avoidance and climbing are reflected fields;
- window and barricade climbs are the game's own connection objects;
- per-round speeds come from the wave's walk/run/sprint values (`CWave`).

See [asset-formats.md](asset-formats.md).

### Console variables worth knowing

The game registers 597 cvars (`re/cvars.json`). They can be set without code, from `console.bin`
or a mod's console file.

| Kind | Cvars |
| --- | --- |
| Camera and aim | `EnableSetFov` + `SetFov` (built-in field of view override, default 50), `TurnSpeed`, `PitchSpeed`, `AimTurnSpeed`, `SprintTurnSpeed` and their `Perked*` variants, `Touch/Analogue/Sticky/AccelAim{X,Y}Sensitivity` |
| Movement | `WalkSpeed`, `SprintSpeed`, `CrouchSpeed`, `ProneSpeed` and `Perked*` variants |
| Rules | `StartingScore`, `LastStandDuration` (co-op) and `LastStandDurationSinglePlayer`, `PlayerDownScorePenalty`, `StaggerStartingZombies`, `GeorgeRomero` |
| Cheats (developer) | `UnlimitedScore`, `UnlimitedHealth`, `WeaponsUnlimitedAmmo`, `UnlimitedStamina`, `AIGodmode` |

The camera and aim cvars are the obvious start for Redux's FOV and turn-rate settings. They are
recorded here, not yet studied.

### How a frame runs (where events and hooks attach)

Mapped in Ghidra; names are in the symbol database.

1. `GameMain` calls `CGame::Update` every frame, which forwards to `CIwGame::Update`.
2. **Begin frame** (`CGame::BeginFrame`): clears the screen, then `UpdateStates` gives the
   current top-level state its `Update`:
   - `CGameStateIngame::Update` runs the in-game sub-state machine;
   - `CIngameStatePlaying::Update` ticks the Marmalade world (`CIwWorld::Update`) and checks
     the pause key;
   - the state also updates the IwUI controller and view (menus and HUD widgets).
3. **End of frame** (`CGame` slot 27):
   - the state's `Render` draws the camera view through the sector manager, then
     `Director_Render` and the HUD;
   - then sound, ambience, music and the network update;
   - then `Director_Tick` advances the game clock (`g_director`) and runs the studio layer.
4. **Studio layer, in dependency order:**
   - every component table's `Update`, which calls each enabled component's update, then
     `Update2` and `Update3`;
   - every system's `Update` and `LateUpdate`;
   - every frame, even when paused: table `PostUpdate` and system `PostUpdate`.

This gives natural places for client events:

- `boz.on("frame")` after `Director_Tick`;
- `boz.on("render")` after `Director_Render`;
- state changes from `CIwGame::SetState` and each state's `Enter` and `Exit`.

Systems are found through their `T::s_instance` globals (65 of them, for example
`CWaveManager`, `CDORoundManager` and `CLevelManager`). The local player is the entity whose id
is at `CLevelManager + 0x1a0`.

## The Redux base mod

Redux (FOV, uncapped mouse look, sensitivity curves, quality-of-life settings) is built **after**
the map and the API, using only the public API. It is the proof that the platform works, not the
reason for it.

## Order of work

1. ELF conversion and the Ghidra project (done: `tools/ghidra/s3e_to_elf.py`).
2. Symbol database format with apply/export scripts.
3. Broad subsystem mapping (the list above), with live-tracing support in the client.
4. Lua runtime, hooks and events; [lua-api.md](lua-api.md) written alongside.
5. Asset overrides and the launcher's Mods tab.
6. The Redux mod.
