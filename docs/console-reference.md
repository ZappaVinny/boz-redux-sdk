# Console reference

Every console variable (cvar) and developer command in *Call of Duty: Black Ops Zombies*
1.0.11, generated from the game definition (`gamedef/console/boz-1.0.11.toml`) and the
notes in `tools/symbols/console_notes.toml`. Regenerate with
`python3 tools/symbols/symbols.py console-doc gamedef/console/boz-1.0.11.toml tools/symbols/console_notes.toml docs/console-reference.md`; do not edit by hand.

## How to use them

Open the Developer mod's console (`` ` `` or F1) and type:

- `Name` prints a variable's value; `Name value` sets it (booleans: `true` / `false`;
  arrays: `{1,2,3}`; graphs are `x,y;x,y;` points).
- `Command arguments` runs a command. `+Name` / `-Name` commands are key press and
  release pairs, meant for key bindings.
- `find text` searches this list; `listVars` and `listCommands` ask the game what is
  registered right now.

Not everything exists all the time. Variables are registered when the code that uses them
first runs, so many appear only once a match has started. Commands belong to a game
system and only answer while it exists (the **Available** column).

Columns: **Type** is the console type; **Default** is the value the game registers;
**Used by** is the function that registers or reads it, where known. **Status** records
in-game testing (works, partial, no effect, crashes); blank means untested.

Known gaps: 19 registrations could not be named by static analysis, so they are missing
here. Variables marked *lookup only* are read by the game but never registered: setting
them fails until something registers them.

Counts: 664 variables, 148 commands.

## Commands

### Built into the console

Available: always.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `cvar` | `<name> <value>` | No handler in the release build: does nothing. The Developer mod's own `cvar <name> <value> [type]` registers the variable through Cvar_Register*, which makes lookup-only variables (StartingScore) work. |  |
| `bind` | `<key> <command>` | No handler in the release build: does nothing. The Developer mod's own `bind <key> <line>` works (this session only). |  |
| `unbindAll` |  | Removes all key bindings. |  |
| `alias` | `<name> <command>` | Makes a name run a command line. |  |
| `help` |  | No handler in the release build. The Developer mod answers `help` itself. |  |
| `listCommands` | `[filter]` | Prints registered commands whose names start with filter. |  |
| `listVars` | `[filter]` | Prints registered variables whose names start with filter. |  |
| `listAliases` | `[filter]` | Prints aliases. |  |
| `listBindingSets` | `[filter]` | Prints binding sets (GameStateIngame, BOPlayerControlsWin, XperiaPlayBO, ...). |  |
| `bindingSetActivate` | `<set>` | Activates a binding set. |  |
| `bindingSetDeactivate` | `<set>` | Deactivates a binding set. |  |
| `saveConsole` |  | Saves console variables (CIwConsole::SaveVars). |  |

### CGameStateIngame

Available: Zombies match.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `ShowMessage` |  |  |  |
| `StartLevel` |  |  |  |
| `TimeFactor` | `<factor>` | Game speed multiplier (1 = normal). |  |
| `TimeTogglePause` |  | Pauses or resumes game time. | works |

### CIngameStatePlaying

Available: Zombies match, playing.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `pauseMenu` |  |  |  |
| `toggleactive` |  |  |  |

### CLevelManager

Available: Zombies match.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `BaddieInteract` |  |  |  |
| `GoodieInteract` |  |  |  |
| `PlayerDie` |  |  |  |
| `RestartLevel` |  |  |  |
| `RunOutOfMemory` |  |  |  |
| `SendMessage` |  |  |  |
| `SwitchPowerOn` |  | Turns the map's power on. | works |

### CWaveManager

Available: Zombies match (rounds).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `KillAllWaveZombies` |  | Zombies: kills the zombies of the current round. |  |
| `KillAllZombies` |  | Zombies: kills every zombie. | works |
| `SpawnWaveZombie` |  | Zombies: spawns a zombie that counts toward the current round. |  |
| `SpawnZombie` |  | Zombies: spawns one zombie. | works |
| `StartWave` |  | Zombies: starts the next round. | works |

### CSpawnManager

Available: Zombies match (spawning).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `spawnEntity` |  |  |  |
| `spawnEntityLoop` |  |  |  |
| `ToggleSpawnPoint` |  |  |  |

### CPlayerController

Available: Zombies match (player).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `EnableLazarusEffect` |  |  |  |
| `KillPlayer` |  | Kills the local player. |  |

### CPlayerWeapon

Available: Zombies match (player weapon).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `ammoLow` |  |  |  |
| `ammoOut` |  |  |  |

### CPerkManager

Available: Zombies match (perks).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `EnablePerk` |  | No handler in the release build: does nothing. The Developer mod's `perks` command grants all perks through CPerkManager::GainPerk. | no effect |
| `ResetAllPerks` |  | Removes the player's perks. |  |

### CVFXManager

Available: Zombies match (effects).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `SwitchFog` |  |  |  |

### CWorld

Available: match (world).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `CamSet` |  |  |  |

### CTeleportManager

Available: Kino der Toten match (teleporters).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `GerschTeleportRandom` |  |  |  |
| `StartTeleportLobby` |  |  |  |
| `StartTeleportProjector` |  |  |  |
| `StartTeleportRandom` |  |  |  |

### CLighthouse

Available: Shi No Numa / map with a lighthouse.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `LighthouseState` |  |  |  |

### CRocketLauncher

Available: Ascension match (rocket).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `RocketAuthenticate` |  |  |  |
| `RocketLaunch` |  |  |  |

### CTutorialManager

Available: tutorial.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `NextTutorial` |  |  |  |

### CIngameStatePaused

Available: Zombies pause menu.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DeviceBack` |  |  |  |
| `Resume` |  |  |  |

### CIngameStateOptions

Available: Zombies options menu.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DeviceBack` |  |  |  |
| `toggleactive` |  |  |  |

### CIngameStateSensitivity

Available: Zombies sensitivity menu.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DeviceBack` |  |  |  |

### CGameStateFrontEnd

Available: main menu.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DeviceBack` |  |  |  |
| `StartLevel` |  |  |  |

### CGame

Available: always.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `BenchmarkTakeSnapshot` |  |  |  |
| `CalculateSoundMemory` |  |  |  |
| `fr` |  |  |  |
| `ger` |  |  |  |
| `it` |  |  |  |
| `ReloadShaders` |  |  |  |
| `ResetAchievements` |  |  |  |
| `ToggleVFXViewer` |  |  |  |
| `VFXViewerBindMaterial` |  |  |  |
| `VFXViewerBindTexture` |  |  |  |

### CIwGame

Available: always.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `overdraw` |  |  |  |
| `textures` |  |  |  |
| `wireframe` |  | Toggles wireframe rendering. | works |

### CIsBulletWorld

Available: always.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `BulletPhysicsEnabled` |  |  |  |

### CIwFreeCameraController

Available: free camera active.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `+FreeCamLower` |  |  |  |
| `+FreeCamMouseStrafe` |  |  |  |
| `+FreeCamMoveDown` |  |  |  |
| `+FreeCamMoveIn` |  |  |  |
| `+FreeCamMoveLeft` |  |  |  |
| `+FreeCamMoveOut` |  |  |  |
| `+FreeCamMoveRight` |  |  |  |
| `+FreeCamMoveUp` |  |  |  |
| `+FreeCamRaise` |  |  |  |
| `+FreeCamRotateDown` |  |  |  |
| `+FreeCamRotateLeft` |  |  |  |
| `+FreeCamRotateRight` |  |  |  |
| `+FreeCamRotateUp` |  |  |  |
| `+FreeCamSlow` |  |  |  |
| `+FreeCamSpeed` |  |  |  |
| `+FreeCamStrafeLeft` |  |  |  |
| `+FreeCamStrafeRight` |  |  |  |
| `-FreeCamLower` |  |  |  |
| `-FreeCamMouseStrafe` |  |  |  |
| `-FreeCamMoveDown` |  |  |  |
| `-FreeCamMoveIn` |  |  |  |
| `-FreeCamMoveLeft` |  |  |  |
| `-FreeCamMoveOut` |  |  |  |
| `-FreeCamMoveRight` |  |  |  |
| `-FreeCamMoveUp` |  |  |  |
| `-FreeCamRaise` |  |  |  |
| `-FreeCamRotateDown` |  |  |  |
| `-FreeCamRotateLeft` |  |  |  |
| `-FreeCamRotateRight` |  |  |  |
| `-FreeCamRotateUp` |  |  |  |
| `-FreeCamSlow` |  |  |  |
| `-FreeCamSpeed` |  |  |  |
| `-FreeCamStrafeLeft` |  |  |  |
| `-FreeCamStrafeRight` |  |  |  |

### CIwCircleCameraController

