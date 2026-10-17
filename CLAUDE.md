# CLAUDE.md

SDK for modding *Call of Duty: Black Ops Zombies* (Android 1.0.11) with the BOZ Redux client:
reverse engineering, the game definition, asset tools, mod templates and packaging. Siblings:
`../boz-redux` (the client: runtime, launcher, mod runtime) and the `gamedef/`
submodule (boz-redux-gamedef: symbols, reflection, events, console).

## Layout

- `gamedef/`: submodule. The SDK generates it; commit inside it, then bump the pointer here.
  The client pins it separately. A breaking change bumps `schema` in `gamedef/gamedef.toml`.
- `tools/ghidra/`: `s3e_to_elf.py`, `rtti_classes.py`, Ghidra Java scripts (run through the
  Ghidra MCP with absolute paths). Pipeline and conventions: `docs/contributing.md`.
- `tools/symbols/symbols.py`: Ghidra exports to gamedef TOML (`from-json`, `reflection`,
  `events`, `console`) and back (`to-json`).
- `tools/bozkit/`: shared Python SDK compiler and asset toolkit (`new`, `inspect`, `validate`,
  `build`, `install`, `package`, `extract`, plus `dump`, `set`, `save`, `settings`, `names`). Tests
  in `tools/bozkit/tests` use synthetic data only. Project guide: `docs/lua-mods.md`; formats:
  `docs/how-the-game-works.md`. `bozkit.desktop` is the optional PySide6 frontend (its look: `bozkit/desktop_style.py`, brand files as package data in `bozkit/branding/`) and must call the same
  compiler rather than maintaining its own serializers.
- `lib/boz/`: the **standard lib** (`boz.*`), the Lua abstraction layer mods use (player, fly,
  rounds, console, pause_settings, text, iwui, frontend, and helpers). Feature generics go here;
  mods only use them. Every public function has a `---` comment: `python3 tools/stdlib/generate_doc.py`
  regenerates `docs/standard-library.md` from them. Mods carry a copy as `scripts/boz` (plain files, so
  GitHub zips and Windows checkouts work); after changing `lib/boz`, copy it into the mod again.
- `mods/developer`: the reference mod (console overlay, cheats, noclip). Linked into the client's
  `mods/` for testing.
- `docs/`: a few large pages, one per big subject (each file's `#` title is a main section of
  the docs website; `##`/`###` headings split it). Add to an existing page unless the subject is
  really different. `docs/README.md` is the introduction and page list. Generated pages and their
  generators are listed in `docs/contributing.md`. `docs/internal/` is gitignored notes.
- `tools/navmesh/`: `boz-navmesh`, the native Recast helper bozkit runs to rebuild navmesh tiles
  (CMake; `tools/navmesh/third_party/recast` is the recastnavigation 1.6.0 submodule). Guide: `docs/map-editor.md, Navigation meshes`.
- `tools/destin/`: submodule for `dade` (`uv tool install dade`). Always pass `--no-delete` to
  `dade marmalade extract-dz`; it deletes the source archive by default.
- `re/` (gitignored): converted ELF, Ghidra project `re/ghidra/BOZ`, generated reports. Contains
  game code; never commit it.
- `game` (gitignored link to `../boz-redux`): the client's game root (`assets/`, `saves/`).
- `.mcp.json` (gitignored): Ghidra MCP config. Scripts need Ghidra started with
  `GHIDRA_MCP_ALLOW_SCRIPTS=1 /opt/ghidra/ghidraRun`.

Never commit game files: APK, `.dz`, extracted assets, converted binaries, Ghidra projects, string
dumps from the game (bozkit's name dictionary stays in `~/.cache/bozkit`).
