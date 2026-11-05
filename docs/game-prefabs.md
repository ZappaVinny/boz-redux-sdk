# Game prefabs

Game prefabs are the game's own objects: perk machines, doors, the mystery box and the rest. Drag
one in and it works with no script. Each is a class you can extend, so you can change what it
does and keep the parts you like.

## How extending works

Select a game prefab and click **New** in its **Script** box. The popup starts on **Object**, with
the right class in **Extends**, and the script has that class's hooks ready.

Here a door stays shut until an easter egg is done:

```lua
local SealedDoor = boz.Door:extend("SealedDoor")

function SealedDoor:on_use(player)
    if not boz.saved.egg_done then
        player:message("It won't move")
        return
    end
    boz.Door.on_use(self, player)     -- pay and open as normal
end

return SealedDoor
```

Three rules cover every class on this page:

1. **Your `on_use` replaces the game's.** When a player uses the object, your function runs *instead*
   of the purchase.
2. **To keep the game's behaviour, hand the use back to it.** That's the line
   `boz.Door.on_use(self, player)`. Without it nothing is paid and nothing opens.
3. **Only an object's script can stop it.** A map script's `:on()` can watch, never stop.

### Handing it back to the game

This pattern is how every game prefab works, so it's worth reading once, slowly:

```lua
function LuckyBox:on_use(player)
    boz.MysteryBox.on_use(self, player)
end
```

- **`function LuckyBox:on_use(player)`** is your version. The game gives you `player`.
- **`boz.MysteryBox.on_use`** is the original, on the class you extended. Your version replaced it
  for this object, but the original is still there on `boz.MysteryBox`.
- **`(self, player)`** is the data, passed back by hand. The original doesn't see what your function
  was given, so you pass it on: first `self`, the object it should act on, then everything your
  function received.
- **The dot matters.** You've used a colon everywhere else, but `boz.MysteryBox:on_use(player)` would
  pass the *class* as `self`, not your box. Calling a parent is the one place you write the dot and
  pass `self` yourself.

Everything you want to change goes around that line:

```lua
local LuckyBox = boz.MysteryBox:extend("LuckyBox")

function LuckyBox:on_use(player)
    if boz.round() < 3 then                  -- before: decide whether it happens
        player:message("The box is sleeping")
        return                               -- leaving now stops it. Nothing is paid.
    end
    player:message("Good luck")              -- before: add something
    boz.MysteryBox.on_use(self, player)      -- hand it back: the game pays and spins
end

function LuckyBox:on_weapon(player, weapon)  -- after: react to the result
    player:message("You got " .. weapon)
end

return LuckyBox
```

Code placed after the hand-back line runs straight away, and it can't tell whether the player could
pay. To react to what really happened, use the object's event hook, like `on_weapon` here.

### What to hand back, by class

| Class | The line |
| --- | --- |
| Door | `boz.Door.on_use(self, player)` |
| Debris | `boz.Debris.on_use(self, player)` |
| Perk | `boz.Perk.on_use(self, player)` |
| MysteryBox | `boz.MysteryBox.on_use(self, player)` |
| PackAPunch | `boz.PackAPunch.on_use(self, player)` |
| PowerSwitch | `boz.PowerSwitch.on_use(self, player)` |
| TrapSwitch | `boz.TrapSwitch.on_use(self, player)` |
| WallBuy | `boz.WallBuy.on_use(self, player)` |
| Barricade | `boz.Barricade.on_use(self, player)` |

Debris has two more originals, because it's written in Lua and not by the game:

| When you override | Hand back with |
| --- | --- |
| `open(player)` | `boz.Debris.open(self, player)`, which returns false when it was open already |
| `start()` | `boz.Debris.start(self)`, or a saved game forgets that it was opened |

**Event hooks have nothing to hand back.** `on_opened`, `on_bought`, `on_spun`, `on_weapon`,
`on_upgraded`, `on_on`, `on_activated`, `on_cooled` and `on_repaired` are yours alone, and the thing has already happened. Don't call a parent
in them. The same goes for `on_event`, and for `start` on everything but Debris. Your own prefabs,
Trap, ZombieSpawn, Volume and Weapon have no `on_use` of the game's, so there's nothing to hand back
there either.

**Always pass everything you were given.** Leaving out `player` happens to work on some classes, but
not all: Debris passes it on to `on_opened`.

### When it goes wrong

The error goes to the log. In the first two the use does nothing and no points are taken. In the
third the door has already opened, and only the rest of your hook is skipped.

