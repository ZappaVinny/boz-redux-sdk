# New levels

How the game finds and loads a level, and what a level it doesn't ship needs. `bozkit.levels`
writes these files; the Blender add-on's **Run new level test** button uses it. This work is
experimental: the first goal is proving that the game loads a level it doesn't ship.

## How a level is loaded

`StartLevel <name>` (front-end console, `FrontEnd_StartGame`) and the menus send
`CEventStartGame` with the level name. The game does not check the name against a list of levels.
`CLevelManager+0x55` holds it, and `StartingLevel` (default `kino`) is used when it is empty.

`CGameStateIngame::vf2` then:

1. Loads the loading screen: the `CResolutionSpecificString` named `loading-<name>` in `fixed`
   gives the screen's group per resolution (`LoadingScreen_GetGroupPath`). **If it is missing,
   the game crashes** (`CIwResManager_LoadGroup` copies a null path).
2. Loads `ResConfig_InGame` with four groups:
   - `ingame/sound/snd_player_<character>`;
   - `ingame/weapons/weapons_<name>`;
   - `ingame/characters/arms/arms_<name>`;
   - `levels/<name>/<name>`.

   `tutorial` uses Kino's weapons and arms.
3. `LevelManager_BindLevel` takes the `CLevel` named `<name>` from the group `<name>` or its
   children.

`CGameStateIngame::Enter` then runs `Level_Load`:

- `<name>_sectors` is optional. It holds rooms, portals and occluders.
- `<name>_statics`: every `CIsEntitySpec` in it becomes an entity.
- `LevelManager_SpawnPlayers` spawns the players at `spawn_player_<n>`.
- The navmesh is the `CIsNavMesh` named `NavMesh`.

`StartFirstWave` queues the `CLevel`'s starting wave (default `wave1`).

Level names are also compared in code for the following:

| Name | What changes |
|------|--------------|
| `callofthedead` | George Romero, outdoor sectors, intro sounds |
| `ascension` | Characters and sound list (`MPCharactersAsce`, `CharacterSoundListAsce`), power-on effects |
| `kino` and `proto` | Teleporter intro sound and `start_kino` |
| `tutorial` | Tutorial manager |

Any other name gets the Kino defaults. The `DeathMachineLevels` and `LightningBoltLevels` cvars
list which levels allow those pickups.

## Groups

A group (`.group.bin`) has these sections:

- **Members**: its name and a u32 flags field (1 marks a shared group).
- **Children** (`0x3b495dc0`): a u8 count, then for each child its path (`levels/kino//kino_statics.group`), `\0`, 8 flag bytes, and the
  hash of the child group's name.
- **ResGroupResources**.

Loading a group loads its children first. A new level can therefore reuse shipped groups by
listing them as children, without copying them; its rooms are reused this way. Some groups are
looked up by name and only their own resources are read, so those must be renamed copies:

- `weapons_<name>`: the player's weapons. Without them the starting `colt45` is missing, and the
  game crashes writing to a null weapon.
- `weapon_projectiles_<name>`: the fallback, `weapon_projectiles_common`, isn't shipped.

The client finds a mod's files by full path, then by base name, so a new level's files go flat
into the mod's `assets` folder.

## Kino copy (`levels.clone_level`)

| File | What it is |
|------|------------|
| `fixed.group.bin` | The game's `fixed` with `loading-<name>` added (a copy of Kino's) |
| `weapons_<name>`, `weapon_projectiles_<name>`, `arms_<name>` | Renamed copies of Kino's |
| `<name>` | Children: Kino's `kino_dynamics` and `<name>_statics` |
| `<name>_statics` | Kino's statics with its `CLevel` renamed; child `<name>_sectors` |
| `<name>_sectors` | Kino's sectors renamed; its children are Kino's room groups |

`bozkit.derbh` reads these groups straight from the client's `assets/blackops_etc.dz`, so no
extraction is needed.

Replacing `fixed.group.bin` from a mod conflicts with any other mod that also replaces it. A
client feature for adding groups at startup would remove the conflict.

## Generated arena (`levels.generate_arena`)

`redux_arena` is the first level with its own geometry. It is a walled 24 m square, and it loads
and plays: rounds, zombies, power, and a perk you can buy.

| Part | Where it comes from |
|------|---------------------|
| Floor and walls | A new `CIwModel` (`native.build_model`), drawn by one placed entity |
| Texture and material | A generated raw BGRA texture (`native.build_texture`) and an opaque material (flags 0) |
| Collision | The `COLLISION` entity's mesh, replaced with the floor, the walls and a box per prop |
| Navmesh | Built fresh with Recast on the template's settings and tile grid (`navbuild.build`) |
| Player and zombie spawns | The template's player spawns and starting-area spawn points, moved into the arena |
| Juggernog, power switch | The template's entities, moved; their models come from `kino_dynamics` |
| Rounds, zombie types, sounds, cameras | Kept from the template's statics |

The level has no rooms (no `<name>_sectors` group). Renderables in render group 20 that are not
inside any room are culled by their bounding sphere only, so they still draw.

Shipped levels bake props into the level's collision and navmesh. A generated level gives every
prop a solid box instead (`levels.prop_boxes`): the prop's own collision box, or else its model's
bounds. Players walk on the navmesh, so a prop without a hole in it can be walked through.

Model layout (`CIwModel_Serialise`), as written by `native.build_model`:

- u32 flags.
- u16 render vertex count, then u16 position count.
- Bounding sphere: i32 x, y, z and u32 radius.
- The block list: u32 count, then for each block its u32 class hash and the block itself (u32 class hash, u16 size in memory, u16 element count, u16 flags, data).
- u32 0, for an empty second list.
- The materials: u32 count, then the u32 material hashes.

Positions are signed 16-bit centimetres. UVs are in 1/4096 units, and 4096 means 1.0.
