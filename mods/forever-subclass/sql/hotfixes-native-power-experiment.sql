-- ForeverSubclass native-power experiment.
-- Stage 1 intentionally touches only the Mage primary class (class 8).
-- The stock Mage keeps Mana; these two records add native Rage and Energy slots.
-- Fixture tuples: 190031901,1,8 and 190031902,3,8.
-- If the Forever client accepts this DB2 hotfix, UnitPower("player", 1/3) will expose them
-- without any ForeverSubclass virtual-resource transport.

SET @FSC_BUILD := 70532;
SET @FSC_POWER_TABLE_HASH := 3224459983; -- ChrClassesXPowerTypes.db2 / 0xC0315ACF
SET @FSC_MAGE_RAGE_ID := 190031901;
SET @FSC_MAGE_ENERGY_ID := 190031902;

-- Remove every earlier revision of this experiment first. The first prototype used one
-- push per record with UniqueId=1; that does not mirror Blizzard/TrinityCore hotfix pushes.
DELETE FROM `hotfix_data`
WHERE `TableHash`=@FSC_POWER_TABLE_HASH
  AND `RecordId` IN (@FSC_MAGE_RAGE_ID,@FSC_MAGE_ENERGY_ID);

DELETE FROM `chr_classes_x_power_types`
WHERE `ID` IN (@FSC_MAGE_RAGE_ID,@FSC_MAGE_ENERGY_ID);

INSERT INTO `chr_classes_x_power_types` (`ID`,`PowerType`,`ClassID`,`VerifiedBuild`) VALUES
(@FSC_MAGE_RAGE_ID,1,8,@FSC_BUILD),
(@FSC_MAGE_ENERGY_ID,3,8,@FSC_BUILD);

-- A hotfix Id is a push id, not a DB2 record id. Official TrinityCore data groups all
-- records belonging to one push under the same Id and UniqueId. Pick a fresh pair every
-- install so a client that cached an older failed experiment is forced to request it again.
SET @FSC_PUSH_ID := (SELECT COALESCE(MAX(`Id`),0)+1 FROM `hotfix_data`);
SET @FSC_UNIQUE_ID := (CRC32(UUID()) | 1);

-- Status 1 = Valid.
INSERT INTO `hotfix_data` (`Id`,`UniqueId`,`TableHash`,`RecordId`,`Status`,`VerifiedBuild`) VALUES
(@FSC_PUSH_ID,@FSC_UNIQUE_ID,@FSC_POWER_TABLE_HASH,@FSC_MAGE_RAGE_ID,1,@FSC_BUILD),
(@FSC_PUSH_ID,@FSC_UNIQUE_ID,@FSC_POWER_TABLE_HASH,@FSC_MAGE_ENERGY_ID,1,@FSC_BUILD);
