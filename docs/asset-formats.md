# Asset formats

How Call of Duty: Black Ops Zombies 1.0.11 stores its data, and how `tools/bozkit` reads and
writes it. Everything here was worked out from the game's own code. No game data is included in this repository.

## Where the files are

- **Packs:** the game's data is in two `.dz` packs (Marmalade derbh archives, extracted by
  `dade marmalade extract-dz --no-delete`). The client uses `blackops_etc.dz` (ETC textures) or
  `blackops_gles1.dz`.
- **Groups:** inside, almost everything is a resource group, a `.group.bin` (180 groups).
- **Loose files:** music (`blackops-music/*.mp3`, `deadops-music/*.mp3`), translations
  (`localisation/*.dat`), cvar defaults (`console.bin`) and the Flash menu movie
  (`fe_v4_cs4_swf.bin`).

A map is split across several groups, for example Kino der Toten:

| Group | Contents |
| --- | --- |
| `levels/kino/kino.group.bin` | the level entry (`CLevel`, `CArea`) |
| `kino_statics` | static geometry |
| `kino_sectors` | visibility sectors and portals |
| `kino_dynamics` | placed entities: doors, perk machines, the box, traps |
| `weapons_kino`, `arms_kino`, `weapon_projectiles_kino` | the map's weapons and first-person arms |

## Resource group (`.group.bin`)

```
header[6]                  0x3d, padding, reserved u16
repeat:
    u32 section_hash       IwHashString of the section name; 0 ends the list
    u32 size               payload length + 4
    payload
```

| Section | Payload |
| --- | --- |
| `ResGroupMembers` | the group name |
| `ResGroupResources` | the resources, by class |

Layout of the `ResGroupResources` payload:

```
u32 type_count
type_count x:
    u32 class_hash, u32 count, u8 names_omitted, u8 has_size
    count x: u32 size, [u32 name_hash], u32 in_group_hash, body
```

The 1.0.11 ETC pack uses 63 resource classes. By size, most are `CIwTexture` (about 300 MB) and
`CIwModel`. `tools/destin` (dade) provides extraction and read-side conversions; `bozkit` owns
BOZ-specific lossless writing and editing.

## Writable-format status

### Material rendering (GLES1 path)

`Rendering_ApplyMaterialGLES` (`0x4a2b74fc`) applies a `CIwMaterial` to the fixed-function
pipeline. Its flags word (runtime `+0x10`) selects:

| Bits | Meaning |
| --- | --- |
| 16–18 | Framebuffer blend: 0/5 opaque, 1/4 `SRC_ALPHA, ONE_MINUS_SRC_ALPHA`, 2 `SRC_ALPHA, ONE`, 3 `ZERO, ONE_MINUS_SRC_COLOR` |
| 19–21 | Texture stage 1 environment: 0 modulate, 1 decal, 2 add, 3 replace, 4 `GL_BLEND`, 5 modulate ×2, 6 modulate ×4 (`GL_COMBINE` with `GL_RGB_SCALE`) |
| 22–24 | Stage-0 variant: 4 replaces RGB with the primary colour; 5 overrides blending with `ZERO, SRC_COLOR` |
| 25–28 | Explicit alpha-test function; the reference is runtime byte `+0x17` |
| 2 | `GL_SMOOTH` (set) or `GL_FLAT` shading |

- **Stage 0:** texture slot 0 is modulated by the primary colour, which is the vertex colour
  (`CIwModelBlockCols`) when the model has one.
- **Stage 1:** texture slot 1 is sampled with the second UV set (`CIwModelBlockGLUVs2`). In
  shipped maps it is a baked lightmap atlas: in the Zombies levels, 1,849 materials have one, 825
  using mode 0 and 1,024 using mode 5 (×2).
- **Alpha test:** blend mode 5 additionally enables `GL_ALPHA_TEST GREATER 0.75` when the primary
  texture's runtime flags (`+0x34`) contain bit 3.

Models without a lightmap carry real baked lighting in their vertex colours. A preview that shows
only the primary texture is far too bright.

The Blender preview implements stages 0 and 1, the blend modes and the mode-5 cutout. It does
everything in the game's display encoding and decodes the result once, under a Standard view
transform. It does not implement the bits 25–28 alpha functions, the stage-0 variants, or the dot3
path that swaps the stages when normal mapping is active.