Available: circle camera active.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `+CircleCamDown` |  |  |  |
| `+CircleCamIn` |  |  |  |
| `+CircleCamLeft` |  |  |  |
| `+CircleCamOut` |  |  |  |
| `+CircleCamRight` |  |  |  |
| `+CircleCamUp` |  |  |  |
| `-CircleCamDown` |  |  |  |
| `-CircleCamIn` |  |  |  |
| `-CircleCamLeft` |  |  |  |
| `-CircleCamOut` |  |  |  |
| `-CircleCamRight` |  |  |  |
| `-CircleCamUp` |  |  |  |

### CGameStore

Available: always (in-app store).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `buyProductByName` |  |  |  |
| `testFreeCODPointsUnlock` |  |  |  |

### CGameNetwork

Available: always (network and DemonWare tests).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DebugFakeLogin` |  |  |  |
| `JoinRoom` |  |  |  |
| `LeaveCurrentRoom` |  |  |  |
| `PublishRoom` |  |  |  |
| `StartSearchRooms` |  |  |  |
| `StopSearchRooms` |  |  |  |

### IwDemonware

Available: online services (DemonWare; to be removed).

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `dwCreateAccount` |  |  |  |
| `dwCreateRoom` |  |  |  |
| `dwJoinRoom` |  |  |  |
| `dwListRooms` |  |  |  |
| `dwLogin` |  |  |  |

### CDOGameStateIngame

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `LoadResults` |  |  |  |
| `LoadSilverbackCutscene` |  |  |  |
| `SetRound` | `<round>` | Dead Ops Arcade: jumps to a round. |  |
| `TimeFactor` | `<factor>` | Game speed multiplier (1 = normal). |  |
| `TimeTogglePause` |  | Pauses or resumes game time. | works |

### CDOHordeManager

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `spawnEnemy` |  | Dead Ops Arcade: spawns an enemy. |  |
| `toggleEnemySpawn` |  | Dead Ops Arcade: zombie spawning on or off. |  |

### CDOIngameStateOptions

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DeviceBack` |  |  |  |

