-- boz.enums: the names of the game's enumerations (the values reflected fields hold).
--
--   enums.name("WeaponBehaviourType", 10)   -> "eDeathMachine"
--   enums.value("PerkType", "ePerkJuggernog") -> 2
--   enums.WeaponBehaviourType[3]            -> "eAutomatic" (lists are 1-based: value + 1)
--
-- How it works: CParsableEnumManager registers each enum from a null-terminated table of names in
-- the game's data (value = position): these are those tables, read from the 1.0.11 image.

local enums = {}

enums.WeaponBehaviourType = {"eMelee", "eSingleShot", "eAutomatic", "eSemiAutomatic", "eShotgun",
    "eAutomaticShotgun", "eRevolver", "eGrenade", "eStickyGrenade", "eSingleShotLauncher",
    "eDeathMachine", "eMine", "eMonkeyBomb", "eClusterBomb", "eGerschDevice", "eThunderGun",
    "eHumanGun", "eWunderWaffe", "eUknown"}
enums.AmmoType = {"eNoAmmo", "eStandardAmmo", "eRifleAmmo", "eShotgunAmmo", "eGrenadeAmmo",
    "eRocketAmmo", "eCrossbowAmmo", "ePowerAmmo", "eLongClip", "eShortClip", "eFragGrenadeIcon",
    "eClaymoreIcon", "eMonkeyBombIcon", "eMatryoshkaDollIcon", "eGerschDeviceIcon"}
enums.ProjectileBehaviourType = {"eNoDetonate", "eTimedDetonate", "eContactDetonate",
    "eProximityDetonate", "eAttractAndDetonate", "eClusterDetonate", "eAttractAndKill"}
enums.RecoilType = {"eNoRecoil", "eLightRecoil", "eMediumRecoil", "eHeavyRecoil"}
enums.CrosshairType = {"eNoCrosshair", "eStandardCrosshair", "eIndirectCrosshair",
    "eMinigunCrosshair", "eThundergunCrosshair"}
enums.SpecialDamageType = {"eNoSpecialDamage", "eHumanGunHit", "eHumanGunHitPAP", "eSpawnChainLightning"}
enums.PerkType = {"ePerkDeadShot", "ePerkDoubleTap", "ePerkJuggernog", "ePerkStaminUp", "ePerkPHD",
    "ePerkRevive", "ePerkSpeedCola", "ePerkMAX"}
enums.SpecialityWaveType = {"eWaveEasy", "eWaveNormal", "eWaveHard", "eWaveMP2", "eWaveMP3", "eWaveMP4"}
enums.POIType = {"eBarricade", "eDoor", "eWeaponChalkOutline", "eMysteryBox", "ePerkMachine",
    "ePackAPunch", "eTrap", "ePowerSwitch", "eTurret", "eTeleporter", "eTeleportMainframe",
    "eLunarLander", "eLunarLanderCentral", "eLunarLanderStation", "eClaymore", "eTutorialPickup",
    "eZipLine", "ePoiUndefined"}
enums.BodyPartType = {"eHead", "eTorso", "eLeftLeg", "eRightLeg", "eLeftArm", "eRightArm", "eLimb", "eUndefined"}
enums.LocatorType = {"eLocatorAll", "eLocatorAIWater", "eLocatorAIDespawn"}
enums.EntityFlags = {"eBOSceneryColliderF", "eBOGoodieF", "eBOBaddieF", "eBOLocalPlayerF", "eBOTriggerF",
    "eBOAutoAimF", "eBOGrenadeF", "eBOClaymoreF", "eBOExplosionF", "eBODogF", "eBOSpaceMonkeyPickableF",
    "eBODumbIdleF", "eBOKnifableF"}
-- Dead Ops Arcade
enums.DOEntityFlags = {"eDefaultF", "eGoodieF", "eBaddieF", "eProjectileF", "eWorldCollisionF",
    "ePhysicsObjectF", "eFlamingBarrelF", "eChickenF", "eAutoAimF", "eExplosionF", "eTeleporterF",
    "eBuffaloF", "eSilverbackF", "ePickupF"}
enums.DODamageFlags = {"eSilverbackImmuneF", "eSilverbackRestrictedF", "eTumbleF", "eFlyUpF",
    "eNoDamageReactionF", "eNoDeathReactionF"}
enums.DOSpawnPointType = {"eTesla", "eFlamingBarrel", "eBuffalo", "eSilverbackBoss"}
enums.DOFateBonuses = {"ePermanentChicken", "ePermanentBoots", "ePermanentDeathMachine", "eFortune"}
enums.DOSynchType = {"eLocalPlayerMaster", "eHostMaster", "eManualMaster", "eManualSlave"}
enums.DOPlayerBody = {"ePlayerBodyWalking", "ePlayerBodyHelicopter", "ePlayerBodyTank"}
enums.DOPlayerShield = {"ePlayerShieldNone", "ePlayerShieldOilDrum", "ePlayerShieldMetallicBall",
    "ePlayerShieldRainbow"}

--- The name of an enum's value (the game's number), or nil.
function enums.name(enum, value)
    local list = enums[enum]
    return list and list[(value or -1) + 1] or nil
end

--- The game's number for an enum value's name, or nil.
function enums.value(enum, name)
    for i, n in ipairs(enums[enum] or {}) do
        if n == name then
            return i - 1
        end
    end
    return nil
end

return enums
