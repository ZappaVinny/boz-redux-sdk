# How the game works

A modder's tour of *Call of Duty: Black Ops Zombies* (1.0.11): the systems you will meet, what
they do, and where to change them. Function and event names are the ones in the game definition
(`gamedef/`), so you can hook them or look up their notes. When the standard lib already covers
something, that is the easier way; see [standard-library.md](standard-library.md).

## The big picture

The game is built in three layers, and the names tell you which one you are looking at:

| Prefix | Layer | Examples |
| --- | --- | --- |
| `C...` (no `Is`/`Iw`) | The game itself | `CWaveManager`, `CMysteryBox`, `CPlayerController`, `CDO*` (Dead Ops) |
| `CIs...` | The studio's engine (Ideaworks): entities, components, events, animation | `CIsEntityDB`, `CIsSubject`, `CIsCamera` |
| `CIw...` | Marmalade, the cross-platform SDK: resources, UI, sound, console | `CIwResManager`, `CIwUISlider`, `CIwConsole` |

Gameplay objects are **entities** made of **components** (a zombie has `CHealth`, an AI
controller, a body, ...). Big systems are **singletons** (`CWaveManager`, `CScoreManager`,
`CLevelManager`, ...). Systems talk through **events**.

There are two game modes: **Zombies** (the first-person maps: Kino der Toten, Ascension, Call of
the Dead, ...) and **Dead Ops Arcade** (top-down, its own `CDO*` systems). Most of this page is
about Zombies.

## Events

Systems announce things with events named `SUBJECT_*`: `SUBJECT_NEW_WAVE`, `SUBJECT_ZOMBIE_DEATH`,
`SUBJECT_ADD_SCORE`, `SUBJECT_ON_PERK_GAINED`, ... A system sends an event; everything that
subscribed to it gets it in its `OnEvent`. `gamedef/events/boz-1.0.11.toml` lists all 337 events
with the classes that send and handle them.

For a mod, events are the natural place to react: hook the handler of the event you care about.

## A frame

Each frame the game updates the current state (main menu, playing, paused, ...), runs the world
and every system and component, draws the scene and the HUD, and updates sound, music and the
network. The client's `frame` event runs once per displayed frame, after all of that.

## Rounds

Rounds are run by `CWaveManager` from round definitions (`CWave`, game data):

- while fewer zombies have spawned than the round's total, and fewer are alive than its maximum,
  it spawns one after a short delay;
- every zombie death counts; when the count reaches the total, the round ends
  (`SUBJECT_WAVE_ENDED`) and after a pause `CWaveManager::StartWave` starts the next one;
- later rounds grow: each value is `base * multiplier ^ (round - first round)`; special rounds
  (hellhounds, monkeys) slot in between.

Round sizes, zombie speeds and health are data, so they can be changed by editing the round
definitions (bozkit) or by hooks at run time. The standard lib has `boz.rounds` for starting
rounds and spawning or killing zombies.

## Points and purchases

`CScoreManager` keeps each player's points:

- earning: `SUBJECT_ADD_SCORE` (kills, repairs) adds points through `CScoreManager::AddScore`;
- spending: every purchase (doors, the box, perks, Pack-a-Punch, traps, turrets) sends
  `SUBJECT_CHARGE_POINTS`;
- in single player, a purchase you cannot afford is paid with COD Points (the store currency) when
  you have enough.

The cheat `UnlimitedScore` makes purchases free; `StartingScore` sets the starting points.

## Combat and health

- **Shooting:** a weapon's shoot animation fires its bullets: each pellet gets spread, a ray is
  cast, and what it hits gets `SUBJECT_WEAPON_HIT` with the body part. The knife does the same
  for a target in front of the player.
- **Health:** `CHealth` clamps damage, regenerates after a delay and sends `SUBJECT_DIED` below
  1 health. `CHealth::Damage` is where damage arrives.
- **Kills:** a dying zombie sends a kill-score event by how it died (head, torso, limb, knife,
  grenade); the killer's score handler looks up the points (doubled during Double Points) and adds
  them. `zombieHeadshotBonus` is extra for headshots.

## Weapons

A weapon is an entity with a `CPlayerWeapon` component: its definition (clip size, damage, fire
rate) and live ammo. Each weapon type (automatic, shotgun, launcher, Wonder Weapons) is a small
state machine: idle, firing, reloading. Weapon stats are data (`weapons_<map>.group.bin`),
readable and editable with bozkit. `WeaponsUnlimitedAmmo` stops ammo use.

## Perks, power-ups and the box

- **Usable objects** (perk machines, the mystery box, Pack-a-Punch, doors, barricades, traps,
  turrets) all have an `Interact`: check the cost, charge points, act.
- **Perks** (`CPerkManager` on the player): Deadshot, Double Tap, Juggernog, Stamin-Up, PHD
  Flopper, Quick Revive, Speed Cola. `boz.player.give_perk` / `give_all_perks` grant them.
- **Power-ups** drop from zombies based on points earned since the last drop; the last dog or
  monkey of a round drops Max Ammo.
- **The box** rolls a weapon and hands it over through `CWeaponManager::GiveWeapon`.

## The player and the camera

The local player's controller is `CPlayerController`; its weapon manager (`CWeaponManager`)
also owns the view's field of view: it eases between the map's default and the weapon's
aim-down-sights zoom each frame. `boz.player.set_fov` changes it properly. `boz.fly` turns on
the game's developer fly mode (noclip).

## Menus

The game has two UI systems:

- **The main menu** is one Flash movie (`fe_v4_cs4_swf.bin`, ActionScript 2) played by an
  embedded Flash player (gameswf). Its screens talk to the game with named messages.
  `boz.frontend` has the building blocks for changing it.
- **The in-game menus** (pause menu, settings, HUD) are Marmalade IwUI pages: trees of widgets
  (labels, images, buttons, sliders) found by name, whose widgets call named handlers on the page.
  `boz.pause_settings` adds settings to the pause menu; `boz.iwui` is the toolkit underneath.

Text is shown by **string id** (`S_MENU_MUSIC`) in the player's language; `boz.text` adds your
own.

## Saves

Saves are `.i3d` files in the client's `saves/` folder: profiles, stats, settings, achievements,
and the mid-match save written at each round start in single player. Each system saves its own
section. bozkit reads them (`bozkit save`, `bozkit settings`); the format is in
[asset-formats.md](asset-formats.md).

## The console

The game kept its developer console: about 660 variables (tuning values and cheats) and 150
commands, listed in [console-reference.md](console-reference.md). Many variables exist only while
a match runs. `boz.console` runs commands and reads and sets variables; the Developer mod gives it
a window.

## Dead Ops Arcade

A separate mode with its own systems: `CDORoundManager` (rounds), `CDOHordeManager` (enemies),
`CDOPickupManager` (power-ups) and `CDOPlayerController` (which can switch between walking, a
helicopter and a tank). Each of its 42 rounds is data: arena, lighting, music, and which enemies
unlock when.

## Zombies and pathing

Zombies move with Recast/Detour, the standard navigation-mesh library: each map has a navmesh,
zombies are crowd agents (speed, avoidance, climbing are data), and window and barricade climbs
are separate connection objects. Per-round speeds come from the round definitions.

## Co-op

The game has local Wi-Fi co-op (discovery plus TCP), with the host running the match and the
other players following it. Online play used Activision's servers, which BOZ Redux does not use.
