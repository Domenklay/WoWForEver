#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
server = (root / "server/ForeverEncyclopediaAbilities.cpp").read_text()
client = (root / "addon/ForeverEncyclopedia/ForeverEncyclopediaAbilities.lua").read_text()

required_server = [
    "creature->spells",
    "sSpellMgr->GetSpellInfo",
    "spell->IsPassive()",
    "spell->SchoolMask",
    "spell->RecoveryTime",
    "spell->CategoryRecoveryTime",
    "identify_abilities",
    '#include "SmartScriptMgr.h"',
    "sSmartScriptMgr->GetScript",
    "SMART_SCRIPT_TYPE_CREATURE",
    "SMART_ACTION_CAST",
    "SMART_ACTION_SELF_CAST",
    "SMART_ACTION_CROSS_CAST",
    "SMART_ACTION_INVOKER_CAST",
    "holder.action.cast.spell",
    "holder.action.crossCast.spell",
    '"BSTART|{}|{}"',
    '"BSPELL|{}|{}|{}|{}|{}|{}|{}|{}"',
    '"BEND|{}"',
]
for needle in required_server:
    if needle not in server:
        raise SystemExit(f"abilities server missing required rule: {needle}")

if "WorldDatabase" in server or "FROM creature_template" in server or "FROM smart_scripts" in server:
    raise SystemExit("knowledge level 4 abilities must use loaded CreatureTemplate/SpellMgr/SmartAIMgr, not ad-hoc world SQL")

required_client = [
    '"inspect " .. tostring(entry)',
    'msg:sub(1, 7) == "BSTART|"',
    'msg:sub(1, 7) == "BSPELL|"',
    'msg:sub(1, 5) == "BEND|"',
    "GetSpellInfo",
    "Способности существа",
    "Способности: ",
    "SmartAI",
    "source = tonumber(source) or 0",
    'text:find("^Класс:")',
]
for needle in required_client:
    if needle not in client:
        raise SystemExit(f"abilities client missing required rule: {needle}")

print("Encyclopedia knowledge level 4 template + SmartAI abilities lint passed")
