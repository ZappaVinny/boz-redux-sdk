# Weapons

The editor's **Weapons** tab changes the weapons of a map project: their damage, fire rate, ammo,
spread and the rest of the game's weapon data, new weapons made from existing ones, and weapons
imported from other maps. Changes are saved as you make them and applied when the map builds.

## The tab

- **The viewport** shows the selected weapon as the player sees it: the arms in their idle pose
  holding the gun, through the game's eye (65 degrees of vertical view), with the game's
  textures. It follows the weapon you select; a new weapon shows its base's gun, an imported one
  its own map's. The viewport's header switches between **First person** and **Free view** (move
  around the gun like any Blender view) and shows or hides the **Arms**.
- **Animations** plays the weapon's animations in the viewport: pick one (raising, idle,
  shooting, reloading, aiming, sprinting, ...), then Play, Loop or drag the Frame slider. They run
  at the game's 24 frames a second. States whose names are not known yet are numbered. Viewing
  only for now; replacing animations comes later.

- **The list** shows the project's weapons. A map made from a whole shipped level lists its guns;
  an Empty or Debug map starts with the Colt alone. The list is what wall buys and the mystery
  box offer. Icons: a pencil for a changed weapon, a plus for a new one, an arrow for one from
  another map.
- **Import from game** adds a weapon: one of the map's own, or another map's (Call of the Dead's
  V-R11, Scavenger and Wunderwaffe DG-2, Ascension's matryoshka dolls and minigun, ...). An
  imported weapon brings its models, skins, skeleton, animations, animation state machines and
  projectile. Its sounds, effects and special behaviour belong to its own map and are not
  brought over: plain guns work, but a wonder weapon (V-R11, Wunderwaffe) crashes the game when
  it hits a zombie. Give a weapon special behaviour with a Lua script (**Add script**) instead.
- **New weapon** copies the selected weapon under a new name: same model and animations, your
  values.
- **Properties** lists every field, grouped. Each shows its unit; the **?** button explains it;
  the arrow resets a changed value. A `*` marks a meaning read from the shipped weapons that the
  game's code has not proven yet.
- **Pack-a-Punch result** picks the weapon an upgrade turns it into.
- **Starting weapon** (tick box): players start with this weapon instead of the Colt, with its
  **spare rounds** (the game's default is 40); they still get the knife and two grenades. Untick
  it to go back to the Colt. It applies to this map only: other maps keep the Colt.
- **Script** (optional) adds a Lua script for special behaviour: see below.

Wall buys pick from the project's list (World tab → the wall buy's **Choose…**); a mystery box's
**Weapon pool** (its settings → **Edit…**) picks which listed weapons it rolls.

## What a weapon is

Each map has a weapons group (`ingame/weapons/weapons_<map>`): one entity per weapon with a
`CPlayerWeapon` component, plus the weapon's models, skins, skeleton, animations and two animation
state machines (the arms' and the gun's; the arms' live in `arms_<map>`). The fire mode is a
class the game makes from **Fire mode** (`CPlayerWeapon::CreateBehaviour`): automatic modes fire
at **Fire rate**; single-shot weapons fire as fast as their fire animation plays, and a reload
lasts as long as its animation (the bullet and the end of a reload are events in the animations),
so those two come with the animation tools, not this form.

Project files: `source/weapons/index.json` (the list) and `source/weapons/<name>.json` for each
changed, new or imported weapon:

```json
{"name": "mp40_heavy", "base": "mp40", "level": "", "fields": {"m_clipSize": 50,
 "m_damage.m_headDamage": 900, "Upgrade": "Afterburner"}, "script": "weapons/mp40_heavy.lua"}
```

`base` is the weapon it is made from (empty: itself), `level` the map it is imported from (empty:
this map's own). The game names weapons in its prompts from its own text, which has no entry for
a new weapon's name yet, so a wall buy selling one may show no name.

## Weapon scripts and boz.weapons

A weapon script runs with `self` as the weapon: `self.name`, and the live weapon's methods.

```lua
-- weapons/mp40_heavy.lua
shots = 0                       -- saved with the game, like any script global

function on_fire(data)          -- every shot (data.clip: rounds before it)
    shots = shots + 1
    if shots % 10 == 0 then self:set_ammo(nil, self:reserve() + 5) end
end

function on_equip() end         -- taken in hand
function on_given() end         -- bought, rolled from the box, or given by a script
function on_reload() end        -- a reload started
```

Any script can use `boz.weapons` (require("boz.weapons")): `current()`, `get(name)`,
`give(name)`, and on a weapon `clip()`, `reserve()`, `set_ammo(clip, reserve)`, `clip_size()`,
`damage()`, `set_damage(head, torso, limbs)`, `fire_rate()`, `set_fire_rate(rpm)`, `in_hand()`.
These change the weapon for the match; the Weapons tab changes it for good. Game events on the
bus: `weapon_given`, `weapon_equipped`, `weapon_reloaded` (`data.weapon`); `weapon_fired` reaches
`boz.on` listeners only (every shot).

## Field reference

<!-- fields:start -->
### Firing

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Fire mode | `behaviour` |  | Single shot | How the weapon fires (CPlayerWeapon::CreateBehaviour). Automatic, Automatic shotgun and Death Machine keep firing while the trigger is held. Values: 0 Melee / no gun, 1 Single shot, 2 Automatic, 3 Burst, 4 Shotgun, 5 Automatic shotgun, 6 Revolver, 7 Grenade, 8 Special grenade, 9 Launcher, 10 Death Machine, 11 Claymore, 12 Monkey bomb, 15 Thundergun, 16 V-R11, 17 Wunderwaffe. |
| Fire rate | `autoROF` | rounds/min | 0 | Automatic modes only (MP40 535, AK-74u 750). Single-shot weapons fire as fast as their fire animation plays. |
| Burst size | `semiBurst` | rounds | 0 | Rounds per trigger pull (Burst). *Likely (from the shipped weapons).* |
| Fires only when aiming | `requiresADS` |  | False | The trigger does nothing unless the player aims down sights. |
| Aim assist | `autoAim` |  | True | The crosshair is pulled toward zombies. *Likely (from the shipped weapons).* |
| Recoil | `recoil` |  | None | How much the view kicks per shot. Values: 0 None, 1 Light, 2 Medium, 3 Heavy. *Likely (from the shipped weapons).* |

### Ammo

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Clip | `m_clipSize` | rounds | 0 | Rounds in one magazine. |
| Reserve | `m_ammoSize` | rounds | 0 | Spare rounds carried besides the clip (Colt: 8 + 80). |
| Reloads one at a time | `loopedReload` |  | False | Rounds go in one by one and the reload can be cut short (pump shotguns). |
| Two shells per step | `doubleShellReload` |  | False | A looped reload loads two shells each step. *Likely (from the shipped weapons).* |
| Taped magazines | `flipClipReload` |  | False | Every other reload uses the second (flipped) magazine animation. |
| Ammo pickup when empty | `lightningBoltPickup` |  | False | When the weapon runs dry the pickup manager is told (shipped weapons leave it off). *Likely (from the shipped weapons).* |

### Damage

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Head | `m_damage.m_headDamage` | points | 0 | Damage of a hit to the head (MP40 400). |
| Torso | `m_damage.m_torsoDamage` | points | 0 | Damage of a hit to the body (MP40 100). |
| Limbs | `m_damage.m_limbDamage` | points | 0 | Damage of a hit to an arm or leg (MP40 100). |
| Falloff starts | `m_falloff.m_startDistance` | cm | 0 | Full damage up to this distance (shotguns 400, Thundergun 1200). |
| Falloff ends | `m_falloff.m_endDistance` | cm | 0 | Distance where damage reaches the falloff damage (shotguns 800). |
| Falloff damage | `m_falloff.m_damageMod` | % | 0 | Damage left at the end distance (shotguns 50). *Likely (from the shipped weapons).* |
| Penetration | `m_penetration.m_penetrationRating` |  | 1 | How far bullets go through zombies and thin surfaces (rifles 10, shotguns 15). *Likely (from the shipped weapons).* |
| Penetration loss | `m_penetration.m_damageFalloff` | % | 0.0 | Damage lost each time a bullet goes through something (30 to 50). *Likely (from the shipped weapons).* |
| Penetration minimum | `m_penetration.m_damageMin` | points | 0 | Damage never drops below this after going through things. *Likely (from the shipped weapons).* |
| Fire rounds | `incendiaryRounds` |  | False | Hits set zombies on fire (Hades, the upgraded Olympia). *Likely (from the shipped weapons).* |
| Melee range | `m_meleeRange` | m | 0.0 | Reach of a melee weapon (knives 1.5). *Likely (from the shipped weapons).* |

### Accuracy

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Spread, steady | `m_accuracy.m_spreadMin` |  | 0.0 | Bullet spread when still and not firing (crosshair size; Colt 0.28). |
| Spread, moving | `m_accuracy.m_spreadMax` |  | 1.0 | Bullet spread at its widest, while moving or firing (Colt 0.525). |
| Crouched | `m_accuracy.m_modCrouched` | x | 1.0 | Spread multiplier while crouched (0.85: 15% tighter). |
| Prone | `m_accuracy.m_modProne` | x | 1.0 | Spread multiplier while prone. |
| Crosshair | `m_accuracy.m_crosshairType` |  | Standard | The crosshair drawn for this weapon. Values: 0 None, 1 Standard, 2 Launcher, 3 Minigun, 4 Thundergun. |

### Aiming

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Aiming field of view | `m_ADSFoV` | degrees | 0.0 | Field of view while aiming down sights (MP40 40, AK-74u 30); 0 keeps the normal view. |

### Projectile

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Projectile | `m_projectileName` |  | 0 | What a launcher or grenade throws (an entity of weapon_projectiles). |
| Launch force | `m_projectileLaunchForce` |  | 0.0 | Speed the projectile leaves with (Thundergun 3000). *Likely (from the shipped weapons).* |

### Pack-a-Punch

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Pack-a-Punch result | `Upgrade` |  | 0 | The weapon Pack-a-Punch turns this one into (none: it cannot be upgraded). |
| Pack-a-Punch sound | `m_playPAPSound` |  | False | Plays the upgraded-weapon sound when fired. *Likely (from the shipped weapons).* |
| Once per game | `isUnique` |  | False | The mystery box gives it only once (Thundergun). *Likely (from the shipped weapons).* |
| Weak weapon | `crappyWeapon` |  | False | Marked as a poor weapon (set on the CZ75 only). *Likely (from the shipped weapons).* |

### HUD

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Ammo icon | `ammoIcon` |  | None | The ammo symbol on the HUD. Values: 0 None, 1 Rifle, 3 Shotgun shells, 4 Grenade launcher, 8 Belt / large, 9 Pistol, 10 Grenade, 11 Claymore, 12 Monkey bomb. |

### Sounds

| Field | Key | Unit | Default | What it does |
| --- | --- | --- | --- | --- |
| Fire | `fireSoundSequence` |  | 0 | Played on every shot. |
| Last round | `m_fireLastBulletSoundSequence` |  | 0 | Played on the last round of a clip. |
| Empty click | `fireEmptySound` |  | 0 | Firing with no ammo. |
| Reload | `reloadSoundSequence` |  | 0 | A full reload. |
| Reload (rounds left) | `reloadPartialSequence` |  | 0 | A reload with rounds still in the clip. |
| Bought | `buySound` |  | 0 | Played when it is bought. |
| Bought (player) | `playerBuySound` |  | 0 | The buyer's own purchase sound. |
| Muzzle flash | `muzzleFlash` |  | 0 | The muzzle flash effect. |

<!-- fields:end -->
