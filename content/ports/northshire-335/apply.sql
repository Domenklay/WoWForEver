-- GPL-2.0. Derived from TrinityCore TDB335.26091; exact donor rows in source.json.
-- Apply with the game services stopped. Does not modify the original NPC/quest.
CREATE TABLE IF NOT EXISTS wowforever_content_ports (
  name varchar(80) NOT NULL PRIMARY KEY,
  installed_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
DROP PROCEDURE IF EXISTS wf_install_northshire_335;
DELIMITER //
CREATE PROCEDURE wf_install_northshire_335()
main: BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  IF EXISTS (SELECT 1 FROM wowforever_content_ports WHERE name='northshire-335-v1') THEN
    COMMIT;
    SELECT 'Already installed; no changes' AS result;
    LEAVE main;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM quest_template WHERE ID=7)
     OR NOT EXISTS (SELECT 1 FROM creature_template WHERE entry=197)
     OR NOT EXISTS (SELECT 1 FROM creature_template WHERE entry=6)
     OR NOT EXISTS (SELECT 1 FROM creature WHERE id=197 AND map=0)
     OR NOT EXISTS (SELECT 1 FROM creature_template_model WHERE CreatureID=197)
     OR NOT EXISTS (SELECT 1 FROM creature_template_difficulty WHERE Entry=197) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Missing Northshire source records; nothing installed';
  END IF;
  IF EXISTS (SELECT 1 FROM `quest_template` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_template_addon` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_classic_level` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_template_classic_level` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_classic_money` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_offer_reward` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_request_items` WHERE `ID`=900007)
     OR EXISTS (SELECT 1 FROM `quest_objectives` WHERE `ID`=9000071)
     OR EXISTS (SELECT 1 FROM `quest_objectives` WHERE `QuestID`=900007)
     OR EXISTS (SELECT 1 FROM `creature_template` WHERE `entry`=900197)
     OR EXISTS (SELECT 1 FROM `creature_template_model` WHERE `CreatureID`=900197)
     OR EXISTS (SELECT 1 FROM `creature_template_difficulty` WHERE `Entry`=900197)
     OR EXISTS (SELECT 1 FROM `creature` WHERE `guid`=900000001)
     OR EXISTS (SELECT 1 FROM `creature` WHERE `id`=900197)
     OR EXISTS (SELECT 1 FROM `creature_queststarter` WHERE `id`=900197)
     OR EXISTS (SELECT 1 FROM `creature_queststarter` WHERE `quest`=900007)
     OR EXISTS (SELECT 1 FROM `creature_questender` WHERE `id`=900197)
     OR EXISTS (SELECT 1 FROM `creature_questender` WHERE `quest`=900007) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Reserved test IDs already occupied; nothing installed';
  END IF;
  CREATE TEMPORARY TABLE wf_copy LIKE `quest_template`;
  INSERT INTO wf_copy SELECT * FROM `quest_template` WHERE `ID`=7;
  UPDATE wf_copy SET `ID`=900007, `QuestType`=2,
    `QuestSortID`=9,
    `QuestInfoID`=0,
    `SuggestedGroupNum`=0,
    `RewardXPDifficulty`=5,
    `RewardBonusMoney`=90,
    `RewardSpell`=0,
    `RewardHonor`=0,
    `RewardKillHonor`=0.0,
    `StartItem`=0,
    `Flags`=524296,
    `RewardFactionID1`=72,
    `RewardFactionValue1`=5,
    `RewardFactionOverride1`=0,
    `RewardFactionFlags`=1,
    `AllowableRaces`=1101,
    `LogTitle`='[335 test] Kobold Camp Cleanup',
    `LogDescription`='Kill 8 Kobold Vermin, then return to Marshal McBride.',
    `QuestDescription`='Your first task is one of cleansing, $N.  A clan of kobolds have infested the woods to the north.  Go there and fight the kobold vermin you find.  Reduce their numbers so that we may one day drive them from Northshire.',
    `AreaDescription`='',
    `QuestCompletionLog`='Return to Marshal McBride at Northshire Abbey in Elwynn Forest.', `RewardNextQuest`=0, `VerifiedBuild`=0;
  INSERT INTO `quest_template` SELECT * FROM wf_copy;
  DROP TEMPORARY TABLE wf_copy;
  INSERT INTO quest_template_addon (ID) VALUES (900007);
  INSERT INTO quest_classic_level (ID,QuestLevel,MinLevel,MaxLevel) VALUES (900007,2,1,0);
  INSERT INTO quest_template_classic_level (ID,LevelType,QuestLevel) VALUES (900007,2,2);
  INSERT INTO quest_classic_money (ID,RewardMoney,RewardMoneyMaxLevel) VALUES (900007,25,90);
  INSERT INTO quest_objectives (ID,QuestID,Type,`Order`,StorageIndex,ObjectID,Amount,Description)
    VALUES (9000071,900007,0,0,0,6,8,'');
  INSERT INTO `quest_offer_reward` (`ID`,`Emote1`,`Emote2`,`Emote3`,`Emote4`,`RewardText`,`EmoteDelay1`,`EmoteDelay2`,`EmoteDelay3`,`EmoteDelay4`,`VerifiedBuild`) VALUES (900007,1,0,0,0,'Well done, citizen. Those kobolds are thieves and cowards, but in large numbers they pose a threat to us. And the humans of Stormwind do not need another threat.$B$BFor defeating them, you have my gratitude.',0,0,0,0,0);
  INSERT INTO `quest_request_items` (`ID`,`VerifiedBuild`,`CompletionText`,`EmoteOnComplete`,`EmoteOnIncomplete`,`EmoteOnCompleteDelay`,`EmoteOnIncompleteDelay`) VALUES (900007,0,'How goes the hunting, $N? Have you found and defeated those vermin?',1,6,0,0);
  CREATE TEMPORARY TABLE wf_copy LIKE `creature_template`;
  INSERT INTO wf_copy SELECT * FROM `creature_template` WHERE `entry`=197;
  UPDATE wf_copy SET `entry`=900197, name='[335 test] Marshal McBride', npcflag=2, AIName='', ScriptName='', VerifiedBuild=0;
  INSERT INTO `creature_template` SELECT * FROM wf_copy;
  DROP TEMPORARY TABLE wf_copy;
  CREATE TEMPORARY TABLE wf_copy LIKE `creature_template_model`;
  INSERT INTO wf_copy SELECT * FROM `creature_template_model` WHERE `CreatureID`=197;
  UPDATE wf_copy SET `CreatureID`=900197;
  INSERT INTO `creature_template_model` SELECT * FROM wf_copy;
  DROP TEMPORARY TABLE wf_copy;
  CREATE TEMPORARY TABLE wf_copy LIKE `creature_template_difficulty`;
  INSERT INTO wf_copy SELECT * FROM `creature_template_difficulty` WHERE `Entry`=197;
  UPDATE wf_copy SET `Entry`=900197;
  INSERT INTO `creature_template_difficulty` SELECT * FROM wf_copy;
  DROP TEMPORARY TABLE wf_copy;
  CREATE TEMPORARY TABLE wf_copy LIKE creature;
  INSERT INTO wf_copy SELECT * FROM creature WHERE id=197 AND map=0 ORDER BY guid LIMIT 1;
  UPDATE wf_copy SET guid=900000001,id=900197,position_x=position_x+1.5,
    position_y=position_y+1.5,MovementType=0,wander_distance=0,ScriptName='',VerifiedBuild=0;
  INSERT INTO creature SELECT * FROM wf_copy;
  DROP TEMPORARY TABLE wf_copy;
  INSERT INTO creature_queststarter (id,quest) VALUES (900197,900007);
  INSERT INTO creature_questender (id,quest) VALUES (900197,900007);
  INSERT INTO wowforever_content_ports (name) VALUES ('northshire-335-v1');
  COMMIT;
  SELECT 'Installed: NPC 900197, quest 900007, kill 8 Kobold Vermin, reward 25 copper' AS result;
END//
DELIMITER ;
CALL wf_install_northshire_335();
DROP PROCEDURE wf_install_northshire_335;
