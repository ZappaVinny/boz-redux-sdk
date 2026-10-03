# BOZ Redux SDK

Tools and documentation for modding _Call of Duty: Black Ops Zombies_ (Android 1.0.11) on PC with
the [BOZ Redux client](https://github.com/ZappaVinny/boz-redux). This repository is where the
game is reverse-engineered and where mods are made: data edits, assets and, later, Lua code mods.

No game files are included, and none ever will be. You need your own copy of the game, set up by
the client.

## Creation Notes

This was created with a human steered Generative AI (LLM) setup, minimal human verification was done besides functionality tests.

## Contents

| Path             | What it is                                                                                                                                            |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gamedef/`       | The game definition ([boz-redux-gamedef](https://github.com/ZappaVinny/boz-redux-gamedef), submodule): named functions, data layouts, events, console |
| `tools/bozkit/`  | Asset toolkit: read and write the game's `.group.bin` data and saves by field name                                                                    |
| `tools/ghidra/`  | Ghidra scripts and converters that build and export the reverse-engineering project                                                                   |
| `tools/symbols/` | Turns Ghidra exports into the game definition files                                                                                                   |
| `tools/destin/`  | [destin](https://github.com/Tatsh/destin) (submodule): `.dz` pack extraction, textures, models                                                        |
| `docs/`          | [Modding design](docs/modding-design.md), [reverse engineering](docs/reverse-engineering.md), [asset formats](docs/asset-formats.md)                  |

## Setup

```bash
git clone --recurse-submodules git@github.com:ZappaVinny/boz-redux-sdk.git
cd boz-redux-sdk
ln -s ../boz-redux game          # your client checkout with the game set up (see sdk.toml)
```

Python 3.11+ for bozkit and the symbol tools; Ghidra 12.1+ only for reverse engineering.

## Quick start: change a weapon

```bash
cd tools/bozkit
python3 -m bozkit names ../../game/assets/boz.s3e.unpacked     # optional: show names, not hashes
python3 -m bozkit dump weapons_kino.group.bin -o weapons.json
python3 -m bozkit set weapons_kino.group.bin colt45 m_clipSize 12 --component CPlayerWeapon -o weapons_kino.mod.group.bin
```

Extract groups from the game's packs with `dade marmalade extract-dz --no-delete`. Loading edited
files in game comes with the client's mod support.

## License

MIT (see `LICENSE`). The game and its data belong to Activision and are not covered or included.
