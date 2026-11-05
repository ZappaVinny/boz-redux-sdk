# Map internals

How the editor's work reaches the game: for when you want to know why something behaves the way it
does, or want to edit the game's own files. You don't need this page to make a map.

## How the rules work

- **Rounds** (Ghidra: `CLevelManager::StartFirstWave`, `CWaveManager`): the level's `CLevel` names
  each game's first round (`m_StartingWavesSP` by difficulty, `m_StartingWavesMP` by players);
  each `CWave` names the next (`m_NextWave`); a `CWaveRepeatable` without a next one repeats,
  scaling by multiplier ^ (round - `m_StartingWave`). `CWaveRepeatable::GetZombieHealth` is
  10 x round^2 - 150; boz.game replaces its result for **Grows by the multiplier**. Special
  rounds (`CWaveSpeciality`, `CWaveMonkey`) are picked by `m_waveType` (0-2 the difficulty, 3-5
  the players). The build writes the map's rounds as `boz_<game>_<n>` and `boz_special_<n>`.
- **Economy:** console variables (`StartingScore`, `PickupPointsThreshold`,
  `ProbabilityOfSpawningEachPickup`, ...), set by boz.game just before the map's level loads
  (`Level_Load`) and put back on other maps. Points come from a `CScoreConfig` (`m_Scores` and
  `m_ScoreLimits`); the map ships its own (`boz_score_<map>`) and points `ScoreConfigName` at it.
- **Loading screen:** `fixed`'s `loading-<map>` names a loading group per screen size; the build
  points them at `loading_<map>`, a copy of Kino's with the picture replaced (1024 x 1024 ETC1,
  encoded by bozkit).
- **Box:** the `CMysteryBox` components still at the game's values.
- **Behaves like:** boz.game answers `String_Equals(level name, "<map>")` with true (the
  level manager's checks: `Level_IsAscension`, `Level_Load`, `LevelManager_SetCamera`,
  `LevelManager_UpdateAmbience`).

`bozkit/game.py` compiles it; `lib/boz/engine/game.lua` and `lib/boz/engine/hooks.lua` run it.

## Game prefab fields

What each of the game's objects is (the asset browser's **Game prefabs** and **Level
markers**), which of its settings the editor lets you change, and why the others stay as they
are. The tables cover every entity in the four shipped levels and every field the game registers
for their components (`gamedef/reflection`).

**Default** is the game's value when a level leaves the field out (shipped data only stores
fields that differ from it).

Fields marked *editor* appear in Properties → Object → Game (Settings) when the game prefab is
selected. Units: points, centimetres (cm), seconds (s; the game stores milliseconds).

