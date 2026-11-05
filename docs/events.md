# Events

Everything your scripts can react to, on one page.

## How to catch one

There are three ways, depending on where your code lives.

**On the object itself:** write a hook in its script. This is the only way that can change what
the object does.

```lua
local Vault = boz.Door:extend("Vault")

function Vault:on_opened(player)
    player:give_points(500)
end

return Vault
```

**On an object, from outside:** use `:on()` from a map script. Your function gets the object
first, then the same arguments.

```lua
local boz = require("boz")

boz.get("Vault"):on("opened", function(vault, player)
    player:give_points(500)
end)
```

**For the whole match:** use `boz.on` with a game event. Your function gets a `data` table.

```lua
local boz = require("boz")

boz.on("zombie_killed", function(data)
    if data.headshot then
        boz.player():give_points(10)
    end
end)
```

Inside an object script, `on_event(name, data)` gets every game event too:

```lua
function Vault:on_event(name, data)
    if name == "round_started" then
        log("round " .. data.round)
    end
end
```

The map's **Game** tab has one more way in: **Hook scripts**. **Create** next to an event makes
`scripts/hooks/<event>.lua`, which returns a function:

```lua
-- scripts/hooks/round_started.lua
return function(data)
    log("round " .. data.round)
end
```

## Object events

Hook is the name in a script. Event is the name for `:on()`.

| Hook | Event | On | Arguments | What it means | Can it stop it? |
| --- | --- | --- | --- | --- | --- |
| `start` | | Every scripted object | | The level started, or a save continued | |
| `on_use` | `use` | Prefabs with a **Use** volume | `player, volume` | A player pressed use | |
| `on_use` | `use` | Door, Perk, MysteryBox, PackAPunch, PowerSwitch, TrapSwitch, WallBuy, Barricade | `player` | A player used it | **Yes**: don't [hand it back](game-prefabs.md#handing-it-back-to-the-game) |
| `on_hit` | `hit` | Prefabs with a **Hit** volume | `player, volume` | It was shot | |
| `on_enter` | `enter` | Prefabs with a **Trigger** volume | `who, volume` | Someone walked in | |
| `on_exit` | `exit` | Prefabs with a **Trigger** volume | `who, volume` | Someone walked out, or a zombie died inside | |
| `on_event` | | Every scripted object | `name, data` | A game event or a `boz.send` | |
| `on_opened` | `opened` | Door, Debris | `player` | It opened | |
| `on_bought` | `bought` | Perk | `player, perk` | A player bought this perk | |
| `on_bought` | `bought` | WallBuy | `player, weapon` | A player paid for the weapon or its ammo | |
| `on_spun` | `spun` | MysteryBox | `player` | A player spun this box | |
| `on_weapon` | `weapon` | MysteryBox | `player, weapon` | This box picked a weapon | |
| `on_upgraded` | `upgraded` | PackAPunch | `player, weapon` | A weapon went into this machine | |
| `on_on` | `on` | PowerSwitch | `player` | The power came on | |
| `on_activated` | `activated` | TrapSwitch | `player` | A player ran this switch | |
| `on_cooled` | `cooled` | Trap, TrapSwitch | | The trap is ready again | |
| `on_repaired` | `repaired` | Barricade | `player` | A player put a board back | |

A script on a volume outside any prefab gets the same hooks, without `volume`.

`bought`, `spun`, `weapon`, `upgraded`, `activated` and `repaired` reach the machine the player just
used. If
something happens with no machine (a script gives a perk), only the game event fires.

**Not yet:** a zombie tearing a board off has no event.

## Game events

Catch these with `boz.on(name, function(data) ... end)`, or in `on_event`.

### Rounds and the power

| Event | Data | When |
| --- | --- | --- |
| `round_started` | `round` | A round started |
| `round_ended` | `round` | A round ended: its last zombie died |
| `power_on` | | The power came on |

### Zombies

| Event | Data | When |
| --- | --- | --- |
| `zombie_killed` | `position`, `entity`, `by_player`, `headshot` | A zombie died |
| `nuke` | | A Nuke went off |

### Players

| Event | Data | When |
| --- | --- | --- |
| `player_hit` | `damage` | A zombie hit the player |
| `player_downed` | | The player went down |
| `player_revived` | | The player was revived |
| `points_earned` | `points`, `player` | Points were earned |
| `points_spent` | `points`, `player` | Points were spent |

`player` in these tables is `true` when it was you, the local player.

### Weapons

| Event | Data | When |
| --- | --- | --- |
| `weapon_given` | `weapon` | The player got a weapon |
| `weapon_equipped` | `weapon` | The player switched weapons |
| `weapon_fired` | `weapon`, `clip` | Every shot |
| `weapon_reloaded` | `weapon` | A reload started |

### Machines and the map

| Event | Data | When |
| --- | --- | --- |
| `perk_bought` | `perk`, `player` | A player got a perk, bought or given |
| `door_opened` | `door`, `hash` | A door opened. `door` is its name. |
| `box_weapon` | `weapon` | The mystery box picked a weapon |
| `pack_a_punch` | `weapon` | A weapon went into Pack-a-Punch |
| `powerup_grabbed` | `powerup`, `player` | A power-up was picked up |
| `carpenter` | | A Carpenter rebuilt the barricades |
| `trap_activated` | | A trap was switched on |
| `trap_cooled` | `trap` | A trap is ready again. `trap` is its name. |
| `barricade_repaired` | | A board went back on a barricade |
| `teleporter_activated` | | A teleporter was used |

Power-up names: `double_points`, `insta_kill`, `max_ammo`, `nuke`, `carpenter`, `firesale`,
`deathmachine`, `perkbottle`, `lightningbolt`.

## Your own events

`boz.send` sends any name you like, to every `boz.on` listener and every object's `on_event`:

```lua
local boz = require("boz")

boz.send("generator_fixed", {room = "Lab"})

boz.on("generator_fixed", function(data)
    log(data.room .. " has power")
end)
```

## Going deeper

The game itself sends 372 low-level `SUBJECT_*` events. Most mods never need them, but they're
listed in [Low-level events](game-events.md).
