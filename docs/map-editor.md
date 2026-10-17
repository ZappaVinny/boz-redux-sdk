# The map editor

Everything about making maps in the BOZ Redux editor: its layout and Build & Run, building the
level, scripting it, its rules, what each of the game's objects does, how walkable areas work,
and editing the game's original level files. Weapons, your own models, effects and sounds have
their own page: [Weapons, models, effects and sounds](weapons-and-assets.md).

## The editor

The BOZ Redux editor is Blender 5.2 LTS set up for making Zombies maps. It opens from the SDK
app (**Open in Editor** on a map project) and saves straight into the project. Everything you
see is drawn the way the game draws it, and **Build & Run** puts your map in the game in one
click.

If you know Blender, most of it will feel familiar: G moves, R rotates, S scales, Tab enters
Edit Mode. Stock Blender features that cannot reach the game are hidden. One Blender unit is
one game centimetre.

### The window

- **Top bar:** the **Project**, **Edit** and **Help** menus, then the tabs, then **Build & Run**
  (with its ⚙ settings) on the right.
- **Viewport:** the map, in material preview with the game's shading.
- **Asset browser** (World tab, left): the game's objects to drag into the map.
- **Outliner:** every object. An object's name is its name in the game and in scripts.
- **Properties:** only Object, Modifiers, Data and Material. The Object tab's **Game** panel
  shows what the selected object is and its settings.
