# How the game works

A modder's tour of *Call of Duty: Black Ops Zombies* (1.0.11): first the systems you will meet,
what they do and where to change them, then how the game loads a level, and finally how it
stores its data in files.

## The game's systems

This section covers the systems you will meet, what they do, and where to change them. Function and event names are the ones in the game definition
(`gamedef/`), so you can hook them or look up their notes. When the standard lib already covers
something, that is the easier way; see the [standard library](standard-library.md).

### The big picture

The game is built in three layers, and the names tell you which one you are looking at:

| Prefix | Layer | Examples |
| --- | --- | --- |
| `C...` (no `Is`/`Iw`) | The game itself | `CWaveManager`, `CMysteryBox`, `CPlayerController`, `CDO*` (Dead Ops) |
| `CIs...` | The studio's engine (Ideaworks): entities, components, events, animation | `CIsEntityDB`, `CIsSubject`, `CIsCamera` |
| `CIw...` | Marmalade, the cross-platform SDK: resources, UI, sound, console | `CIwResManager`, `CIwUISlider`, `CIwConsole` |

Gameplay objects are **entities** made of **components** (a zombie has `CHealth`, an AI
controller, a body, ...). Big systems are **singletons** (`CWaveManager`, `CScoreManager`,
`CLevelManager`, ...). Systems talk through **events**.

There are two game modes: **Zombies** (the first-person maps: Kino der Toten, Ascension, Call of
the Dead, ...) and **Dead Ops Arcade** (top-down, its own `CDO*` systems). Most of this section is
about Zombies.

### Events

Systems announce things with events named `SUBJECT_*`: `SUBJECT_NEW_WAVE`, `SUBJECT_ZOMBIE_DEATH`,
`SUBJECT_ADD_SCORE`, `SUBJECT_ON_PERK_GAINED`, ... A system sends an event; everything that
subscribed to it gets it in its `OnEvent`. `gamedef/events/boz-1.0.11.toml` lists all 337 events
with the classes that send and handle them.

For a mod, events are the natural place to react: hook the handler of the event you care about.

### A frame

Each frame the game updates the current state (main menu, playing, paused, ...), runs the world
and every system and component, draws the scene and the HUD, and updates sound, music and the
network. The client's `frame` event runs once per displayed frame, after all of that.

### Rounds

Rounds are run by `CWaveManager` from round definitions (`CWave`, game data):

- while fewer zombies have spawned than the round's total, and fewer are alive than its maximum,
  it spawns one after a short delay;
- every zombie death counts; when the count reaches the total, the round ends
  (`SUBJECT_WAVE_ENDED`) and after a pause `CWaveManager::StartWave` starts the next one;
- later rounds grow: each value is `base * multiplier ^ (round - first round)`; special rounds
  (hellhounds, monkeys) slot in between.

Round sizes, zombie speeds and health are data, so they can be changed by editing the round
definitions (bozkit) or by hooks at run time. The standard lib has `boz.rounds` for starting
rounds and spawning or killing zombies.

**Spawning.** Every zombie, dog and monkey is spawned from a spawn description
(`ZombieSpawnInfo`: what spawns, a new name, a spawn point, a look, a position) through
`CWaveManager::OnSpawnZombie`: its health is the round's (times the difficulty's multiplier), its
speed tier is picked from the round's walk / run / sprint shares, and it counts toward the round
when it is tracked. A plain zombie's spec comes from its look (`CZombieConfiguration`, the level
lists the ones it picks from). George (Call of the Dead) spawns through the wave manager's boss
spawn, which keeps him. An AI spawned off the navmesh dies within seconds.
`boz.zombies.spawn` / `spawn_george` / `spawn_at_point` do this.

### Points and purchases

`CScoreManager` keeps each player's points:

- earning: `SUBJECT_ADD_SCORE` (kills, repairs) adds points through `CScoreManager::AddScore`;
- spending: every purchase (doors, the box, perks, Pack-a-Punch, traps, turrets) sends
  `SUBJECT_CHARGE_POINTS`;
- in single player, a purchase you cannot afford is paid with COD Points (the store currency) when
  you have enough.

The cheat `UnlimitedScore` makes purchases free; `StartingScore` sets the starting points.

### Combat and health

- **Shooting:** a weapon's shoot animation fires its bullets: each pellet gets spread, a ray is
  cast, and what it hits gets `SUBJECT_WEAPON_HIT` with the body part. The knife does the same
  for a target in front of the player.
