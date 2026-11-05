# Prefabs

A prefab is the thing you will make most: a few parts that act as one object, with a script that
says what it does. This page goes from nothing to complete working objects.

The game's own objects are prefabs too. They have their own page,
[Game prefabs](game-prefabs.md), but everything here works on them as well.

## What a prefab is

A prefab is **parts plus an optional script**:

- **Parts** are models, volumes and other prefabs, grouped under one object.
- **The script** is a class. It says what the object does when things happen to it.

You make a prefab when you want:

- something that does a job (a button, a pad, a secret);
- more than one of the same thing (ten skulls that all behave alike);
- a piece you can reuse in other maps.

## Make one in the editor

We will make a skull you can shoot for points.

1. In the **World** tab, drag a model into the map from the asset browser's **Models**. Pick any
   small one.
2. From **Volumes**, drag a **Hit** volume over it. Scale it so it covers the model. It is a
   see-through red box; size is its scale (100 cm at scale 1).
3. Select both and press **Ctrl+G** (**Make prefab**). They are now one object, grouped under an
   Empty. Name it `Skull`.
4. Each part keeps a **part name** inside the prefab. In the outliner they show as
   `Skull › Model` and `Skull › Hit`. Rename them if you like; scripts use these names.

**Ctrl+Alt+G** (**Ungroup**) takes a prefab apart again.

### Save it to the library

With the prefab selected, click **Save as new prefab**. It now shows in the asset browser under
**My prefabs**, and dropping it places an independent copy. **Project → Prefab library** deletes
prefabs from the library.

## Your first script

Select the prefab. In the **Script** box of the **Game** panel, click **New**. Keep the name `Skull`,
choose **Basic prefab**, and click OK. The editor makes `scripts/prefabs/Skull.lua` and opens it in the
**Scripts** tab. Replace what is there with:

```lua
local Skull = boz.Prefab:extend("Skull")

---@setting points int 100 "Points for shooting it"

function Skull:on_hit(player)
    self:hide()
    player:give_points(self.settings.points)
    player:message("Skull found")
end

return Skull
```

Press **Build & Run**, shoot the skull, and it vanishes and pays you. Line by line:

```lua
local Skull = boz.Prefab:extend("Skull")
```

Makes a new class called `Skull`, based on `boz.Prefab`. Your class gets everything a prefab can
do, and adds to it.

```lua
---@setting points int 100 "Points for shooting it"
```

A setting. It shows in the editor's **Settings** box with the label *Points for shooting it*, as
a whole number that starts at 100. Each skull you place can have its own value. Press **Reload**
in the Script box after adding one.

```lua
function Skull:on_hit(player)
```

A **hook**: a function with a special name that runs when something happens. `on_hit` runs when
a **Hit** volume in this prefab is shot. `player` is who shot it.

```lua
    self:hide()
```

`self` is this skull, the one that was shot. Hiding it makes it vanish, and its Hit volume stops
working too.

```lua
    player:give_points(self.settings.points)
    player:message("Skull found")
```

Pays the player the value from the editor, and shows a line of text on the screen.

```lua
return Skull
```

Hands your class to the game. **Every object script must end with this.** Without it the script
does nothing and the log shows an error.

## Choosing a template

**New** asks for a name and a template:

| Template | What you get |
| --- | --- |
| **Empty** | Just the class and `return`, for you to fill in |
| **Basic prefab** | A prefab with `start`, `on_use` and `on_event`, and a setting to show how it's done |
| **Object** | Extends one of the game's objects, which you pick from the **Extends** list, with that object's hooks ready |

The popup starts on what fits the selected object: **Object** with the right class for a door or a
perk machine, and **Basic prefab** for your own prefabs. **Empty** extends the object's own class too,
so a door stays a door. If a script with that name exists, the popup says so, and **New** attaches
that script as it is.

## The shape of a script

Every object script looks the same:

```lua
local Name = boz.Prefab:extend("Name")    -- 1. make the class

---@setting ...                           -- 2. settings and links, if you want them
---@link ...

function Name:start()                     -- 3. hooks and your own functions
end

return Name                               -- 4. hand it back
```