### CDOIngameStatePaused

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DeviceBack` |  |  |  |
| `Resume` |  |  |  |

### CDOIngameStatePlaying

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `pauseMenu` |  |  |  |
| `toggleactive` |  |  |  |

### CDOIngameStateResult

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `CamCycle` |  |  |  |

### CDOPersistentStorage

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `GodMode` |  |  |  |
| `InfiniteBombBoost` |  |  |  |
| `ManyLives` |  |  |  |

### CDOPickupManager

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `spawnPickup` |  |  |  |

### CDOPlayerController

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `AutoAim` |  |  |  |
| `SpawnDeathGems` |  |  |  |

### CDORoundManager

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `CamCycle` |  |  |  |
| `CastShadowFromFreeCamera` |  |  |  |
| `DODeviceFreeCam` |  |  |  |

### CDOUIHud

Available: Dead Ops Arcade.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `DOAccelerometerTouchFire` |  |  |  |
| `DOAccelStick` |  |  |  |
| `DODuelStick` |  |  |  |

### Unknown owner

Available: unknown owner.

| Command | Arguments | Notes | Status |
| --- | --- | --- | --- |
| `+FreeCamMouseStrafe` |  |  |  |
| `+FreeCamSlow` |  |  |  |
| `+FreeCamSpeed` |  |  |  |
| `-FreeCamMouseStrafe` |  |  |  |
| `-FreeCamSlow` |  |  |  |
| `-FreeCamSpeed` |  |  |  |

## Variables

### Dead Ops Arcade

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `doAchievementEasyRhinoKillCount` | int | `20` | CDOPlayerController::vf23 |  |  |
| `doAchievementWholeNineYardsFireTime` | int | `2` | CDOPersistentStorage::vf6 |  |  |
| `doAnaloguePadAimingResponse` | graph | `0,0;4096,4096;` |  |  |  |
| `doAnaloguePadMovingResponse` | graph | `0,0;4096,4096;` |  |  |  |
| `doArmouryChance` | int | `20` |  |  |  |
| `doArmouryUnlock` | int | `5` |  |  |  |
| `doArrowDisplayTime` | int | `4` |  |  |  |
| `doAutoAimAngleWeight` | float | `0.7` |  |  |  |
| `doAutoAimConeLength` | float | `2000` |  |  |  |
| `doAutoAimHorizAngle` | floatangle | `15` |  |  |  |
| `doAutoAimVertAngle` | floatangle | `15` |  |  |  |
| `doBattleChickenApproachSpeed` | graph | `0,0;300,4096;` |  |  |  |
| `doBattleChickenDragCoeffient` | float | `0.1` | CDOBattleChickenBodyHandler::vf24 |  |  |
| `doBattleChickenFlightHeight` | float | `120` | CDOPlayerController::vf23 |  |  |
| `doBattleChickenLife` | int | `20000` | CDOPickupSpawn::vf25 |  |  |
| `doBattleChickenMaxAcceleration` | float | `10.0` | CDOBattleChickenBodyHandler::vf24 |  |  |
| `doBattleChickenSpinSpeed` | float | `3.0` | CDOBattleChickenController::vf24 |  |  |
| `doBattleFollowDistance` | float | `300` |  |  |  |
| `doBodyLifetime` | int | `20000` |  |  |  |
| `doBombDropHeight` | float | `2000` |  |  |  |
| `doBonusGap` | int | `2` |  |  |  |
| `doBonusRoomMusic` | string | `temple` |  |  |  |
| `doBootsDuration` | int | `10000` | CDOPickupBoots::vf24 |  |  |
| `doBootsSpeed` | float | `1.3` |  |  |  |
| `doBuffaloMinMaxX` | floatarray | `{-2000,2000}` | CDOBuffalo::vf23 |  |  |
| `doBuffaloMinMaxZ` | floatarray | `{-2000,2000}` | CDOBuffalo::vf23 |  |  |
| `doBuffaloSpawnDelayTime` | int | `1000` | CDORoundManager::vf11 |  |  |
| `doDeathGemStartDistance` | float | `100.0` |  |  |  |
| `doDeathGemStartHeight` | float | `50.0` |  |  |  |
| `doDeathGemStartImpulse` | float | `100.0` |  |  |  |
| `doFadeInTime` | int | `1000` |  |  |  |
| `doFadeOutTime` | int | `1000` |  |  |  |
| `doFateChance` | int | `30` |  |  |  |
| `doFateLightningSpawnHeight` | float | `1000` | CDOFateBonusTrigger::vf23 |  |  |
| `doFateMaxTriggers` | int | `4` |  |  |  |
| `doFatePickupAcceleration` | float | `7000` | CDOPickupFate::vf22 |  |  |
| `doFateSpawnHeight` | float | `1000` | CDOPlayerController::vf23 |  |  |
| `doFateTimeout` | int | `5000` | CDORoomOfFateHelper::vf8 |  |  |
| `doFlameDeceleration` | float | `1500` |  |  |  |
| `doFlameSizeIncrease` | float | `2.5` |  |  |  |
| `doFlamingBarrelSpawnInterval` | intarray | `{1000,3000}` |  |  |  |
| `doFreezeZombie` | bool | `false` |  |  |  |
| `doGoldenBuffaloNumPickups` | intarray | `{1,5}` | CDOBuffalo::OnEvent |  |  |
| `doGoldenBuffaloProportion` | float | `0.1` | CDORoundManager::vf11 |  |  |
| `doGoreLife` | floatarray | `{0.3,1.0}` | CDOGore::CDOGore |  |  |
| `doGoreMaxRange` | floatarray | `{0.2,1.0}` | CDOGoreManager::CDOGoreManager |  |  |
| `doGravity` | float | `980.6650391` | CDOAIControllerBossSilverback::vf23 |  |  |
| `doHelicopterDragCoeffient` | float | `0.1` | CDOHelicopterBodyHandler::vf24 |  |  |
| `doHelicopterFlightHeight` | float | `100.0` | CDOHelicopterBodyHandler::vf22 |  |  |
| `doHelicopterMaxAcceleration` | float | `10.0` | CDOHelicopterBodyHandler::vf24 |  |  |
| `doHelicopterTilt` | graph | `0.0,0.0;2.0,0.2;` | CDOHelicopterBodyHandler::vf24 |  |  |
| `doHelicopterTurnDamping` | float | `0.1` |  |  |  |
| `doHelicopterTurnElasticity` | float | `0.1` |  |  |  |
| `doHerdeDelayTime` | intarray | `{1000,5000}` | CDORoundManager::vf11 |  |  |
| `doHerdeSize` | intarray | `{3,5}` | CDORoundManager::vf11 |  |  |
| `doJumpDrop` | float | `10.0` |  |  |  |
| `doJumpVelocityDampening` | float | `0.8` |  |  |  |
| `doLightningFlashCount` | intarray | `{1,3}` | CDORoundManager::vf11 |  |  |
| `doLightningFlashTime` | intarray | `{10,60}` | CDORoundManager::vf11 |  |  |
| `doLightningSpeed` | float | `-800` |  |  |  |
| `doLightningStrikeWaitTime` | intarray | `{1000,10000}` | CDORoundManager::vf11 |  |  |
| `doMaxBuffaloSpawnPoint` | int | *lookup only* | CDORoundManager::CDORoundManager |  |  |
| `doMaxChickens` | int | `5` |  |  |  |
| `doMaxFlamingBarrelSpawnPoint` | int | *lookup only* | CDORoundManager::CDORoundManager |  |  |
| `doMaxNextRoundTriggers` | int | *lookup only* | CDORoundManager::CDORoundManager |  |  |
| `doMaxPickupSpawnPoints` | int | *lookup only* | CDOPickupManager::CDOPickupManager |  |  |
| `doMaxSilverbackBossSpawnPoint` | int | *lookup only* | CDORoundManager::CDORoundManager |  |  |
| `doMaxTeslaSpawnPoints` | int | *lookup only* | CDORoundManager::CDORoundManager |  |  |
| `doMaxZombieSpawnPoints` | int | *lookup only* | CDOHordeManager::CDOHordeManager |  |  |
| `doMetallicBallArcingRange` | float | `100` |  |  |  |
| `doMetallicBallCount` | int | `4` | CDOPickupPlayerShield::vf24 |  |  |
| `doMetallicBallDistance` | float | `200.0` |  |  |  |
| `doMetallicBallSpinSpeed` | float | `2.0` |  |  |  |
| `doMoarSpawnPoints` | intarray | `{4,18,34}` |  |  |  |
| `doMultiplayerDeadDownTime` | int | `90000` |  |  |  |
| `doMutliplierBracket` | intarray | `{1000,1500,2500,4500,6500,9000,12000,16000,22500}` | CDOPersistentStorage::CDOPersistentStorage |  |  |
| `doNetworkPositionThresholdSqr` | int | `15000` | CDOTransformSynchroniser::vf23 |  |  |
| `doNetworkRotationThreshold` | float | `0.174532` | CDOTransformSynchroniser::vf23 |  |  |
| `doNumWaves` | floatarray | `{3,30}` |  |  |  |
| `doOilDrumCount` | int | `2` | CDOPickupPlayerShield::vf24 |  |  |
| `doOilDrumDistance` | float | `200.0` |  |  |  |
| `doOilDrumOutwardReleaseMass` | float | `1.0` | CDOSpinningShieldBarrel::vf23 |  |  |
| `doOilDrumSpinSpeed` | float | `2.0` |  |  |  |
| `doPickupArmouryMaxSpawn` | int | `5` |  |  |  |
| `doPickupArmouryMinItemsPerSpawnpoint` | int | `6` |  |  |  |
| `doPickupArmouryMinSpawn` | int | `5` |  |  |  |
| `doPickupBonusMaxItemsPerSpawnpoint` | int | `10` | CDOPickupManager::vf2 |  |  |
| `doPickupBonusMaxSpawn` | int | `4` | CDOPickupManager::vf2 |  |  |
| `doPickupBonusMinItemsPerSpawnpoint` | int | `8` | CDOPickupManager::vf2 |  |  |
| `doPickupBonusMinSpawn` | int | `4` | CDOPickupManager::vf2 |  |  |
| `doPickupRadius` | float | `50.000000` |  |  |  |
| `doPickupRoundBeginMaxItemsPerSpawnpoint` | int | `10` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundBeginMaxSpawn` | int | `4` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundBeginMinItemsPerSpawnpoint` | int | `2` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundBeginMinSpawn` | int | `1` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundCompleteMaxItemsPerSpawnpoint` | int | `10` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundCompleteMaxSpawn` | int | `4` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundCompleteMinItemsPerSpawnpoint` | int | `2` | CDOPickupManager::vf2 |  |  |
| `doPickupRoundCompleteMinSpawn` | int | `3` | CDOPickupManager::vf2 |  |  |
| `doPickupWaveCompleteMaxItemsPerSpawnpoint` | int | `10` | CDOPickupManager::vf2 |  |  |
| `doPickupWaveCompleteMaxSpawn` | int | `4` | CDOPickupManager::vf2 |  |  |
| `doPickupWaveCompleteMinItemsPerSpawnpoint` | int | `2` | CDOPickupManager::vf2 |  |  |
| `doPickupWaveCompleteMinSpawn` | int | `1` | CDOPickupManager::vf2 |  |  |
| `doPlayerJumpDuration` | float | `2` | CDOIngameStateResult::vf11 |  |  |
| `doPlayerRepelFactor` | float | `0.75` | CDOPlayerController::vf23 |  |  |
| `doPlayerSpawnRadius` | float | `150` |  |  |  |
| `doPlayerSpecs` | string |  |  |  |  |
| `doPointsPerBonusLife` | int | `200000` |  |  |  |
| `doRainbowRingRepelSpeed` | graph | `0,0;300,4096;` | CDOAIController::vf24 |  |  |
| `doRainbowRingTrapDistance` | float | `210` | CDOAIController::vf24 |  |  |
| `doRainbowShieldBaseRadius` | float | `203` |  |  |  |
| `doRainbowShieldContractTime` | int | `1000` | CDOShieldRainbow::vf24 |  |  |
| `doRainbowShieldExpandTime` | int | `1000` | CDOShieldRainbow::vf24 |  |  |
| `doRainbowShieldMaxScale` | float | `1.5` | CDOShieldRainbow::vf24 |  |  |
| `doResultsGravity` | float | `3000` |  |  |  |
| `doReturnToSpawnPointDistance` | float | `200` | CDOAIController::vf24 |  |  |
| `doReviveDownTime` | int | `2000` |  |  |  |
| `doReviveEffectActiveTime` | int | `9000` | CDOPlayerController::vf23 |  |  |
| `doReviveEffectAnimatePeriod` | float | `1000.0` |  |  |  |
| `doReviveEffectColour` | intarray | `{0,255,0,255}` |  |  |  |
| `doReviveEffectHalfTime` | int | `4000` |  |  |  |
| `doReviveEffectMaxScale` | float | `1.0` |  |  |  |
| `doReviveEffectTimeRemainingWarnBegin` | int | `1000` |  |  |  |
| `doReviveEffectTimeRemainingWarnEnd` | int | `500` |  |  |  |
| `doReviveEffectWarningColour` | intarray | `{255,0,0,255}` |  |  |  |
| `doRoomOfFateRange` | intarray | `{13,15}` |  |  |  |
| `doSentryGunAscendAcceleration` | float | `9806.65` | CDOSentryGunController::vf24 |  |  |
| `doSentryGunAscendHeight` | float | `5000` | CDOSentryGunController::vf24 |  |  |
| `doSentryGunCollectRange` | float | `1000` |  |  |  |
| `doSentryGunDescendAcceleration` | float | `9806.65` | CDOSentryGunController::vf24 |  |  |
| `doSentryGunFireBurstTime` | int | `4000` | CDOSentryGunController::vf24 |  |  |
| `doSentryGunLife` | int | `10000` | CDOSentryGunController::vf19 |  |  |
| `doSentryGunTargetRetryTime` | int | `1000` |  |  |  |
| `doSentryGunTurnSpeed` | float | `3.0` | CDOSentryGunController::vf24 |  |  |
| `doSeperationFactor` | float | `30` |  |  |  |
| `doSeperationRange` | float | `200` |  |  |  |
| `doShieldLifetime` | int | `20000` | CDOPickupPlayerShield::vf24 |  |  |
| `doSilverbackAscendHeight` | float | `15000` |  |  |  |
| `doSilverbackBargeDistance` | float | `600` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackBargeProbability` | floatarray | `{0.1,0.1,0.25}` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackBargeSpeed` | float | `5.000000` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackJumpDuration` | float | `2` |  |  |  |
| `doSilverbackLeapHeight` | float | `1000` | CDOAIControllerBossSilverback::vf23 |  |  |
| `doSilverbackLeapProbability` | floatarray | `{0.1,0.55,0.25}` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackMaxBargeRange` | float | `500.000000` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackMeleeAttackRange` | float | `150.000000` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackMinLeapRange` | float | `200.000000` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSilverbackSpecialAttackInterval` | int | `10000` | CDOAIControllerBossSilverback::vf24 |  |  |
| `doSpeedBoostDuration` | int | `800` |  |  |  |
| `doStartBombs` | int | `2` |  |  |  |
| `doStartLives` | int | `3` |  |  |  |
| `doTankAccel` | float | `1500` | CDOTankBodyHandler::vf24 |  |  |
| `doTankDecel` | float | `1600` |  |  |  |
| `doTankMaxMoveThreshold` | float | `0.06981` | CDOTankBodyHandler::vf24 |  |  |
| `doTankMaxSpeed` | float | `800` | CDOTankBodyHandler::vf24 |  |  |
| `doTankMaxTurn` | float | `6.283185` | CDOTankBodyHandler::vf24 |  |  |
| `doTankMinTurnThreshold` | float | `0.005000` | CDOTankBodyHandler::vf24 |  |  |
| `doTankTurretMaxTurn` | float | `6.0` | CDOTankBodyHandler::vf24 |  |  |
| `doTeleporterRiseSpeed` | float | `25` |  |  |  |
| `doTeleporterRotationSpeed` | float | `0.5` | CDOTeleporter::vf23 |  |  |
| `doTeleporterStartHeight` | float | `100.0` | CDOTeleporter::vf22 |  |  |
| `doTeslaEnemyDamageRadius` | float | `115.0` | CDOTeslaTower::vf23 |  |  |
| `doTeslaPlayerDamageRadius` | float | `90.0` | CDOTeslaTower::vf23 |  |  |
| `DOToolTipCount` | int | `14` |  |  |  |
| `doTransformSyncRandTime` | int | *lookup only* | CDOTransformSynchroniser::Init |  |  |
| `doTransformSyncTime` | int | *lookup only* | CDOTransformSynchroniser::Init |  |  |
| `LoadingCallbackBytes` | int | `100000` | CDOIngameStateLoading::vf11 |  |  |
| `LoadingCallbackMs` | int | `200` | CDOIngameStateLoading::vf10 |  |  |
| `TouchComponentPressTimeOut` | int | `200` | CDOTouchComponentAnaloguePad::vf2 |  |  |