| The log says | You wrote | Write |
| --- | --- | --- |
| `attempt to index a nil value (field '_handle')` | `boz.Perk:on_use(player)` | `boz.Perk.on_use(self, player)`, with a dot |
| `attempt to call a nil value (method '_piece')` | `boz.Perk.on_use(player)` | `boz.Perk.on_use(self, player)`, with `self` first |
| `attempt to call a nil value (field 'on_opened')` | `boz.Door.on_opened(self, player)` | Nothing: event hooks have no parent |

### What you can and can't change

**What you can override:** `on_use` on everything a player can use, and the `on_<event>` hooks in
each class's table. Those hooks run *after* the event, so they add to it.

**What you can't override:** the rest of what the game does by itself, such as how a box picks a
weapon, how a trap kills, or how zombies pick a spawn. Change those with settings, or use the
methods to trigger things yourself.

### Settings

Every class has settings in the editor's **Settings** box, and your script reads them through
`self.settings`, by the names in each table below.

The **Live** column says what a change does while the game runs:

- **Yes:** read it or write it at any time, and the game uses the new value at once.
- **Read only:** you get the value set in the editor; writing it changes nothing in the game.
- **Next move:** the game uses the new value the next time the box arrives somewhere.

```lua
local CheapPerk = boz.Perk:extend("CheapPerk")

function CheapPerk:on_event(name, data)
    if name == "round_started" and data.round == 10 then
        self.settings.cost = self.settings.cost // 2      -- half price from round 10
    end
end

return CheapPerk
```

You can add your own `---@setting` and `---@link` lines too. They join the same boxes.

### What every class has

