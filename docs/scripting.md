# Scripting reference

The functions you will use most, by topic. [Prefabs](prefabs.md) shows how they fit together.
This page is the lookup.

In an object script `boz` is already there. In `main.lua` and other files, start with:

```lua
local boz = require("boz")
```

## The basics

| Call | What it does |
| --- | --- |
| `log(...)` | Writes to `boz-log.txt` and the editor's Log area |
| `boz.get(name)` | The object with that name, as its class. A part is `"Prefab.Part"`. |
| `boz.all(class)` | Every object of a class: `boz.all(boz.Perk)` |
| `boz.player()` | You |
| `boz.players()` | Every player in the match |
| `boz.on(name, fn)` | Calls `fn(data, name)` on a game event or a `boz.send` |
| `boz.send(name, data)` | Sends an event to every `boz.on` and every `on_event` |
| `boz.after(seconds, fn)` | Runs `fn` once, later |
| `boz.every(seconds, fn)` | Runs `fn` again and again; `:cancel()` stops it |
| `boz.saved` | A table all scripts share, kept in saved games |

```lua
for _, perk in ipairs(boz.all(boz.Perk)) do
    perk.settings.cost = 500
end
```

Positions are tables `{x = 0, y = 100, z = 0}` in centimetres, with y up.

## Objects