### Online services and network

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `IgnoreCentral` | bool | `false` |  |  |  |
| `MultiplayerLobby4PlayersTimeoutMs` | int | `5000` | CFrontendStateConnectCommon::vf19 |  |  |
| `MultiplayerLobbyTimeMs` | int | `20000` | CFrontendStateConnectCommon::vf22 |  |  |
| `MultiplayerLobbyTimeWifiMs` | int | `20000` | CFrontendStateConnectWifi::vf22 |  |  |
| `MultiplayerSpectatorCameraOffsetVec3` | intarray | `{0,2880,-1280}` |  |  |  |
| `NetworkEndpointOne2One` | bool | `false` |  |  |  |
| `OnlineJoiningTimeout` | int | `10000` | CFrontendStateConnectOnline::vf17 |  |  |
| `RemotePlayerNetworkPitchError` | float | `0.15f` |  |  |  |
| `RemotePlayerNetworkPositionErrorSquared` | int | `500` |  |  |  |
| `RemotePlayerNetworkRollError` | float | `0.15f` |  |  |  |
| `RoomMaxPlayers` | int | `2` | CIwNetworkRoom::vf15 |  |  |
| `TeleportProbabilityToRandomRoom` | int | `50` |  |  |  |
| `TeleportProjectorRoomTimeMS` | int | `30000` |  |  |  |
| `TeleportRandomRoomTimeMS` | int | `5000` |  |  |  |
| `ZombieNetworkAngleError` | float | `0.05` |  |  |  |
| `ZombieNetworkPositionErrorSquared` | int | `15000` |  |  |  |

### Zombies and AI

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `AIGodmode` | bool | `false` | CAIControllerRomero::vf26 | Zombies and other AI cannot be hurt. |  |
| `AIHostTimeoutToFrozen` | int | `3000` |  |  |  |
| `AIIgnoreGersch` | bool | `false` | CAIControllerZombie::vf26 |  |  |
| `AIMonkeyClaymoreDestroyRadius` | float | `800` |  |  |  |
| `AIMonkeyGerschAboutToShutTime` | int | `1000` |  |  |  |
| `AIMonkeyGroundAttackProbability` | int | `5` |  |  |  |
| `AIMonkeyGroundPoundBlurFadeInTime` | int | `500` | CAIControllerMonkey::vf26 |  |  |
| `AIMonkeyGroundPoundSlowDownFactor` | float | `0.5` | CAIControllerMonkey::vf26 |  |  |
| `AIMonkeyGroundPoundSlowDownTime` | int | `3000` | CAIControllerMonkey::vf26 |  |  |
| `AIMonkeyMaxDistFromAgentTreshold` | int | `4000` |  |  |  |
| `AIMonkeyPickUpGranadeMaxVelocity` | float | `100` |  |  |  |
| `AIMonkeyPickUpGranadeRadius` | float | `150` |  |  |  |
| `AIMonkeysGerschJumpIntoDistance` | float | `100` |  |  |  |
| `AIMonkeyTargetPlayerSqRadius` | float | `250000.0f` |  |  |  |
| `AIMonkeyThrowGranadeReferenceForce` | float | `500.0f` |  |  |  |
| `AIMonkeyThrowGranadeReferenceMass` | float | `0.6f` |  |  |  |
| `AIMonkeyTryThrowBackGranadeRadius` | float | `250` |  |  |  |
| `AIPlayerTargetChangeFarDistTrashold` | float | `1000` |  |  |  |
| `AIPlayerTargetChangeMinSqDistance` | float | `100.0f` |  |  |  |
| `AIRomeroGroundPoundSlowDownFactor` | float | `0.5` | CAIControllerRomero::vf26 |  |  |
| `AIRomeroGroundPoundSlowDownTime` | int | `3000` | CAIControllerRomero::vf26 |  |  |
| `AITargetChangeLogicUpdateMs` | int | `2000` | CAIControllerHellhound::vf24 |  |  |
| `AIZombieElectricAttackSlowDownFactor` | float | `0.5` | CAIControllerZombie::vf28 |  |  |
| `AIZombieElectricAttackSlowDownTime` | int | `3000` | CAIControllerZombie::vf28 |  |  |
| `AmbientZombiesMaxRange` | float | `3000.0` |  |  |  |
| `baseZombieHealth` | int | `20` |  |  |  |
| `DisableZombieSpawning` | bool | `false` |  |  |  |
| `DrawToAgentPosition` | bool | `false` | CAIControllerHellhound::vf21 |  |  |
| `ForceZombiePositionToAgent` | bool | `false` | CAIControllerHellhound::vf25 |  |  |
| `HangingZombieOffset` | float | `250.0f` |  |  |  |
| `maxSpawnedZombies` | int | `32` |  |  |  |
| `MonkeyDeathRingLifetime` | int | `500` |  |  |  |
| `MonkeyDeathRingSpeed` | float | `15` |  |  |  |
| `NumZombiesToInterval` | fixed | `0.1` |  |  |  |
| `PlayerCollideZombieHeight` | float | `3.5` |  |  |  |
| `PlayerCollideZombieRadius` | float | `3.5` |  |  |  |
| `PlayerVoxRomeroNearlyDead` | int | `50` | CAIControllerRomero::vf26 |  |  |
| `RomeroAttackRange` | float | `280` |  |  |  |
| `RomeroCheckRoaringChanceDelay` | int | `1000` |  |  |  |
| `RomeroClimbFinishDist` | float | `75.0` |  |  |  |
| `RomeroClimbSnapSpeed` | float | `0.5` |  |  |  |
| `RomeroDeathMachineDamageMultiplier` | float | `0.1` | CAIControllerRomero::vf26 |  |  |
| `RomeroDistOffsetFromBarricade` | float | `100` |  |  |  |
| `RomeroFastWalkStopDistance` | float | `180` |  |  |  |
| `RomeroHeavyDamagePercentage` | float | `0.25` | CAIControllerRomero::vf26 |  |  |
| `RomeroJumpFinishDist` | float | `200.0` |  |  |  |
| `RomeroLightDamagePercentage` | float | `0.75` | CAIControllerRomero::vf26 |  |  |
| `RomeroMediumDamagePercentage` | float | `0.5` | CAIControllerRomero::vf26 |  |  |
| `RomeroPerkXSparationOffset` | float | `80` |  |  |  |
| `RomeroRoaringChance` | float | `0.6` |  |  |  |
| `RomeroSlowWalkStopDistance` | float | `100` |  |  |  |
| `RomeroSnapSpeed` | float | `1.0` |  |  |  |
| `RomeroSpawnFxDelay` | int | `4000` |  |  |  |
| `RomeroSpawnFxEnd` | int | `8000` |  |  |  |
| `RomeroSpawnFxRomero` | int | `5000` |  |  |  |
| `RomeroVoxRomeroNearlyDead` | int | `20` | CAIControllerRomero::vf25 |  |  |
| `RomeroVoxTargetCloseDistSq` | float | `70000` | CAIControllerRomero::vf25 |  |  |
| `RomeroVoxTimeMinMax` | intarray | `{50000, 90000}` | CAIControllerRomero::vf25 |  |  |
| `StaggerStartingZombies` | int | `500` | CWaveManager::vf2 |  |  |
| `Tcolor` | intarray | `{255,204,204,204}` | CAIControllerMonkey::OnEvent |  |  |
| `TutorShootAngleDelta` | float | `0.05f` | CAITutor::vf23 |  |  |
| `TutorShootTimeMS` | int | `800` | CAITutor::vf23 |  |  |
| `TutorTargetRange` | int | `290000` | CAITutor::vf23 |  |  |
| `TutorTargetTimer` | int | `500` | CAITutor::vf23 |  |  |
| `TutorTurnRate` | float | `5.0f` | CAITutor::vf23 |  |  |
| `ZombieAllowHostMigrationDelay` | int | `1000` |  |  |  |
| `ZombieAttackingDistanceBarricadeIncrease` | float | `55` | CAIControllerZombie::vf22 |  |  |
| `ZombieAttackingDistancePushBack` | float | `0.1` |  |  |  |
| `ZombieAttackingDistanceTolerance` | float | `0.1` | CAIControllerZombie::vf22 |  |  |
| `ZombieAttackPauseTime` | int | `500` |  |  |  |
| `ZombieClimbFinishDist` | float | `75.0` |  |  |  |
| `ZombieClimbSnapSpeed` | float | `0.5` |  |  |  |
| `ZombieDamageFreezeFraction` | float | `0.25` | CAIControllerZombie::vf26 |  |  |
| `zombieDeathFadeTime` | int | `5` |  |  |  |
| `ZombieDistOffsetFromBarricade` | int | `10000` |  |  |  |
| `ZombieEasyHealthMultiplier` | float | `0.5` |  |  |  |
| `ZombieFreezeTimeMS` | int | `3000` | CAIControllerZombie::vf28 |  |  |
| `ZombieHangTime` | int | `10000` |  |  |  |
| `ZombieHardHealthMultiplier` | float | `1.0` |  |  |  |
| `zombieHeadshotBonus` | intarray | `{0,0,0,10,10,20,20,30,30,40}` | CAIControllerZombie::State_Dead | Extra points for a headshot kill, by zombie type index (read in CAIControllerZombie::State_Dead). |  |
| `ZombieHellhoundMaxDistFromAgentTreshold` | int | `4000` |  |  |  |
| `zombieHordeSize` | floatarray | `{500,2000}` |  |  |  |
| `ZombieIceOffset` | float | `15.0` | CAIControllerZombie::vf28 |  |  |
| `ZombieJumpFinishDist` | float | `260.0` |  |  |  |
| `ZombieMaxDistFromAgentTolerance` | int | `200` |  |  |  |
| `ZombieMoonWalkWaterSpeedModifier` | float | `1.0` | CAIControllerZombie::vf28 |  |  |
| `ZombieNormalHealthMultiplier` | float | `1.0` |  |  |  |
| `ZombieOffMeshLinkEngageTimeout` | int | `30000` |  |  |  |
| `ZombieRunWaterSpeedModifier` | float | `1.0` | CAIControllerZombie::vf28 |  |  |
| `ZombiesCheckDistanceFromGershDeviceInterval` | int | `1000` |  |  |  |
| `ZombieScreamAltTimer` | int | `3000` | CAIControllerZombie::vf22 |  |  |
| `ZombieSnapSpeed` | float | `1.0` | CAIControllerZombie::vf22 |  |  |
| `ZombieSprintWaterSpeedModifier` | float | `1.0` | CAIControllerZombie::vf28 |  |  |
| `ZombieWalkFastWaterSpeedModifier` | float | `1.0` | CAIControllerZombie::vf28 |  |  |
| `ZombieWalkWaterSpeedModifier` | float | `1.0` | CAIControllerZombie::vf28 |  |  |
| `ZombieZiplineStartFailsafeTime` | int | `2000` |  |  |  |

