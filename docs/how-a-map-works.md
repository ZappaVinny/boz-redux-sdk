# How a map works

This page is the whole model on one page. Read it once and the rest of the docs will make sense.

## Three things you place

Everything in a map is one of three things:

| You place | What it is | Example |
| --- | --- | --- |
| **Model** | Something you can see | A wall, a floor, a statue |
| **Volume** | An invisible box that notices things | A **Trigger** (walked into), a **Hit** (shot), a **Use** (the player presses use) |
| **Prefab** | A group of models and volumes that act as one object, with an optional script | A skull you can shoot, a perk machine, a door |

```text
Vault  (a prefab, with a script)
├── Door      a model
├── Frame     a model
└── Keypad    a Use volume
```

The game's own objects (perk machines, doors, the mystery box) are prefabs too. You drag them in,
they work straight away, and you can change them from a script. See
[Game prefabs](game-prefabs.md).

## What an object does in the game

Every model and prefab has three switches in the editor's **In the game** box:

| Switch | What it means | From a script |
| --- | --- | --- |
| **Visible** | The master switch. A hidden object can't be seen, stops nothing and blocks nothing. | `object:hide()`, `object:show()` |
| **Walking** | **Walk on it** (it is floor), **Blocks** (nobody can walk through it) or **Walk through** (it doesn't matter to walking). | `object:set_blocks_walking(true)` |
| **Stops bullets** | Shots hit it and leave a mark, or pass through. | `object:set_stops_bullets(false)` |

The thing to remember: **players and zombies both walk on the walkable area, not on the models.**
The walkable area (the *navmesh*) is a map of where anyone can go, built from your floors and
walls when you build the map. Collision only decides what bullets hit.

So a wall needs both: **Blocks** to stop people, and **Stops bullets** to stop shots. A pane of
bulletproof glass you can walk through has only the second. A line nobody can cross but everyone
can shoot over has only the first.

The editor's **Show → Walkable** draws the walkable area, so you can see where people can go.

## New map or Remix

| Kind | You start with | Use it for |
| --- | --- | --- |
| **New map** | A floor, four player spawns and the Colt | Building your own level. This is the normal choice. |
| **Remix** (Kino der Toten, Ascension, Call of the Dead, Tutorial) | The whole original map | Changing a map that already exists |

Everything in these docs works in both. In a remix the rooms stay as they are, and the original
objects can be moved, changed, hidden or removed.

## Names

An object's name in the editor is its name in scripts. A part of a prefab is `Prefab.Part`:

```lua
local boz = require("boz")

local vault = boz.get("Vault")            -- the prefab
local door = boz.get("Vault.Door")        -- one of its parts
```

`boz.get` gives you the object as its class, so a door has door methods and a perk machine has
perk methods. Copies you place get their own names, and a script runs once for each copy.

## Links

A link is one object pointing at another: this switch runs that trap, this perk needs that power
switch, this window belongs to that spawn. You make them in the **Links** box of the selected
object. The viewport draws them as lines (**Show → Links**).

Your own scripts can ask for links too, and read them with `self:links("name")`. See
[Links](prefabs.md#links).

## Two kinds of script

| | **Object script** | **Map script** |
| --- | --- | --- |
| Where | `scripts/prefabs/<Name>.lua`, attached to an object | `scripts/main.lua` |
| What it is | A class: what this object *is* and *does* | A list of things to listen for |
| Runs | Once for each object that has it | Once, when the game starts |
| Can it stop the object's behaviour? | Yes | No, it can only watch |

```lua
-- scripts/prefabs/Skull.lua: an object script, attached to a prefab
local Skull = boz.Prefab:extend("Skull")

function Skull:on_hit(player)
    self:hide()
    player:give_points(100)
end

return Skull
```

```lua
-- scripts/main.lua: the map script
local boz = require("boz")

boz.on("round_started", function(data)
    boz.player():message("Round " .. data.round)
end)

boz.get("Front_Door"):on("opened", function(door, player)
    player:give_points(500)
end)
```

Rule of thumb: if it is about **one object**, put it on the object. If it is about **the whole
match**, put it in `main.lua`.

## What Build & Run does

1. Saves your map and turns it into a mod, working out the walkable area and collision.
2. Installs the mod in your client, last in the load order.
3. Starts the game and goes straight into your map.

If something would stop the build, the **Problems** panel tells you and selects the object.

Next: [Prefabs](prefabs.md), where you make your own.
