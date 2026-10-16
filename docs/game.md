# Game rules

The **Game** tab sets a map's rules: its name and loading screen, its rounds, the special rounds,
which zombie looks spawn, the points and power-ups, and scripts that run when things happen. Until
you change a section, the map uses its base level's own rules (shown in the tab); the first change
makes them the map's own (`source/game.json`).

## Level info

- **Name:** the map's name in the launcher and the mod list.
- **Loading screen:** a picture (PNG or JPG) shown while the map loads. It fills the screen at 4:3
  (1024 x 768); the "Loading" text and the tips are drawn over it. Pure magenta (255, 0, 255) shows
  as black.
- **Starting weapon:** set in the Weapons tab (shown here).
- **Power on at the start:** the power is on as soon as the map starts.
- **Behaves like:** some of the game's code checks the map's name. Pick Kino, Ascension or Call of
  the Dead and the level manager's checks answer as that map: Kino's teleport start, Ascension's
  round effects, Call of the Dead's snow camera and start sound (the build brings what they
  play). Other code that compares names itself (Call of the Dead's zombies and Pack-a-Punch,
  Ascension's attack distances) stays with those maps.

## Rounds

Each game has its own rounds: single player on easy, normal and hard, and co-op with 2, 3 or 4
players. Pick one under **Game**, or tick **Same for all** to change every game at once (**Use these
rounds in every game** copies the shown game's rounds to the rest).

The list holds the rounds in order. Each round sets:

| Setting | What it does |
| --- | --- |
| Zombies | how many zombies the round has |
| Health | each zombie's health (an easy game halves it) |
| At once | the most zombies alive at the same time |
| Spawn at start | zombies that spawn as soon as the round starts |
| Walkers, Fast walkers, Runners, Sprinters | the share of zombies at each speed (0-1) |
| Spawn interval | milliseconds between spawns |
| Break after | milliseconds from the round's end to the next round |
| Start delay | milliseconds from the round's start to its first spawn |
| Zombie type | what spawns (empty: the map's zombie) |
| Powered zombies, type and health | extra zombies once the power is on (Kino's crawlers) |
| Fog | the fog the round sets |

The last round can **repeat**: it plays again and again, each time growing by its multipliers
(**Zombies x**, **At once x**, **Spawn interval x**, **Powered zombies x**) once the round number
is past **Grows after round**. For example 25 zombies with Zombies x 1.1 from round 10 gives
round 12 30 zombies (25 x 1.1 x 1.1).

**Repeating health:** the game ignores a repeating round's health and uses 10 x round x round -
150 (round 20: 3850). **Grows by the multiplier** uses the round's **Health** and **Health x**
instead.

The graph on the right shows zombies (orange) and health (blue) for rounds 1 to 40 of the shown
game. **Back to the base level's rounds** forgets the map's own rounds.

## Special rounds

Dog rounds (and Ascension's space monkeys) come between normal rounds. Each is for one game
(**For**). The game runs them in order: one plays **Times** times, then the next takes over. A
special round comes after **At least** and at most **At most** normal rounds, with **Chance**
percent each round in between. **Count by players** is how many spawn with 1, 2, 3 or 4 players.
**Add a special round** makes a dog round to start from.

## Zombie types

A level has a few zombie looks (a skeleton and body part models). Zombies spawn with one of the
ticked looks, picked at random.

## Pickups and economy

Tick a setting to change it on this map (other maps keep the game's values):

- **Points at start**, **Points lost when down** (share of points), **Self revive** cost.
- Power-up drops: **Points between drops**, **Kills between drops**, **Drop chance** (per kill once
  a drop is due), **Drops per round**.
- Power-up times: **Double points**, **Insta-kill**, **Fire sale**, **Death machine** (ms).
- **Change the power-ups:** how likely each power-up is against the others (0: never).
- **Change the points:** points for a hit, each kind of kill, a barricade board, Carpenter and the
  Nuke, and the barricade limit (at most this x the round number per round).
- **Change the mystery box:** its cost, the fire sale cost and how many weapons it shows when it
  spins. A box given its own cost in the World tab keeps it.
- Zombies alive at most, base zombie health, grenades per round.

## Hooks

Every event a script can follow, with **Create** (a stub in `scripts/hooks/<event>.lua`) or
**Open**. The script returns a function that runs every time the event happens:

```lua
-- scripts/hooks/round_started.lua
return function(data)
    log("round " .. data.round)
end
```

The list grows with the standard library.

## How it works

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

`bozkit/game.py` compiles it; `lib/boz/game.lua` and `lib/boz/hooks.lua` run it.