### Weapons and the mystery box

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `AllWeapons` | bool | `false` |  | Developer cheat: gives every weapon, including ones from other maps whose animations are not loaded. Those have no ammo, cannot be switched away from, and equipping one crashed the game in CWeaponManager::SetWeapon (null animation state machine); the client now recovers from that fault. | crashes |
| `ClipPlaneNearZ` | int | `10` |  |  |  |
| `DeathMachineWeapon` | string | `olympia` |  |  |  |
| `DisableGerschOpenFX` | bool | `false` | CProjectileEntity::OnEvent |  |  |
| `DisableImpactDecals` | bool | `false` | CImpactEffect::Init |  |  |
| `EndWaveGrenades` | int | `2` |  |  |  |
| `FastReloadFactor` | float | `2.0` |  |  |  |
| `GrenadeFuseLength` | float | `3.0` |  |  |  |
| `GrenadeSpawnOffsetY` | float | `25.0` |  |  |  |
| `GrenadeSpawnOffsetZ` | float | `100.0` |  |  |  |
| `GrenadeThrowForce` | float | `1000.0` |  |  |  |
| `GrenadeYForceMultiplier` | float | `1500.0` |  |  |  |
| `GrenadeYVelocityDampen` | float | `0.7` |  |  |  |
| `GunSwayAlpha` | float | `3.0` |  |  |  |
| `GunSwayBeta` | float | `2.0` |  |  |  |
| `GunSwaydx` | float | `1.57` |  |  |  |
| `GunSwaydy` | float | `0.0` |  |  |  |
| `GunSwaySpeed` | float | `1.5` |  |  |  |
| `GunSwayUseDebugValues` | bool | `false` |  |  |  |
| `GunSwayX` | float | `0.04` |  |  |  |
| `GunSwayY` | float | `0.04` |  |  |  |
| `LastStandWeaponMulti` | string | `colt45_laststand` |  |  |  |
| `LastStandWeaponSingle` | string | `m_sally_laststand` |  |  |  |
| `LightningBoltWeapon` | string | `dragunov` |  |  |  |
| `MaxRecoilPitch` | float | `0.5` |  |  |  |
| `MaxRecoilYaw` | float | `0.5` |  |  |  |
| `MinigunBarrelMaxSpeed` | int | `3996` | CDeathMachineBehaviour::vf10 |  |  |
| `MysteryBoxMaxGoodSound` | int | `3` | CMysteryBox::vf24 |  |  |
| `MysteryBoxOverrideWeaponCount` | int | `-1` | CMysteryBox::vf23 |  |  |
| `MysteryBoxPauseTime` | int | `1000` | CMysteryBox::vf23 |  |  |
| `MysteryBoxRespawnTime` | int | `20000` |  |  |  |
| `MysteryBoxTeddyHeight` | float | `700.0` | CMysteryBox::vf23 |  |  |
| `MysteryBoxTeddyScale` | float | `1.0` |  |  |  |
| `MysteryBoxTeddyTime` | int | `1000` | CMysteryBox::vf23 |  |  |
| `MysteryBoxWeaponHeight` | float | `100.0` | CMysteryBox::vf23 |  |  |
| `MysteryBoxWeaponLOD` | int | `1` |  |  |  |
| `MysteryBoxWeaponLowerTime` | int | `3000` | CMysteryBox::vf23 |  |  |
| `MysteryBoxWeaponScale` | float | `0.015625f` |  |  |  |
| `MysteryBoxWeaponStartHeight` | float | `20.0` | CMysteryBox::vf24 |  |  |
| `MysteryBoxWeaponSwitchTime` | int | `2000` | CMysteryBox::vf23 |  |  |
| `MysteryBoxWeaponSwitchTimeMax` | int | `1500` | CMysteryBox::vf23 |  |  |
| `MysteryBoxWeaponSwitchTimeMin` | int | `50` | CMysteryBox::vf23 |  |  |
| `MysteryBoxWeaponTime` | int | `1500` | CMysteryBox::vf23 |  |  |
| `PackAPunchRespawnTime` | int | `150000` |  |  |  |
| `PackAPunchSpawnDelay` | int | `2000` | CPackAPunch::vf23 |  |  |
| `PAPMachineWeaponEndX` | float | `0.0` |  |  |  |
| `PAPMachineWeaponHeight` | float | `90.0` |  |  |  |
| `PAPMachineWeaponInPAPTime` | int | `8000` |  |  |  |
| `PAPMachineWeaponInTime` | int | `8000` |  |  |  |
| `PAPMachineWeaponOutTime` | int | `8000` |  |  |  |
| `PAPMachineWeaponStartX` | float | `90.0` |  |  |  |
| `PlayerStartAmmo` | int | `40` |  |  |  |
| `PlayerStartWeapon` | string | `colt45` |  |  |  |
| `RecoilDamping` | float | `5.0` |  |  |  |
| `RecoilDampingADS` | float | `20.0` |  |  |  |
| `RecoilDrag` | float | `0.4` |  |  |  |
| `RecoilXDecayHeavy` | float | `1.25` |  |  |  |
| `RecoilXDecayLight` | float | `1.25` |  |  |  |
| `RecoilXDecayMedium` | float | `1.25` |  |  |  |
| `RecoilXScaleHeavy` | float | `0.52` |  |  |  |
| `RecoilXScaleLight` | float | `0.47` |  |  |  |
| `RecoilXScaleMedium` | float | `0.47` |  |  |  |
| `RecoilYDecayHeavy` | float | `4.5` |  |  |  |
| `RecoilYDecayLight` | float | `1.25` |  |  |  |
| `RecoilYDecayMedium` | float | `1.65` |  |  |  |
| `RecoilYScaleHeavy` | float | `1.2` |  |  |  |
| `RecoilYScaleLight` | float | `0.47` |  |  |  |
| `RecoilYScaleMedium` | float | `0.65` |  |  |  |
| `VFXDecalFadeDuration` | int | `3000` | CImpactEffect::vf22 |  |  |
| `WeaponsUnlimitedAmmo` | bool | `false` |  | Firing takes no ammo (checked in the weapon's firing state). | works |

### Camera, aiming and controls

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `AccelAimXSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `AccelAimYSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `accelDampingHorizontal` | fixed | `0.1` |  |  |  |
| `accelDampingVertical` | fixed | `0.1` |  |  |  |
| `accelerometerSmoothingEnabled` | bool | `true` | CAccelerometerInput::CAccelerometerInput |  |  |
| `accelerometerSmoothingProfile` | graph | `0,5;6000,500;` | CAccelerometerInput::CAccelerometerInput |  |  |
| `AccelHorizontalRampAiming` | graph | `0,0;216,0;1034,470;3873,1477;` |  |  |  |
| `AccelHorizontalRampRunning` | graph | `0,0;216,0;1034,470;3873,1477;` |  |  |  |
| `AccelHorizontalRampWalking` | graph | `0,0;216,0;1034,470;3416,3008;` |  |  |  |
| `accelScreenTiltCorrectionDamping` | fixed | `0.25` |  |  |  |
| `accelScreenTiltCorrectionDampingShift` | int | `3` | CAccelerometerInput::CAccelerometerInput |  |  |
| `accelScreenTiltCorrectionStrength` | fixed | `0.5` |  |  |  |
| `AccelVerticalRampAiming` | graph | `-4096,-512;0,512;` |  |  |  |
| `AccelVerticalRampRunning` | graph | `-4096,-512;0,512;` |  |  |  |
| `AccelVerticalRampWalking` | graph | `-4096,-512;0,512;` |  |  |  |
| `AimAssistADSLockDuration` | float | `0.5f` |  |  |  |
| `AimAssistADSLockFOV` | float | `20.0f` |  |  |  |
| `AimAssistADSLockRange` | float | `50.0f` |  |  |  |
| `AimAssistADSLockSpeed` | float | `1.0f` |  |  |  |
| `AimAssistLockFOV` | float | `40.0f` |  |  |  |
| `AimAssistLockHeightMax` | float | `2.2f` |  |  |  |
| `AimAssistLockHeightMin` | float | `-0.3f` |  |  |  |
| `AimAssistLockRange` | float | `10.0f` |  |  |  |
| `AimAssistLockSpeed` | float | `1.0f` |  |  |  |
| `AimAssistUnlockFOV` | float | `44.0f` |  |  |  |
| `AimAssistUnlockHeightMax` | float | `2.3f` |  |  |  |
| `AimAssistUnlockHeightMin` | float | `-0.4f` |  |  |  |
| `AimAssistUnlockRange` | float | `12.0f` |  |  |  |
| `AimAssistUnlockSpeed` | float | `1.0f` |  |  |  |
| `AimCrouchSpeed` | float | `0.6` | CPlayerController::vf23 |  |  |
| `AimPitchSpeed` | float | `1.0` |  |  |  |
| `AimProneSpeed` | float | `0.3` | CPlayerController::vf23 |  |  |
| `AimTurnSpeed` | float | `1.0` |  |  |  |
| `AimWalkSpeed` | float | `1.0` | CPlayerController::vf23 |  |  |
| `AnalogueAimXSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `AnalogueAimYSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `analoguePadAimingResponse` | graph | `0,0;4096,4096;` |  |  |  |
| `AutoFaceTurnRate` | float | `5.0f` |  |  |  |
| `AutoPitchTurnRate` | float | `2.0f` |  |  |  |
| `ButtonDoubleTapTimeOut` | int | `400` | CInputManager::vf4 |  |  |
| `DoubleTapTimeOut` | int | `200` | CTouchComponentAnaloguePad::vf2 |  |  |
| `EnableSetFov` | bool | `false` |  | Turns on the SetFov override (CWeaponManager::UpdateFov). | works |
| `FiringTapTimeOut` | int | `200` | CTouchComponentAnaloguePad::vf2 |  |  |
| `FreeFlySpeed` | float | `60.0` | CPlayerFreeFly::Init | Speed of the developer fly mode (CPlayerFreeFly, registered as "Flying!"): distance per movement event at full stick, and per SUBJECT_PLAYER_ASCEND. Registered when the player spawns. The Developer mod's `noclip` toggles the mode. | works |
| `InputWaitingTime` | int | `1000` | CIngameStateResults::vf2 |  |  |
| `MaxPitch` | float | `0.5` |  |  |  |
| `MinigunBarrelAcceleration` | int | `300` |  |  |  |
| `PerkedAimCrouchSpeed` | float | `1.2` | CPlayerController::vf23 |  |  |
| `PerkedAimPitchSpeed` | float | `2.0` |  |  |  |
| `PerkedAimProneSpeed` | float | `0.6` | CPlayerController::vf23 |  |  |
| `PerkedAimTurnSpeed` | float | `2.0` |  |  |  |
| `PerkedAimWalkSpeed` | float | `1.0` | CPlayerController::vf23 |  |  |
| `PerkedPitchSpeed` | float | `2.0` |  |  |  |
| `PerkedSprintPitchSpeed` | float | `2.0` |  |  |  |
| `PerkedSprintTurnSpeed` | float | `2.0` |  |  |  |
| `PerkedTurnSpeed` | float | `2.0` |  |  |  |
| `PitchSpeed` | float | `1.0` |  | Vertical look speed multiplier. |  |
| `RocketAcceleration` | float | `0.01` |  |  |  |
| `SetFov` | float | `50.0` |  | Field of view in degrees while EnableSetFov is on, clamped to at most the base FOV (the map's MainCamera m_fov, 50 on Kino): it can only narrow the view. Widen it by raising CWeaponManager +0xc4 (the Developer mod's FOV slider). | partial |
| `SprintDownFactor` | float | `1.2` | CTouchComponentStickyStick::vf6 |  |  |
| `SprintPitchSpeed` | float | `1.0` |  |  |  |
| `SprintTurnSpeed` | float | `1.0` |  |  |  |
| `StickyAimXSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `StickyAimYSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `StickyEdgeBehaviour` | int | `100` |  |  |  |
| `StickySpeed` | float | `0.1` |  |  |  |
| `TimeToMove` | int | `100` | CTouchComponentControl::vf2 |  |  |
| `TouchAimXSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `TouchAimYSensitivity` | floatarray | `{ 1.0, 1.0 }` |  |  |  |
| `TouchControlAimingResponse` | graph | `0,0;50,0;50,2048;4096,4096;` | CTouchComponentControl::CTouchComponentControl |  |  |
| `TouchControlBalance` | float | `12.0` |  |  |  |
| `TurnMult` | float | `0.25` | CPlayerController::vf23 |  |  |
| `TurnSpeed` | float | `1.0` |  | Horizontal look speed multiplier. |  |
| `UIDoubleClickReleaseTime` | int | `150` | CInputManager::vf4 |  |  |

### Player

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `baseMiniBossHealth` | int | `200` |  |  |  |
| `CrouchSpeed` | float | `0.6` | CPlayerController::vf23 |  |  |
| `EnableAutoCrouch` | bool | `false` | CPlayerController::vf23 |  |  |
| `HealthIgnoreBleedOutTime` | bool | `false` | CHealth::Update | Downed players never bleed out (read in CHealth::Update). | works |
| `HealthLowTreshold` | float | `0.7` |  |  |  |
| `KillStreakQuota` | int | `50` | CPlayerController::vf23 |  |  |
| `KillStreakVoxDelayTime` | int | `10000` | CPlayerController::vf23 |  |  |
| `LastStandDuration` | int | `30000` | CPlayerController::vf24 |  |  |
| `LastStandDurationSinglePlayer` | int | `10000` | CPlayerController::vf24 |  |  |
| `LastStandSpeed` | float | `0.2` | CPlayerController::vf23 |  |  |
| `MaxNumPlayers` | int | `4` |  |  |  |
| `MaxTimeInWater` | int | `30000` | CPlayerController::vf22 |  |  |
| `MTXReviveCost` | int | `1000` | CIngameStateQuickRevive::vf2 |  |  |
| `PerkedCrouchSpeed` | float | `1.2` | CPlayerController::vf23 |  |  |
| `PerkedProneSpeed` | float | `0.6` | CPlayerController::vf23 |  |  |
| `PerkedSprintingCapacity` | float | `200.0` |  |  |  |
| `PerkedSprintingRatePerSec` | float | `30.0` |  |  |  |
| `PerkedSprintingRecoveryRatePerSec` | float | `400.0` |  |  |  |
| `PerkedSprintingThreshold` | float | `200.0` |  |  |  |
| `PerkedSprintSpeed` | float | `6.0` | CPlayerController::vf23 |  |  |
| `PerkedWalkSpeed` | float | `2.0` | CPlayerController::vf23 |  |  |
| `PerkUnderAttackFadeTimeMS` | int | `500` | CPerkManager::vf25 |  |  |
| `PerkUnderAttackFlashTimeMS` | int | `6000` | CPerkManager::vf23 |  |  |
| `PlayerChangeHeightTime` | float | `0.5` |  |  |  |
| `PlayerCollideMoveFactor` | float | `0.25` |  |  |  |
| `playerCrouchFootstepsMultipler` | float | `2.0` |  |  |  |
| `PlayerDownScorePenalty` | float | `0.05` | CPlayerController::vf24 |  |  |
| `PlayerExplosionVoxMinInterval` | int | `30000` |  |  |  |
| `playerLastStandFootstepsMultipler` | float | `0.0` |  |  |  |
| `PlayerLowHealthThreshold` | int | `15` |  |  |  |
| `playerProneFootstepsMultipler` | float | `0.0` |  |  |  |
| `PlayerQuickReviveTime` | int | `2500` |  |  |  |
| `PlayerReviveMaxDist` | float | `300.0` |  |  |  |
| `PlayerReviveTime` | int | `10000` |  |  |  |
| `playerSprintFootstepsMultipler` | float | `0.5` |  |  |  |
| `PlayerVoxWaterDelay` | int | `3000` |  |  |  |
| `ProneSpeed` | float | `0.3` | CPlayerController::vf23 |  |  |
| `RemotePlayerLastStandBackAngle` | floatangle | `135.0f` |  |  |  |
| `RemotePlayerLastStandFrontAngle` | floatangle | `45.0f` |  |  |  |
| `RenderFromPlayer` | bool | `false` | CGameStateIngame::vf6 |  |  |
| `ReviveImmunityTime` | int | `500` |  |  |  |
| `ReviveIndicatorAngle` | float | `0.5` |  |  |  |
| `ReviveIndicatorEndCol` | intarray | `{255,0,0,255}` |  |  |  |
| `ReviveIndicatorHeight` | float | `150.0` |  |  |  |
| `ReviveIndicatorMinScale` | float | `0.5` |  |  |  |
| `ReviveIndicatorStartCol` | intarray | `{255,255,0,255}` |  |  |  |
| `SprintAngle` | float | `0.5` | CPlayerController::vf23 |  |  |
| `SprintingCapacity` | float | `100.0` |  |  |  |
| `SprintingRatePerSec` | float | `30.0` |  |  |  |
| `SprintingRecoveryRatePerSec` | float | `100.0` |  |  |  |
| `SprintingThreshold` | float | `80.0` |  |  |  |
| `SprintSpeed` | float | `3.0` | CPlayerController::vf23 |  |  |
| `StartSinglePlayerGame` | bool | `true` | CFrontendStateSinglePlayer::CFrontendStateSinglePlayer |  |  |
| `TrapNonDamagePeriodMS` | int | `1000` | CPlayerController::vf23 |  |  |
| `UnlimitedHealth` | bool | `false` |  | Player takes no damage. | works |
| `UnlimitedScore` | bool | `false` | CScoreManager::CScoreManager | Purchases cost nothing: CScoreManager skips SUBJECT_CHARGE_POINTS and SUBJECT_POINTS_PENALTY. Registered with the description "Unlimited points to buy stuff". | works |
| `UnlimitedStamina` | bool | `false` | CPlayerController::vf23 | Sprint never runs out. | works |
| `UnlimitedWaterMove` | bool | `false` |  |  |  |
| `WalkFraction` | float | `0.9` | CPlayerController::vf23 |  |  |
| `WalkSpeed` | float | `1.0` | CPlayerController::vf23 |  |  |

### Rounds, spawning, score and pickups

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `baseSpawnDelay` | intarray | `{500,2000}` |  |  |  |
| `CarpenterScoreTime` | int | `1000` |  |  |  |
| `CentrifugeWavesStart` | int | `2` |  |  |  |
| `DefaultPowerSwitchName` | string | `PowerSwitch` |  |  |  |
| `DefaultSpawnedRocketName` | string | `SpawnedRocket` | CRocketLauncher::vf23 |  |  |
| `GeorgeRomero` | bool | `true` | CWaveManager::vf2 |  |  |
| `LighthouseFaceInterpTime` | int | `500` | CLighthouse::vf24 |  |  |
| `LighthouseSpinSpeed` | float | `30.0` | CLighthouse::vf24 |  |  |
| `LighthouseSpinTime` | int | `20000` | CLighthouse::vf24 |  |  |
| `MaxPickupsPerWave` | int | `4` |  |  |  |
| `midroundPickups` | floatarray | `{1,25}` |  |  |  |
| `midroundPickupTime` | intarray | `{1000,2000}` |  |  |  |
| `minSpawnDelay` | intarray | `{0,500}` |  |  |  |
| `PickupDropOnDeathProbability` | int | `2` |  |  |  |
| `PickupKillThreshold` | int | `0` |  |  |  |
| `PickupOverrideType` | int | `-1` |  |  |  |
| `PickupPointsThreshold` | int | `1000` |  |  |  |
| `ProbabilityOfSpawningEachPickup` | intarray | `{10,10,10,10,10,10,10,10,0}` | CPickupManager::CPickupManager |  |  |
| `RateMeWaveNos` | intarray | `{5,10,15,20}` |  |  |  |
| `ScoreConfigName` | string | `score_table` |  |  |  |
| `spawnDelayRoundDecrement` | int | `25` |  |  |  |
| `SpawnMaxDistance` | float | `5000.0` |  |  |  |
| `StartingScore` | int | *lookup only* | CScoreManager::GetScore | Points each player starts a match with (read by CScoreManager::GetScore / AddScore when a player's score is created). Never registered by the game; register it first (Developer mod: cvar StartingScore 5000). | works |
| `TeleportDurationMS` | int | `1000` | CTeleportManager::vf2 |  |  |
| `TeleportFadeMS` | int | `100` | CTeleportManager::vf2 |  |  |
| `TeleportWormholeTimeMS` | int | `2000` |  |  |  |

### Audio

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `DefaultSoundSpecMaxPolyphony` | int | `3` | CIwSoundSpec::CIwSoundSpec |  |  |
| `GameResultsFXVolume` | float | `0.3` | CIngameStateResults::vf2 |  |  |
| `masterVolume` | int | `5` |  |  |  |
| `musicEnabled` | int | `1` |  | 1 plays music, 0 mutes it. |  |
| `soundEnabled` | int | `1` |  | 1 plays sound effects, 0 mutes them. |  |
| `UseFastIwVolumesIntersection` | bool | `true` |  |  |  |

### Graphics and effects

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `BodyGibsRandomDirDeviation` | floatarray | `{0.4, 0.2, 0.2}` | CBodyGib::Init |  |  |
| `DecalDistance` | int | `1000` |  |  |  |
| `DecalsMax` | int | `32` |  |  |  |
| `DisableAllWeather` | bool | `false` |  |  |  |
| `DisableFogExtraFarPlane` | bool | `false` |  |  |  |
| `DisableImpactVFX` | bool | `false` |  |  |  |
| `FogAltTransitionTime` | int | `5000` | CVFXManager::vf2 |  |  |
| `FogBaseZRange` | int | `12256` |  |  |  |
| `FogLevelsMax` | int | `3` |  |  |  |
| `FogOverrideColour` | intarray | `{-1,-1,-1}` | CIwFogManager::CIwFogManager |  |  |
| `FogOverrideFarPlane` | float | `-0.001` |  |  |  |
| `FogOverrideLength` | float | `0.1` |  |  |  |
| `FogOverrideNearPlane` | float | `-0.001` |  |  |  |
| `FogReturnTime` | int | `1000` |  |  |  |
| `FogTransitionTime` | int | `4000` |  |  |  |
| `FrameBoneDefaultHighAccuracy` | bool | `true` | CIsFrameBone::CIsFrameBone |  |  |
| `LighthouseBeamRenderGroupBack` | int | `20` |  |  |  |
| `LighthouseBeamRenderGroupFront` | int | `25` |  |  |  |
| `LighthouseGlowTime` | int | `1000` |  |  |  |
| `LighthouseMaxFlashTime` | int | `100` |  |  |  |
| `LighthouseRenderGroupSwitchAngle` | float | `90.0` |  |  |  |
| `LighthouseSauronInterpTime` | int | `500` |  |  |  |
| `LighthouseSauronTime` | int | `10000` |  |  |  |
| `LODMaxDistanceQualityProportion` | float | `8.0` | CIsLODControllerDistance::vf23 |  |  |
| `LODOverrideQualitySetting` | float | `-1.0` | CIsLODControllerDistance::vf23 |  |  |
| `LODQuotaDeathQualityModifier` | float | `3.0` |  |  |  |
| `LODQuotaFrustrumRadiusBuffer` | float | `70.0f` | CIsLODControllerQuotaManager::FixedStep |  |  |
| `LODQuotaLevelsMax` | int | `3` | CIsLODControllerQuotaManager::vf2 |  |  |
| `LODQuotaQualityReducer` | int | `2` | CIsLODControllerQuotaManager::vf2 |  |  |
| `MaterialFrameTime` | int | `60` | CFullscreenFXManager::vf2 |  |  |
| `NumSubOTRenderableSlots` | float | `0.66666` |  |  |  |
| `RenderOccluder` | bool | `false` |  |  |  |
| `RenderPortals` | bool | `false` |  |  |  |
| `RenderProps` | bool | `true` |  |  |  |
| `RenderSectors` | bool | `false` |  |  |  |
| `RenderSectorsGeom` | bool | `true` |  |  |  |
| `SnowDetectRaycastLength` | float | `1000` |  |  |  |
| `SnowObeyOverride` | bool | `false` |  |  |  |
| `SnowOverrideEnabled` | bool | `false` |  |  |  |
| `StartMaterialFadeTime` | int | `500` | CFullscreenFXManager::vf2 |  |  |
| `VFXPosZOffset` | float | `2` |  |  |  |
| `WaterLayer0TimeMult` | float | `-0.05` |  |  |  |
| `WaterLayer0XScale` | float | `1.0` |  |  |  |
| `WaterLayer0YScale` | float | `1.0` |  |  |  |
| `WaterLayer1TimeMult` | float | `0.05` |  |  |  |
| `WaterLayer1XScale` | float | `1.0` |  |  |  |
| `WaterLayer1YScale` | float | `1.0` |  |  |  |
| `WaterLevel` | float | `0.0` |  |  |  |

### Menus, HUD and store

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `AchievementDisplayShowTimes` | intarray | `{ 100,200 }` | Cvar_RegisterIntArray2 |  |  |
| `EnableVideo` | bool | `true` |  |  |  |
| `FreeCODPointsOnBuildUpdate` | int | `5000` | CGameStore::vf7 |  |  |
| `FreeCODPointsOnNewDay` | int | `100` | CGameStore::vf7 |  |  |
| `GameOverWaitingTime` | int | `5000` | CIngameStateResults::vf2 |  |  |
| `HUDMessagingFont` | string | `CCAdamKubertItalic_10pt` |  |  |  |
| `HUDMessagingXY` | intarray | `{ 100, 5 }` |  |  |  |
| `HUDPointsMaxCount` | int | `5` |  |  |  |
| `HUDPointsPosX` | int | `25` |  |  |  |
| `HUDPointsPosY` | int | `50` |  |  |  |
| `HUDPointsRandomDisplacementX` | int | `20` |  |  |  |
| `HUDPointsRandomDisplacementY` | int | `10` |  |  |  |
| `MessageFadeTime` | int | `500` |  |  |  |
| `MessageQueueMaxSize` | int | `7` |  |  |  |
| `MessageTime` | int | `4000` |  |  |  |
| `OnlineRetrievingTimeout` | int | `30000` | CFrontendStateMTXStore::vf10 |  |  |
| `RateMeDelayTimer` | int | `2000` | CIngameStateResults::vf2 |  |  |
| `SaveOnPause` | bool | `true` | CIngameStatePaused::Enter | Saves the game when the pause menu opens. |  |
| `SaveOnSuspend` | bool | `true` | CIngameStatePlaying::OnEvent | Saves the game when the app is suspended. |  |
| `UICallReleaseTime` | int | `250` |  |  |  |
| `UIDoubleClickTime` | int | `250` |  |  |  |
| `VideoResolution` | intarray | `{480,270}` |  |  |  |
| `VideoResolutionHires` | intarray | `{960,540}` |  |  |  |
| `XPBarSpeed` | float | `0.2f` | CIngameStateResults::vf2 |  |  |

### Saves

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `DoubleBufferSave` | bool | `true` |  |  |  |

### Other

| Variable | Type | Default | Used by | Notes | Status |
| --- | --- | --- | --- | --- | --- |
| `ADSDeltaYThreshold` | float | `0.05` |  |  |  |
| `ADSZoomInSpeed` | float | `80.0` |  |  |  |
| `ADSZoomOutSpeed` | float | `80.0` |  |  |  |
| `analoguePadMovingResponse` | graph | `0,0;4096,4096;` |  |  |  |
| `AscensionMaxAttackDistPolys` | int | `4` |  |  |  |
| `BIHMaxDepth` | int | `20` |  |  |  |
| `BIHMaxSingled` | int | `6` |  |  |  |
| `BOGravity` | float | `-981.0` | CBodyHandler::vf22 |  |  |
| `BOToolTipCount` | int | `58` |  |  |  |
| `ConnControlAttempts` | int | `15` |  |  |  |
| `ConnControlMsgTimeMs` | int | `1000` |  |  |  |
| `ConstrainHeightExtendsX` | float | `0.1` |  |  |  |
| `ConstrainHeightExtendsY` | float | `0.6` |  |  |  |
| `ConstrainHeightExtendsZ` | float | `0.1` |  |  |  |
| `ConstrainHeightThreshold` | float | `50.0` |  |  |  |
| `crazyFudgeSpeed` | float | `6.0` |  |  |  |
| `DeathMachineTime` | int | `30000` |  |  |  |
| `DetailDistance` | int | `1300` |  |  |  |
| `DoublePointsTime` | int | `30000` |  |  |  |
| `DoubleTapCancelThreshold` | int | `100` |  |  |  |
| `DropRaycastDistance` | float | `10000` |  |  |  |
| `ExplosionHeightOffset` | float | `75.0f` |  |  |  |
| `ExplosionRayCast` | bool | `true` |  |  |  |
| `failsafeMeleeBloodSplatDisplacement` | float | `20.0` |  |  |  |
| `FallHeightFailSafe` | float | `-1000.0` |  |  |  |
| `FallRaycastDistance` | float | `5000` |  |  |  |
| `FastShootingFactor` | float | `1.333333333333333` |  |  |  |
| `FireSaleEnableTime` | int | `3000` |  |  |  |
| `FireSaleTime` | int | `20000` |  |  |  |
| `flingerGravity` | float | `-981.0f` | CFlinger::vf23 |  |  |
| `flingerTime` | float | `2.4f` | CFlinger::vf23 |  |  |
| `ForceBaddiesPositionSynchRandTimeoutMs` | int | `1500` | CBodyHandler::vf23 |  |  |
| `ForceBaddiesPositionSynchTimeoutMs` | int | `3000` | CBodyHandler::vf23 |  |  |
| `ForceGoodiePositionSynchTimeoutMs` | int | `2000` |  |  |  |
| `FullScreenBlurMinCoeff` | float | `0.2` |  |  |  |
| `HeadBobScale` | float | `3.0` |  |  |  |
| `HeadBobSpeedMult` | float | `10.0` |  |  |  |
| `healthIncrease` | int | `3` |  |  |  |
| `InstaKillTime` | int | `30000` |  |  |  |
| `IsASMNumReservedTriggers` | int | `32` |  |  |  |
| `IsDirectionSmoothingSpeed` | int | `24570` |  |  |  |
| `JumpCheckTimer` | int | `200` |  |  |  |
| `LazarusTime` | int | `15000` |  |  |  |
| `maxDyingEntities` | int | *lookup only* | CIwWorld::CIwWorld |  |  |
| `MaxIntervalMul` | fixed | `1.5` |  |  |  |
| `MinigunBarrelDeceleration` | int | `200` |  |  |  |
| `MinIntervalMul` | fixed | `0.0` |  |  |  |
| `moveVecMinimumSquaredLength` | float | `0.005` |  |  |  |
| `NoExplosions` | bool | `false` | CExplosion::vf23 |  |  |
| `NotableEntAngle` | float | `90.0` |  |  |  |
| `NotableEntFilterDistance` | float | `700.0` |  |  |  |
| `numGasSmokes` | int | `8` |  |  |  |
| `OnlineIsHostNotClient` | bool | `true` |  |  |  |
| `OnlineUseGameCenterMM` | bool | `true` |  |  |  |
| `OverrideClimbTriggerVal` | int | `0` |  |  |  |
| `OwnExplosionDamageModifier` | float | `50.0f` |  |  |  |
| `PauseInTime` | int | `4000` |  |  |  |
| `PauseInTimeCOTD` | int | `200` |  |  |  |
| `PauseOutTime` | int | `8000` |  |  |  |
| `PauseOutTimeCOTD` | int | `3000` |  |  |  |
| `playerMoveSpeedDamp` | float | `300.0` |  |  |  |
| `playerNormalFootstepsMultipler` | float | `1.0` |  |  |  |
| `POIGridSize` | int | `300` |  |  |  |
| `RayCastTestEnabled` | bool | `true` | CGameStateIngame::vf6 |  |  |
| `RocketMaxHeight` | float | `25000.0` |  |  |  |
| `RocketSwitchHeight` | float | `5000.0` |  |  |  |
| `romeroHitReactionDelay` | int | `4000` |  |  |  |
| `SplashScreenMs` | int | `3000` |  |  |  |
| `TapOffset` | int | `50` |  |  |  |
| `TapOffset3GS` | int | `50` |  |  |  |
| `TapOffsetIpad` | int | `50` |  |  |  |
| `TimerSync` | int | `10000` |  |  |  |
| `UDPPacketCorruptionRate` | int | `0` |  |  |  |
| `UDPPacketLossRate` | int | `0` |  |  |  |
