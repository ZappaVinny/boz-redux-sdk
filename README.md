# BOZ Redux SDK

Tools and documentation for modding _Call of Duty: Black Ops Zombies_ (Android 1.0.11) on PC with
the [BOZ Redux client](https://github.com/ZappaVinny/boz-redux). This repository is where the
game is reverse-engineered and where mods are made: Lua code mods, the standard lib they are built
from, data edits and assets.

No game files are included, and none ever will be. You need your own copy of the game, set up by
the client.

## Creation Notes

This was created with a human steered Generative AI (LLM) setup, minimal human verification was done besides functionality tests.

## Contents

| Path             | What it is                                                                                                                                            |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gamedef/`       | The game definition ([boz-redux-gamedef](https://github.com/ZappaVinny/boz-redux-gamedef), submodule): named functions, data layouts, events, console |
| `tools/bozkit/`  | Shared project compiler and asset toolkit: build/install/package mods and edit game data                                                             |
| `tools/ghidra/`  | Ghidra scripts and converters that build and export the reverse-engineering project                                                                   |
| `tools/symbols/` | Turns Ghidra exports into the game definition files                                                                                                   |
| `tools/destin/`  | [destin](https://github.com/Tatsh/destin) (submodule): `.dz` pack extraction, textures, models                                                        |
| `lib/boz/`       | The standard lib (`boz.*`): the Lua library mods are built from ([reference](docs/standard-library.md))                                               |
| `mods/`          | Reference mods: `developer` (the game's developer console in an overlay), `redux` (PC settings in the pause menu)                                    |
| `docs/`          | [Roadmap](docs/roadmap.md), [SDK projects](docs/sdk-projects.md), [native editing](docs/native-editing.md), [making mods](docs/making-mods.md), [standard library](docs/standard-library.md), [Lua API](docs/lua-api.md), [compatibility](docs/compatibility.md), [asset formats](docs/asset-formats.md), and RE references |

## Setup

```bash
git clone --recurse-submodules git@github.com:ZappaVinny/boz-redux-sdk.git
cd boz-redux-sdk
ln -s ../boz-redux game          # your client checkout with the game set up (see sdk.toml)
```

Python 3.11+ for bozkit and the symbol tools; Ghidra 12.1+ only for reverse engineering.

Install the SDK CLI and optional desktop application:

```bash
python3 -m pip install -e .
python3 -m pip install -e '.[desktop]'  # optional: boz-sdk desktop application
```

## Quick start: make a mod

Create an [SDK project](docs/sdk-projects.md), then build or install it. The compiler adds the
standard library automatically:

```bash
bozkit new hello --id hello --name Hello --author you
bozkit build hello
bozkit install hello --client ../boz-redux
```

Read [making mods](docs/making-mods.md) for the Lua side. A script can use the standard library:

```lua
local pause_settings = require("boz.pause_settings")
local player = require("boz.player")

pause_settings.add_slider{id = "fov", label = "Field of view", min = 50, max = 120, step = 1,
    get = function() return settings.get("fov", 50) end,
    set = function(v) settings.set("fov", v); player.set_fov(v) end}
```

`mods/redux` and `mods/developer` are complete examples.

## Quick start: change a weapon's data

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
.venv/bin/bozkit extract ../boz-redux/original/obb/blackops_etc.dz /tmp/boz-etc --kind dz
.venv/bin/bozkit dump /tmp/boz-etc/ingame/weapons/weapons_kino.group.bin \
  --class CIsEntitySpec -o /tmp/weapons-kino.json
```

Extract groups with `bozkit extract`, edit them, and put complete or modified files in a project's
`assets/` folder. The SDK supports these files for local development and packaging. Authors are
responsible for deciding what game-derived content they may distribute; game assets must never be
committed to this repository. See [native asset editing](docs/native-editing.md) for tested
material, collision, portal, navigation, texture, and static-model workflows using files in this
workspace, plus the explicit limits for unsupported native layouts.

## License

MIT (see `LICENSE`). The game and its data belong to Activision and are not covered or included.