- **Health:** `CHealth` clamps damage, regenerates after a delay and sends `SUBJECT_DIED` below
  1 health. `CHealth::Damage` is where damage arrives. The most health can be (+0x44) is set at
  spawn (the round's health for a zombie) and doubled by Juggernog; the reflected
  `m_MaxHealth` is only the spec's base.
- **What weapons do to zombies:** a zombie's controller gets the hit as an event and reacts:
  ice (the freeze ray: frozen, then shattered), fire, the full-body explosion, chain lightning,
  the black hole and the Thundergun each have their own death. `boz.zombies` sends these
  directly (`z:freeze()`, `z:burn()`, `z:explode()`, ...).
- **Kills:** a dying zombie sends a kill-score event by how it died (head, torso, limb, knife,
  grenade); the killer's score handler looks up the points (doubled during Double Points) and adds
  them. `zombieHeadshotBonus` is extra for headshots.

### Weapons

A weapon is an entity with a `CPlayerWeapon` component: its definition (clip size, damage, fire
rate) and live ammo. Each weapon type (automatic, shotgun, launcher, Wonder Weapons) is a small
state machine: idle, firing, reloading. Weapon stats are data (`weapons_<map>.group.bin`),
readable and editable with bozkit. `WeaponsUnlimitedAmmo` stops ammo use.

### Perks, power-ups and the box

- **Usable objects** (perk machines, the mystery box, Pack-a-Punch, doors, barricades, traps,
  turrets) all have an `Interact`: check the cost, charge points, act.
- **Perks** (`CPerkManager` on the player): Deadshot, Double Tap, Juggernog, Stamin-Up, PHD
  Flopper, Quick Revive, Speed Cola, kept as bits with a HUD icon each.
  `boz.player.give_perk` / `give_all_perks` grant them, `take_perk` / `take_all_perks` take them.
- **Using something** only works when the player's points cover it as of the last frame (the
  score updates a frame later); `piece:use_free()` credits the cost, uses it a frame later with
  purchases free (the `UnlimitedScore` cvar, `boz.score.free_purchases`) and takes the credit back.
- **Power-ups** drop from zombies based on points earned since the last drop; the last dog or
  monkey of a round drops Max Ammo.
- **The box** rolls a weapon and hands it over through `CWeaponManager::GiveWeapon`.

### The player and the camera

The local player's controller is `CPlayerController`; its weapon manager (`CWeaponManager`)
also owns the view's field of view: it eases between the map's default and the weapon's
aim-down-sights zoom each frame. `boz.camera.set_fov` changes it properly. `boz.fly` turns on
the game's developer fly mode (noclip). Camera shakes are data (`CCameraShakeConfig`: duration,
how far, how often it changes); one plays at a time (`boz.camera.shake`).

Rotations are quaternions stored scalar first (s, x, y, z) everywhere: transforms, spawns,
spawn descriptions. `boz.entities` takes and gives `{x, y, z, w}`.

### Menus

The game has two UI systems:

- **The main menu** is one Flash movie (`fe_v4_cs4_swf.bin`, ActionScript 2) played by an
  embedded Flash player (gameswf). Its screens talk to the game with named messages.
  `boz.frontend` has the building blocks for changing it.
- **The in-game menus** (pause menu, settings, HUD) are Marmalade IwUI pages: trees of widgets
  (labels, images, buttons, sliders) found by name, whose widgets call named handlers on the page.
  `boz.pause_settings` adds settings to the pause menu; `boz.iwui` is the toolkit underneath.

Text is shown by **string id** (`S_MENU_MUSIC`) in the player's language; `boz.text` adds your
own.

### Saves

