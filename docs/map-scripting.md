# Map scripting: prefabs, volumes and Lua

A map is made of three kinds of object, and scripts tie them together:

| Kind | What it is | In the editor |
| --- | --- | --- |
| **Model** | A mesh you see and bump into: a game model, or your own | Palette Models, Add → Game shapes, Project → Import model |
| **Volume** | An invisible box that sends events: **Trigger** (walked into), **Hit** (shot), **Use** (player presses use) | Palette Volumes |
| **Prefab** | One object made of parts (models, volumes, prefabs), with an optional script. **Game prefabs** are the game's own: perk machines, wall buys, doors, spawns, ... | Select objects, **Make prefab** (Ctrl+G); palette Game prefabs and Level markers |

Every object's **name** is how scripts find it. Inside a prefab, a part keeps its **part name**
(Door, Skull, ...), and scripts reach it with `self:part("Door")`.

## 1. Build it in the editor

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

## 2. Write the script

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

## 3. Reuse it

**Save as new prefab** puts `Vault` in the project's prefab library: it shows in the asset
browser on the left under **My prefabs**, and you drag copies into the map like any other asset
(Project → Prefab library deletes them). Each copy is independent: change its properties or
its parts without touching the others. To make a new base, edit a copy and Save as new prefab
again under another name.

## What scripts get

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

### Game events

| Event | `data` |
| --- | --- |
| `round_started` | `round`: the round number |
| `power_on` | |
| `perk_bought` | `perk` ("Juggernog", "Quick Revive", ...), `player` (true for the local player) |
| `door_opened` | `door`: the door's name (`0x...` for a door the map does not name), `hash` |
| `zombie_killed` | `position` ({x, y, z}), `entity` (the zombie, the same as `who.entity` in `on_enter`), `by_player`, `headshot` |
| `player_downed`, `player_revived` | |
| `weapon_given`, `weapon_equipped`, `weapon_reloaded` | `weapon` (its name); `weapon_fired` reaches `boz.on` only. Weapon scripts: [weapons.md](weapons.md) |

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
chain. See [standard-library.md](standard-library.md) for `boz.objects` and `boz.prefabs`.

## Saved with the game

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

## How it works

The build lists every scripted object and every volume in `scripts/boz/world_data.lua`, with
property values and parts. `boz.world` starts `boz.prefabs` when each level starts. Objects are
found by their `CIsNamed` name, and the events are hooks on the game's own functions:

- collision enter and exit for Trigger volumes;
- the easter egg skull's weapon hit for Hit volumes;
- `Poi_SendUse` for Use volumes;
- `CWaveManager::StartWave` for `round_started`;
- the power switch's flag for `power_on`;
- `CPerkManager::GainPerk` for `perk_bought`, `CDoor::OnEvent` for `door_opened`, the zombie's
  dead state for `zombie_killed`, the player's stance for `player_downed` / `player_revived`;
- `CSaveManager::SaveGame` and `CSaveManager::NotifyLoad` for saved globals, kept in the map
  mod's settings (`saves/mods/<map>.cfg`), next to the game's own save, which is never changed.

[toolkit-fields.md](toolkit-fields.md) lists what each game prefab and volume is made of.