### Texture coordinates

`CIwModelBlockGLUVs` and `CIwModelBlockGLUVs2` share one layout: a u16 render-vertex count at
block `+6`, then one signed 16-bit (u, v) pair per render vertex from `+10`, in 1/4096 units. They
follow the GL convention: v = 0 addresses the first stored texel row. Readable textures confirm
this. On the tutorial's "WISH too OFTEN" sign, its posters and its building facade, the geometric
top of the surface has v = 0. Tools that display images upright must mirror v (`1 - v`).

### Raw texture formats

Uncompressed textures store A, R, G, B from the most significant bits of a little-endian word:
format `0x0e` is 32-bit (bytes B, G, R, A) and `0x05` is its 16-bit 4444 twin. The tutorial ships
some textures as `0x0e` and Kino ships the same textures as `0x05`, with matching values. For
example, the graffiti sign's alpha-0 red background is `00 00 ff 00` in one and `0x0f00` in the
other. Most alpha-tested and blended map art uses these formats, so reading `0x05` as RGB565 turns
red art green and shows transparent areas as solid colour.

### Cooked texture payloads

In the supported cooked ETC1/DXT1 layout, the u32 at body offset 35 is the mip
count, followed by width and height at 39 and 43. The size table starts at 47
and reserves twelve u32 slots, with one populated size per mip. Native constructor
`0x4a24c7b4` allocates a fixed `0x48`-byte platform header and copies the first mip
immediately after it. That header starts at body offset 23, so base-level blocks
start at **95**, not 79 or immediately after the populated size entries. The decoder checks the
base block size and complete mip payload bounds. Synthetic tests exercise 7,
8, 9 and 11 levels in both formats; these differing table lengths also occur
in the private tutorial group. The old incorrect offset decoded table words as
image blocks and rejected its seven-level texture altogether.

### Resource coverage

| Resource | Parse/write status | Editing status |
| --- | --- | --- |
| Resource groups | Complete | Resources may be replaced without changing unknown sections or other bodies |
| Reflected resources | Complete | Named typed properties, including nested objects and lists |
| Entity specifications | Complete | Components, children, reflected fields; collision payload retained raw |
| `CIwMaterial` | Complete | Compact records contain flags and one primary texture reference; full records contain four texture slots, packed colours and a shader-technique reference; unknown auxiliary data retained |
| `CIwModel` | Static GL triangle geometry, render-vertex remaps, vertex colours, both UV sets, explicit primitive material indices, terminal material references, and lossless preservation | glTF/Blender export; source-backed position and UV edits retain unknown blocks; additional primitive types remain |
| `CIsNavMesh` | Complete for shipped resources | Recast agent/build settings; Detour tiles retained raw |
| `CIwTexture` | Row-major ARGB4444 (`0x05`) and 32-bit ARGB (`0x0e`, bytes B, G, R, A) plus cooked ETC1 and DXT1 mip payloads | PNG import for writable raw formats; raw and cooked formats decode for Blender/material previews |
| `CIsPortal` | Complete | Vertices, plane, and connected sector names |
| Collision triangle meshes | Complete for Zombies maps | Vertices, indices, per-triangle materials, glTF; the embedded Bullet shape is updated to match |
| `CIsNavMeshConnection` | Complete | Endpoints, rotation, and raw offset-named settings |

Run `bozkit corpus` on private extracted groups for exact machine-readable counts. A corpus report
contains filenames, counts, capabilities, and SHA-256 hashes, never resource bodies. Excluding
out-of-scope Dead Ops paths, all 128 Zombies groups and 25,415 resources currently round-trip
byte-identically across 57 resource classes. Structured codec coverage is full for all 7,097
materials, 3,268 entity specs, 198 portals, 8 navigation connections, 5 collision meshes, and 4
navmeshes. All 3,562 model bodies are preserved byte-identically. Static model export was visually
validated with the named `colt45` resource, including its planar center-offset positions,
render-vertex remap, UVs, and all material-indexed triangle lists. `CIwModelBlockCols` stores either
four component planes or one compact grayscale byte per render vertex; the latter expands to opaque
RGBA at load. BGRA8888 texture export was visually
validated with the named `main_menu_logo` resource. ETC1 and DXT1 decoding was visually validated
against the same tutorial floor material from the corresponding platform archives.

