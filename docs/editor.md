# The editor

A tour of the BOZ Redux editor: what each part is for and where to find it. For the ideas behind
it, read [How a map works](how-a-map-works.md). For scripting, go to [Prefabs](prefabs.md).

The editor is Blender 5.2 LTS set up for making Zombies maps. It opens from the SDK app (**Open in
Editor** on a map project) and saves straight into the project. Everything is drawn the way the
game draws it, and **Build & Run** puts your map in the game in one click.

If you know Blender, it will feel familiar: G moves, R rotates, S scales, Tab enters Edit Mode.
One Blender unit is one game centimetre.

## The window

- **Top bar:** the **Project**, **Edit** and **Help** menus, the tabs, and **Build & Run** (with its
  ⚙ settings) on the right.
- **Viewport:** the map, with the game's shading.
- **Asset browser** (World tab, left): the game's objects to drag into the map.
- **Outliner:** every object. An object's name is its name in the game and in scripts.
- **Properties:** the Object tab's **Game** panel shows what the selected object is and its boxes.
- **Sidebar** (N in the viewport): the **BOZ** tab, **Problems**, and **Shipped files**.
- **Log** areas: the build's output and the game's `boz-log.txt`.

### The tabs

| Tab | What you do there | Guide |
| --- | --- | --- |
| **Game** | The map's rules: name, loading screen, rounds, special rounds, points, power-ups, the box | [Game rules](#game-rules) |
| **World** | Build the level | [Building the world](#building-the-world) |
| **Weapons** | Change, copy and import weapons; give them your own models and sounds | [Weapons](weapons-and-assets.md#weapons) |
| **Assets** | Import your own models and make game versions of them | [Your own models](weapons-and-assets.md#your-own-models) |
| **Effects** | Pick the game's effects and projectiles for your scripts | [Effects and projectiles](weapons-and-assets.md#effects-and-projectiles) |
| **Animation** | Change a weapon's animations | [Animations](weapons-and-assets.md#animations) |
| **Scripts** | Edit the map's Lua scripts | [Prefabs](prefabs.md) |
| **Audio** | Replace the game's sounds with your own | [Sounds](weapons-and-assets.md#sounds) |

**Characters** and **UI / HUD** are planned, and show what's coming.

### Menus

- **Project:** Save, Build & Run and its settings, **Import model…** (FBX, glTF and OBJ, scaled
  from metres), **Add game shape**, the **Prefab library**, **Check for problems**, **Open project
  folder**, and back to the SDK app.
- **Edit:** undo, redo, undo history, Blender's preferences.
- **Help:** these guides.

## Build & Run

**Project → Save** (Ctrl+S) saves the scene and the project's `source/` folder, which is what the
build reads.

**Build & Run** saves, builds the map into a mod, installs it into your client (last in the load
order, so its files win), and starts the game straight into your map. It won't start while the
game is already running.

The ⚙ next to it sets how the test starts: **Unlimited health**, **Unlimited points** and
**Starting points**. They only apply to the game Build & Run starts. The same dialog sets the map's
**base level**: the shipped level its rounds, zombie types, sounds and cameras come from. The
Developer mod is always on in a test, so its console (`` ` `` or F1) is at hand.

### Playing your map later

After the first Build & Run your map is a mod in the client. Press **PLAY** in the client's
launcher and it's in the list. **PLAY SOLO** starts it, and **CO-OP ROOM** joins or hosts a room for
that map. Players who install your packaged mod get the same choice.

## Problems

The **Problems** panel in the sidebar has two parts:

- **Warnings:** what looks wrong in the map right now, each with a button that selects the object.
- **Last build:** what the build said.

**Project → Check for problems** runs the checks by hand.

## Building the world

The **World** tab is where you build the level.

### The asset browser

| Group | What's in it |
| --- | --- |
| **Game prefabs** | Machines (perks, Pack-a-Punch, mystery box, power switch), Buying (wall buys), Doors (including **Debris**), Barricades (including **Window**), Defence (traps, trap switch) |
| **Level markers** | Spawns, Jump points, Sound |
| **Volumes** | Trigger, Hit, Use |
| **Models**, **Textures** | Everything from every map |
| **My prefabs**, **My assets** | Your own |

The editor builds the library from the SDK's asset library the first time (about 30 seconds) and
again after that changes.

### Building with shapes

Add → **Game shapes** (also the World header's **Shapes** button) adds blocks, walls, floors, ramps,
stairs and pillars at game size, with a tiling texture and the right settings. Blender's own Add →
Mesh shapes are 2 cm big here, since one unit is a centimetre, and the Problems panel flags
anything that small.

For detailed models (a statue, a gun) use the Assets tab, which makes a game version with the right
number of triangles ([Your own models](weapons-and-assets.md#your-own-models)).

### The In the game box

Every model and prefab has this box. The ideas are in
[What an object does in the game](how-a-map-works.md#what-an-object-does-in-the-game).

| Control | What it does |
| --- | --- |
| **Visible** | The master switch. Off: it starts hidden, and stops and blocks nothing. |
| **Scripts can switch it** | Lets scripts change it during play. Always on for an object with a script. |
| **Walking** (models) | **Walk on it**, **Blocks** or **Walk through** |
| **Blocks walking** (game prefabs) | On: nobody can walk through it |
| **Stops bullets** | Shots hit it, or pass through |
| **Shape** | **Box** uses the model's bounds, **Mesh** its triangles |

Barricades don't stop bullets by default, and a trap always does (that's its kill volume).

### The Settings box

Every setting of the object: the game's own (cost, Needs power, ...) and your script's. See each
class on [Game prefabs](game-prefabs.md).

### The Script box

**New** asks for a name and a template (**Empty**, **Basic prefab** or **Object**), makes
`scripts/prefabs/<Name>.lua` and opens it in the **Scripts** tab. See
[Choosing a template](prefabs.md#choosing-a-template). **Pick…** uses a script you already have. The other buttons open it, **Reload** its settings and links, and remove
it. See [Prefabs](prefabs.md).

### The Links box

Links point objects at each other. Each link shows who it points to, with:

- **+** to search for an object;
- the select arrow, **Link selected**, to link what you have selected;
- **×** to remove one;
- **↺** to go back to the default.

Your script's `---@link` lines show here too. See [Links](prefabs.md#links).

### Prefabs

**Make prefab** (Ctrl+G) groups the selected models, volumes and prefabs. **Ungroup** (Ctrl+Alt+G)
takes it apart. **Save as new prefab** stores it under **My prefabs**. Walkthrough:
[Make one in the editor](prefabs.md#make-one-in-the-editor).

### Game prefabs

- **Wall buy:** **Choose…** picks one of the project's weapons. The editor shows the weapon and its
  chalk drawing: the weapon's own, one drawn from its model, your image, or none.
- **Edit its model** gives a game prefab an editable copy of its mesh. It keeps its behaviour and
  the game draws your mesh. **Use the game's model** goes back.
- **Zombie spawn:** **Type** picks how they arrive.
- **Window:** a barricade and a spawn, ready for you to link.

### Textures

Properties → Material shows every texture slot with a preview:

- **Replace…** loads an image file.
- **From game…** uses any of the game's textures, with game shading.
- **✕** goes back to the default grid texture.

Game models need **Make editable** before their textures can change. Dropping a texture from the
asset browser onto an object gives it the same game-shaded material.

### Seeing what the game sees

The viewport's switches are in the tool settings bar, next to Orientation and Drag. The **Show**
menu (also in the sidebar's BOZ tab) switches overlays:

- **Markers** and **Triggers**;
- **Links** between objects;
- **Walkable** and **Collision**, which build the map and show where people can walk (blue, orange
  where a door blocks it) and what bullets hit. **Refresh** builds them again after edits.

### Walkable areas

Players and zombies walk on the walkable area, so it's what to check when someone walks through a
wall or can't reach a room. Turn on **Show → Walkable**:

- **No blue where you want people:** the floor isn't **Walk on it**.
- **Blue through a wall:** the wall isn't **Blocks**.
- **Nothing changed after an edit:** press **Refresh**.

It needs the navmesh helper ([Installation](getting-started.md#the-navmesh-helper)). How it works
inside is in [Map internals](map-internals.md#navigation-meshes).

### Remixing a shipped map

Maps made from **Kino der Toten**, **Call of the Dead**, **Ascension** or the **Tutorial** start as
the whole original map. Its objects are game prefabs you can move, rotate, scale, delete (X), copy
(Shift+D), change the settings of, or start hidden. Only what you changed is written into the map,
and **Put back as the level has it** undoes the changes to an object. The rooms stay as they are.

## Game rules

The **Game** tab sets a map's rules: its name and loading screen, its rounds, the special rounds,
which zombie looks spawn, the points and power-ups. Until
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

Every event a script can follow, with **Create** and **Open**. See
[How to catch one](events.md#how-to-catch-one).