`boz` is ready to use in object scripts. You don't need to `require` it.

Two things trip people up if Lua is new to them:

- Use a **colon** for methods: `function Skull:on_hit(player)` and `self:hide()`. The colon is
  what passes `self`.
- `self` is one object. If you place ten skulls, there are ten `self`s, and each one has its own
  fields and settings.

A script's class *extends* another: it gets everything that class has, and any function you write
with the same name replaces the original. Your own prefabs have nothing to lose, but a game prefab
does, so there you hand the use back to the game. See
[Handing it back to the game](game-prefabs.md#handing-it-back-to-the-game).

You can add your own functions and call them from hooks:

```lua
local Skull = boz.Prefab:extend("Skull")

function Skull:collect(player)
    self:hide()
    player:give_points(100)
end

function Skull:on_hit(player)
    self:collect(player)
end

return Skull
```

## What every object has

Your class starts with all of this, before you write a line. `self` in a script, or anything from
`boz.get`, has the same things.

```lua
local Vault = boz.Prefab:extend("Vault")

function Vault:start()
    log(self.name)                     -- "Vault_2": its name in the editor
    log(self.kind)                     -- "prefab"
    log(self:class_name())             -- "Vault"
    log(self.settings.bonus)           -- a value from the Settings box
    log(self:position().x)             -- where it is
    local keypad = self:part("Keypad") -- one of its parts
    log(keypad:part_name())            -- "Keypad"
    log(keypad:parent().name)          -- "Vault_2"
end

return Vault
```

### Who it is

| You write | What you get |
| --- | --- |
| `self.name` | Its name in the editor. A part is `"Prefab.Part"`. Copies each have their own. |
| `self.kind` | `"model"`, `"volume"` or `"prefab"` |
| `self:class_name()` | The name of its class, like `"Skull"` or `"Perk"` |
| `self:is_a(boz.Door)` | True when it is that class, or extends it |
| `self:part_name()` | Its name inside its prefab, like `"Door"`, or nil |
| `self:parent()` | The prefab it is part of, or nil |

### Where it is

| You write | What you get |
| --- | --- |
| `self:position()` | `{x, y, z}` in centimetres, y up. For a prefab, the middle of its parts. |
| `self:rotation()` | `{x, y, z, w}`, a quaternion |
| `self:near(target, distance)` | True when within `distance` cm of a position or object |
| `self:exists()` | True while it is in the running level |

### Its In the game box

Each switch in the editor can be read and changed.

| Switch | Read it | Change it |
| --- | --- | --- |
| **Visible** | `self:visible()` | `self:show()`, `self:hide()`, `self:set_visible(on)` |
| **Walking** | `self:blocks_walking()` | `self:set_blocks_walking(on)` |
| **Stops bullets** | `self:stops_bullets()` | `self:set_stops_bullets(on)` |

A hidden object reads false for the last two, because it stops nothing. A prefab reads true if any
of its parts does. These two are only reliable on objects a script can reach: ones with a script,
or with **Scripts can switch it** on.

### Its settings and links

| You write | What you get |
| --- | --- |
| `self.settings.name` | A value from the **Settings** box. Writing it changes it. |
| `pairs(self.settings)` | Every setting, to loop over |
| `self:links("name")` | The objects it links to, as a list |
| `self:linked_from("name")` | The objects that link to it, as a list |

`"name"` is your own `---@link`, or one of the game's:

| Link | In the editor | On |
| --- | --- | --- |
| `"power"` | **Power switch** | Anything that needs power |
| `"traps"` | **Traps** | Trap switches |
| `"siblings"` | **Opens with** | Doors and debris |
| `"spawns"` | **Window spawns** | Barricades |

```lua
local trap = boz.get("Lobby_Trap")
for _, switch in ipairs(trap:linked_from("traps")) do
    log(switch.name .. " runs this trap")
end
```

### Its parts

| You write | What you get |
| --- | --- |
| `self:part("Door")` | One part, as its class |
| `self:parts()` | A list of `{name =, object =}` |

### Listening and sending

| You write | What it does |
| --- | --- |
| `self:on("hit", fn)` | Calls `fn(object, ...)` when the event happens to it |
| `self:send("name", data)` | The same as `boz.send` |

Volumes have [their own values](#reading-and-changing-a-volume), and each game prefab adds its
methods on [Game prefabs](game-prefabs.md). There's no way to move or turn an object from a script
yet.

## Hooks

These are the hooks a prefab has. You only write the ones you need.

| Hook | When it runs | Needs |
| --- | --- | --- |
| `start()` | The level starts | Nothing |
| `on_use(player, volume)` | A player presses use | A **Use** volume |
| `on_hit(player, volume)` | Something is shot | A **Hit** volume |
| `on_enter(who, volume)` | Someone walks in | A **Trigger** volume |
| `on_exit(who, volume)` | Someone walks out | A **Trigger** volume |
| `on_event(name, data)` | A game event, or a `boz.send` | Nothing |

`volume` is the part name of the volume, so one prefab can tell its volumes apart. A script
attached to a single volume, outside any prefab, gets no `volume` argument.

### start

Runs when the level starts, once for each object. Use it to set the object up.

```lua
local Crate = boz.Prefab:extend("Crate")

function Crate:start()
    self:hide()              -- starts hidden, something shows it later
end

return Crate
```

`start` also runs when a saved game continues, after the object's saved fields are back. So a
good `start` looks at what is saved:

```lua
function Crate:start()
    if self.collected then
        self:hide()
    end
end
```

### on_use

Runs when a player stands at a **Use** volume and presses use. The volume's **Prompt** is the text
they see, and its **Cost** is taken *before* the hook runs. If they can't pay, the hook doesn't
run.

```lua
local Button = boz.Prefab:extend("Button")

function Button:on_use(player, volume)
    player:message("Click")
    boz.get("Front_Door"):open()
end

return Button
```

### on_hit

Runs when a **Hit** volume is shot.

```lua
local Target = boz.Prefab:extend("Target")

function Target:on_hit(player, volume)
    if volume == "Bullseye" then
        player:give_points(500)
    else
        player:give_points(50)
    end
end

return Target
```

### on_enter and on_exit

Run when someone walks into or out of a **Trigger** volume. `who` depends on the volume's **Set
off by**:

- **Players** (the default): `who` is the player.
- **Zombies**: `who` is a [zombie](scripting.md#zombies), dogs and monkeys included.
- **Anyone**: `who` is either. Check `who.zombie` before you call player methods on it.

```lua
local Fence = boz.Prefab:extend("Fence")

function Fence:on_enter(who, volume)
    if who.zombie then
        who:kill()
        return
    end
    who:message("Mind the fence")
end

function Fence:on_exit(who, volume)
    log("someone left")
end

return Fence
```

A zombie that dies inside the volume counts as leaving, so `on_exit` runs for it too.

### on_event

Runs for every game event (`round_started`, `power_on`, ...) and for every `boz.send` from your
own scripts. `name` says which it was. The full list is on the [Events](events.md) page.

```lua
local Lamp = boz.Prefab:extend("Lamp")

function Lamp:start()
    self:hide()
end

function Lamp:on_event(name, data)
    if name == "power_on" then
        self:show()
    end
end

return Lamp
```

## Volumes

Volumes are how a prefab notices the world. They are invisible in the game. Drag one from
**Volumes** in the asset browser, scale it, and make it a part of your prefab.

| Volume | Colour in the editor | Its event |
| --- | --- | --- |
| **Trigger** | Teal | `on_enter`, `on_exit` |
| **Hit** | Red | `on_hit` |
| **Use** | Green | `on_use` |

Volume settings:

| Setting | What it does |
| --- | --- |
| **Set off by** | Triggers: **Players**, **Zombies** or **Anyone** |
| **Only once** | It works one time, then never again |
| **Prompt** | Use volumes: the text the player sees |
| **Cost** | Use volumes: the points it takes. No points, no hook. |

A hidden volume does nothing. So `self:hide()` on a prefab also switches off its volumes, and
`self:part("Keypad"):hide()` switches off just one.

### Reading and changing a volume

A volume is a `boz.Volume`. It has everything in [What every object has](#what-every-object-has),
and every setting from the editor:

| You write | What you get |
| --- | --- |
| `volume:type()` | `"trigger"`, `"hit"` or `"use"` |
| `volume:set_off_by()` | `"players"`, `"zombies"` or `"anyone"` |
| `volume:once()` | True when **Only once** is on |
| `volume:used()` | True once it has fired |
| `volume:prompt()`, `volume:set_prompt(text)` | The **Prompt** |
| `volume:cost()`, `volume:set_cost(points)` | The **Cost** |

A new prompt shows the next time a player reaches the volume.

```lua
local Shrine = boz.Prefab:extend("Shrine")

function Shrine:on_use(player, volume)
    local keypad = self:part(volume)
    keypad:set_cost(keypad:cost() * 2)      -- dearer each time
    keypad:set_prompt("Pray again")
end

return Shrine
```

To put a script on a single volume outside any prefab, click **New** with the volume selected: it
extends `boz.Volume`, and `self` has these too.

## Parts

A script can reach each part by its part name:

```lua
local Vault = boz.Prefab:extend("Vault")

function Vault:on_use(player)
    self:part("Door"):hide()                       -- just the door
    self:part("Frame"):set_stops_bullets(false)
end

return Vault
```

`self:parts()` lists them, each with its `name` and `object`:

```lua
function Vault:start()
    for _, part in ipairs(self:parts()) do
        log(part.name)
    end
end
```

Prefabs can have prefabs inside them, and game prefabs can be parts too. `self:part("Machine")`
on a perk machine part gives you a real `boz.Perk`, with all its methods. From outside the prefab,
the same part is `boz.get("Vault.Door")`.

What you do to the prefab itself goes to all of its parts: `self:hide()` hides all of them.

## Settings

Settings let you change a value in the editor without touching the script, and give each placed
copy its own value.

```lua
local Pad = boz.Prefab:extend("Pad")

---@setting bonus int 500 "Bonus points"
---@setting delay seconds 2 "Wait before paying"
---@setting once bool true "Pay only once"
---@setting greeting text "Welcome" "Message"

function Pad:on_use(player)
    boz.after(self.settings.delay, function()
        player:give_points(self.settings.bonus)
        player:message(self.settings.greeting)
    end)
end

return Pad
```

The shape is `---@setting name kind default "Label"`. After adding one, press **Reload** in the
Script box and it appears in the **Settings** box.

| Kind | In the editor | In the script |
| --- | --- | --- |
| `int` | Whole number | Number |
| `float` | Number | Number |
| `bool` | Tick box | `true` or `false` |
| `seconds` | Seconds | Number of seconds |
| `text` | Text | String |
| `weapon` | A weapon of the map | Weapon name |
| `sound` | A sound | Sound name |
| `object` | An object of the map | Object name, for `boz.get` |
| `event` | An event name | String, for `boz.send` |

Read and change them through `self.settings`:

```lua
local value = self.settings.bonus
self.settings.bonus = value * 2
```

On a [game prefab](game-prefabs.md), the Settings box has the machine's own settings as well as
yours, and `self.settings` reaches both. `self.settings.cost` on a perk machine is its real cost.

## Links

A setting holds a value. A link holds **other objects**, chosen in the editor with search and
lines drawn in the viewport. Use a link when your script acts on something else in the map.

```lua
local Lever = boz.Prefab:extend("Lever")

---@link doors door many "Doors it opens"

function Lever:on_use(player)
    for _, door in ipairs(self:links("doors")) do
        door:open()
    end
end

return Lever
```

The shape is `---@link name kind one|many "Label"`. Press **Reload**, and the **Links** box shows
your link. Click **+** to search, or select objects and use **Link selected**. **×** removes one.

`self:links("name")` always gives a list, even for `one`:

```lua
local target = self:links("target")[1]
```

The kind limits what can be linked:

| Kind | Links to |
| --- | --- |
| `perk` | Perk machines |
| `door` | Doors and debris |
| `barricade` | Window barricades |
| `trap` | Traps |
| `trap_switch` | Trap switches |
| `power_switch` | Power switches |
| `mystery_box` | Mystery boxes |
| `pack_a_punch` | Pack-a-Punch machines |
| `wall_buy` | Wall buys |
| `zombie_spawn` | Zombie spawns |
| `player_spawn` | Player spawns |
| `volume` | Volumes |
| `model` | Models |
| `prefab` | Your prefabs |
| `any` | Anything |

**Links or a name?** `boz.get("Front_Door")` is fine for one object in one map. A link is better
for a prefab you will reuse: each copy can point at something different, and renaming an object
doesn't break it.

## Doing things

[What every object has](#what-every-object-has) lists the calls. A few things to know:

An object only changes during play if a script can reach it. Objects with a script always can. For
others, turn on **Scripts can switch it** in the **In the game** box. Without it the build bakes
the object into the level, and `hide()` does nothing.

`set_blocks_walking` needs **Walking: Blocks** in the editor, because that is what reserves the
gap in the walkable area.

### Timers

```lua
boz.after(5, function()
    log("five seconds later")
end)

local beat = boz.every(1, function()
    log("every second")
end)

beat:cancel()      -- stops it
```

Times are in seconds of game time, so they stop while the game is paused.

### Players

`player` in a hook is a [boz.Player](scripting.md#players). Anywhere else, use `boz.player()`:

```lua
local player = boz.player()
player:give_points(500)
player:give_perk("Juggernog")
player:give_weapon("mp40")
player:teleport(boz.get("Spawn_Room"))
player:message("Hello", 5)
```

## Talking between objects

Three ways, simplest first.

**Call it.** If you can reach the object, call its methods:

```lua
boz.get("Vault.Door"):hide()
```

**Send an event.** `boz.send` reaches every `boz.on` listener and every object's `on_event`. The
sender doesn't need to know who listens. Good for "something happened" messages.

```lua
-- in one script
boz.send("alarm", {room = "Lab"})
```

```lua
-- in another object's script
function Siren:on_event(name, data)
    if name == "alarm" then
        log("alarm in " .. data.room)
    end
end
```

**Listen from a map script.** `:on()` watches an object from outside:

```lua
-- scripts/main.lua
local boz = require("boz")

boz.get("Vault"):on("use", function(vault, player, volume)
    log("someone used the vault")
end)
```

Listeners at the top of `main.lua` work even though no level is loaded yet, and they keep working
across levels. They run after the object's own hook, and they can't stop it.

## Saving state

Saved games keep two things for you:

- **Fields on `self`**, unless the name starts with `_`.
- **`boz.saved`**, one table every script shares.

```lua
local Skull = boz.Prefab:extend("Skull")

function Skull:start()
    if self.found then
        self:hide()
    end
end

function Skull:on_hit(player)
    self.found = true            -- this skull stays found in a saved game
    self:hide()
    boz.saved.skulls = (boz.saved.skulls or 0) + 1
end

return Skull
```

Use a `_` name for anything that shouldn't survive a reload, like a "running" flag. Saved values
should be plain: numbers, strings, booleans, tables of those.

## Recipes

Complete prefabs to copy. Each says what to build, then gives the script.

### A secret wall

Shoot nothing, buy nothing: the player presses use on a wall and it opens.

**Build:** a wall model with **Walking: Blocks** and **Stops bullets** on, and a **Use** volume in
front of it with the prompt *Push the wall*. Group them.

```lua
local SecretWall = boz.Prefab:extend("SecretWall")

function SecretWall:on_use(player)
    self:hide()
    player:message("The wall gives way")
end

return SecretWall
```

Hiding does all the work: the wall vanishes, people can walk through, bullets pass, and the
Use volume stops prompting.

### A pay-to-open gate

The game has this built in: [Debris](game-prefabs.md#debris). It is any model that disappears
when bought, and it can be extended.

**Build:** your gate model, and a **Use** volume with a **Cost** and the prompt *Open the gate*.
Group them, attach this script.

```lua
local Gate = boz.Debris:extend("Gate")

function Gate:open(player)
    if not boz.Debris.open(self, player) then
        return false
    end
    player:message("The gate falls")
    return true
end

return Gate
```

### A three-skull easter egg

Shoot three skulls and a reward appears. It needs two scripts: one for the skulls, and one for
whatever opens.

**Build:** the `Skull` prefab from earlier, placed three times. A hidden model or prefab called
`Reward`, with this second script attached.

```lua
-- scripts/prefabs/Skull.lua
local Skull = boz.Prefab:extend("Skull")

function Skull:start()
    if self.found then
        self:hide()
    end
end

function Skull:on_hit(player)
    self.found = true
    self:hide()
    boz.saved.skulls = (boz.saved.skulls or 0) + 1
    if boz.saved.skulls == 3 then
        boz.send("egg_done", {player = player})
    end
end

return Skull
```

```lua
-- scripts/prefabs/Reward.lua
local Reward = boz.Prefab:extend("Reward")

function Reward:start()
    if not boz.saved.egg_done then
        self:hide()
    end
end

function Reward:on_event(name, data)
    if name == "egg_done" then
        boz.saved.egg_done = true
        self:show()
        data.player:message("Something opened...")
    end
end

return Reward
```

### A timed trap

Pay to run it, and for a few seconds it kills every zombie close by.

**Build:** a model and a **Use** volume with a **Cost** and the prompt *Run the trap*. Group them.

```lua
local ZapPad = boz.Prefab:extend("ZapPad")

---@setting radius int 300 "Reach (cm)"
---@setting runs_for seconds 10 "Runs for"

function ZapPad:on_use(player)
    if self._running then
        return
    end
    self._running = true
    local zap = boz.every(0.5, function()
        for _, zombie in ipairs(boz.zombies()) do
            if self:near(zombie, self.settings.radius) then
                zombie:kill()
            end
        end
    end)
    boz.after(self.settings.runs_for, function()
        zap:cancel()
        self._running = false
    end)
end

return ZapPad
```

`_running` starts with `_` so a save never keeps it. The volume's cost is taken even while the
trap runs; a player who pays twice loses the second payment. To avoid that, leave **Cost** at 0
and use `player:spend(1000)` after the `_running` check. `spend` returns true when it paid.

### A teleport pad

Walk on it and arrive somewhere else. Each pad picks its own destination.

**Build:** a floor model and a **Trigger** volume over it, set off by **Players**. Group them.
After adding the script, press **Reload**, and link **Destination** to any object.

```lua
local Pad = boz.Prefab:extend("Pad")

---@link destination any one "Destination"
---@setting cooldown seconds 3 "Wait between uses"

function Pad:on_enter(player)
    local target = self:links("destination")[1]
    if not target or self._waiting then
        return
    end
    self._waiting = true
    player:teleport(target)
    boz.after(self.settings.cooldown, function()
        self._waiting = false
    end)
end

return Pad
```

## When something goes wrong

**Nothing happens at all.** Open the editor's **Log** area or `boz-log.txt` in the client folder.
A script error shows there with its line, and it never crashes the game. Add `log("here")` to see
if a hook runs at all.

| What you see | Why | Fix |
| --- | --- | --- |
| Log says the script must return a class | The last line is missing | End with `return Name` |
| `attempt to index a nil value (local 'self')` | A dot where a colon goes | `function Skull:on_hit`, `self:hide()` |
| A game prefab stopped working, or the log names `_handle` or `_piece` | The use wasn't handed back correctly | See [Handing it back to the game](game-prefabs.md#handing-it-back-to-the-game) |
| `on_hit` never runs | The prefab has no **Hit** volume, the volume is too small, or a model in front of it takes the shot | Add or resize it. **Show → Triggers** helps. |
| `on_use` never runs | No **Use** volume, or the player can't afford its **Cost** | Check both |
| `hide()` does nothing | The object has no script and **Scripts can switch it** is off | Turn it on |
| A new setting isn't in the panel | The panel wasn't reloaded | Press **Reload** in the Script box |
| `who:message` errors in `on_enter` | A zombie set it off | Check `who.zombie` first, or set **Set off by** to Players |
| `boz.get` gives something that does nothing | The name is wrong | Names are the ones in the outliner; parts are `Prefab.Part` |

The **Problems** panel checks the map before you build: **Project → Check for problems**.

Next: [Game prefabs](game-prefabs.md) to change the game's own objects, or the
[Events](events.md) table.
