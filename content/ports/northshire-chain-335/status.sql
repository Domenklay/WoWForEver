SELECT ID,LogTitle,RewardNextQuest,StartItem FROM quest_template WHERE ID IN (910783,910007,910015,910021,910054);
SELECT ID,PrevQuestID,ProvidedItemCount FROM quest_template_addon WHERE ID IN (910783,910007,910015,910021,910054);
SELECT QuestID,Type,ObjectID,Amount FROM quest_objectives WHERE QuestID IN (910783,910007,910015,910021,910054);
SELECT guid,id,map,position_x,position_y,position_z FROM creature WHERE id IN (910823,910197,910240);
SELECT id,quest FROM creature_questender WHERE quest=910783;
SELECT entry,name,npcflag FROM creature_template WHERE entry IN (910823,910197,910240);
