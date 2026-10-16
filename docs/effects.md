# Effects

Scripts can spawn the game's effects and projectiles anywhere, for as long as they want, with
`boz.effects`. A projectile brings the game's own behaviour with it: a Gersch device opens a black
hole that pulls zombies in and kills them, a monkey bomb lures them, a bolt explodes where it
hits.

## The Effects tab

**Game effects** lists everything the game can spawn. **Show** filters it:

- **Effects:** particles and visual effects. The shared ones (impacts, ice, the Gersch device's
  swirl, ...) are on every map; a map's own effects come from that map.
- **Projectiles:** each map's grenades, bolts, lures and devices, with what they do and which
  weapons fire them (Ascension's `bh_bomb projectile` is the Gersch device: "Black hole").

Search by name, map or behaviour. Pick one, give it a **Name** (what scripts call it) and **Use in
this map**. One from another map is carried into your map when it builds, with everything it
needs (its models, materials, textures, and the sounds its behaviour plays).

**This map's effects** lists the ones the map uses: rename or remove them, and **Copy script line**
copies a line of Lua that spawns the selected one where the player aims. A projectile has two
switches, and the build gives the map its own copy of it without what they leave out:

- **Hide its model:** no model (a black hole without the Gersch device lying on the floor).
- **Stays where spawned:** no physics (no gravity or rolling: it stays exactly where a script
  spawns it; a black hole then opens right where the shot lands).

## boz.effects

```lua
local effects = require("boz.effects")

-- A one-off effect, removed after two seconds.
effects.spawn("impactRayGun", effects.aim(), {lifetime = 2})

-- A black hole where the player aims, for six seconds, its swirl at chest height.
local hole = effects.projectile("gersch", effects.aim(), {trigger = "open", lifetime = 6, raise = 200})
hole:remove()               -- or close it early (with its own sound)
```

- `effects.spawn(name, position, options)`: an effect at `{x, y, z}` (game centimetres, y up).
  Options: `rotation` `{x, y, z, w}`, `lifetime` (seconds, then it is removed).
- `effects.projectile(name, position, options)`: a projectile the game runs. Options: `trigger`
  (`"open"`), `lifetime` (seconds), `raise` (centimetres: it floats that far above the position;
  for one that **Stays where spawned**), `hidden` (its own model is not drawn: a black hole
  without the device lying on the floor), `freeze` (stay where spawned instead of settling on the
  floor), `lift` (centimetres up, default 10, so it does not start in the floor; `raise` replaces
  it), `rotation`. It is the
  player's, and so are its kills (zombies turning to a device ask for its owner, so it always has
  one). The game sets a new projectile up a frame after it spawns; the trigger, lifetime and
  hiding are applied then (`:ready()` says when), so scripts need not wait.
- `effects.aim()`: the point the player's crosshair is on (where a shot lands, up to 100 m) and
  whether it is a live zombie.
- `effects.sound(name, position)`: plays a game sound there.
- What they return: `:alive()`, `:ready()`, `:position()`, `:move(position)`,
  `:trigger(name)`, `:hide()`, `:show()`, `:freeze()`, `:lifetime(seconds)`, `:remove()`.

Names are the map's effects (the Effects tab), or the game's own names of the shared effects
(`"gersch_Effect"`, `"impactRayGun"`, `"iceShatter"`, ...), or `"0x..."` hashes.

### What projectiles do

| Behaviour | What it does | Triggers |
| --- | --- | --- |
| Thrown (lifetime) | Grenades: explode after their time | `explode` |
| Bolt | Ray gun, launchers: explode where they hit | `explode` |
| Lure | Monkey bomb: zombies are drawn to it | |
| Black hole | Gersch device: zombies within 50 m walk into it and die within 1.5 m; a player inside is sent to one of the map's Gersch teleport points (a map without them: nothing happens) | `open` |

A black hole's swirl draws about a metre below the device (the device normally lies on the floor
and the swirl model is built downwards from it), so a hole spawned on the floor shows its centre
under the floor: `raise = 200` puts the ball at chest height. A raised black hole kills just as
far around it on the floor: its kill reach grows with the height, so zombies walking under it
still die.

A black hole normally opens once it has come to rest and lasts 8 seconds; `trigger = "open"`
opens it at once and `lifetime` sets how long it stays open.

## Example: the idgun opens a black hole where it fires

In the Effects tab, use Ascension's `bh_bomb projectile` as `gersch` and tick **Hide its model** and
**Stays where spawned**. In the Weapons tab, set the
weapon's **Fire mode** to **Single shot** (a Thundergun-based weapon would otherwise still fire its
own blast; the Thundergun's bullets do no damage, so the black hole does the killing), and give it
a script (**Add script**):

```lua
local effects = require("boz.effects")

-- Every shot: a black hole where the shot lands, for six seconds.
function on_fire(data)
    local where = effects.aim()
    if where then
        effects.projectile("gersch", where, {trigger = "open", lifetime = 6, raise = 200})
    end
end
```

## How it works

From the game's code (Ghidra names in the game definition): `Spawn_ByHash(CSpawnManager, spec
hash, position, rotation)` creates any entity spec a loaded group holds (`Entity_CreateFromSpec`,
then the `CIsTransform`'s position +0xa8 and rotation +0x98, x y z w). A projectile is an entity
with a `CProjectileEntity` whose `behaviourType` (1 thrown, 2 bolt, 4 lure, 6 Gersch device)
decides what `Projectile_UpdateFlight`, `Projectile_UpdateGersch` and `Projectile_Impact` do; it
keeps its lifetime (ms) at +0xc0, its open state at +0xc7 and its owner at +0x88, and takes events
on its subject at +0x28. A Gersch device that receives `SUBJECT_SPAWN_GERSCH_EFFECT` spawns
`gersch_Effect` (shared), plays `gersch_opens` and loops `gersch_loop` (Ascension's sounds), and
counts its lifetime down to `SUBJECT_TERMINATE` (removes the effect, plays `gersch_shuts`). Zombies
(`CAIControllerZombie`) ask `ProjectileManager_FindNearest` for an open device within 5000 units,
walk into it, and die (`SUBJECT_ZOMBIE_GERSCH_DEATH`) within `m_proximityRadius` x 100 (the
projectile's +0x90, metres, measured in 3D from its centre: `raise` widens it to
sqrt(r² + raise²)). The swirl (`gersch_Effect`, a billboard model) spawns at the device's
position and rotation and draws from 22 to 205 units below it.
`WeaponManager_UpdateAim` ray-casts the crosshair every frame into the weapon manager's +0xcc.

The catalog and carrying are `bozkit/effects.py`; the map's effects are `source/effects.json`.
