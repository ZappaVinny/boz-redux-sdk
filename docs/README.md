# Introduction

The BOZ Redux SDK is the toolkit for modding *Call of Duty: Black Ops Zombies* (Android 1.0.11) on
PC with the [BOZ Redux client](https://github.com/ZappaVinny/boz-redux). Build your own Zombies
maps, make your own weapons, and change how the game plays, all with free tools and no reverse
engineering.

No game files come with the SDK. You need your own copy of the game, installed with the client.

## What you can do

**Build maps.** Start from an empty floor, or remix Kino der Toten, Ascension or Call of the Dead.
The editor is Blender set up for Zombies: it draws your map the way the game does, and **Build &
Run** puts you in it in one click.

**Use everything in the game.** Every model, texture, machine, door and trap from every map is in
the asset browser, ready to drag in. Perk machines, the mystery box, Pack-a-Punch, wall buys, traps
and windows work as soon as you place them.

**Bring your own models and textures.** Import FBX, glTF and OBJ. The editor makes a game version
with the right number of triangles, and shows you how it will look.

**Make weapons.** Copy any gun, change its damage, fire rate and ammo, or give it your own model.
Edit its animations and its Pack-a-Punch upgrade.

**Change the sound.** Replace any of the game's sounds with your own, give each weapon its own
sounds, and play music and voice lines from scripts.

**Add effects.** Use the game's effects and projectiles anywhere: black holes, explosions, lightning.

**Set the rules.** Shape every round: how many zombies, their health and speed, how the game scales
as rounds climb, with a graph to see it. Set dog rounds, points, power-ups and the box, and give
each difficulty and player count its own balance.

**Script anything.** Group objects into prefabs and give them a Lua script: buttons, traps,
teleporters, easter eggs. Extend the game's own objects to change what they do, with settings and
links right in the editor.

**Change the controls and the screen.** Add key binds and pause-menu settings, draw your own
windows, or change the field of view.

**Play together.** Every map works in LAN co-op, and players start it straight from the client's
launcher.

**Share it.** One click packages your work as a mod that players drop into their client.

## Where to start

New here? Go through these in order:

1. [Getting started](getting-started.md): install the tools and make a map with your first script.
2. [How a map works](how-a-map-works.md): the whole model, on one page.
3. [Prefabs](prefabs.md): make your own objects, with recipes to copy.

## The documentation

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Install, your first map, your first script, the SDK app |
| [How a map works](how-a-map-works.md) | Models, volumes, prefabs, walking, names, links, scripts |
| [Prefabs](prefabs.md) | Making your own objects: hooks, volumes, settings, links, recipes |
| [Game prefabs](game-prefabs.md) | Each of the game's objects: settings, what you can override, examples |
| [Events](events.md) | Everything your scripts can react to |
| [Scripting reference](scripting.md) | The functions you will use most |
| [Script mods](script-mods.md) | Mods with no map, hooks, packaging, the client's Lua API |
| [The editor](editor.md) | A tour of the editor, and game rules |
| [Weapons & assets](weapons-and-assets.md) | Weapons, your own models, effects, sounds |
| [Console reference](console-reference.md) | Every console variable and command |
| [Low-level events](game-events.md) | Every `SUBJECT_*` event the game sends |
| [SDK reference](sdk-reference.md) | The `bozkit` command line, project files, compatibility |
| [Map internals](map-internals.md) | Game prefab fields, navmeshes, editing shipped files |
| [How the game works](how-the-game-works.md) | The game's systems and data formats |
| [Contributing](contributing.md) | Working on the SDK, reverse engineering, the roadmap |
