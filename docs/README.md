# Introduction

The BOZ Redux SDK is the toolkit for modding *Call of Duty: Black Ops Zombies* (Android 1.0.11)
on PC with the [BOZ Redux client](https://github.com/ZappaVinny/boz-redux). With it you can:

- write **Lua mods** that change how the game plays: new rules, cheats, settings, menus, hooks
  into any game function;
- build **maps** in the BOZ Redux editor (built on Blender): change Kino der Toten, Ascension or
  Call of the Dead, or make a level of your own, with your own weapons, models, sounds, effects
  and scripted objects;
- read and edit the game's **data files** directly from the command line.

No game files come with the SDK. You need your own copy of the game, installed with the client.

## The documentation

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Installing the client, the SDK and the editor; the SDK app; your first mod and your first map, step by step |
| [Lua mods](lua-mods.md) | How mod scripts run, recipes, hooks, projects and packaging, and the client's Lua API |
| [The map editor](map-editor.md) | The editor, building the world, map scripting, game rules, the game's objects, walkable areas, editing the original levels |
| [Weapons, models, effects and sounds](weapons-and-assets.md) | Weapons and their animations, your own models, the game's effects and projectiles, sounds |
| [Standard library](standard-library.md) | Every `boz.*` function |
| [Console reference](console-reference.md) | Every console variable and command in the game |
| [Game events](game-events.md) | Every `SUBJECT_*` event the game sends |
| [SDK reference](sdk-reference.md) | The `bozkit` command line, map project files, compatibility |
| [How the game works](how-the-game-works.md) | The game's systems, how levels load, how the game stores its data |
| [Contributing](contributing.md) | Working on the SDK, reverse-engineering the game, the roadmap |

New here? Start with [Getting started](getting-started.md).
