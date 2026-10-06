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

| Resource | Parse/write status | Editing status |
| --- | --- | --- |
| Resource groups | Complete | Resources may be replaced without changing unknown sections or other bodies |
| Reflected resources | Complete | Named typed properties, including nested objects and lists |
| Entity specifications | Complete | Components, children, reflected fields; collision payload retained raw |
| `CIwMaterial` | Complete | Flags and texture references; unknown bytes retained |
| `CIwModel` | Static GL triangle geometry and lossless preservation | glTF export; source-backed edits retain unknown blocks; additional primitive types remain |
| `CIsNavMesh` | Complete for shipped resources | Recast agent/build settings; Detour tiles retained raw |
| `CIwTexture` | Row-major RGB565 and BGRA8888 | PNG export/import; unsupported packed, compressed, or swizzled formats fail closed |
| `CIsPortal` | Complete | Vertices, plane, and connected sector names |
| Collision triangle meshes | Complete for Zombies maps | Vertices, indices, per-triangle materials, glTF; Bullet metadata retained raw |
| `CIsNavMeshConnection` | Complete | Endpoints, rotation, and raw offset-named settings |

Run `bozkit corpus` on private extracted groups for exact machine-readable counts. A corpus report
contains filenames, counts, capabilities, and SHA-256 hashes, never resource bodies. Excluding
out-of-scope Dead Ops paths, all 128 Zombies groups and 25,415 resources currently round-trip
byte-identically across 57 resource classes. Structured codec coverage is full for all 7,097
materials, 3,268 entity specs, 198 portals, 8 navigation connections, 5 collision meshes, and 4
navmeshes. All 3,562 model bodies are preserved byte-identically. Static model export was visually
validated with the named `colt45` resource, including its planar center-offset positions,
render-vertex remap, UVs, and triangle list. BGRA8888 texture export was visually validated with
the named `main_menu_logo` resource.

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
  standard Detour version 7 tile data (`DNAV`). The settings begin with cell size, cell height,
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

The five Zombies map collision resources use this layout. `bozkit` edits triangle geometry and
material assignment while retaining the serialized Bullet shape byte-for-byte.

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
