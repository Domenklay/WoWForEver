-- Bind only the subclass script; preserve all existing scripts on these spells.
-- Negative IDs ask TrinityCore to include the complete native rank chain.
START TRANSACTION;
DELETE FROM spell_script_names WHERE ScriptName='spell_forever_subclass';
INSERT INTO spell_script_names (spell_id,ScriptName) VALUES
(-6673,'spell_forever_subclass'),(-635,'spell_forever_subclass'),
(-3044,'spell_forever_subclass'),(-1752,'spell_forever_subclass'),
(-585,'spell_forever_subclass'),(-2050,'spell_forever_subclass'),
(-2054,'spell_forever_subclass'),(-2060,'spell_forever_subclass'),
(-2061,'spell_forever_subclass'),(-403,'spell_forever_subclass'),
(-331,'spell_forever_subclass'),(-116,'spell_forever_subclass'),
(-2136,'spell_forever_subclass'),(-686,'spell_forever_subclass'),
(-5176,'spell_forever_subclass'),(-5185,'spell_forever_subclass'),
(-6807,'spell_forever_subclass'),(-1082,'spell_forever_subclass');
COMMIT;
