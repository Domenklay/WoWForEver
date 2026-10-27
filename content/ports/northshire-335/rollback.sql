-- GPL-2.0. Derived from TrinityCore TDB335.26091; exact donor rows in source.json.
-- Apply with the game services stopped. Does not modify the original NPC/quest.
CREATE TABLE IF NOT EXISTS wowforever_content_ports (
  name varchar(80) NOT NULL PRIMARY KEY,
  installed_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
-- Remove only records reserved for this port. Character progress is deliberately retained.
DROP PROCEDURE IF EXISTS wf_remove_northshire_335;
DELIMITER //
CREATE PROCEDURE wf_remove_northshire_335()
main: BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  IF NOT EXISTS (SELECT 1 FROM wowforever_content_ports WHERE name='northshire-335-v1') THEN
    COMMIT;
    SELECT 'Not installed; no changes' AS result;
    LEAVE main;
  END IF;
  DELETE FROM `quest_template` WHERE `ID`=900007;
  DELETE FROM `quest_template_addon` WHERE `ID`=900007;
  DELETE FROM `quest_classic_level` WHERE `ID`=900007;
  DELETE FROM `quest_template_classic_level` WHERE `ID`=900007;
  DELETE FROM `quest_classic_money` WHERE `ID`=900007;
  DELETE FROM `quest_offer_reward` WHERE `ID`=900007;
  DELETE FROM `quest_request_items` WHERE `ID`=900007;
  DELETE FROM `quest_objectives` WHERE `QuestID`=900007;
  DELETE FROM `creature_template` WHERE `entry`=900197;
  DELETE FROM `creature_template_model` WHERE `CreatureID`=900197;
  DELETE FROM `creature_template_difficulty` WHERE `Entry`=900197;
  DELETE FROM `creature` WHERE `guid`=900000001;
  DELETE FROM `creature_queststarter` WHERE `id`=900197;
  DELETE FROM `creature_queststarter` WHERE `quest`=900007;
  DELETE FROM `creature_questender` WHERE `id`=900197;
  DELETE FROM `creature_questender` WHERE `quest`=900007;
  DELETE FROM wowforever_content_ports WHERE name='northshire-335-v1';
  COMMIT;
  SELECT 'Removed test NPC and quest; original Northshire records unchanged' AS result;
END//
DELIMITER ;
CALL wf_remove_northshire_335();
DROP PROCEDURE wf_remove_northshire_335;
