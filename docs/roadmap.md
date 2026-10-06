# SDK roadmap

The SDK is becoming a Lua-first development suite for Zombies: a shared compiler, desktop project
manager and Blender add-on that edit existing maps first, then create complete new maps. Dead Ops
modding and LAN co-op are not part of this work.

## Architecture boundary

| Layer | Owns |
| --- | --- |
| Client | Universal facilities every mod can use: loading, Lua, hooks, files, input, rendering and diagnostics |
| Standard library (`boz.*`) | Safe domain APIs that combine the game's internal systems into concepts such as player, weapons and world |
| Mods | Concrete gameplay, maps, objectives, settings and menus built from those abstractions |

A missing feature moves downward only when it is reusable: mod behavior becomes a standard-library
API when many mods need it; client code is added only for universal runtime infrastructure.

## Phases

1. **Project foundation:** versioned projects, validation, deterministic builds, installation,
   packaging, compatibility metadata and the desktop shell.
2. **Writable formats:** native textures, materials, models, entities, collision, sectors, portals
   and navigation, with lossless preservation of unknown data.
3. **Existing-map Blender tools:** import, edit, validate and export map content through the shared
   compiler.
4. **Lua platform:** world, entity, weapon, interaction, navigation, audio, asset and debugging APIs,
   plus generated editor annotations.
5. **Custom-map MVP:** generate and register a complete Zombies map whose gameplay lives in Lua.
6. **Full suite:** skeletal models, animations, weapons, effects, audio, localization, UI,
   lightmaps, migrations and compatibility guarantees.

The full 64-bit runtime rewrite waits until the custom-map MVP. A bounded design and benchmark
prototype may start after the existing-map editor, but project, package, gamedef and Lua interfaces
must remain independent of host bitness.

## Assets

Local projects and packages may contain extracted, complete or modified game assets. Distribution
validation warns about recorded game-derived provenance but does not block builds. Game data and
derived assets must never be committed to official project repositories.

## Phase gates

Each phase ends in a tested, documented, buildable state. Before requesting commit approval, the
assistant provides practical commands and workflows the user can run to exercise the new features,
what successful behavior looks like, and where to find logs or build output. The phase's diffs,
automated results and proposed per-repository commit messages are then presented for explicit
approval. The assistant never commits, pushes, tags or publishes automatically. Phases 1–4 are
development milestones, not public SDK releases; the first preview can be considered only after
the custom-map MVP passes its acceptance tests.