## Hashes

Names are stored as `IwHashString(name)`: `h = 5381; h = h * 33 + c` for each byte, with A–Z
lowercased, as a 32-bit value. Resource names are usually not stored. `bozkit names` builds a
local dictionary from strings in your own game files to show them.

## Reflected data (`LFER` blobs)

Gameplay data is stored as property blobs that the engine's reflection system reads back by name.
The field names and types are in `gamedef/reflection/boz-1.0.11.toml`.

```
"LFER"                     tag ("REFL" reversed)
u32 class_hash
u32 size                   bytes from the tag; 0 = empty placeholder (16 bytes)
u32 count                  records (authoritative; a few shipped blobs have a stale size)
count x:
    u32 owner_hash         class declaring the field
    u32 type_hash          "float", "unsigned int", "CIwFVec3", ...
    u32 1
    u32 name_hash          "m_ZombieCount"
    u32 1
    u32 value_size
    value                  raw; struct fields hold a nested blob, strings end with 0
```

**Reflected resources** (`CWave`, `CDORound`, `CLevel`, `CZombieConfiguration`,
`CScoreConfig`, ...): `u32 blob_size` followed by the blob.

**Entity specs** (`CIsEntitySpec`: weapons, pickups, map objects) are recursive:

```
u32 component_count
component_count x:
    u32 spec_class         CIsComponentSpec, or CIsCollisionMeshSpec
    u32 reserved
    u32 component_type     CPlayerWeapon, CHealth, CPerk, CMysteryBox, CIsTransform, ...
    u32 size
    blobs filling size     usually one blob
    [collision data]       CIsCollisionMeshSpec only: Bullet shape, triangle mesh,
                           per-triangle material flags
u32 child_count
child_count x: u32 class (CIsEntitySpec), u32 reserved, entity spec (this layout)
```

For Zombies content, bozkit decodes and re-encodes all 3,268 entity specs and 1,040 reflected
resources byte-for-byte.

## Navigation meshes (`CIsNavMesh`)

Zombie pathing uses Recast/Detour.

- **Layout:** each `CIsNavMesh` body begins with an 80-byte Recast build configuration and a
  40-byte Detour mesh-set header. Each tile then has an 8-byte reference/size header followed by
  Detour version 7 tile data (`DNAV`) with BOZ's widened 40-byte polygons and off-mesh
  connections (see [navigation meshes](navmesh.md)). The settings begin with cell size, cell height,
  agent height, agent radius, max climb and max slope; Zombies maps commonly use
  0.1 / 0.15 / 1.5 / 0.4 / 0.4 / 50°.
- **Where:** Zombies map `*_statics` groups hold one or more tiles.
- **Off-mesh links:** window and barricade climbs are not Detour links. They are separate
  objects (`CIsNavMeshConnection` resources, `CJumpConnection` components).
- **Agents:** a zombie moves as a crowd agent (`CIsCrowdAgent`: `m_maxSpeed`,
  `m_maxAcceleration`, `m_separationWeight`, `m_obstacleAvoidanceQuality`, `m_canClimbBarricades`).

Existing Recast/Detour tools can read the tile data, which matters for map editing later.

`CIsNavMeshConnection::Serialise` at `0x4a0a4e95` confirms its packed 55-byte field order:

```text
vec3 start, vec3 end, quat rotation
u8 field_0x50, unaligned u32 field_0x54
float field_0x48, float field_0x4c
bool field_0x5c, bool field_0x5d
```

The offset-based names are intentional until behavior proves their semantics.

## Visibility portals (`CIsPortal`)

```text
u32 vertex_count
vertex_count * vec3 vertices
vec3 plane_normal, float plane_distance
u32 front_sector_hash, u32 back_sector_hash
cstring front_sector_name, cstring back_sector_name
```

The hashes are regenerated from the sector names when written.

## Collision meshes

`CIsCollisionMeshSpec` appends this data after its reflection blobs:

