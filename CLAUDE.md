# CLAUDE.md

SDK for modding *Call of Duty: Black Ops Zombies* (Android 1.0.11) with the BOZ Redux client:
reverse engineering, the game definition, asset tools and (later) mod templates, packaging and
the Redux base mod. Siblings: `../boz-redux` (the client: runtime, launcher, mod runtime) and the
`gamedef/` submodule (boz-redux-gamedef: symbols, reflection, events, console).

## Layout

- `gamedef/`: submodule. The SDK generates it; commit inside it, then bump the pointer here.
  The client pins it separately. A breaking change bumps `schema` in `gamedef/gamedef.toml`.
- `tools/ghidra/`: `s3e_to_elf.py`, `rtti_classes.py`, Ghidra Java scripts (run through the
  Ghidra MCP with absolute paths). Pipeline and conventions: `docs/reverse-engineering.md`.
- `tools/symbols/symbols.py`: Ghidra exports to gamedef TOML (`from-json`, `reflection`,
  `events`, `console`) and back (`to-json`).
- `tools/bozkit/`: Python asset toolkit (`python3 -m bozkit dump|set|save|settings|names`, tests in
  `tools/bozkit/tests`, synthetic data only). Formats: `docs/asset-formats.md`.
- `tools/destin/`: submodule for `dade` (`uv tool install dade`). Always pass `--no-delete` to
  `dade marmalade extract-dz`; it deletes the source archive by default.
- `re/` (gitignored): converted ELF, Ghidra project `re/ghidra/BOZ`, generated reports. Contains
  game code; never commit it.
- `game` (gitignored link to `../boz-redux`): the client's game root (`assets/`, `saves/`).
- `.mcp.json` (gitignored): Ghidra MCP config. Scripts need Ghidra started with
  `GHIDRA_MCP_ALLOW_SCRIPTS=1 /opt/ghidra/ghidraRun`.

Never commit game files: APK, `.dz`, extracted assets, converted binaries, Ghidra projects, string
dumps from the game (bozkit's name dictionary stays in `~/.cache/bozkit`).

## Working with the user

- The user runs the game, Ghidra and VS Code; don't launch windows unless asked.
- Commit only with the user's approval of that commit; pushing is the user's job.