Anything from `boz.get`, and `self` in a script. The full list, with examples, is
[What every object has](prefabs.md#what-every-object-has).

| Call | What it does |
| --- | --- |
| `.name`, `.kind`, `.settings` | Its name, `"model"`/`"volume"`/`"prefab"`, and its settings |
| `class_name()`, `is_a(class)` | Its class |
| `part_name()`, `parent()`, `part(name)`, `parts()` | Prefabs and their parts |
| `position()`, `rotation()`, `near(target, cm)`, `exists()` | Where it is |
| `visible()`, `show()`, `hide()`, `set_visible(on)` | Visible |
| `blocks_walking()`, `set_blocks_walking(on)` | Walking |
| `stops_bullets()`, `set_stops_bullets(on)` | Stops bullets |
| `links(name)`, `linked_from(name)` | Links |
| `on(event, fn)`, `send(name, data)` | Events |

Volumes add `type()`, `set_off_by()`, `once()`, `used()`, `prompt()`, `set_prompt(text)`, `cost()` and
`set_cost(points)`. Each game prefab's own methods are on [Game prefabs](game-prefabs.md).

## Players

Get one with `boz.player()`, or from a hook's `player` argument.

| Call | What it does |
| --- | --- |
| `points()` | Points the player has |
| `give_points(n)` | Gives points; a negative number takes them |
| `spend(n)` | Takes points if the player has enough; returns true when paid |
| `health()`, `set_health(n)` | Health |
| `set_god(on)`, `god()` | No damage |
| `give_perk(name)`, `take_perk(name)`, `has_perk(name)`, `perks()` | Perks |
| `give_weapon(name)`, `take_weapon(name)`, `weapon()` | Weapons. The new weapon goes in hand. |
| `position()`, `teleport(place)` | Where the player is. `place` is a position or an object. |
| `downed()`, `kill()` | Down in last stand, or killed |
| `stance()`, `set_stance(name)` | `"standing"`, `"crouching"`, `"prone"`, `"downed"` |
| `speed(name)`, `set_speed(name, value)` | A movement speed, like `"SprintSpeed"` |
| `stat(name)`, `add_stat(name, n)` | A stat, like `"STAT_ZOMBIESKILLED"` |
| `message(text, seconds)` | A line of text on the screen |

```lua
local player = boz.player()
if player:spend(1000) then
    player:give_perk("Juggernog")
    player:set_speed("SprintSpeed", 1.5)
end
```

## Zombies

| Call | What it does |
| --- | --- |
| `boz.zombies(kind)` | The zombies alive. `kind` is `"zombie"`, `"dog"`, `"monkey"` or `"all"`. |
| `boz.spawn_zombie(spec, position, options)` | Spawns one. `spec` is `"zombie"`, `"zombie_dog"`, ... Options: `health`, `speed`. |

A zombie that just died stays in the list for a moment, with 0 health.

Each zombie has `.zombie` (always true, to tell it from a player in a volume's hooks), and:

| Call | What it does |
| --- | --- |
| `kind()`, `alive()` | What it is, and whether it is still in the match |
| `position()`, `teleport(position)` | Where it is |
| `health()`, `max_health()`, `set_health(n)` | Health |
| `damage(n)`, `kill()` | Hurts or kills it. The kill counts for the player. |
| `set_speed(tier)` | `"walk"`, `"walk_fast"`, `"run"` or `"sprint"` |
| `freeze()`, `burn()`, `explode()`, `lightning()`, `gersch()`, `shockwave()` | The game's weapon effects |

```lua
boz.on("round_started", function(data)
    if data.round == 5 then
        boz.spawn_zombie("zombie", boz.get("Boss_Spot"):position(), {health = 5000, speed = "sprint"})
    end
end)

for _, zombie in ipairs(boz.zombies("dog")) do
    zombie:freeze()
end
```

## Rounds

| Call | What it does |
| --- | --- |
| `boz.round()` | The round number |
| `boz.start_round(n)` | Goes to a round |
| `boz.rounds.zombies_left()` | Zombies still to kill this round |
| `boz.rounds.alive()` | Zombies alive now |
| `boz.rounds.powered()` | True once the power is on |
| `boz.rounds.special()` | True during a dog or monkey round |
| `boz.rounds.set_spawning(on)` | Stops or starts spawning |
| `boz.rounds.start_next()` | Starts the next round |
| `boz.rounds.set_wave(field, value)` | Changes the running round, such as `"m_ZombieHealth"` |

To shape a map's rounds as a whole, use the [Game tab](editor.md#game-rules).

## Systems

Each one is ready as `boz.<name>`.

### boz.hud

```lua
boz.hud.message("The power is on", 3)
boz.hud.hide("Clip_Label")
boz.hud.show("Clip_Label")
```

`boz.hud.ELEMENTS` lists the names.

### boz.audio

```lua
boz.audio.play("my_sound")                        -- everywhere
boz.audio.play("gersch_opens", self:position())   -- at a place
boz.audio.sequence("dog_wave_start")              -- a voice line or sting
boz.audio.music("115.mp3", {loop = true})
boz.audio.music_volume(0.5)
```

See [Sounds](weapons-and-assets.md#sounds) for finding names and adding your own.

### boz.effects

```lua
boz.effects.spawn("impactRayGun", self:position(), {lifetime = 3})
boz.effects.explode(self:position())
boz.effects.projectile("gersch", self:position(), {trigger = "open", lifetime = 6})
```

See [Effects and projectiles](weapons-and-assets.md#effects-and-projectiles).

### boz.pickups

```lua
boz.pickups.spawn("max_ammo", self:position())    -- drops one
boz.pickups.give("insta_kill")                    -- as if collected
```

Names are in [Events](events.md#machines-and-the-map).

### boz.camera and boz.screen

```lua
boz.camera.set_fov(90)
boz.camera.shake("romero-transform-shake")
boz.screen.effect("nuke")              -- a full-screen flash
boz.screen.fog("Monkeys")              -- a fog setting
```

### boz.input

Works with the game's actions, whatever keys the player bound: `shoot`, `aim`, `reload`, `use`,
`melee`, `grenade`, `tactical`, `crouch`, `fire_mode`, `switch_weapon`.

```lua
boz.input.on_action("melee", function(down)
    if down then log("knife") end
end)
boz.input.send("reload")
```

For keys, use the client's `input.bind("F5", fn)` ([Script mods](script-mods.md#input-module)).

### boz.console and boz.cvars

The game's own settings and cheats ([Console reference](console-reference.md)):

```lua
boz.console.set("WeaponsUnlimitedAmmo", true)
log(boz.console.get("WalkSpeed"))
boz.console.exec("SwitchPowerOn")
```

### boz.menu

Rows in the pause menu's Settings page ([example](script-mods.md#add-a-setting-to-the-pause-menu)):

```lua
boz.menu.add_checkbox{
    id = "hard_mode",
    label = "Hard mode",
    get = function() return settings.get("hard_mode", false) end,
    set = function(on) settings.set("hard_mode", on) end,
}
```

### boz.text

Your own text for the game's menus and prompts: `boz.text.add(id, value)`.

### boz.stats

```lua
log(boz.stats.get("STAT_ZOMBIESKILLED"))
boz.stats.add("STAT_HEADSHOTS", 1)
boz.stats.unlock("BOGravity")
```

### boz.weapons

The player's weapons by name: `give`, `take`, `upgrade`, `refill`, `owned`, `current`.

```lua
boz.weapons.give("mp40")
boz.weapons.upgrade("mp40")
boz.weapons.refill("mp40")
```

### boz.map

The level: `boz.map.set_time_scale(0.5)`, `boz.map.toggle_pause()`, `boz.map.playing()`.

### boz.fly and boz.deadops

`boz.fly.set(true)` turns noclip on. `boz.deadops` is for the Dead Ops mini-game.

## Classes of your own

`boz.class` is what every class here is built on. You can use it for your own helpers:

```lua
local Counter = boz.class:extend("Counter")

function Counter:init(limit)
    self.count, self.limit = 0, limit
end

function Counter:add()
    self.count = self.count + 1
    return self.count >= self.limit
end

local kills = Counter:new(10)
```

## Advanced

Below all this is `boz.engine.*`: `require("boz.engine.reflect")` reaches every field of the
game's data, `require("boz.engine.entities")` every entity, and
`require("boz.engine.game_events")` the [low-level events](game-events.md). Each file in the SDK's
`lib/boz/engine` starts with a short description. Most mods never need them.