```text
u32 bullet_shape_size, u8 bullet_shape[bullet_shape_size]
u32 vertex_count, u32 index_count, u32 material_name_count
material_name_count * cstring material_name
vertex_count * vec3 vertices
index_count * u32 indices
(index_count / 3) * u8 triangle_material
```

The triangles are stored twice, and the game uses both copies. `CIsCollisionMeshSpec::Serialise`
(`0x4a0527ec`):

- loads `bullet_shape`, a complete Bullet 2.78 file (`BULLETf_v278`: 32-bit pointers,
  little-endian), through `btBulletWorldImporter` and keeps collision shape 0 as the physics shape;
- builds its own bounding interval hierarchy for ray casts (`Collision_BuildBIH`, `0x4a05184c`,
  limited by the cvars `BIHMaxDepth` and `BIHMaxSingled`) from the plain arrays that follow.

In every shipped map the two copies are identical. Neither one stops the player from walking:
`CPlayerController::FixedStep` moves the player on the Detour navmesh (`Player_MoveOnNavMesh`,
`Nav_FindNearestPoly` with extents 0.1 × 3 × 0.1 m, `Nav_MoveAlongSurface`, `Nav_GetPolyHeight`;
world positions are divided by 100). Collision edits therefore change what bullets and other ray
casts hit, while walkable space and floor height follow the navmesh. A test with a raised collision
floor confirmed this: shots hit it and the player walked through it.

The Bullet file's chunks are:

| Chunk | Contents |
| --- | --- |
| `SHAP` | `btTriangleMeshShapeData` (60 bytes), shape type 21, one mesh part |
| `ARAY` | `btMeshPartData` (32 bytes): vertex/index array pointers, triangle and vertex counts |
| `ARAY` | `btIntIndexData` indices |
| `ARAY` | `btVector3FloatData` vertices (16 bytes each) |
| `QBVH` + `ARAY`s | the quantized BVH and its nodes and subtree headers |
| `DNA1` | Bullet's type catalogue |

When collision geometry changes, `bozkit` (`bullet.py`) rewrites the vertex and index chunks and
the part counts, and clears the shape's `m_quantizedFloatBvh` pointer. The game's
`btBulletWorldImporter::createBvhTriangleMeshShape` (`0x4a02020e`) then builds a fresh BVH at load
instead of trusting the stale one. Unchanged geometry keeps every byte.

The world collision mesh is cooked from the render geometry: in Kino 64,420 of its 78,864
triangles have all three vertices on vertices of exactly one placed model (133 of 607 models
contribute). Editors can therefore treat those triangles as belonging to that model.

Collision vertices are in the local space of the entity's `CIsTransform`. Call of the Dead and one
Ascension collision entity have a non-zero position.

## Entity transforms and hierarchy

`CIsTransform` component blobs store any of `m_localPosition` (`CIwFVec3`), `m_localRotation`
(`CIwFQuat`, xyzw) and `m_localScale` (`CIwFVec3`); a missing field is the identity. Scales such as
1/16 and 1/64 occur. An entity spec's children are positioned relative to their parent, and 129
renderable children exist in the Zombies levels. Reflection reads properties by name, so `bozkit`
adds a missing field when an edit needs it.

## Entity links and areas

Gameplay entities refer to each other through `CIsNamed` names (IwHashString of the name). These
field names are missing from the reflection export and were recovered by hashing the game's
strings:

| Component | Field | Holds |
| --- | --- | --- |
| `CPerk`, `CDoor`, `CPackAPunch`, `CTrapSwitch`, `CTeleporter`, `CTVScreen`, `CProjectorScreen`, `CTurret`, `CTeleportMainframe` | `powerSwitch` (u32) | the power switch |
| `CTrapSwitch` | `traps` (list) | the traps it fires |
| `CDoor` | `m_Siblings` (list) | doors that open with it |
| `CDoor` | `m_AreasUnlock` (list) | `CArea` resource names it unlocks |
| `CSpawnPoint` | `users` (list) | AI configuration names allowed to spawn (`zombie_kino`, `zombie_dog`) |
| `CPerk` | `m_perkJingle` (string) | the perk's music sting |
| `CEasterEgg` | `m_GroupName` (string) | its sound |