- **Sidebar** (N in the viewport): the **BOZ** tab (show options, the selected object's links),
  **Problems**, and **Shipped files**.
- **Log** areas: the build's output and the game's `boz-log.txt`.

### The tabs

| Tab | What you do there | Guide |
| --- | --- | --- |
| **Game** | The map's rules: name, loading screen, rounds, special rounds, points, power-ups, the box, scripts for game events | [Game rules](#game-rules) |
| **World** | Build the level: models, volumes, prefabs, the game's machines, doors and spawns | [Building the world](#building-the-world) |
| **Weapons** | Change, copy and import weapons; give them your own models and sounds | [Weapons](weapons-and-assets.md#weapons) |
| **Characters** | Not available yet | |
| **Assets** | Import your own models and make game versions of them | [Your own models](weapons-and-assets.md#your-own-models) |
| **Effects** | Pick the game's effects and projectiles for your scripts | [Effects and projectiles](weapons-and-assets.md#effects-and-projectiles) |
| **Animation** | Change a weapon's animations | [Weapons](weapons-and-assets.md#animations) |
| **Scripts** | Edit the map's Lua scripts | [Map scripting](#map-scripting) |
| **Audio** | Replace the game's sounds with your own | [Sounds](weapons-and-assets.md#sounds) |
| **UI / HUD** | Not available yet | |

Features that are planned but not built yet show as panels in their tab, so you can see what is
coming.

### Saving a map

**Project → Save** (Ctrl+S) saves the scene as `map.blend` and writes the project's `source/`
folder, which is what the build reads ([Project files](sdk-reference.md#project-files)). Edited
scripts are saved with it.

### Build & Run

**Build & Run** saves, builds the map into a mod, installs it into your client (last in the load
order, so its files win), and starts the game. Once the main menu is up, the game goes straight
into your map.

The ⚙ next to it sets how the test starts:

- **Unlimited health**
- **Unlimited points**
- **Starting points**

They are set for the game Build & Run starts; starting the game any other way leaves them off.
The same dialog sets the map's **base level** (the shipped level its rounds, zombie types,
sounds and cameras come from). The Developer mod is always on in a test, so its console (`` ` ``
or F1) is at hand.

If something would stop the build, the **Problems** tab in the sidebar lists it, with a button
that selects the object at fault. **Project → Check for problems** runs the same checks.
Build & Run refuses to start while the game is already running.

### Playing your map later

After the first Build & Run your map is a mod in the client, and the client knows it is a map.
The client launcher's list next to **PLAY** offers **Main menu** and each map from your enabled
mods; pick yours and press **PLAY** to start the game straight into it. Players who install
your packaged mod get the same choice.

### Menus

- **Project:** Save, Build & Run and its settings, **Import model…** (FBX, glTF and OBJ, scaled
  from metres), **Add game shape**, the **Prefab library**, **Check for problems**, **Open project
  folder**, and back to the SDK app.
- **Edit:** undo, redo, undo history, Blender's preferences.
- **Help:** these guides.

## Building the world

The editor's **World** tab is where you build the level itself: walls and floors, the game's
perk machines, doors and spawns, invisible volumes for your scripts, and prefabs that bundle
them into reusable pieces. This section explains the kinds of object and the tools for placing
them.

### Three kinds of object

| Kind | What it is | How you add it |
| --- | --- | --- |
| **Model** | A mesh you see and bump into: a game model, or your own | Asset browser → Models, Add → Game shapes, Project → Import model |
| **Volume** | An invisible box that sends events to scripts: **Trigger** (walked into), **Hit** (shot), **Use** (the player presses use) | Asset browser → Volumes |
| **Prefab** | One object made of parts (models, volumes and other prefabs), with an optional script. **Game prefabs** are the game's own objects: perk machines, wall buys, doors, spawns, ... | Select objects and **Make prefab** (Ctrl+G); asset browser → Game prefabs and Level markers |

Every object's name is its name in the game and in scripts.

#### Model objects

A model is a **game model** (dragged from the asset browser) or **your own mesh** (built in
Blender, from Add → Game shapes, Project → Import model, or **Make editable** on a game model).

Its **Collision** decides how the game treats it:

- **Walkable:** players stand on it, and the walkable area (navmesh) is built on top of it.
- **Blocking:** it blocks players, zombies and bullets.
- **None:** it is only drawn.

**Box** uses the model's bounds for collision, **Mesh** its triangles. Copies made with Alt+D
share one mesh, in Blender and in the game.

#### Volume objects

A volume is drawn as a see-through box: teal for Trigger, red for Hit, green for Use. Its size
is its scale (100 cm at scale 1). A volume's **Set off by** (Players, Zombies, Anyone) and
**Only once** filter its events; a Use volume also has a **Prompt** and a **Cost**. What
scripts do with volumes is in [Map scripting](#map-scripting).

#### Prefab objects

**Make prefab** (Ctrl+G, or the Object menu) groups the selected models, volumes and prefabs
under an Empty; **Ungroup** (Ctrl+Alt+G) takes it apart again. A part keeps its **part name**
inside the prefab (in the game: `<Prefab>.<Part>`); its object is named `<Prefab> › <Part>`, so
searching the outliner for a prefab shows all of it.

**Save as new prefab** stores a prefab in the project's library. It appears in the asset browser
under **My prefabs**; dropping it places an independent copy. Project → Prefab library deletes
library prefabs.

### The game's own objects

The asset browser's **Game prefabs** are working copies of the game's objects:

- **Machines:** the perk machines, Pack-a-Punch, the mystery box, the power switch.
- **Buying:** wall buys.
- **Doors** and **Barricades**, in every design the game's maps have.
- **Defence:** traps and trap switches.

**Level markers** are the invisible ones: player and zombie spawns, jump points, sound emitters.
In the viewport they are small cubes coloured by type.

A game prefab's **Game** panel (Properties → Object) shows its settings: cost, **Needs power**,
use distance and so on. [Game prefab fields](#game-prefab-fields) explains every
one. Game prefabs can be parts of your own prefabs.

- **Wall buy:** **Choose…** picks one of the project's weapons (add more in the Weapons tab).
  The editor shows the weapon and its chalk drawing: the weapon's own, one drawn from its model,
  your own image, or none.
- **Edit its model** gives a game prefab an editable copy of its mesh. It keeps its behaviour (a
  Pack-a-Punch still upgrades weapons) and the game draws your mesh. **Use the game's model**
  goes back.

A dropped game prefab becomes a working entity of the map's base level when it has one, else
another map's (brought over with everything it needs), else the shared template.

### When the level starts

Models and prefabs have **When the level starts** settings:

- **Visible**
- **Collision**
- **Blocks the walkable area:** the navmesh under it stays shut until a script opens it, so
  players and zombies cannot pass. A wall that a script removes uses this.

### Object scripts

Any object can have a **Script**. **New** makes `scripts/prefabs/<Name>.lua` from a template and
opens it in the **Scripts** tab; **Pick…** uses an existing script. The script's `---@property`
lines become fields in the panel, with a value for each object. See
[Map scripting](#map-scripting).

### Building with shapes

Add → **Game shapes** (also the World header's **Shapes** button) adds blocks, walls, floors,
ramps, stairs and pillars at game size, with a tiling texture and the right collision. Blender's
own Add → Mesh shapes are 2 cm big here, since one unit is a centimetre; the Problems panel flags
anything that small.

**Project → Import model…** brings in FBX, glTF and OBJ files, scaled from metres. For detailed
models (a statue, a gun) use the Assets tab instead: it makes a game version with the right
number of triangles ([Your own models](weapons-and-assets.md#your-own-models)).

### Textures

Properties → Material shows every texture slot with a preview:

- **Replace…** loads an image file.
- **From game…** uses any of the game's textures, with game shading.
- **✕** goes back to the default grid texture.

Game models need **Make editable** before their textures can change. Dropping a texture from
the asset browser onto an object gives it the same game-shaded material.

### Changing an original map

Maps made from **Kino der Toten**, **Call of the Dead**, **Ascension** or the **Tutorial** start
as the whole original map. Its entities (perks, doors, wall buys, spawns, triggers, traps, ...)
are game prefabs you can move, rotate, scale, delete (X), copy (Shift+D), change the settings of,
or start hidden. Only what you changed is written into the map; **Put back as the level has it**
undoes the changes to an object. The rooms themselves stay as they are.

### Seeing what the game sees

The **Show** menu (World viewport header, and the sidebar's BOZ tab) switches overlays:

- **Markers** and **Triggers** (the game's own volumes on entities);
- **Links** between objects (power, doors, areas);
- **Walkable** and **Collision**, which build the map and show its navmesh (blue, orange where a
  door blocks it) and collision mesh. **Refresh** builds them again after edits.

Game models use the game's materials (vertex colours, lightmaps, blend modes); your own materials
are drawn unlit, as the game draws them. The viewport uses the Standard view transform so colours
match the game.

### The asset browser

The World tab's asset browser shows the "BOZ Game" library:

- **Game prefabs:** Machines, Buying, Doors, Barricades, Defence;
- **Level markers:** Spawns, Jump points, Sound;
- **Volumes:** Trigger, Hit, Use;
- **Models** and **Textures** from every map;
- **My prefabs** and **My assets**: your own.

The editor builds the library from the SDK's asset library the first time (about 30 seconds) and
again after the asset library changes.

## Map scripting

Scripts make a map do things: a door that opens when a skull is shot, an easter egg, a trap of
your own. A script is a Lua file attached to an object in the editor; it reacts to volumes and
game events, and changes objects. This section builds an example step by step, then lists
everything a script can use.

A map is made of three kinds of object ([Building the world](#building-the-world)), and scripts tie them
together:

| Kind | What it is | In the editor |
| --- | --- | --- |
| **Model** | A mesh you see and bump into: a game model, or your own | Palette Models, Add → Game shapes, Project → Import model |
| **Volume** | An invisible box that sends events: **Trigger** (walked into), **Hit** (shot), **Use** (player presses use) | Palette Volumes |
| **Prefab** | One object made of parts (models, volumes, prefabs), with an optional script. **Game prefabs** are the game's own: perk machines, wall buys, doors, spawns, ... | Select objects, **Make prefab** (Ctrl+G); palette Game prefabs and Level markers |

Every object's **name** is how scripts find it. Inside a prefab, a part keeps its **part name**
(Door, Skull, ...), and scripts reach it with `self:part("Door")`.

### 1. Build it in the editor

An example: a vault door that opens when a skull is shot.

1. Add a wall: Add → Game shapes → Wall. In its Game panel, under **When the level starts**,
   tick **Blocks the walkable area**, so zombies and players can't walk through until it opens.
2. Drop a **Hit volume** from the palette (Volumes) where the skull should be. Drop the
   Insta-Kill model from Models → Shared on the same spot, so there is something to see.
3. Select the wall, the volume and the model, then **Make prefab** (Ctrl+G). Name the prefab
   `Vault`. Set the parts' **part names** to `Door`, `Skull` and `Skull_model`.
4. In the prefab's **Script** box, press **New** and name it `Vault`. The editor makes
   `scripts/prefabs/Vault.lua` and opens it in the **Scripts** tab. Saving the map (Ctrl+S)
   saves the script too; the link button next to the script opens your own editor instead.

### 2. Write the script

```lua
---@property reward integer 500 "Points for opening it"

function on_hit(volume, info)
    self:part("Skull_model"):hide()
    self:part("Door"):hide():set_collision(false):open_navmesh()
    boz.send("vault_open", {vault = self.name})
end
```

That is the whole script. `self` is the prefab it is attached to, so there is nothing to set up.
`on_hit` only runs when one of the prefab's **Hit volumes** is shot. Models never send it. With a
single Hit volume there is nothing to check; with several, `volume` says which one
(`if volume == "Skull" then ... end`).

Save the script, then press **Reload properties** in the Script box. The `---@property` lines
show up as fields, here **Reward**. Each prefab using the script has its own value, and at
runtime it is `self.properties.reward`.
Build & Run.

### 3. Reuse it

**Save as new prefab** puts `Vault` in the project's prefab library: it shows in the asset
browser on the left under **My prefabs**, and you drag copies into the map like any other asset
(Project → Prefab library deletes them). Each copy is independent: change its properties or
its parts without touching the others. To make a new base, edit a copy and Save as new prefab
again under another name.

### What scripts get

A script is just its functions. When the level starts, it runs once for every object it is
attached to, each run with its own `self` and its own top-level variables (a `local hits = 0` at
the top counts for that object alone). `boz` is the scripting module. `print(...)` shows in the
Developer console (` or F1) and in `boz-log.txt`. Every handler is optional:

| Handler | When |
| --- | --- |
| `start()` | The level started |
| `on_enter(volume, who)`, `on_exit(volume, who)` | A Trigger volume of the prefab: `who.player`, `who.zombie` |
| `on_hit(volume, info)` | A Hit volume of the prefab was shot |
| `on_use(volume, who)` | The player pressed use at a Use volume of the prefab (its cost already paid) |
| `on_event(name, data)` | `boz.send(name, data)` from any script, and the game events below |

#### Map script game events

| Event | `data` |
| --- | --- |
| `round_started` | `round`: the round number |
| `power_on` | |
| `perk_bought` | `perk` ("Juggernog", "Quick Revive", ...), `player` (true for the local player) |
| `door_opened` | `door`: the door's name (`0x...` for a door the map does not name), `hash` |
| `zombie_killed` | `position` ({x, y, z}), `entity` (the zombie, the same as `who.entity` in `on_enter`), `by_player`, `headshot` |
| `player_downed`, `player_revived` | |
| `weapon_given`, `weapon_equipped`, `weapon_reloaded` | `weapon` (its name); `weapon_fired` reaches `boz.on` only. Weapon scripts: [Weapons](weapons-and-assets.md#weapon-scripts) |
| `round_ended` | `round`: the round that ended (once per round) |
| `points_earned`, `points_spent` | `points`, `player` (true for the local player) |
| `player_hit` | `damage`: what the zombie's hit took |
| `box_weapon` | `weapon`: what the mystery box picked |
| `pack_a_punch` | `weapon`: the weapon that went in |
| `powerup_grabbed` | `powerup` ("nuke", "max_ammo", "insta_kill", ...), `player` |
| `nuke`, `carpenter`, `trap_activated`, `teleporter_activated` | |

"Killed near something" needs no event of its own: compare `data.position` with an object
(`self:part("Altar"):near(data.position, 200)`), or put a Trigger volume around the spot and
remember which zombies are in it (`who.zombie`, `who.entity` in `on_enter` / `on_exit`).

`volume` is the volume's part name: only volumes send these. A volume with its own script gets
its own name. Any other function a script defines can be called by other scripts:
`boz.find("Vault_1"):open()` runs `function open() ... end` of Vault_1's script.

| On `self` | |
| --- | --- |
| `self.name`, `self.properties` | Its name, and the property values set in the editor |
| `self:part(name)`, `self:parts()` | A part (a `boz.objects` handle), and all parts |
| `self:hide()`, `self:show()`, `self:set_collision(on)`, `self:open_navmesh()`, `self:close_navmesh()` | The whole prefab (every part), or the model |
| `self:position()`, `self:near(target, cm)` | Where it is ({x, y, z} in centimetres; a prefab's middle), and whether any part is within `cm` of a position or another object |

| Module | |
| --- | --- |
| `boz.send(name, data)`, `boz.on(name, fn)` | The event bus between scripts |
| `boz.find(name)` | Another scripted object (its instance), else its `boz.objects` handle |
| `boz.after(seconds, fn)`, `boz.every(seconds, fn)` | Run `fn` once after a delay, or repeatedly. Game time: they wait while the game is paused. Both return a timer with `:cancel()` |
| `boz.globals` | One table every script of the map shares, saved with the game |

Every volume event also goes to `boz.on` listeners as `"<volume>.<event>"`, so any script can
listen: `boz.on("Vault_1.Skull.hit", fn)` (`on_event` does not get these; the volume's own
script already had its handler). A Trigger volume sends `on_enter` once when something comes in
and `on_exit` once it has left. A Use volume works from every side, within an arm's length of its
box. A volume's **Set off by** (Players, Zombies, Anyone) and
**Only once** filter its events. A Use volume shows its **Prompt** (and **Cost**) while the player
can use it, and takes the points before `on_use` runs.

A part handle (`boz.objects`) has `show()`, `hide()`, `set_visible(on)`, `set_collision(on)`,
`open_navmesh()`, `close_navmesh()`, `position()`, `near(target, cm)` and `on(event, fn)`. All of them return the handle, so they
chain. See the [standard library](standard-library.md) for `boz.objects` and `boz.prefabs`.

### Saved with the game

A script's **global** variables are saved when the game saves (the autosave at every round
start, and pausing) and come back when the player continues that save. `local` variables are
not saved: how you declare a variable decides it.

```lua
skulls_shot = 0          -- global: saved
door_open = false        -- global: saved
local hint_timer = nil   -- local: this session only

function on_hit(volume, info)
    skulls_shot = skulls_shot + 1
    if skulls_shot == 3 then
        door_open = true
        self:part("Door"):hide():set_collision(false):open_navmesh()
    end
end

function start()
    if door_open then     -- continued from a save where it was already open
        self:part("Door"):hide():set_collision(false):open_navmesh()
    end
end
```

Each object keeps its own: every Vault copy saves its own `skulls_shot`. `boz.globals` is one
table for the whole map (`boz.globals.eggs_done = 2`). When the level starts, each script runs
top to bottom (its defaults), then a continued save puts its values back, then `start()` runs.
Numbers, strings, booleans and tables of those are saved; functions, object handles and timers
are not.

### How map scripts work

The build lists every scripted object and every volume in `scripts/boz/world_data.lua`, with
property values and parts. `boz.world` starts `boz.prefabs` when each level starts. Objects are
found by their `CIsNamed` name. Volume events are `boz.objects` hooks on the game's own functions:

- collision enter and exit for Trigger volumes;
- the easter egg skull's weapon hit for Hit volumes;
- `Poi_SendUse` for Use volumes.

The game events come from `boz.match_events` (any mod can use it directly):

- `CWaveManager::StartWave` for `round_started`;
- the wave manager's power flag for `power_on`;
- `CPerkManager::GainPerk` for `perk_bought`, a door's state turning open for `door_opened`, the
  zombie's dead state for `zombie_killed`, the player's stance for `player_downed` /
  `player_revived`;
- `CScoreManager::AddScore` for `points_earned`, `CPickupManager::ApplyPickup` for
  `powerup_grabbed`, and the game's own events for the rest (`SUBJECT_WAVE_ENDED`,
  `SUBJECT_CHARGE_POINTS`, `SUBJECT_ENEMY_ATTACK_DAMAGE`, `SUBJECT_MB_CHOOSE_WEAPON`,
  `SUBJECT_PACKAPUNCH_START`, `SUBJECT_NUKE_NOW`, `SUBJECT_CARPENTER_ACTIVATED`,
  `SUBJECT_ON_TRAP_ACTIVATED`, `SUBJECT_ON_TELEPORTER_ACTIVATED`), once each (they reach several
  subjects).

Timers are `boz.timers` (game time: frames in which `CPlayerController::FixedStep` ran). Saved
globals use `boz.saved`:

- `CSaveManager::SaveGame` and `CSaveManager::NotifyLoad` for saved globals, kept in the map
  mod's settings (`saves/mods/<map>.cfg`), next to the game's own save, which is never changed.

[Game prefab fields](#game-prefab-fields) lists what each game prefab and volume is made of.

## Game rules

The **Game** tab sets a map's rules: its name and loading screen, its rounds, the special rounds,
which zombie looks spawn, the points and power-ups, and scripts that run when things happen. Until
you change a section, the map uses its base level's own rules (shown in the tab); the first change
makes them the map's own (`source/game.json`).

### Level info

- **Name:** the map's name in the launcher and the mod list.
- **Loading screen:** a picture (PNG or JPG) shown while the map loads. It fills the screen at 4:3
  (1024 x 768); the "Loading" text and the tips are drawn over it. Pure magenta (255, 0, 255) shows
  as black.
- **Starting weapon:** set in the Weapons tab (shown here).
- **Power on at the start:** the power is on as soon as the map starts.
- **Behaves like:** some of the game's code checks the map's name. Pick Kino, Ascension or Call of
  the Dead and the level manager's checks answer as that map: Kino's teleport start, Ascension's
  round effects, Call of the Dead's snow camera and start sound (the build brings what they
  play). Other code that compares names itself (Call of the Dead's zombies and Pack-a-Punch,
  Ascension's attack distances) stays with those maps.

### Rounds

Each game has its own rounds: single player on easy, normal and hard, and co-op with 2, 3 or 4
players. Pick one under **Game**, or tick **Same for all** to change every game at once (**Use these
rounds in every game** copies the shown game's rounds to the rest).

The list holds the rounds in order. Each round sets:

| Setting | What it does |
| --- | --- |
| Zombies | how many zombies the round has |
| Health | each zombie's health (an easy game halves it) |
| At once | the most zombies alive at the same time |
| Spawn at start | zombies that spawn as soon as the round starts |
| Walkers, Fast walkers, Runners, Sprinters | the share of zombies at each speed (0-1) |
| Spawn interval | milliseconds between spawns |
| Break after | milliseconds from the round's end to the next round |
| Start delay | milliseconds from the round's start to its first spawn |
| Zombie type | what spawns (empty: the map's zombie) |
| Powered zombies, type and health | extra zombies once the power is on (Kino's crawlers) |
| Fog | the fog the round sets |

The last round can **repeat**: it plays again and again, each time growing by its multipliers
(**Zombies x**, **At once x**, **Spawn interval x**, **Powered zombies x**) once the round number
is past **Grows after round**. For example 25 zombies with Zombies x 1.1 from round 10 gives
round 12 30 zombies (25 x 1.1 x 1.1).

**Repeating health:** the game ignores a repeating round's health and uses 10 x round x round -
150 (round 20: 3850). **Grows by the multiplier** uses the round's **Health** and **Health x**
instead.

The graph on the right shows zombies (orange) and health (blue) for rounds 1 to 40 of the shown
game. **Back to the base level's rounds** forgets the map's own rounds.

### Special rounds

Dog rounds (and Ascension's space monkeys) come between normal rounds. Each is for one game
(**For**). The game runs them in order: one plays **Times** times, then the next takes over. A
special round comes after **At least** and at most **At most** normal rounds, with **Chance**
percent each round in between. **Count by players** is how many spawn with 1, 2, 3 or 4 players.
**Add a special round** makes a dog round to start from.

### Zombie types

A level has a few zombie looks (a skeleton and body part models). Zombies spawn with one of the
ticked looks, picked at random.

### Pickups and economy

Tick a setting to change it on this map (other maps keep the game's values):

- **Points at start**, **Points lost when down** (share of points), **Self revive** cost.
- Power-up drops: **Points between drops**, **Kills between drops**, **Drop chance** (per kill once
  a drop is due), **Drops per round**.
- Power-up times: **Double points**, **Insta-kill**, **Fire sale**, **Death machine** (ms).
- **Change the power-ups:** how likely each power-up is against the others (0: never).
- **Change the points:** points for a hit, each kind of kill, a barricade board, Carpenter and the
  Nuke, and the barricade limit (at most this x the round number per round).
- **Change the mystery box:** its cost, the fire sale cost and how many weapons it shows when it
  spins. A box given its own cost in the World tab keeps it.
- Zombies alive at most, base zombie health, grenades per round.

### Hook scripts

Every event a script can follow, with **Create** (a stub in `scripts/hooks/<event>.lua`) or
**Open**. The script returns a function that runs every time the event happens:

```lua
-- scripts/hooks/round_started.lua
return function(data)
    log("round " .. data.round)
end
```

The list grows with the standard library.

### How the rules work

- **Rounds** (Ghidra: `CLevelManager::StartFirstWave`, `CWaveManager`): the level's `CLevel` names
  each game's first round (`m_StartingWavesSP` by difficulty, `m_StartingWavesMP` by players);
  each `CWave` names the next (`m_NextWave`); a `CWaveRepeatable` without a next one repeats,
  scaling by multiplier ^ (round - `m_StartingWave`). `CWaveRepeatable::GetZombieHealth` is
  10 x round^2 - 150; boz.game replaces its result for **Grows by the multiplier**. Special
  rounds (`CWaveSpeciality`, `CWaveMonkey`) are picked by `m_waveType` (0-2 the difficulty, 3-5
  the players). The build writes the map's rounds as `boz_<game>_<n>` and `boz_special_<n>`.
- **Economy:** console variables (`StartingScore`, `PickupPointsThreshold`,
  `ProbabilityOfSpawningEachPickup`, ...), set by boz.game just before the map's level loads
  (`Level_Load`) and put back on other maps. Points come from a `CScoreConfig` (`m_Scores` and
  `m_ScoreLimits`); the map ships its own (`boz_score_<map>`) and points `ScoreConfigName` at it.
- **Loading screen:** `fixed`'s `loading-<map>` names a loading group per screen size; the build
  points them at `loading_<map>`, a copy of Kino's with the picture replaced (1024 x 1024 ETC1,
  encoded by bozkit).
- **Box:** the `CMysteryBox` components still at the game's values.
- **Behaves like:** boz.game answers `String_Equals(level name, "<map>")` with true (the
  level manager's checks: `Level_IsAscension`, `Level_Load`, `LevelManager_SetCamera`,
  `LevelManager_UpdateAmbience`).

`bozkit/game.py` compiles it; `lib/boz/game.lua` and `lib/boz/hooks.lua` run it.

## Game prefab fields

What each of the game's objects is (the asset browser's **Game prefabs** and **Level
markers**), which of its settings the editor lets you change, and why the others stay as they
are. The tables cover every entity in the four shipped levels and every field the game registers
for their components (`gamedef/reflection`).

**Default** is the game's value when a level leaves the field out (shipped data only stores
fields that differ from it).

Fields marked *editor* appear in Properties → Object → Game (Settings) when the game prefab is
selected. Units: points, centimetres (cm), seconds (s; the game stores milliseconds).

Every object (models and prefabs) also has **When the level starts**: Visible, Collision and
Blocks the walkable area, and a **Script** whose `---@property` lines add fields of their own
([Map scripting](#map-scripting)). The original map's own entities can start hidden or
without collision; their walkable area stays as shipped.

### The game prefabs

#### Perk machines (`CPerk`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_perkSinglePCost` | — | Points it costs in solo | editor: Cost |
| `m_perkMultiPCost` | 1500 | Points it costs in co-op | editor: Co-op cost |
| `powerSwitch` | 0 | Name of the power switch it waits for. `boz_no_power` makes it work without power (`boz.world` powers it at `CPerk::Init`) | editor: Needs power |
| `CPOI.m_MaxDistance` | 300 | How close players must be to use it (cm) | editor: Use distance |
| `m_numOfUses` | 3 on Quick Revive | Solo Quick Revive uses | no (Quick Revive only) |
| `perkName`, `m_PerkType`, sting | — | Which perk it gives and its jingle | no: pick another machine instead |
| `CHealth.m_MaxHealth` 500 | — | Monkeys attack machines (Ascension) | no |
| `CIsCollisionBox` 150 × 270 × 120 cm | — | The machine's solid box | no |

#### Pack-a-Punch (`CPackAPunch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | 5000 | Points an upgrade costs | editor: Cost |
| `powerSwitch` | — | Power switch it waits for; off writes 0 and `m_HasPower` = true | editor: Needs power |
| `CPOI.m_MaxDistance` | 300 | Use distance (cm) | editor |
| `m_HasPower`, `m_State`, `m_WeaponHash`, ... | — | Runtime state | no |

#### Mystery box (`CMysteryBox`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | 950 | Points a spin costs | editor: Cost |
| `m_FireSaleCost` | 10 | Points a spin costs during a Fire Sale | editor |
| `m_MinWeapons`, `m_MaxWeapons` | 4, 10 | The box moves after a random number of uses between these | editor |
| `m_Weapons` | empty | The weapon pool (empty: the level's) | not yet: needs the Weapons tab |
| `m_RefundCost`, `m_State`, timers | — | Runtime state | no |

The level picks which box location is active (`CLevel` `MysteryBoxStart`, `MysteryBoxAvoid`).

#### Power switch (`CPowerSwitch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `StartEnabled` | true | Players can pull it from the start (Ascension's launch switch starts disabled) | editor: Usable from the start |
| `playSound` | — | Sound when pulled | no |

#### Wall buy (`CWeaponChalkOutline`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| weapon (`model` child asset name) | — | The weapon it sells | editor: Weapon |
| `m_cost` | — | Points the weapon costs | editor: Cost |
| `m_ammoCost` | 0 (half the cost in game) | Points a refill costs | editor: Ammo cost |
| `m_upgradedAmmoCost` | 0 | Points a refill of the upgraded weapon costs | editor: Upgraded ammo cost |
| chalk decal | the weapon's own | The drawing on the wall (a separate decal) | editor: Chalk |
| `m_weaponType` | — | Prompt type: firearm, melee, grenade | no: follows the weapon |
| `CPOI.m_BiDirection` | true when placed | Usable from either side | set by the compiler |

#### Doors and debris (`CDoor`, one design per model in the game)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | — | Points to open | editor: Cost |
| `powerSwitch` | 0 | Opens itself when this power switch is pulled (not buyable) | editor: Needs power |
| `m_HideAfterActivate` | false | The model disappears once opened (debris) | editor: Disappears when opened |
| `playSound` | — | Sound when opening | no |
| `m_AreasUnlock` | — | Zones (`CArea`) it unlocks | placed doors unlock none (generated maps have one area) |
| `CIsCollisionBox` 300 × 300 × 10 cm | — | Blocks players until open | no |

The navmesh under a door is tagged with its name and closed until it opens (`CDoor::Init`,
`CDoor::OnEvent` → `NavMesh_SetTagOpen`).

#### Window barricade (`CBarricade`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_StartBroken` | false | The planks start torn down | editor: Starts broken |
| `CPOI` | 170 cm | Repair reach | no |

#### Trap and trap switch (`CTrap`, `CTrapSwitch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `CTrap.m_ActivePeriodMS` | 30 s | How long it runs once bought | editor: Runs for (s) |
| `CTrap.m_CoolDownPeriodMS` | 10 s | Wait before it can be bought again | editor: Cool-down (s) |
| `CTrap.m_PlayerDamage` | 115 / 230 | Damage to players who walk in | editor |
| `CTrap.damageEffect`, `startSound` | — | Effect and sound | no |
| `CTrapSwitch` cost | 1000 | Points to run the trap | editor: Cost |
| `CTrapSwitch.powerSwitch` | — | Power switch it waits for | editor: Needs power |
| `CTrapSwitch` traps list | — | Which traps it runs | not yet: needs links |

#### Spawns (`CSpawnPoint`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `spawnType` | — | windows, ground, Lightning (dogs), Hole, Monkey | the level marker you pick |
| `m_StartActive` | false | Used from the first round, not only once players reach its area | editor: Active from the start |

Player spawns are the entities named `spawn_player_1` to `_4`.

#### Level markers: jump point, sound emitter

| Piece | Field | Meaning | Editor |
| --- | --- | --- | --- |
| Jump point | `m_jumpAreaHash` | The jump area zombies cross to | no: linked by the level |
| Sound emitter | `soundName` | The sound it plays | editor: Sound |
| Sound emitter | `StartEnabled` | Plays from the start | editor: Plays from the start |

### Volume entities

Volumes are not game prefabs: they have no behaviour of their own and only send events to
scripts. Each compiles to an entity made from a shipped template:

| Volume | Made from | In the game | Script event |
| --- | --- | --- | --- |
| Trigger | Call of the Dead's snow trigger box (`CIsCollisionBox`, `m_Ghost` on, `CCollisionFilter`, `CEntityFlags`) | A ghost box sized by the volume | `enter` / `exit` (`CIsCollisionObject::OnCollisionEnter` / `OnCollisionExit`) |
| Hit | Kino's musical easter egg skull (`CEasterEgg`, `CHealth`, `CIsCollisionSphere`) | A sphere of the volume's largest side, with a song of its own so it stays out of the level's easter egg | `hit` (`CEasterEgg::OnEvent`, skipped for the game) |
| Use | A barricade's `CPOI` and `CIsBroadcaster`, without the barricade | A point of interest the game draws no prompt for; reach: half the size plus 75 cm | `use` (`Poi_SendUse`); the prompt and cost come from `boz.prefabs` |

### Points of interest (`CPOI`)

Everything players use has a `CPOI`. `m_poiType` picks the prompt: 0 barricade, 1 door, 2 wall
buy, 3 box, 4 perk, 5 Pack-a-Punch, 6 trap switch, 7 power, 8 turret, 9 teleporter, 10 mainframe,
11 lander, 12–13 lander station, 14 revive, 15 claymore, 16 tutorial pickup
(`LevelManager_UpdateNearestPoi`, `CIngameStatePlaying::OnEvent`). The other fields set the reach:
`m_MaxDistance` (cm), `m_ViewingAngle`, `m_AngleDistanceOffset`, `m_HeightOffset`,
`m_MaxYDistance`, `m_BiDirection` (either side), `m_Moveable`, `m_IsReverseViewAngle`. Pressing
use runs `Poi_SendUse`, which broadcasts the interact event to the entity in reach.

### Not game prefabs yet

These are in the shipped levels; each needs its own game prefab or links before it is useful:

- Turret (`CTurret`: cost, duration, damage, range, rate of fire, cool-down, power).
- Teleporter, mainframe and Gersch points (`CTeleporter`, `CTeleportMainframe`, `CTeleportPointGersch`).
- Rides: lunar landers, zipline, flinger, centrifuge, ice slide (Ascension, Call of the Dead).
- Animated scenery, TV and projector screens, fog effects, lights.

## Navigation meshes

In BOZ, players and zombies do not walk on the level's collision. They walk on a separate
**navigation mesh** (navmesh): a map of the floor where anyone can go. Collision only decides
what bullets and other ray casts hit. So when you add a wall, the navmesh has to change too, or
players walk straight through it.

You rarely need to think about this: when you save a map whose collision changed, the SDK
rebuilds the navmesh around the change, and doors and blocking objects are handled for you. In
the editor, **Show → Walkable** draws the navmesh. This section explains how it works, for when
something does not walk the way you expect.

The game moves the player in `CPlayerController::FixedStep` through `Player_MoveOnNavMesh`
(`Nav_FindNearestPoly`, `Nav_MoveAlongSurface`, `Nav_GetPolyHeight`); zombies use the same mesh.

### The helper program

The rebuild runs [Recast](https://github.com/recastnavigation/recastnavigation) through a small
native program, `boz-navmesh`. Build it once as described in
[Installation](getting-started.md#the-navmesh-helper). Without it, saving still
works and reports that the navmesh was not rebuilt.

### How BOZ stores navmeshes

A `CIsNavMesh` resource holds the build settings and a tiled Detour v7 navmesh (see
[Asset formats](how-the-game-works.md#navigation-meshes-cisnavmesh)). The 80-byte settings block is
RecastDemo's: cell size and height, agent height, radius, climb and slope, region minimum and
merge sizes, edge length and error, vertices per polygon, detail sampling distance and error,
tile size, and the build bounds. Tiles are `tile size × cell height` wide (32 × 0.15 = 4.8 m in
Kino; the original tool multiplied by the wrong cell dimension), and positions are metres, the
game's units divided by 100.

BOZ modified Detour. A polygon is 40 bytes instead of 32: `firstLink`, six vertices, six
neighbours, **32-bit flags**, a **32-bit name hash**, the vertex count, the area and type, and two
bytes of padding. An off-mesh connection is 40 bytes instead of 36: an extra float (0.9 in every
shipped link) follows the radius. Polygon flags and name hashes carry gameplay:

| Flag | Name hash | Meaning |
| --- | --- | --- |
| `0x1` | | walkable |
| `0x2` | a door's name | floor the door blocks until it opens |
| `0x4000` | a jump area (`CPlayerJumpPoint`) | jump point |
| `0x8` | | water (Call of the Dead) |
| `0x40`, `0x80`, `0x100`, `0x200`, `0x1000`, `0x8000` | | further area types, not yet identified |

Off-mesh connections are the zombie window crossings (one per barricade, named after the
barricade's plank entity), climbs (`TheatreLeft_Climb_1`) and drops from balconies. They are
one-way.

### How the rebuild works

The shipped navmeshes were built from the level's collision (79% of their surfaces lie within one
cell height of it), with triangles wound the opposite way to Recast's convention. Collision
boxes on entities count as obstacles; doors do not, because the navmesh runs under doors and
their tags gate it.

On save, the SDK builds this input from the game's original files and from the current level;
triangles that differ mark dirty areas, and only the tiles overlapping them are rebuilt from the
game's original navmesh with the stored settings. Because the comparison is always against the
game, repeated saves give the same result. **Rebuild navmesh** in the sidebar runs it even when
nothing else changed.

- Every other tile stays byte-identical. An untouched level keeps its navmesh exactly.
- In a rebuilt tile, polygons are kept where the shipped navmesh had floor or inside the edited
  areas. The original designers also cut areas away (for example the street outside Kino) that
  nothing in the level data describes; this keeps those cuts. Other polygons get flags 0, which
  the game's query filter skips.
- Outside the edited areas the shipped floor itself is extra walkable input (inflated by the
  agent radius, which Recast erodes again). Some shipped floor has no geometry under it at all,
  such as the drop-off point on Kino's lobby balcony, so this keeps rebuilt tiles faithful and
  keeps window crossings and climbs anchored.
- New polygons take the flags and name hash of the shipped polygon under them, so door gating,
  jump areas and water carry over.
- A tile whose rebuild would drop one of its window crossings or climbs keeps its shipped data.

Rebuilding every Kino tile at once (the worst case) reproduces 94% of the shipped walkable area,
96% of the rebuilt area lies on shipped floor, and 44 of the 48 window crossings and climbs are
rebuilt (the other four tiles keep their shipped data). In normal use only the tiles around an
edit are rebuilt.

### Blocking objects: cutting instead of rebuilding

An object set to **Block the walkable area** (a wall a script opens) does not change the
level's collision: the floor under it is tagged with its name, so `NavMesh_SetTagOpen` can shut
and open it. Rebuilding its tiles with Recast would lose floor the designers made from other
input than the collision (Kino's stairs are a ramp up to 0.8 m under the steps, and a rebuilt
tile next to them lost a quarter of their floor, trapping players). So the SDK keeps those
tiles exactly as shipped and cuts the blocker's outline into their polygons (`bozkit.navcut`):

- the pieces inside the outline are tagged (flags `| 0x2`, the object's name hash);
- every new corner also goes into each polygon edge it lies on, so neighbouring polygons
  still share whole edges (Detour links polygons only through shared edges);
- polygons over six corners are halved along diagonals; new corners take their height from
  the shipped detail surface; tile-border portals keep their sides; the BV tree is rebuilt.

Floor area, connectivity and portals stay exactly the shipped ones; only tiles under a blocker
change. Real geometry changes (your own walls and floors, moved or removed entities) still
rebuild their tiles with Recast first, and blockers are cut in afterwards. Volumes (Trigger,
Hit, Use) change nothing walkable and leave the navmesh alone.

### Navmesh limits

- Tags stay where they were: moving a door does not move the floor it gates.
- New window crossings and climbs cannot be added yet.
- Windows builds of the helper are not produced yet.

## Editing shipped map files

The editor's **Shipped files** tools open the game's own map files (`.group.bin`) directly,
show everything in them (models, gameplay objects, links, collision, portals, the navmesh), and
save your changes into a mod. They never change the game's own files.

**Most of the time you want a map project instead.** A map made from the Kino der Toten, Call
of the Dead or Ascension template is the whole original map, which you change in the World tab
and play as a map of its own ([Your first map](getting-started.md#your-first-map)). The
Shipped files tools are for changing the original levels themselves, in place, and for looking
at how the game's maps are built. Format details are in [Asset formats](how-the-game-works.md#asset-formats).

### Open the tools

Open any map project in the editor (**Open in Editor** in the SDK launcher). The tools are in the
**Shipped files** tab of the 3D View sidebar; set the client folder there.

### Extract the game data

The tools read an extracted copy of the game's data. Extract the pack your client downloaded
(in its `original/obb/` folder) once:

```bash
bozkit extract path/to/boz-redux/original/obb/blackops_etc.dz ~/boz-etc --kind dz
```

The examples below use `~/boz-etc`.

### Import a level

A map is spread over many groups. Kino der Toten's `levels/kino` folder has 25: `kino_statics`
places objects whose models live in `kino_dynamics` and in the shared `ingame` group, and every
room (`theatre_shared`, `lobby_shared`, ...) has its own geometry, portals and lightmaps.

1. Start from a fresh scene and choose **Shipped files > Import level folder**.
2. Select `~/boz-etc/levels/kino`. With **Shared in-game group** enabled, the add-on also reads
   `~/boz-etc/ingame/ingame.group.bin` and the level's weapon groups
   (`ingame/weapons/*_kino.group.bin`, for the wall-buy displays) to resolve placements, but
   imports none of their own content.
3. The Outliner gets one **BOZ &lt;group&gt;** collection per group, holding **Placed Models**,
   **Markers**, **Shapes**, **Collision**, **Portals** and **Navigation**. Only the models are
   visible after import. The sidebar's **Show** switches turn each overlay on across the whole
   level: Markers, Badges, Areas, Links, Shapes, Collision, Portals and Nav. **Marker types**
   narrows markers and badges to the kinds you want (for example only perks and doors).
4. Switch the viewport to **Material Preview**.

Kino takes a few seconds and produces about 600 placed models. The importer reports anything it
could not resolve, such as placements whose model is in a group outside the folder, as warnings in
Blender's status bar instead of silently dropping them.

**Import native group** imports a single `.group.bin`. That suits self-contained groups such as
`levels/tutorial/tutorial_statics.group.bin` or one room.

### What you see

**Placed models.** Every renderable entity becomes an object at its native position, rotation and
scale. All placements of one model share one Blender mesh, so editing the geometry of one changes
them all, exactly as in the game. Entities nested inside other entities keep their parent: a
non-renderable parent becomes an empty, and children move with it.

**Shading.** The preview follows the game's GLES1 material path:

- The primary texture is multiplied by the vertex colour. Vertex colours carry the baked lighting
  of unlit models.
- Lightmapped materials add the second texture, a baked lightmap atlas, through the model's second
  UV set (`UVMap2`), combined the way the material's flags select (usually multiply, or multiply ×2).
- Alpha blending, additive and inverse blending, and the alpha-test cutout follow the material's
  blend mode.

The colours are computed in the game's display encoding and decoded once, so import switches the
scene's view transform to **Standard**. Filmic or AgX would wash the result out.

The preview does not reproduce real-time lights on dynamic objects, fog, or the rare dot3
normal-map path.

**Markers.** Every entity without a model of its own becomes a small coloured diamond in
**&lt;group&gt; Markers**, and every model with a gameplay job (perk machines, doors, the power
switch, box locations, traps, Pack-a-Punch, barricades) gets a locked diamond badge above it that
moves with the model. Names say what the thing is, using the level designer's own names where the
data has them, for example `Quick Revive perk "QuickRevive"` or `Door 750 "Lobby_To_Atrium"`; the
`boz_description` custom property explains it (`Quick Revive perk machine, 500 points, linked to
the power switch`) and `boz_components` lists everything the entity contains. Colours by job:

| Colour | Job | Colour | Job |
| --- | --- | --- | --- |
| purple | perk machine | magenta | Pack-a-Punch |
| cyan | mystery box location | orange | door or debris |
| yellow | power switch | red | trap or trap switch |
| green | wall buy | brown | barricade |
| blue | teleporter | pink | Easter egg |
| dark red | zombie or player spawn | light blue | particle effect |
| lime | interact point | teal | sound |
| white | zombie jump point | grey | locator, camera, group |

Markers move, rotate and save like objects. A perk machine's glow and particles are separate
effect markers next to it, so select them together when you move the machine. Entities attached
to a bone are placed at their parent's origin.

**Links and areas.** Entities refer to each other by name, and **Show > Links** draws those
references as lines (by default only for the selected objects):

| Colour | Link | Meaning |
| --- | --- | --- |
| yellow | power | needs the power switch (doors, perks, Pack-a-Punch, trap switches, teleporters, TVs) |
| red | traps | a trap switch fires these traps |
| orange | siblings | doors that open together |
| cyan | unlocks | the areas a door opens |
| violet | members | an area's spawn points, perk machines, teleport points, shortcuts and locators |

Areas (zones such as `lobby` or `theatre`) appear as violet diamonds at the centre of their
members when **Show > Areas** is on. Spawns in an area only activate once a door unlocks it.

The **Selected** panel under BOZ Redux describes the active object, lists its links with a button
to select each target, an **×** to remove a link and **+** to link the other selected objects
(select the targets first, the object to link from last; a single link such as power is
replaced). **Linked from** lists everything that refers to it. Only entities with a game name can
be linked to. Link edits are saved with the rest.

**Shapes.** Collision boxes, spheres and capsules on entities and each interaction point's reach
are translucent children of their entity in **&lt;group&gt; Shapes**, hidden until you turn on
**Show > Shapes**. Their colour gives the role: red for solid collision, green for ghost
(pass-through trigger) volumes, yellow discs for how close a player must be to interact. They move
with their entity in the game. Edit them to change the game's values: a box's scale is its half
size and its position its centre; a sphere's uniform scale is its radius; a capsule's X/Y scale is
its radius and Z its half height; a reach disc's scale is the interaction distance and its height
the height offset. Shapes cannot be rotated relative to their entity. The level's world collision
(orange wire) is separate from these shapes.

**Collision.** A level's world collision is one mesh, cooked from the render models: in Kino, 82%
of its triangles lie exactly on one placed model. Those triangles are imported as a hidden wire
child of that model (`<model> collision`), so moving, rotating or scaling the model carries its
collision with it. Collision that belongs to no single model (invisible walls, simplified
surfaces) stays in the level's collision object. Saving stitches everything back into the one
mesh the game loads, in the original triangle order; where a moved piece shared a vertex with a
still one, the vertex is split. In Call of the Dead and Ascension the collision object has its own
position.

**Portals** show their front and back sector names in the `boz_front_sector` and
`boz_back_sector` custom properties. **Navigation connections** (window and barricade climbs) are
two-point edges.

**Navmesh.** **Show > Navmesh** draws where players and zombies can walk: blue floor, orange
floor a door blocks until it opens, white jump areas, violet other tagged floor, and lines for
the zombie window crossings and climbs. It is display only. Saving rebuilds the tiles around
changed collision and refreshes this overlay; **Rebuild navmesh** forces it (see
[Navigation meshes](#navigation-meshes)).

### Editing a shipped level

Supported:

- **Transforms:** move, rotate and scale placed models, entity empties and collision objects.
  Rotation mode may be changed; export reads the final transform.
- **Model geometry:** vertex positions and both UV sets, with unchanged topology. Native models
  duplicate vertices at UV seams; moving one copy moves all copies of that position, and moving
  copies to different places is rejected.
- **Collision:** move pieces with their models, or edit vertex positions and per-face material
  slots of any collision object, with unchanged topology. Deleting a collision piece is rejected
  on save. Collision
  decides what bullets and other ray casts hit; export updates both copies the game loads (the
  ray-cast arrays and the Bullet physics shape). Where players and zombies can walk is the navmesh,
  which saving rebuilds around changed collision.
- **Portals:** vertices and sector names.
- **Navigation connections:** either endpoint.

**Duplicate and delete.** Select models or markers and use **Duplicate** (the copy follows the
mouse; click to place it) or **Delete** in the sidebar:

- A copy brings everything attached: child entities, its collision piece, shapes, badge and
  links. Names other entities can refer to get a free suffix (`QuickRevive` becomes
  `QuickRevive_2`); generic names shared by several entities stay. A copied spawn point, perk
  machine or teleport point joins the same areas as the original, so it works from the start.
  Copying a child entity adds another child to the same parent.
- Delete removes the entity, its children and its collision triangles, and takes it out of every
  area. It is refused while a power, trap, door-sibling or area-unlock link still points at it;
  remove those links first. The sidebar shows how many deletions wait for the next save.
- Saving creates and removes the entities, rebuilds the navmesh around them and reloads the
  level so the new entities get their final names and identities. Blender's own Shift+D copy is
  not a BOZ copy; **Validate** reports it.

Not supported yet:

- Adding or removing vertices or faces, applying modifiers, or reassigning model materials.
- Duplicating a copy before it has been saved.
- Re-parenting objects. An object must keep the parent it was imported with.
- Editing Detour navmesh polygons. Their tiles are preserved byte-for-byte.

### Save, reload and play

The sidebar's **Client** field is your BOZ Redux client folder (set it once; Blender remembers it)
and **Mod** names the mod your edits go into.

**Give your edits a mod of their own** (type a new name, for example `kino_edits`). **Mod**
starts as the Developer mod, and edits saved there change the original map for as long as the
Developer mod is on, which is easy to forget. With a mod of their own, the launcher's **Mods**
tab switches your edits on and off.

1. **Validate BOZ scene** reports non-triangle faces, empty geometry, duplicated identities,
   and changed parents.
2. **Save to mod** writes every changed group into `<client>/mods/<mod>/assets/` under its game
   file name, creating the mod if needed. Unchanged groups are not written. Saving again replaces
   the mod's earlier copies; the game's own files are never written.
3. **Import level folder** has **Include mod edits** enabled by default: groups already saved to
   your mod are loaded instead of the game's copies, exactly as the client does. Continue editing
   and save again.
4. Start the game. New mods are enabled automatically (the launcher's Mods tab can disable it),
   so the edits appear the next time the level loads.

Every unknown section and unsupported resource body stays byte-identical. Editing the geometry of
a model that lives in the shared `ingame` group saves a new `ingame.group.bin` in the mod; moving
it changes only the group that places it.

**Build & Run** saves to your mod and starts the game straight into the level. The sidebar's
**Test with** mod (the Developer mod by default) does the starting: Build & Run stores the level
in that mod's settings, and the mod's `boz.levels.autostart_from_settings()` runs the front end's `StartLevel`
console command once the menu is up, then clears the request, so a normal launch still shows the
menu. Any mod can be the test mod if it calls `levels.autostart_from_settings()` (see the
[standard library](standard-library.md)). The game's output goes to `boz-log.txt` in the client
folder. Build & Run refuses to start while the game is already running, or when the test mod is
missing or switched off. When two enabled mods replace the same file, the one loaded later wins;
if another mod would hide your edits, Build & Run moves your mod to the end of `client.ini`'s
`[mods] order` (the launcher's Mods tab shows the same list) and says so.

The arrow buttons next to **Mod** and **Test with** list the mods already in the client; editing
an existing mod is just choosing it there.

Under **Files**, **Import native group** opens a single `.group.bin`, **Export edited level** writes
changed groups into any folder (for example an SDK project's `assets/`), and **Export edited
group** writes one group to a new file (`<name>-edited.group.bin`, byte-identical without edits).

### Try the shipped-file tools

A short round trip, all in the editor's sidebar and the game:

1. Set **Client** to your `boz-redux` folder. **Import level folder** on `levels/kino`.
2. Move two objects, rotate one, scale one, and raise a small wall of floor collision in
   kino_statics by about a player's height. **Validate**, then **Save to mod**; the status line
   names the groups it saved.
3. **File > New**, then **Import level folder** on `levels/kino` again: every edit is still there.
4. Play Kino with the mod: the objects sit where you put them, shots stop on the raised
   collision, and you can no longer walk through it: saving rebuilt the navmesh around it.
5. Disable the mod in the launcher and play again: everything is back to normal.
