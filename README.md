# BOZ Redux SDK

Tools and documentation for modding _Call of Duty: Black Ops Zombies_ (Android 1.0.11) on PC with
the [BOZ Redux client](https://github.com/ZappaVinny/boz-redux). This repository is where the
game is reverse-engineered and where mods are made: Lua code mods, the standard lib they are built
from, data edits and assets.

No game files are included, and none ever will be. You need your own copy of the game, set up by
the client.

## Creation Notes

This was created with a human steered Generative AI (LLM) setup, minimal human verification was done besides functionality tests.

## Documentation

Start at the [introduction](docs/README.md), or go straight to
[Getting started](docs/getting-started.md), [Lua mods](docs/lua-mods.md),
[The map editor](docs/map-editor.md) or the [standard library](docs/standard-library.md).
Maintainers: [Contributing](docs/contributing.md).

## Quick start

```bash
git clone --recurse-submodules https://github.com/ZappaVinny/boz-redux-sdk.git
cd boz-redux-sdk
python3 -m pip install -e '.[desktop]'
boz-sdk                                   # the SDK app: projects, the asset library, the editor
```

Or from the command line:

```bash
bozkit new hello --id hello --name Hello --author you
bozkit install hello --client path/to/boz-redux
```

## Contents

| Path | What it is |
| --- | --- |
| `tools/bozkit/` | The SDK in Python: project compiler, game file formats, asset library, the SDK app |
| `blender/` | The map editor (a Blender 5.2 LTS application template) |
| `lib/boz/` | The standard library (`boz.*`), the Lua library mods are built from |
| `mods/developer/` | The Developer mod: the game's developer console in an overlay, cheats, noclip |
| `gamedef/` | The game definition ([boz-redux-gamedef](https://github.com/ZappaVinny/boz-redux-gamedef), submodule): named functions, data layouts, events, console |
| `tools/ghidra/`, `tools/symbols/` | Reverse-engineering scripts and the converters to the game definition |
| `tools/navmesh/` | The native Recast helper that rebuilds navmesh tiles |
| `tools/destin/` | [destin](https://github.com/Tatsh/destin) (submodule): `.dz` pack extraction |
| `docs/` | The documentation |

## License

MIT (see `LICENSE`). The game and its data belong to Activision and are not covered or included.