All of [What every object has](prefabs.md#what-every-object-has): `self.name`, `self.settings`,
`self:position()`, `self:visible()`, `self:links("power")`, `self:class_name()` and the rest. On top
of that:

| Method | What it does |
| --- | --- |
| `on_use(player)` | The game's purchase: pays and runs it. If you override it, [hand it back](#handing-it-back-to-the-game). |
| `use_free()` | Runs it without paying |
| `field("name")`, `set_field("name", value)` | Any field of the game's data by its game name, for when no setting exists. See [Under the hood](map-internals.md#game-prefab-fields). |

## Door

A door the player buys open. Pick one of the game's designs from **Doors** in the asset browser.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `cost` | Cost | Whole number | Yes |
| `needs_power` | Needs power | Link | Read only |
| `disappears_when_opened` | Disappears when opened | On or off | Yes |

| Method | What it does |
| --- | --- |
| `open()` | Opens it, free |
| `is_open()` | True once open |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player tries to buy it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_opened(player)` | It has opened | No |

Pay out when a door opens:

```lua
local BonusDoor = boz.Door:extend("BonusDoor")

function BonusDoor:on_opened(player)
    player:give_points(250)
end

return BonusDoor
```

A door can also open by itself, from any script:

```lua
boz.get("Front_Door"):open()
```

## Debris

Debris is a **door of your own**: any model that vanishes when bought. There's no game design to
pick. You bring the model, and it does the rest. `boz.Debris` extends `boz.Door`, so it is a door
to everything else, and `is_a(boz.Door)` is true.

**Make it:** drag **Debris** from **Doors**, or make a prefab with your model and a **Use**
volume. The volume holds the **Cost** and **Prompt**, not a Cost setting.

When bought it hides, which opens walking and bullets, plays the debris sound, sends `opened` and
opens anything in its **Opens with** link. It stays open in saved games.

| Method | What it does |
| --- | --- |
| `open(player)` | Opens it. Returns false when already open. **Override this one.** |
| `is_open()` | True once open |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | The Use volume was bought, already paid | **Yes**, but the points are gone. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `open(player)` | It opens, from any cause | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_opened(player)` | It has opened | No |

Because a Debris can be anything, it can do more than open a path:

```lua
local Rubble = boz.Debris:extend("Rubble")

function Rubble:open(player)
    if not boz.Debris.open(self, player) then
        return false
    end
    boz.audio.play("buy_debris")
    boz.send("zone_opened", {name = self.name})
    return true
end

return Rubble
```

## Perk

A perk machine. Pick one from **Machines**.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `cost` | Cost | Whole number | Yes |
| `co_op_cost` | Co-op cost | Whole number | Yes |
| `needs_power` | Needs power | Link | Read only |
| `use_distance` | Use distance | Number (cm) | Yes |

Players also need to be in front of the machine. Standing behind it or to one side shows no prompt.

| Method | What it does |
| --- | --- |
| `give()` | Gives the perk to the player for free |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player tries to buy it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_bought(player, perk)` | A player bought it. `perk` is its name. | No |

A perk you must earn:

```lua
local EarnedPerk = boz.Perk:extend("EarnedPerk")

function EarnedPerk:on_use(player)
    if boz.round() < 5 then
        player:message("Come back on round 5")
        return
    end
    boz.Perk.on_use(self, player)
end

return EarnedPerk
```

`on_bought` needs a real purchase at this machine. A perk given by a script
(`player:give_perk("Juggernog")`) goes to the player without touching any machine, so no machine
hears about it. `boz.on("perk_bought", ...)` still does.

Perk names: `Deadshot`, `Double Tap`, `Juggernog`, `Stamin-Up`, `PHD Flopper`, `Quick Revive`,
`Speed Cola`.

## MysteryBox

The mystery box. The map can have several; the game moves it between them.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `cost` | Cost | Whole number | Yes |
| `fire_sale_cost` | Fire sale cost | Whole number | Yes |
| `uses_before_it_moves_at_least` | Uses before it moves, at least | Whole number | Next move |
| `uses_before_it_moves_at_most` | Uses before it moves, at most | Whole number | Next move |
| `weapon_pool` | Weapons | A list, edited with **Edit…** | Read only |

| Method | What it does |
| --- | --- |
| `bring_out()` | Brings the box out here |
| `send_away()` | Sends it away, with its animation |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player tries to spin it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_spun(player)` | A player spun it | No |
| `on_weapon(player, weapon)` | The box picked a weapon | No |

```lua
local LoudBox = boz.MysteryBox:extend("LoudBox")

function LoudBox:on_weapon(player, weapon)
    player:message("You rolled: " .. weapon)
end

return LoudBox
```

## PackAPunch

Upgrades the weapon in the player's hands. **It needs a mystery box in the map**: the build stops
with an error otherwise. A weapon with no upgrade is refused, and nothing is paid. Set a weapon's
upgrade with **Pack-a-Punch result** in the **Weapons** tab.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `cost` | Cost | Whole number | Yes |
| `needs_power` | Needs power | Link | Read only |
| `use_distance` | Use distance | Number (cm) | Yes |

| Method | What it does |
| --- | --- |
| `bring_out()` | Brings the machine out |
| `send_away()` | Sends it away |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player tries to use it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_upgraded(player, weapon)` | A weapon went in | No |

```lua
local OnePunch = boz.PackAPunch:extend("OnePunch")

function OnePunch:on_use(player)
    if self.used then
        player:message("It's spent")
        return
    end
    boz.PackAPunch.on_use(self, player)
end

function OnePunch:on_upgraded(player, weapon)
    self.used = true
end

return OnePunch
```

## PowerSwitch

Turns on the power. Anything with **Needs power** waits for it.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `usable_from_the_start` | Usable from the start | On or off | Yes |

| Method | What it does |
| --- | --- |
| `turn_on()` | Turns the power on |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player pulls it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_on(player)` | The power came on, from any cause | No |

The power needing a key:

```lua
local LockedSwitch = boz.PowerSwitch:extend("LockedSwitch")

function LockedSwitch:on_use(player)
    if not boz.saved.has_key then
        player:message("It needs a key")
        return
    end
    boz.PowerSwitch.on_use(self, player)
end

return LockedSwitch
```

## TrapSwitch and Trap

A **Trap** is the thing that hurts. A **TrapSwitch** is what players pay at. Link them in the
switch's **Traps** link. Any switch can run any trap, and one switch can run several. The palette
has **Trap: Firepit**, **Trap: Electro zapper** and **Trap: Firewall** in **Defence**.

### TrapSwitch

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `cost` | Cost | Whole number | Yes |
| `needs_power` | Needs power | Link | Read only |
| `use_distance` | Use distance | Number (cm) | Yes |

| Method | What it does |
| --- | --- |
| `activate()` | Runs its traps without paying |
| `busy()` | True while one of its traps runs or cools down |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player tries to run it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_activated(player)` | A player ran it | No |
| `on_cooled()` | A trap of its traps is ready again | No |

While a linked trap runs or cools down, the switch does nothing and costs nothing.

### Trap

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `runs_for` | Runs for | Seconds | Yes |
| `cool_down` | Cool-down | Seconds | Yes |
| `player_damage` | Player damage | Whole number | Yes |

| Method | What it does |
| --- | --- |
| `activate(seconds)` | Runs the trap, for `seconds` or its own time |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_cooled()` | Its cool-down ended, and it's ready again | No |

A trap has no player use, so there's no `on_use`. Run it from something else:

```lua
local Tripwire = boz.Prefab:extend("Tripwire")

---@link trap trap one "Trap it sets off"

function Tripwire:on_enter(who)
    self:links("trap")[1]:activate(5)
end

return Tripwire
```

## WallBuy

A weapon on a wall. Pick the weapon with **Choose…**; it must be one of the map's weapons, which
you add in the **Weapons** tab.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `weapon` | Weapon | Picked with **Choose…** | Read only |
| `cost` | Cost | Whole number | Yes |
| `ammo_cost` | Ammo cost | Whole number | Yes |
| `upgraded_ammo_cost` | Upgraded ammo cost | Whole number | Yes |
| `chalk` | Chalk | The drawing on the wall | Read only |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player tries to buy it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_bought(player, weapon)` | A player paid for the weapon or its ammo. `weapon` is its name. | No |

```lua
local Sniper = boz.WallBuy:extend("Sniper")

function Sniper:on_use(player)
    if boz.round() < 10 then
        player:message("Locked until round 10")
        return
    end
    boz.WallBuy.on_use(self, player)
end

return Sniper
```

## Barricade

The boards across a window. Zombies tear them down, and players rebuild them. Link a barricade to
a zombie spawn of **Type: Window** to make a working window, or use **Window** in the palette,
which gives you both to link yourself.

A black arrow in the viewport shows which way zombies cross.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `starts_broken` | Starts broken | On or off | Read only |

**Stops bullets** in the **In the game** box is off by default, so players can shoot through
windows. It can't be changed from a script.

| Method | What it does |
| --- | --- |
| `repair()` | Puts one board back |

| Override | When | Can stop it? |
| --- | --- | --- |
| `on_use(player)` | A player uses it | **Yes**. To keep it, [hand it back](#handing-it-back-to-the-game). |
| `on_repaired(player)` | A player put a board back. Runs for each board. | No |

There's no event yet for a torn board. `on_repaired` is for a player's repairs: a Carpenter or
`repair()` from a script only shows as the game event `barricade_repaired`.

## ZombieSpawn

Where zombies come from. **Zombie spawn** is one marker in **Level markers**; its **Type** picks
how they arrive: Window, Ground, From above, Ceiling, Climb, Dogs or Monkeys.

| Setting | Label | Kind | Live |
| --- | --- | --- | --- |
| `active_from_the_start` | Active from the start | On or off | Read only here; use `set_active` |

**Off** means the spawn starts working once players reach its area.

| Method | What it does |
| --- | --- |
| `set_active(on)` | Lets zombies come out of it, or not |

There's nothing to override: a spawn has no player use. Switch them from another object:

```lua
local Alarm = boz.Prefab:extend("Alarm")

---@link spawns zombie_spawn many "Spawns it wakes"

function Alarm:on_use(player)
    for _, spawn in ipairs(self:links("spawns")) do
        spawn:set_active(true)
    end
end

return Alarm
```

## Weapon

A weapon isn't placed in the map, but it takes a script the same way: **Weapons** tab → **Script**.
Weapons extend `boz.Weapon`.

| Hook | When it runs |
| --- | --- |
| `on_given()` | Bought, rolled from the box, or given by a script |
| `on_equip()` | Taken in hand |
| `on_fire(data)` | Every shot. `data.clip` is the rounds before it. |
| `on_reload()` | A reload started |

| Method | What it does |
| --- | --- |
| `clip()`, `reserve()` | Ammo now |
| `clip_size()`, `reserve_size()` | The most it holds |
| `set_ammo(clip, reserve)` | Sets the ammo |
| `fire_rate()`, `set_fire_rate(rpm)` | Rounds per minute |
| `damage()`, `set_damage(head, torso, limbs)` | Damage |
| `in_hand()` | True while in the player's hand |

Ammo and damage calls need the player to have the weapon, and otherwise give `nil`.

```lua
local IdGun = boz.Weapon:extend("IdGun")

function IdGun:on_fire(data)
    if data.clip == 1 then
        boz.player():message("Last round!")
    end
end

return IdGun
```

The hooks only watch, so they can't stop a shot. For the rest of what a weapon can be (its model,
animations, sounds, numbers), see [Weapons & assets](weapons-and-assets.md).