Lists are serialised as `u32 count` followed by the values. A `CArea` resource is a zone:
`m_SpawnPoints`, `m_PerkMachines`, `m_GerschTeleportPoints`, `m_Shortcuts` and `m_Locators` list
entity names, and its resource name matches the visibility sector of the same name. `CLevel`
names the `m_StartingArea`, `MysteryBoxAvoid`, `m_zombiesConfigurations`, `m_StartingWavesSP/MP`,
`m_PerksAvailable` and `m_Achievements`. Kino has 9 areas; its 137 links all resolve.

## How levels create entities

A level has no list of its entities. `Level_Load` (`0x4a1aae4c`) loads `<level>_sectors`
(portals and occluders), then `<level>_statics`, and `Entity_CreateAllFromGroup` creates an
entity for every `CIsEntitySpec` resource in it. `Sector_LoadGroup` (`0x4a230d3c`) does the same
for each room's `*_shared` group; resources whose names end in `_shell`, `_inside_shell`,
`_mergemodel`, `_details`, `_decals` (and singular or `_inside_` variants) become the room's shell,
detail and decal sets. `Entity_CreateFromSpec` gives each entity a fresh runtime id, creates the
spec's children recursively and applies every component spec. Adding a spec resource to a group
therefore adds an entity, and removing one removes it. Entities are found by their `CIsNamed`
name hash, so copies of referable entities need unique names. Entity spec resources store no
name, only their in-group hash; a new one only needs a hash unique within its group.
`CIsEntitySpec_Design_Door`, `_PerkMachine`, `_Art_Prop` and similar class names are factory
aliases of `CIsEntitySpec` left over from the authoring tool.

## Maps across groups

Placements reference resources by name hash, not by group. Kino's `kino_statics` places 73 objects
using 23 models from `kino_dynamics` and `ingame`. Each room's `*_shared` group holds that room's
models, materials, portals, occluders and light boxes, while many of its textures live in other
groups. Editors must resolve references across all of a level's groups plus `ingame`, and write
each edit back to the group that owns the resource.

## Saves (`.i3d`)

Saves are written with IwSerialise (`CSaveManager::Serialise`). Every file begins:

```
u32 version              0x493e1 game saves, 0x493e0 the others (1.0.11)
u32 checksum             Adler-32 of the whole file with this field zeroed
```

Game save (`N_save_game.i3d`):

```
cstring level            "kino"
u32 dynamic_count        entities spawned at run time (DynamicEntityData section)
u32 section_count
section_count x: u32 owner (object name hash or class hash), u32 class_hash, u32 size, data
```

- **Owners:** every placed object saves its own section (doors, barricades, traps, perk machines,
  the box, teleporters), and so does every system (`CScoreManager`: current and total score;
  `CWaveManager`; `player_weapon`; `CPlayerController`).
- **Section data:** many sections are reflection blobs (decoded by name); the others are 32-bit
  word streams.

`save_settings.i3d` holds the options from `CSaveManager` +0xf8, in this order (see
`bozkit/save.py`):

- sensitivity X/Y, detail level, brightness;
- invert Y, left-handed controls, auto-aim;
- music and sound-effects volume, control method, accelerometer calibration;
- the last level played.

Strings in these files end with a zero.

## bozkit

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
.venv/bin/bozkit extract ../boz-redux/original/obb/blackops_etc.dz /tmp/boz-etc --kind dz
.venv/bin/bozkit corpus /tmp/boz-etc --exclude '*deadops*' -o /tmp/boz-etc-corpus.json
.venv/bin/bozkit dump /tmp/boz-etc/ingame/levels/kino/kino.group.bin -o /tmp/kino.json
.venv/bin/bozkit texture-export /tmp/boz-etc/frontend/frontend.group.bin \
  main_menu_logo /tmp/main_menu_logo.png
.venv/bin/bozkit model-export /tmp/boz-etc/ingame/weapons/weapons_kino.group.bin \
  colt45 /tmp/colt45.gltf
.venv/bin/python -m unittest discover tools/bozkit/tests
```

`dump` writes every reflected resource and entity spec with named fields and typed values. `set`
changes one field and writes a new group. Complete edited game files are valid project inputs and
may be built into local test mods. Official BOZ repositories must not track those files;
distribution validation warns when their game-derived provenance is recorded.
