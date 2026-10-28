-- ForeverSubclass native-power experiment.
-- Stage 1 intentionally touches only the Mage primary class (class 8).
-- The stock Mage keeps Mana; these two hotfix records add native Rage and Energy slots.
-- Fixture tuples: 190031901,1,8 and 190031902,3,8.
-- If the Forever client accepts the DB2 hotfix, UnitPower("player", 1/3) will expose them
-- without any ForeverSubclass virtual-resource transport.

SET @FSC_BUILD := 70532;
SET @FSC_POWER_TABLE_HASH := 3224459983; -- ChrClassesXPowerTypes.db2 / 0xC0315ACF
SET @FSC_MAGE_RAGE_ID := 190031901;
SET @FSC_MAGE_ENERGY_ID := 190031902;

DELETE FROM `hotfix_data`
WHERE `TableHash`=@FSC_POWER_TABLE_HASH
  AND `RecordId` IN (@FSC_MAGE_RAGE_ID,@FSC_MAGE_ENERGY_ID);

DELETE FROM `chr_classes_x_power_types`
WHERE `ID` IN (@FSC_MAGE_RAGE_ID,@FSC_MAGE_ENERGY_ID);

INSERT INTO `chr_classes_x_power_types` (`ID`,`PowerType`,`ClassID`,`VerifiedBuild`) VALUES
(@FSC_MAGE_RAGE_ID,1,8,@FSC_BUILD),
(@FSC_MAGE_ENERGY_ID,3,8,@FSC_BUILD);

-- Status 1 = Valid. Each Id is a separate deterministic hotfix push.
INSERT INTO `hotfix_data` (`Id`,`UniqueId`,`TableHash`,`RecordId`,`Status`,`VerifiedBuild`) VALUES
(@FSC_MAGE_RAGE_ID,1,@FSC_POWER_TABLE_HASH,@FSC_MAGE_RAGE_ID,1,@FSC_BUILD),
(@FSC_MAGE_ENERGY_ID,1,@FSC_POWER_TABLE_HASH,@FSC_MAGE_ENERGY_ID,1,@FSC_BUILD);
