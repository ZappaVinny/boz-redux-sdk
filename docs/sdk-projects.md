# SDK projects

An SDK project is the editable source for one BOZ Redux mod. It can contain Lua, complete or
modified game assets, and files made from scratch. Building it creates the folder the client loads;
packaging it creates the same folder in a reproducible ZIP.

The SDK never silently removes game-derived files. The development profile accepts them. The
distribution profile warns when a file has been marked as game-derived so the author can decide
what they are permitted to share. Game assets and derived files must not be committed to the
official BOZ Redux repositories.

## Install the tools

From the SDK checkout:

```bash
python3 -m pip install -e .
# Include the desktop application:
python3 -m pip install -e '.[desktop]'
```

The installed commands are `bozkit` and `boz-sdk`. Without installing, run the CLI from
`tools/bozkit` as `python3 -m bozkit`.

## Create and build a project

```bash
bozkit new my-mod --id my_mod --name "My mod" --author "Your name"
bozkit inspect my-mod
bozkit validate my-mod
bozkit build my-mod
bozkit install my-mod --client ../boz-redux
bozkit package my-mod
```

`build` writes `build/<mod id>/`. `package` writes
`build/<mod id>-<version>.zip`. Builds contain a `boz-build.json` report with the project schema,
profile, dependencies, provenance entries, warnings, and SHA-256 of every output file. ZIP paths,
timestamps and ordering are normalized so identical inputs produce identical archives.

Installation refuses to replace an existing mod unless `--force` is passed.

## Project layout

```text
my-mod/
  boz-project.toml
  scripts/
    main.lua
  assets/
  build/                 generated and ignored
```

The initial project manifest is:

```toml
schema = 1

[mod]
id = "my_mod"
name = "My mod"
version = "0.1.0"
author = "Your name"
game = "1.0.11"
description = ""

[paths]
scripts = "scripts"
assets = "assets"

[build]
include_standard_library = true
```

With `include_standard_library`, the compiler copies the SDK's current `lib/boz` into
`scripts/boz`. The editable project does not need to carry duplicate library files.

Dependencies are recorded in the build report and generated manifest:

```toml
[[dependencies]]
id = "another_mod"
version = ">=0.2.0"
```

The current client does not enforce dependency versions yet. Recording them now makes projects
forward-compatible with that client capability.

## Asset provenance and validation

Provenance is optional and informational:

```toml
[[provenance]]
path = "assets/kino_statics.group.bin"
kind = "game-derived"
note = "Edited from the user's installed 1.0.11 data"
```

Supported conventions are `authored`, `game`, `game-derived`, `extracted`, `generated`, and
`unknown`; custom values are retained. Distribution validation warns for `game`, `game-derived`
and `extracted`. It does not fail the build or omit the file.

```bash
bozkit validate my-mod --profile development
bozkit validate my-mod --profile distribution
```

## Extract installed assets

The extraction command delegates to `dade` and always passes `--no-delete` for DZ archives:

```bash
bozkit extract blackops_etc.dz extracted/
bozkit extract kino_statics.group.bin kino_statics/ --kind group
```

The original source archive remains in place.

## Desktop application

Run `boz-sdk`. **Create Project** selects an empty destination folder and collects the mod id,
display name, author, version and description. It displays the fixed game version, 1.0.11; projects
targeting any other version are rejected. The application creates the complete project there:
`boz-project.toml`, `scripts/main.lua`, `assets/` and `.gitignore`. **Open Existing**
selects a project that already has a manifest. The same application validates, builds and installs
the project through the shared compiler. Asset editors and Blender integration will use this same
project model rather than implementing separate serializers.
