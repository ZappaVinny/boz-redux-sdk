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

The 1.0.11 packs use 63 resource classes. By size, most are `CIwTexture` (about 300 MB) and
`CIwModel`. `tools/destin` (dade) converts textures, materials, models and fonts.

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

bozkit decodes and re-encodes all of it byte for byte: every group, all 4,344 entity specs and
all 1,128 reflected resources in both packs.

## Navigation meshes (`CIsNavMesh`)

Zombie and Dead Ops pathing uses Recast/Detour.

- **Layout:** each `CIsNavMesh` body is 128 bytes of Recast build settings, followed by standard
  Detour (version 7) tile data (`DNAV`). The settings start with cell size, cell height, agent
  height, agent radius, max climb and max slope; for example 0.3 / 0.2 / 1.5 / 0.5 / 0.9 / 45°
  in Dead Ops, and 0.1 / 0.15 / 1.5 / 0.4 / 0.4 / 50° in the Zombies maps.
- **Where:** Dead Ops arenas hold one tile; the Zombies maps (`*_statics`) hold several.
- **Off-mesh links:** window and barricade climbs are not Detour links. They are separate
  objects (`CIsNavMeshConnection` resources, `CJumpConnection` components).
- **Agents:** a zombie moves as a crowd agent (`CIsCrowdAgent`: `m_maxSpeed`,
  `m_maxAcceleration`, `m_separationWeight`, `m_obstacleAvoidanceQuality`, `m_canClimbBarricades`).

Existing Recast/Detour tools can read the tile data, which matters for map editing later.

## Dead Ops data

- **Rounds:** Dead Ops runs on 42 `CDORound` resources (`deadops-ingame.group.bin`). Each picks the
  arena (`environment`, for example `lv1_island`), lightmap variant, music track, sun direction
  and colour tint.
- **Hordes:** the enemies come from `CDOZombieSpawner` hordes, a list of `CDOZombieConfig`. Each
  enemy type has `name`, `roundUnlocked`, `baseSpawnRate`, `spawnRateIncrease`, `maxSpawnRate`
  and `miniboss`.

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
cd tools/bozkit
python3 -m bozkit names ../../game/assets/boz.s3e.unpacked GROUP.group.bin ...   # optional, local names
python3 -m bozkit dump GROUP.group.bin -o group.json [--class CWave]
python3 -m bozkit set GROUP.group.bin colt45 m_clipSize 12 --component CPlayerWeapon -o NEW.group.bin
python3 -m bozkit save ../../game/saves/data-etc/1_save_game.i3d -o save.json
python3 -m bozkit settings ../../game/saves/data-etc/save_settings.i3d --set sensitivity_x=1.5 -o NEW.i3d
python3 -m unittest discover tests
```

`dump` writes every reflected resource and entity spec with named fields and typed values. `set`
changes one field and writes a new group, which you can test by putting it in a mod's `assets/`
folder. Edited game files are still the game's files: to share a change, make it in code as the
file loads (`assets.patch`, see [making-mods.md](making-mods.md)).
