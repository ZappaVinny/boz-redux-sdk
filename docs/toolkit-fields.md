# Toolkit fields

What each toolkit piece is in the game, which of its fields the editor lets you change, and why
the others stay as they are. The survey covers every entity in the four shipped levels' statics
groups, and every field the game's reflection registers for their components
(`gamedef/reflection`). Shipped data only stores fields that differ from the class default, so
**Default** is the constructor's value where the data leaves a field out.

Fields marked *editor* appear in Properties → Object → Game when the piece is selected. Units:
points, centimetres (cm), seconds (s; the game stores milliseconds).

## Pieces

### Perk machines (`CPerk`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_perkSinglePCost` | — | Points it costs in solo | editor: Cost |
| `m_perkMultiPCost` | 1500 | Points it costs in co-op | editor: Co-op cost |
| `powerSwitch` | 0 | Name of the power switch it waits for. `boz_no_power` makes it work without power (`boz.world` powers it at `CPerk::Init`) | editor: Needs power |
| `CPOI.m_MaxDistance` | 300 | How close players must be to use it (cm) | editor: Use distance |
| `m_numOfUses` | 3 on Quick Revive | Solo Quick Revive uses | no (Quick Revive only) |
| `perkName`, `m_PerkType`, sting | — | Which perk it gives and its jingle | no: pick another machine instead |
| `CHealth.m_MaxHealth` 500 | — | Monkeys attack machines (Ascension) | no |
| `CIsCollisionBox` 150 × 270 × 120 cm | — | The machine's solid box | no |

### Pack-a-Punch (`CPackAPunch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | 5000 | Points an upgrade costs | editor: Cost |
| `powerSwitch` | — | Power switch it waits for; off writes 0 and `m_HasPower` = true | editor: Needs power |
| `CPOI.m_MaxDistance` | 300 | Use distance (cm) | editor |
| `m_HasPower`, `m_State`, `m_WeaponHash`, ... | — | Runtime state | no |

### Mystery box (`CMysteryBox`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_Cost` | 950 | Points a spin costs | editor: Cost |
| `m_FireSaleCost` | 10 | Points a spin costs during a Fire Sale | editor |
| `m_MinWeapons`, `m_MaxWeapons` | 4, 10 | The box moves after a random number of uses between these | editor |
| `m_Weapons` | empty | The weapon pool (empty: the level's) | not yet: needs the Weapons tab |
| `m_RefundCost`, `m_State`, timers | — | Runtime state | no |

The level picks which box location is active (`CLevel` `MysteryBoxStart`, `MysteryBoxAvoid`).

### Power switch (`CPowerSwitch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `StartEnabled` | true | Players can pull it from the start (Ascension's launch switch starts disabled) | editor: Usable from the start |
| `playSound` | — | Sound when pulled | no |

### Wall buy (`CWeaponChalkOutline`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| weapon (`model` child asset name) | — | The weapon it sells | editor: Weapon |
| `m_cost` | — | Points the weapon costs | editor: Cost |
| `m_ammoCost` | 0 (half the cost in game) | Points a refill costs | editor: Ammo cost |
| `m_upgradedAmmoCost` | 0 | Points a refill of the upgraded weapon costs | editor: Upgraded ammo cost |
| chalk decal | the weapon's own | The drawing on the wall (a separate decal) | editor: Chalk |
| `m_weaponType` | — | Prompt type: firearm, melee, grenade | no: follows the weapon |
| `CPOI.m_BiDirection` | true when placed | Usable from either side | set by the compiler |

### Doors and debris (`CDoor`, one design per model in the game)

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

### Window barricade (`CBarricade`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `m_StartBroken` | false | The planks start torn down | editor: Starts broken |
| `CPOI` | 170 cm | Repair reach | no |

### Trap and trap switch (`CTrap`, `CTrapSwitch`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `CTrap.m_ActivePeriodMS` | 30 s | How long it runs once bought | editor: Runs for (s) |
| `CTrap.m_CoolDownPeriodMS` | 10 s | Wait before it can be bought again | editor: Cool-down (s) |
| `CTrap.m_PlayerDamage` | 115 / 230 | Damage to players who walk in | editor |
| `CTrap.damageEffect`, `startSound` | — | Effect and sound | no |
| `CTrapSwitch` cost | 1000 | Points to run the trap | editor: Cost |
| `CTrapSwitch.powerSwitch` | — | Power switch it waits for | editor: Needs power |
| `CTrapSwitch` traps list | — | Which traps it runs | not yet: needs links |

### Spawns (`CSpawnPoint`)

| Field | Default | Meaning | Editor |
| --- | --- | --- | --- |
| `spawnType` | — | windows, ground, Lightning (dogs), Hole, Monkey | the piece you pick |
| `m_StartActive` | false | Used from the first round, not only once players reach its area | editor: Active from the start |

Player spawns are the entities named `spawn_player_1` to `_4`.

### Interact point, jump point, sound emitter

| Piece | Field | Meaning | Editor |
| --- | --- | --- | --- |
| Interact point | `CPOI.m_MaxDistance` | Use distance (cm); scripts get "use" | editor |
| Jump point | `m_jumpAreaHash` | The jump area zombies cross to | no: linked by the level |
| Sound emitter | `soundName` | The sound it plays | editor: Sound |
| Sound emitter | `StartEnabled` | Plays from the start | editor: Plays from the start |

## Points of interest (`CPOI`)

Everything players use has a `CPOI`. `m_poiType` picks the prompt: 0 barricade, 1 door, 2 wall
buy, 3 box, 4 perk, 5 Pack-a-Punch, 6 trap switch, 7 power, 8 turret, 9 teleporter, 10 mainframe,
11 lander, 12–13 lander station, 14 revive, 15 claymore, 16 tutorial pickup
(`LevelManager_UpdateNearestPoi`, `CIngameStatePlaying::OnEvent`). The other fields set the reach:
`m_MaxDistance` (cm), `m_ViewingAngle`, `m_AngleDistanceOffset`, `m_HeightOffset`,
`m_MaxYDistance`, `m_BiDirection` (either side), `m_Moveable`, `m_IsReverseViewAngle`. Pressing
use runs `Poi_SendUse`, which broadcasts the interact event to the entity in reach.

## Not pieces yet

These are in the shipped levels; each needs its own piece or links before it is useful:

- Turret (`CTurret`: cost, duration, damage, range, rate of fire, cool-down, power).
- Teleporter, mainframe and Gersch points (`CTeleporter`, `CTeleportMainframe`, `CTeleportPointGersch`).
- Rides: lunar landers, zipline, flinger, centrifuge, ice slide (Ascension, Call of the Dead).
- Animated scenery, TV and projector screens, fog effects, lights.
