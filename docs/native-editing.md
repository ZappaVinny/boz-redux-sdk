# Native asset editing

`bozkit` edits complete native resources and writes a new group; it never overwrites the input.
Unknown group sections, resource bodies, model metadata, material bytes, and navigation tile data
are retained unless a command explicitly rebuilds that resource.

The commands below use the 1.0.11 ETC archive already present in this workspace. Keep the extracted
files and generated edits outside the repositories:

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
.venv/bin/bozkit extract ../boz-redux/original/obb/blackops_etc.dz /tmp/boz-etc --kind dz
.venv/bin/bozkit corpus /tmp/boz-etc --exclude '*deadops*' -o /tmp/boz-etc-corpus.json
```

The corpus command must finish successfully with `all_byte_identical: true`. Its `classes` array
shows full, partial, or preserve-only codec coverage for every resource class encountered.

For visual editing of complete groups, continue with the
[Blender existing-map guide](blender-existing-maps.md).

## Models and glTF

Export the named Colt M1911 model and open the resulting glTF in Blender:

```bash
.venv/bin/bozkit model-export \
  /tmp/boz-etc/ingame/weapons/weapons_kino.group.bin colt45 /tmp/colt45.gltf
```

The exporter decodes center-offset component-planar positions, the unique-to-render vertex remap,
UVs, and GL triangle lists. Model bodies and unknown blocks still round-trip byte-identically.
Source-backed geometry edits require unchanged topology. Models using other primitive block types
or multiple primitive groups are rejected or remain preservation-only rather than being guessed.

## Materials

Inspect a material and change its flags or a texture hash by zero-based slot:

```bash
.venv/bin/bozkit material-dump \
  /tmp/boz-etc/ingame/ingame.group.bin 0x61ec0f93 -o /tmp/material.json
.venv/bin/bozkit material-set \
  /tmp/boz-etc/ingame/ingame.group.bin 0x61ec0f93 \
  --texture 0=0x12345678 -o /tmp/ingame-material-test.group.bin
```

The material writer retains unknown header and trailer bytes.

## Navigation

Inspect the tutorial map's Recast settings and create a copy with a different agent radius:

```bash
.venv/bin/bozkit nav \
  /tmp/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x021eeaf7
.venv/bin/bozkit nav \
  /tmp/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x021eeaf7 \
  --set agent_radius=0.5 -o /tmp/tutorial-nav-test.group.bin
```

The editable settings are `cell_size`, `cell_height`, `agent_height`, `agent_radius`,
`agent_max_climb`, and `agent_max_slope`. Detour tiles remain byte-identical.

Inspect or translate a navigation connection from the shared in-game group:

```bash
.venv/bin/bozkit nav-connection \
  /tmp/boz-etc/ingame/ingame.group.bin 0x67b09c42
.venv/bin/bozkit nav-connection \
  /tmp/boz-etc/ingame/ingame.group.bin 0x67b09c42 \
  --translate 0 0 10 -o /tmp/ingame-nav-connection-test.group.bin
```

Fields whose behavior is not yet proven retain offset-based names in output and `--set`; this keeps
the format writable without presenting guesses as stable semantics.

## Portals

Inspect a tutorial visibility portal or translate it while retaining its sector relationship:

```bash
.venv/bin/bozkit portal \
  /tmp/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x332aca12
.venv/bin/bozkit portal \
  /tmp/boz-etc/levels/tutorial/tutorial_statics.group.bin 0x332aca12 \
  --translate 0 0 10 -o /tmp/tutorial-portal-test.group.bin
```

`--front` and `--back` change the connected sector names and regenerate their cached hashes.

## Collision

Export and losslessly re-import the tutorial map's collision triangles:

```bash
.venv/bin/bozkit collision-export \
  /tmp/boz-etc/levels/tutorial/tutorial_statics.group.bin 0xebf33ad1 \
  /tmp/tutorial-collision.gltf
.venv/bin/bozkit collision-import \
  /tmp/boz-etc/levels/tutorial/tutorial_statics.group.bin 0xebf33ad1 \
  /tmp/tutorial-collision.gltf -o /tmp/tutorial-collision-test.group.bin
```

The default import requires unchanged vertex and index counts and keeps the material names and
per-triangle material bytes. `--rebuild-mesh` allows topology changes; new triangles receive
material byte zero when the old material array no longer fits. Either way, the embedded Bullet
physics shape is updated to the same triangles, and its stale BVH is dropped so the game rebuilds
it at load (see [collision meshes](asset-formats.md#collision-meshes)).

## Textures

Export the recognizable red main-menu logo:

```bash
.venv/bin/bozkit texture-export \
  /tmp/boz-etc/frontend/frontend.group.bin main_menu_logo /tmp/main_menu_logo.png
```

Row-major ARGB4444 (`0x05`) and 32-bit ARGB (`0x0e`) textures can be exported and replaced. PNG import
preserves a source texture's unknown header fields and native pixel format. Cooked ETC1 and DXT1
textures, which make up most map textures, decode for previews (Blender) but cannot be written yet.
Other layouts fail rather than producing a plausible-looking corrupt image.

Complete edited groups can be placed under an SDK project's `assets/` tree and built normally.
They may be used for local testing, but must never be committed to an official BOZ repository.