Every object also has the [In the game box](editor.md#the-in-the-game-box) and a **Script** whose
`---@setting` lines add fields of their own ([Settings](prefabs.md#settings)). The original map's
own entities can start hidden or without collision; their walkable area stays as shipped.

### The game prefabs

#### Perk machines (`CPerk`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_perkSinglePCost` | — | Points it costs in solo | editor: Cost |
| `m_perkMultiPCost` | 1500 | Points it costs in co-op | editor: Co-op cost |
| `powerSwitch` | 0 | Name of the power switch it waits for. `boz_no_power` makes it work without power (the runtime powers it at `CPerk::Init`) | editor: Needs power |
| `CPOI.m_MaxDistance` | 300 | How close players must be to use it (cm) | editor: Use distance |
| `m_numOfUses` | 3 on Quick Revive | Solo Quick Revive uses | no (Quick Revive only) |
| `perkName`, `m_PerkType`, sting | — | Which perk it gives and its jingle | no: pick another machine instead |
| `CHealth.m_MaxHealth` 500 | — | Monkeys attack machines (Ascension) | no |
| `CIsCollisionBox` 150 × 270 × 120 cm | — | The machine's solid box | no |

#### Pack-a-Punch (`CPackAPunch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | 5000 | Points an upgrade costs | editor: Cost |
| `powerSwitch` | — | Power switch it waits for; off writes 0 and `m_HasPower` = true | editor: Needs power |
| `CPOI.m_MaxDistance` | 300 | Use distance (cm) | editor |
| `m_HasPower`, `m_State`, `m_WeaponHash`, ... | — | Runtime state | no |

#### Mystery box (`CMysteryBox`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | 950 | Points a spin costs | editor: Cost |
| `m_FireSaleCost` | 10 | Points a spin costs during a Fire Sale | editor |
| `m_MinWeapons`, `m_MaxWeapons` | 4, 10 | The box moves after a random number of uses between these | editor |
| `m_Weapons` | empty | The weapon pool (empty: the level's) | not yet: needs the Weapons tab |
| `m_RefundCost`, `m_State`, timers | — | Runtime state | no |

The level picks which box location is active (`CLevel` `MysteryBoxStart`, `MysteryBoxAvoid`).

#### Power switch (`CPowerSwitch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `StartEnabled` | true | Players can pull it from the start (Ascension's launch switch starts disabled) | editor: Usable from the start |
| `playSound` | — | Sound when pulled | no |

#### Wall buy (`CWeaponChalkOutline`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| weapon (`model` child asset name) | — | The weapon it sells | editor: Weapon |
| `m_cost` | — | Points the weapon costs | editor: Cost |
| `m_ammoCost` | 0 (half the cost in game) | Points a refill costs | editor: Ammo cost |
| `m_upgradedAmmoCost` | 0 | Points a refill of the upgraded weapon costs | editor: Upgraded ammo cost |
| chalk decal | the weapon's own | The drawing on the wall (a separate decal) | editor: Chalk |
| `m_weaponType` | — | Prompt type: firearm, melee, grenade | no: follows the weapon |
| `CPOI.m_BiDirection` | true when placed | Usable from either side | set by the compiler |

#### Doors and debris (`CDoor`, one design per model in the game)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | — | Points to open | editor: Cost |
| `powerSwitch` | 0 | Opens itself when this power switch is pulled (not buyable) | editor: Needs power |
| `m_HideAfterActivate` | false | The model disappears once opened (debris) | editor: Disappears when opened |
| `playSound` | — | Sound when opening | no |
| `m_AreasUnlock` | — | Zones (`CArea`) it unlocks | placed doors unlock none (generated maps have one area) |
| `CIsCollisionBox` 300 × 300 × 10 cm | — | Blocks players until open | no |

The navmesh under a door is tagged with its name and closed until it opens (`CDoor::Init`,
`CDoor::OnEvent` → `NavMesh_SetTagOpen`).

#### Window barricade (`CBarricade`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_StartBroken` | false | The planks start torn down | editor: Starts broken |
| `CPOI` | 170 cm | Repair reach | no |

#### Trap and trap switch (`CTrap`, `CTrapSwitch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `CTrap.m_ActivePeriodMS` | 30 s | How long it runs once bought | editor: Runs for (s) |
| `CTrap.m_CoolDownPeriodMS` | 10 s | Wait before it can be bought again | editor: Cool-down (s) |
| `CTrap.m_PlayerDamage` | 115 / 230 | Damage to players who walk in | editor |
| `CTrap.damageEffect`, `startSound` | — | Effect and sound | no |
| `CTrapSwitch` cost | 1000 | Points to run the trap | editor: Cost |
| `CTrapSwitch.powerSwitch` | — | Power switch it waits for | editor: Needs power |
| `CTrapSwitch` traps list | — | Which traps it runs | not yet: needs links |

#### Spawns (`CSpawnPoint`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `spawnType` | — | windows, ground, Lightning (dogs), Hole, Monkey | the level marker you pick |
| `m_StartActive` | false | Used from the first round, not only once players reach its area | editor: Active from the start |

Player spawns are the entities named `spawn_player_1` to `_4`.

#### Level markers: jump point, sound emitter

| Piece | Field | Meaning | Editor |
| --- | --- | --- | --- |
| Jump point | `m_jumpAreaHash` | The jump area zombies cross to | no: linked by the level |
| Sound emitter | `soundName` | The sound it plays | editor: Sound |
| Sound emitter | `StartEnabled` | Plays from the start | editor: Plays from the start |

### Volume entities

Volumes are not game prefabs: they have no behaviour of their own and only send events to
scripts. Each compiles to an entity made from a shipped template:

| Volume | Made from | In the game | Script event |
| --- | --- | --- | --- |
| Trigger | Call of the Dead's snow trigger box (`CIsCollisionBox`, `m_Ghost` on, `CCollisionFilter`, `CEntityFlags`) | A ghost box sized by the volume | `enter` / `exit` (`CIsCollisionObject::OnCollisionEnter` / `OnCollisionExit`) |
| Hit | Kino's musical easter egg skull (`CEasterEgg`, `CHealth`, `CIsCollisionSphere`) | A sphere of the volume's largest side, with a song of its own so it stays out of the level's easter egg | `hit` (`CEasterEgg::OnEvent`, skipped for the game) |
| Use | A barricade's `CPOI` and `CIsBroadcaster`, without the barricade | A point of interest the game draws no prompt for; reach: half the size plus 75 cm | `use` (`Poi_SendUse`); the prompt and cost come from `boz.prefabs` |

### Points of interest (`CPOI`)

Everything players use has a `CPOI`. `m_poiType` picks the prompt: 0 barricade, 1 door, 2 wall
buy, 3 box, 4 perk, 5 Pack-a-Punch, 6 trap switch, 7 power, 8 turret, 9 teleporter, 10 mainframe,
11 lander, 12–13 lander station, 14 revive, 15 claymore, 16 tutorial pickup
(`LevelManager_UpdateNearestPoi`, `CIngameStatePlaying::OnEvent`). The other fields set the reach:
`m_MaxDistance` (cm), `m_ViewingAngle`, `m_AngleDistanceOffset`, `m_HeightOffset`,
`m_MaxYDistance`, `m_BiDirection` (either side), `m_Moveable`, `m_IsReverseViewAngle`. Pressing
use runs `Poi_SendUse`, which broadcasts the interact event to the entity in reach.

### Not game prefabs yet

These are in the shipped levels; each needs its own game prefab or links before it is useful:

- Turret (`CTurret`: cost, duration, damage, range, rate of fire, cool-down, power).
- Teleporter, mainframe and Gersch points (`CTeleporter`, `CTeleportMainframe`, `CTeleportPointGersch`).
- Rides: lunar landers, zipline, flinger, centrifuge, ice slide (Ascension, Call of the Dead).
- Animated scenery, TV and projector screens, fog effects, lights.

## Navigation meshes

In BOZ, players and zombies do not walk on the level's collision. They walk on a separate
**navigation mesh** (navmesh): a map of the floor where anyone can go. Collision only decides
what bullets and other ray casts hit. So when you add a wall, the navmesh has to change too, or
players walk straight through it.

You rarely need to think about this: when you save a map whose collision changed, the SDK
rebuilds the navmesh around the change, and doors and blocking objects are handled for you. In
the editor, **Show → Walkable** draws the navmesh. This section explains how it works, for when
something does not walk the way you expect.

The game moves the player in `CPlayerController::FixedStep` through `Player_MoveOnNavMesh`
(`Nav_FindNearestPoly`, `Nav_MoveAlongSurface`, `Nav_GetPolyHeight`); zombies use the same mesh.

### The helper program

The rebuild runs [Recast](https://github.com/recastnavigation/recastnavigation) through a small
native program, `boz-navmesh`. Build it once as described in
[Installation](getting-started.md#the-navmesh-helper). Without it, saving still
works and reports that the navmesh was not rebuilt.

### How BOZ stores navmeshes

A `CIsNavMesh` resource holds the build settings and a tiled Detour v7 navmesh (see
[Asset formats](how-the-game-works.md#navigation-meshes-cisnavmesh)). The 80-byte settings block is
RecastDemo's: cell size and height, agent height, radius, climb and slope, region minimum and
merge sizes, edge length and error, vertices per polygon, detail sampling distance and error,
tile size, and the build bounds. Tiles are `tile size × cell height` wide (32 × 0.15 = 4.8 m in
Kino). Recast normally multiplies the tile size by the cell size; the game's original build tool
used the cell height instead, and the shipped navmeshes are laid out that way.
Positions are metres, the game's units divided by 100.

BOZ modified Detour. A polygon is 40 bytes instead of 32: `firstLink`, six vertices, six
neighbours, **32-bit flags**, a **32-bit name hash**, the vertex count, the area and type, and two
bytes of padding. An off-mesh connection is 40 bytes instead of 36: an extra float (0.9 in every
shipped link) follows the radius. Polygon flags and name hashes carry gameplay:

| Flag | Name hash | Meaning |
| --- | --- | --- |
| `0x1` | | walkable |
| `0x2` | a door's name | floor the door blocks until it opens |
| `0x4000` | a jump area (`CPlayerJumpPoint`) | jump point |
| `0x8` | | water (Call of the Dead) |
| `0x40`, `0x80`, `0x100`, `0x200`, `0x1000`, `0x8000` | | further area types, not yet identified |

Off-mesh connections are the zombie window crossings (one per barricade, named after the
barricade's plank entity), climbs (`TheatreLeft_Climb_1`) and drops from balconies. They are
one-way.

### How the rebuild works

The shipped navmeshes were built from the level's collision, with triangles wound the opposite
way to Recast's convention. Collision
boxes on entities count as obstacles; doors do not, because the navmesh runs under doors and
their tags gate it.

On save, the SDK builds this input from the game's original files and from the current level;
triangles that differ mark dirty areas, and only the tiles overlapping them are rebuilt from the
game's original navmesh with the stored settings. Because the comparison is always against the
game, repeated saves give the same result. **Rebuild navmesh** in the sidebar runs it even when
nothing else changed.

- Every other tile stays byte-identical. An untouched level keeps its navmesh exactly.
- In a rebuilt tile, polygons are kept where the shipped navmesh had floor or inside the edited
  areas. The original designers also cut areas away (for example the street outside Kino) that
  nothing in the level data describes; this keeps those cuts. Other polygons get flags 0, which
  the game's query filter skips.
- Outside the edited areas the shipped floor itself is extra walkable input (inflated by the
  agent radius, which Recast erodes again). Some shipped floor has no geometry under it at all,
  such as the drop-off point on Kino's lobby balcony, so this keeps rebuilt tiles faithful and
  keeps window crossings and climbs anchored.
- New polygons take the flags and name hash of the shipped polygon under them, so door gating,
  jump areas and water carry over.
- A tile whose rebuild would drop one of its window crossings or climbs keeps its shipped data.

In normal use only the tiles around an edit are rebuilt.

**Accuracy.** 79% of the shipped navmesh surfaces lie within one cell height of the level's
collision, which is how the collision is known to be their source. Rebuilding every Kino tile at
once (the worst case) reproduces 94% of the shipped walkable area, 96% of the rebuilt area lies on
shipped floor, and 44 of the 48 window crossings and climbs are rebuilt (the other four tiles keep
their shipped data).

### Blocking objects: cutting instead of rebuilding

An object set to **Block the walkable area** (a wall a script opens) does not change the
level's collision: the floor under it is tagged with its name, so `NavMesh_SetTagOpen` can shut
and open it. Rebuilding its tiles with Recast would lose floor the designers made from other
input than the collision. Kino's stairs, for example, are a ramp up to 0.8 m under the steps:
rebuilding a tile next to them loses a quarter of their floor and traps players. So the SDK keeps
those tiles exactly as shipped and cuts the blocker's outline into their polygons
(`bozkit.navcut`):

- the pieces inside the outline are tagged (flags `| 0x2`, the object's name hash);
- every new corner also goes into each polygon edge it lies on, so neighbouring polygons
  still share whole edges (Detour links polygons only through shared edges);
- polygons over six corners are halved along diagonals; new corners take their height from
  the shipped detail surface; tile-border portals keep their sides; the BV tree is rebuilt.

Floor area, connectivity and portals stay exactly the shipped ones; only tiles under a blocker
change. Real geometry changes (your own walls and floors, moved or removed entities) still
rebuild their tiles with Recast first, and blockers are cut in afterwards. Volumes (Trigger,
Hit, Use) change nothing walkable and leave the navmesh alone.

### Navmesh limits

- Tags stay where they were: moving a door does not move the floor it gates.
- New window crossings and climbs cannot be added yet.
- Windows builds of the helper are not produced yet.

## Editing shipped map files

The editor's **Shipped files** tools open the game's own map files (`.group.bin`) directly,
show everything in them (models, gameplay objects, links, collision, portals, the navmesh), and
save your changes into a mod. They never change the game's own files.

**Most of the time you want a map project instead.** A map made from the Kino der Toten, Call
of the Dead or Ascension template is the whole original map, which you change in the World tab
and play as a map of its own ([Your first map](getting-started.md#your-first-map)). The
Shipped files tools are for changing the original levels themselves, in place, and for looking
at how the game's maps are built. Format details are in [Asset formats](how-the-game-works.md#asset-formats).

### Open the tools

Open any map project in the editor (**Open in Editor** in the SDK app). The tools are in the
**Shipped files** tab of the 3D View sidebar; set the client folder there.

### Extract the game data

The tools read an extracted copy of the game's data. Extract the pack your client downloaded
(in its `original/obb/` folder) once:

```bash
bozkit extract path/to/boz-redux/original/obb/blackops_etc.dz ~/boz-etc --kind dz
```

The examples below use `~/boz-etc`.

### Import a level

A map is spread over many groups. Kino der Toten's `levels/kino` folder has 25: `kino_statics`
places objects whose models live in `kino_dynamics` and in the shared `ingame` group, and every
room (`theatre_shared`, `lobby_shared`, ...) has its own geometry, portals and lightmaps.

1. Start from a fresh scene and choose **Shipped files > Import level folder**.
2. Select `~/boz-etc/levels/kino`. With **Shared in-game group** enabled, the add-on also reads
   `~/boz-etc/ingame/ingame.group.bin` and the level's weapon groups
   (`ingame/weapons/*_kino.group.bin`, for the wall-buy displays) to resolve placements, but
   imports none of their own content.
3. The Outliner gets one **BOZ &lt;group&gt;** collection per group, holding **Placed Models**,
   **Markers**, **Shapes**, **Collision**, **Portals** and **Navigation**. Only the models are
   visible after import. The sidebar's **Show** switches turn each overlay on across the whole
   level: Markers, Badges, Areas, Links, Shapes, Collision, Portals and Nav. **Marker types**
   narrows markers and badges to the kinds you want (for example only perks and doors).
4. Switch the viewport to **Material Preview**.

Kino takes a few seconds and produces about 600 placed models. The importer reports anything it
could not resolve, such as placements whose model is in a group outside the folder, as warnings in
Blender's status bar instead of silently dropping them.

**Import native group** imports a single `.group.bin`. That suits self-contained groups such as
`levels/tutorial/tutorial_statics.group.bin` or one room.

### What you see

**Placed models.** Every renderable entity becomes an object at its native position, rotation and
scale. All placements of one model share one Blender mesh, so editing the geometry of one changes
them all, exactly as in the game. Entities nested inside other entities keep their parent: a
non-renderable parent becomes an empty, and children move with it.

**Shading.** The preview follows the game's GLES1 material path:

- The primary texture is multiplied by the vertex colour. Vertex colours carry the baked lighting
  of unlit models.
- Lightmapped materials add the second texture, a baked lightmap atlas, through the model's second
  UV set (`UVMap2`), combined the way the material's flags select (usually multiply, or multiply ×2).
- Alpha blending, additive and inverse blending, and the alpha-test cutout follow the material's
  blend mode.

The colours are computed in the game's display encoding and decoded once, so import switches the
scene's view transform to **Standard**. Filmic or AgX would wash the result out.

The preview does not reproduce real-time lights on dynamic objects, fog, or the rare dot3
normal-map path.

**Markers.** Every entity without a model of its own becomes a small coloured diamond in
**&lt;group&gt; Markers**, and every model with a gameplay job (perk machines, doors, the power
switch, box locations, traps, Pack-a-Punch, barricades) gets a locked diamond badge above it that
moves with the model. Names say what the thing is, using the level designer's own names where the
data has them, for example `Quick Revive perk "QuickRevive"` or `Door 750 "Lobby_To_Atrium"`; the
`boz_description` custom property explains it (`Quick Revive perk machine, 500 points, linked to
the power switch`) and `boz_components` lists everything the entity contains. Colours by job:

| Colour | Job | Colour | Job |
| --- | --- | --- | --- |
| purple | perk machine | magenta | Pack-a-Punch |
| cyan | mystery box location | orange | door or debris |
| yellow | power switch | red | trap or trap switch |
| green | wall buy | brown | barricade |
| blue | teleporter | pink | Easter egg |
| dark red | zombie or player spawn | light blue | particle effect |
| lime | interact point | teal | sound |
| white | zombie jump point | grey | locator, camera, group |

Markers move, rotate and save like objects. A perk machine's glow and particles are separate
effect markers next to it, so select them together when you move the machine. Entities attached
to a bone are placed at their parent's origin.

**Links and areas.** Entities refer to each other by name, and **Show > Links** draws those
references as lines (by default only for the selected objects):

| Colour | Link | Meaning |
| --- | --- | --- |
| yellow | power | needs the power switch (doors, perks, Pack-a-Punch, trap switches, teleporters, TVs) |
| red | traps | a trap switch fires these traps |
| orange | siblings | doors that open together |
| cyan | unlocks | the areas a door opens |
| violet | members | an area's spawn points, perk machines, teleport points, shortcuts and locators |

Areas (zones such as `lobby` or `theatre`) appear as violet diamonds at the centre of their
members when **Show > Areas** is on. Spawns in an area only activate once a door unlocks it.

The **Selected** panel under BOZ Redux describes the active object, lists its links with a button
to select each target, an **×** to remove a link and **+** to link the other selected objects
(select the targets first, the object to link from last; a single link such as power is
replaced). **Linked from** lists everything that refers to it. Only entities with a game name can
be linked to. Link edits are saved with the rest.

**Shapes.** Collision boxes, spheres and capsules on entities and each interaction point's reach
are translucent children of their entity in **&lt;group&gt; Shapes**, hidden until you turn on
**Show > Shapes**. Their colour gives the role: red for solid collision, green for ghost
(pass-through trigger) volumes, yellow discs for how close a player must be to interact. They move
with their entity in the game. Edit them to change the game's values: a box's scale is its half
size and its position its centre; a sphere's uniform scale is its radius; a capsule's X/Y scale is
its radius and Z its half height; a reach disc's scale is the interaction distance and its height
the height offset. Shapes cannot be rotated relative to their entity. The level's world collision
(orange wire) is separate from these shapes.

**Collision.** A level's world collision is one mesh, cooked from the render models (in Kino, 82%
of its triangles lie exactly on a single placed model). Those triangles are imported as a hidden wire
child of that model (`<model> collision`), so moving, rotating or scaling the model carries its
collision with it. Collision that belongs to no single model (invisible walls, simplified
surfaces) stays in the level's collision object. Saving stitches everything back into the one
mesh the game loads, in the original triangle order; where a moved piece shared a vertex with a
still one, the vertex is split. In Call of the Dead and Ascension the collision object has its own
position.

**Portals** show their front and back sector names in the `boz_front_sector` and
`boz_back_sector` custom properties. **Navigation connections** (window and barricade climbs) are
two-point edges.

**Navmesh.** **Show > Navmesh** draws where players and zombies can walk: blue floor, orange
floor a door blocks until it opens, white jump areas, violet other tagged floor, and lines for
the zombie window crossings and climbs. It is display only. Saving rebuilds the tiles around
changed collision and refreshes this overlay; **Rebuild navmesh** forces it (see
[Navigation meshes](#navigation-meshes)).

### Editing a shipped level

Supported:

- **Transforms:** move, rotate and scale placed models, entity empties and collision objects.
  Rotation mode may be changed; export reads the final transform.
- **Model geometry:** vertex positions and both UV sets, with unchanged topology. Native models
  duplicate vertices at UV seams; moving one copy moves all copies of that position, and moving
  copies to different places is rejected.
- **Collision:** move pieces with their models, or edit vertex positions and per-face material
  slots of any collision object, with unchanged topology. Deleting a collision piece is rejected
  on save. Collision
  decides what bullets and other ray casts hit; export updates both copies the game loads (the
  ray-cast arrays and the Bullet physics shape). Where players and zombies can walk is the navmesh,
  which saving rebuilds around changed collision.
- **Portals:** vertices and sector names.
- **Navigation connections:** either endpoint.

**Duplicate and delete.** Select models or markers and use **Duplicate** (the copy follows the
mouse; click to place it) or **Delete** in the sidebar:

- A copy brings everything attached: child entities, its collision piece, shapes, badge and
  links. Names other entities can refer to get a free suffix (`QuickRevive` becomes
  `QuickRevive_2`); generic names shared by several entities stay. A copied spawn point, perk
  machine or teleport point joins the same areas as the original, so it works from the start.
  Copying a child entity adds another child to the same parent.
- Delete removes the entity, its children and its collision triangles, and takes it out of every
  area. It is refused while a power, trap, door-sibling or area-unlock link still points at it;
  remove those links first. The sidebar shows how many deletions wait for the next save.
- Saving creates and removes the entities, rebuilds the navmesh around them and reloads the
  level so the new entities get their final names and identities. Blender's own Shift+D copy is
  not a BOZ copy; **Validate** reports it.

Not supported yet:

- Adding or removing vertices or faces, applying modifiers, or reassigning model materials.
- Duplicating a copy before it has been saved.
- Re-parenting objects. An object must keep the parent it was imported with.
- Editing Detour navmesh polygons. Their tiles are preserved byte-for-byte.

### Save, reload and play

The sidebar's **Client** field is your BOZ Redux client folder (set it once; Blender remembers it)
and **Mod** names the mod your edits go into.

**Give your edits a mod of their own** (type a new name, for example `kino_edits`). **Mod**
starts as the Developer mod, and edits saved there change the original map for as long as the
Developer mod is on, which is easy to forget. With a mod of their own, the launcher's **Mods**
tab switches your edits on and off.

1. **Validate BOZ scene** reports non-triangle faces, empty geometry, duplicated identities,
   and changed parents.
2. **Save to mod** writes every changed group into `<client>/mods/<mod>/assets/` under its game
   file name, creating the mod if needed. Unchanged groups are not written. Saving again replaces
   the mod's earlier copies; the game's own files are never written.
3. **Import level folder** has **Include mod edits** enabled by default: groups already saved to
   your mod are loaded instead of the game's copies, exactly as the client does. Continue editing
   and save again.
4. Start the game. New mods are enabled automatically (the launcher's Mods tab can disable
   them), so the edits appear the next time the level loads.

Every unknown section and unsupported resource body stays byte-identical. Editing the geometry of
a model that lives in the shared `ingame` group saves a new `ingame.group.bin` in the mod; moving
it changes only the group that places it.

**Build & Run** saves to your mod and starts the game straight into the level. The sidebar's
**Test with** mod (the Developer mod by default) does the starting: Build & Run stores the level
in that mod's settings, and the mod's `require("boz.engine.levels").autostart_from_settings()` runs the front end's `StartLevel`
console command once the menu is up, then clears the request, so a normal launch still shows the
menu. Any mod can be the test mod if it calls `levels.autostart_from_settings()`. The game's output goes to `boz-log.txt` in the client
folder. Build & Run refuses to start while the game is already running, or when the test mod is
missing or switched off. When two enabled mods replace the same file, the one loaded later wins;
if another mod would hide your edits, Build & Run moves your mod to the end of `client.ini`'s
`[mods] order` (the launcher's Mods tab shows the same list) and says so.

The arrow buttons next to **Mod** and **Test with** list the mods already in the client; editing
an existing mod is just choosing it there.

Under **Files**, **Import native group** opens a single `.group.bin`, **Export edited level** writes
changed groups into any folder (for example an SDK project's `assets/`), and **Export edited
group** writes one group to a new file (`<name>-edited.group.bin`, byte-identical without edits).

### Example: a round trip

This walk-through edits Kino in place with the tools above, saves the edits to a mod and plays
them, all from the editor's sidebar and the game:

1. Set **Client** to your `boz-redux` folder. **Import level folder** on `levels/kino`.
2. Move two objects, rotate one, scale one, and raise a small wall of floor collision in
   kino_statics by about a player's height. **Validate**, then **Save to mod**; the status line
   names the groups it saved.
3. **File > New**, then **Import level folder** on `levels/kino` again: every edit is still there.
4. Play Kino with the mod: the objects sit where you put them, shots stop on the raised
   collision, and you can no longer walk through it: saving rebuilt the navmesh around it.
5. Disable the mod in the launcher and play again: everything is back to normal.