Saves are `.i3d` files in the client's `saves/` folder: profiles, stats, settings, achievements,
and the mid-match save written at each round start in single player. Each system saves its own
section. bozkit reads them (`bozkit save`, `bozkit settings`); the format is in
[Asset formats](#saves-i3d).

### The console

The game kept its developer console: about 660 variables (tuning values and cheats) and 150
commands, listed in the [console reference](console-reference.md). Many variables exist only while
a match runs. `boz.console` runs commands and reads and sets variables; the Developer mod gives it
a window.

### Dead Ops Arcade

A separate mode with its own systems: `CDORoundManager` (rounds), `CDOHordeManager` (enemies),
`CDOPickupManager` (power-ups) and `CDOPlayerController` (which can switch between walking, a
helicopter and a tank). Each of its 42 rounds is data: arena, lighting, music, and which enemies
unlock when.

### Zombies and pathing

Zombies move with Recast/Detour, the standard navigation-mesh library: each map has a navmesh,
zombies are crowd agents (speed, avoidance, climbing are data), and window and barricade climbs
are separate connection objects. Per-round speeds come from the round definitions.

### Co-op

The game has local Wi-Fi co-op (discovery plus TCP), with the host running the match and the
other players following it. Online play used Activision's servers, which BOZ Redux does not use.

## How levels load

How the game finds and loads a level, and what a level the game does not ship needs to load. The
SDK's map build (`bozkit.world_compile`, `bozkit.levels`) writes exactly these files; this section is
for understanding a build, or for making levels with your own tools.

### How a level is loaded

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

### Level groups

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

### A copy of Kino (`levels.clone_level`)

The smallest new level is a renamed copy of Kino:

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

### A level with its own geometry

The **Debug arena** template (`world.template_world("debug")`, compiled by
`world_compile.compile_world` like every map project) is a walled 24 m square built from scratch.
It loads and plays: rounds, zombies, power, and a perk to buy.

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

## Asset formats

How Call of Duty: Black Ops Zombies 1.0.11 stores its data, and how `tools/bozkit` reads and
writes it. Everything here was worked out from the game's own code. No game data is included in this repository.

### Where the files are

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

### Resource group (`.group.bin`)

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

### Writable-format status

#### Material rendering (GLES1 path)

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

#### Texture coordinates

`CIwModelBlockGLUVs` and `CIwModelBlockGLUVs2` share one layout: a u16 render-vertex count at
block `+6`, then one signed 16-bit (u, v) pair per render vertex from `+10`, in 1/4096 units. They
follow the GL convention: v = 0 addresses the first stored texel row. Readable textures confirm
this. On the tutorial's "WISH too OFTEN" sign, its posters and its building facade, the geometric
top of the surface has v = 0. Tools that display images upright must mirror v (`1 - v`).

#### Raw texture formats

Uncompressed textures use Marmalade's formats, named by channel from the most significant bits of
a little-endian word: `0x0e` is ABGR_8888 (bytes **R, G, B, A**), `0x0a` is BGR_888 (bytes
R, G, B) and `0x05` is 16-bit with **red in the top nibble, alpha in the bottom** (GL RGBA4444: the
HUD's `hud_icons` atlas shows its grey weapon icons in game only read this way). Evidence: textures
that are ETC1 in `blackops_etc.dz` and `0x0a` in `blackops_gles1.dz` match pixel for pixel in
R, G, B order; a texture written as B, G, R, A showed red and blue swapped in the game; and the
tutorial's graffiti sign, `0x0e` in one level and `0x05` in another, has the same alpha-0
background in both (`00 00 ff 00` and `0x0f00`, blue). bozkit before 2026-10-10 read these as
B, G, R, A, which swapped red and blue in previews and in re-encoded textures.
Most alpha-tested and blended map art uses these formats, so reading `0x05` as RGB565 turns
red art green and shows transparent areas as solid colour.

Layout (`CIwTexture::Serialise`, then `CIwImage::Serialise`), in every shipped raw texture:

| Offset | Field |
|--------|-------|
| 0 | u32 texture flags, u8, u8, two i16 |
| 10 | image: u8 format, u16 image flags, u16 width, u16 height, u16 pitch, u32 |
| 23 | texels: pitch × height bytes |
| end − 1 | u8 "has mipmaps", always 0 |

The image flags' bits 1 and 2 (a palette, or no texels) never occur. The last byte is easy to
mistake for texel data. Before 2026-10-09, bozkit read the texels from offset 24, one byte late,
which shifted the colour channels. It also wrote textures without the final byte. The game then
read a texel byte as "has mipmaps", which can crash it.

#### Cooked texture payloads

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

#### Resource coverage

| Resource | Parse/write status | Editing status |
| --- | --- | --- |
| Resource groups | Complete | Resources may be replaced without changing unknown sections or other bodies |
| Reflected resources | Complete | Named typed properties, including nested objects and lists |
| Entity specifications | Complete | Components, children, reflected fields; collision payload retained raw |
| `CIwMaterial` | Complete | Compact records contain flags and one primary texture reference; full records contain four texture slots, packed colours and a shader-technique reference; unknown auxiliary data retained |
| `CIwModel` | Static GL triangle geometry, render-vertex remaps, vertex colours, both UV sets, explicit primitive material indices, terminal material references, and lossless preservation | glTF/Blender export; source-backed position and UV edits retain unknown blocks; additional primitive types remain |
| `CIsNavMesh` | Complete for shipped resources | Recast agent/build settings; Detour tiles retained raw |
| `CIwTexture` | Row-major ABGR_4444 (`0x05`) and ABGR_8888 (`0x0e`, bytes R, G, B, A) plus cooked ETC1 and DXT1 mip payloads | PNG import for writable raw formats; raw and cooked formats decode for Blender/material previews |
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
RGBA at load. 32-bit texture export was visually
validated with the named `main_menu_logo` resource. ETC1 and DXT1 decoding was visually validated
against the same tutorial floor material from the corresponding platform archives.

### Hashes

Names are stored as `IwHashString(name)`: `h = 5381; h = h * 33 + c` for each byte, with A–Z
lowercased, as a 32-bit value. Resource names are usually not stored. `bozkit names` builds a
local dictionary from strings in your own game files to show them.

### Reflected data (`LFER` blobs)

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

### Navigation meshes (`CIsNavMesh`)

Zombie pathing uses Recast/Detour.

- **Layout:** each `CIsNavMesh` body begins with an 80-byte Recast build configuration and a
  40-byte Detour mesh-set header. Each tile then has an 8-byte reference/size header followed by
  Detour version 7 tile data (`DNAV`) with BOZ's widened 40-byte polygons and off-mesh
  connections (see [Navigation meshes](map-editor.md#navigation-meshes)). The settings begin with cell size, cell height,
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

### Visibility portals (`CIsPortal`)

```text
u32 vertex_count
vertex_count * vec3 vertices
vec3 plane_normal, float plane_distance
u32 front_sector_hash, u32 back_sector_hash
cstring front_sector_name, cstring back_sector_name
```

The hashes are regenerated from the sector names when written.

### Collision meshes

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

### Entity transforms and hierarchy

`CIsTransform` component blobs store any of `m_localPosition` (`CIwFVec3`), `m_localRotation`
(`CIwFQuat`, xyzw) and `m_localScale` (`CIwFVec3`); a missing field is the identity. Scales such as
1/16 and 1/64 occur. An entity spec's children are positioned relative to their parent, and 129
renderable children exist in the Zombies levels. Reflection reads properties by name, so `bozkit`
adds a missing field when an edit needs it.

### Entity links and areas

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

### How levels create entities

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

### Maps across groups

Placements reference resources by name hash, not by group. Kino's `kino_statics` places 73 objects
using 23 models from `kino_dynamics` and `ingame`. Each room's `*_shared` group holds that room's
models, materials, portals, occluders and light boxes, while many of its textures live in other
groups. Editors must resolve references across all of a level's groups plus `ingame`, and write
each edit back to the group that owns the resource.

#### Map-agnostic assets (bozkit.bundle)

Nothing in the game's data ties a resource to a map: `CIwResManager` finds a name in whatever
groups are loaded. So a map can use anything from any map, provided its own groups carry it.
`bozkit.bundle` does that for every build:

- **The registry** indexes every resource of every group (class, name, group, body) and what it
  refers to: an entity spec's hash-typed properties, a model's materials, a material's textures, a
  reflected resource's hashes, and for other binary resources (skins, skeletons, animations, state
  machines, sound specs and sequences) any word that names a game resource. Code references come
  from the game definition's runtime names (`gamedef/runtime`, made by
  `tools/ghidra/ExportBozRuntimeNames.java`): per class, the names its functions hash or play at
  run time. A spec with a `CProjectileEntity` brings `gersch_Effect`, the Gersch sounds and
  `matr_pop_00`, which no data names.
- **A bundle** walks the closure from what a map uses (placed entities and models, weapons and
  their projectiles, named effects, every spec a script names by game name or `"0x..."` hash,
  zombie looks of the Game tab, what "behaves like" plays) and copies what the map's loaded groups
  (the shared groups and the children of the map's groups) do not already hold.
- **Where it goes:** projectile specs and any other entity spec go into
  `weapon_projectiles_<map>` (never the statics group: the level makes an entity of every spec
  there), weapon specs into `weapons_<map>` (the game reads those groups' own resources), what a
  spec uses with it, everything else into the statics group.
- **Clashing names:** names are not unique across groups (every weapon has models named `Base`
  and `LOD1`). A resource whose name the map already holds with a different body is copied as
  `boz_<group>_<name>`, and the copied resources that use it are changed to point at that name.
- **Not copied:** level structure (`CLevel`, `CArea`, navmeshes, portals, occluders, `CWave`, the
  score table, loading strings): every map has its own.
- Specs that cannot stand alone are not in the Effects catalog: no `CIsTransform` (parts of other
  effects), a `CIsBoneAttachment` (they need a bone), an emitter without an `emitterSpec`
  (`base_emitter`). Spawned anyway, the first two crash the game in `CIsRenderable::UpdateTransform`
  and the last in `CIsRenderableGFXEmitter::Init`; boz.effects removes a spawned spec without a
  transform at once.

Verified in the game: every one of the 228 effects and projectiles of every map spawns on a map
built from Kino (Call of the Dead's draw there too); no reference of another map's effect is
missing from the built map.

### Saves (`.i3d`)

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

### Reading these files

The [bozkit command line](sdk-reference.md#bozkit-command-line) reads and writes every format in this section:
`dump` writes every reflected resource and entity spec of a group as JSON, with named fields
and typed values, `set` changes one field, and the resource commands export and import models,
textures, materials, collision, portals and navmeshes. `corpus` checks that a whole extracted
pack reads and writes back byte for byte.

### Skeletal animation (CIwAnimSkel, CIwAnimSkin, CIwAnim, CIsAnimStateMachine)

First-person arms and guns are skinned models. A skeleton lists its bones (name, parent, a
compressed rotation, a position relative to the parent); a skin stores, for each set of up to
four bones, every vertex's position in each bone's space and its weights (the vertex is the
weighted sum of the bones' transforms applied to those positions; skeleton units are the model's
x 4); an animation keeps its keyframes as the game holds them in memory (per bone a position and
a quaternion, 24 keyframes a second); a state machine names its states (by hash only: the
names found so far are in `viewmodel.STATE_NAMES`) ("idle", "shooting", "reloading", ...) and the
animation each plays. The arms hold the gun at their TAG_WEAPON bone. The byte layouts are in
`bozkit/anim.py`; `bozkit/viewmodel.py` poses a weapon's first-person view from them in any
state and keyframe (`Rig`). Keyframes carry their times (4096 = 1 second, on a 30 a second
grid, not evenly spaced). `anim.encode_skel` and `anim.encode_anim` write skeletons and
animations (every shipped one round-trips byte for byte) and `anim.patch_asm` copies a state
machine with other animations; `bozkit/weapon_anim.py` builds a weapon's own skeleton and
animations with them. `anim.encode_skin` writes skins (every shipped skin round-trips byte for
byte; weight bytes add up to 128) and `anim.build_skin` makes one for a model on a skeleton's
bind pose; `bozkit/weapon_model.py` puts your own model on a weapon that way. A skinned model's
flags are 0x30000 (rigid: 0x20000); a weapon's spec points at its model and skin (same hash) in
renderableAsset, renderableAssetADS (aiming down the sights, on some guns) and LODS (three
distance models).

### Sounds (CIwSoundData, CIwSoundSpec, CSoundSequence)

About 730 sounds, in `ingame/ingame.group.bin` (the shared ones: weapons, zombies, power-ups,
rounds, buying), each map's statics group, `ingame/sound/snd_player_<character>.group.bin`
(voices) and `fixed`/`shared` (interface). Layouts from the Serialise methods in Ghidra:

- **CIwSoundData:** u32 data bytes, u32 sample count, the data, u32 sample rate, u16 format
  (2 = ADPCM); the ADPCM class (CIwSoundDataADPCM) adds u32 samples per block and u32 block
  bytes. Every shipped sound is mono Microsoft IMA ADPCM: 512-byte blocks of 1017 samples at
  22050 Hz (206 sounds) or 256-byte blocks of 505 samples at 11025 Hz (521). A block starts with
  s16 predictor, u8 step index, u8 0, then two 4-bit samples a byte, low nibble first. All 727
  round-trip through `sound.decode_data` / `encode_data`.
- **CIwSoundSpec** (CIwSoundSpecSound, 48 bytes): u16 flags; s16 volume min/max, pan min/max,
  pitch min/max (4096 = 1.0); s32 100; s32 0x1800; u32 1; u32 0; u8; u16 max polyphony (the
  `DefaultSoundSpecMaxPolyphony` cvar, 3); u8; u16 priority (100); u32 sound group
  (CIwSoundGroup); u32; u32 the CIwSoundData it plays. In the shared group a spec and its data
  share one hash. CIwSoundSpecAudio streams mp3 through s3eAudio (music).
- **CSoundSequence:** u8, u32 command count, then per command u32 class hash, u32 0 and its
  fields: CSoundSequenceCommandPlay / PlayAsync u32 sound (a spec or a CSoundVariation), u32,
  u8; CSoundSequenceCommandDelay s32 milliseconds. CSoundSequenceManager::Play(hash) plays one;
  weapon fields (fireSoundSequence, reloadSoundSequence, ...) name them.
- **CSoundVariation:** a reflected resource (`LFER`) listing the specs it picks from.

`bozkit/sound.py` reads all of these, encodes ADPCM, lists a level's sounds as slots and
replaces a slot by swapping its CIwSoundData (the spec, its settings and every sequence stay).
