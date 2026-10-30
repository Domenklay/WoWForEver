#!/usr/bin/env python3
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
talents = (root / "server/ForeverEncyclopediaTalents.cpp").read_text()
runtime = (root / "server/ForeverEncyclopediaRuntimeV3.cpp").read_text()

for source_name, source in (("talents", talents), ("runtime-v3", runtime)):
    bad_patterns = [
        r"SELECT\s+talent_key\s*,\s*rank\b",
        r"\(account_id\s*,\s*talent_key\s*,\s*rank\b",
        r"UPDATE\s+rank\s*=",
        r"VALUES\s*\(\s*rank\s*\)",
    ]
    for pattern in bad_patterns:
        if re.search(pattern, source, re.IGNORECASE):
            raise SystemExit(f"{source_name}: unsafe MySQL reserved identifier usage: {pattern}")

if "SELECT talent_key,`rank`" not in talents:
    raise SystemExit("talent server must quote MySQL `rank`")
if "SELECT talent_key,`rank`" not in runtime:
    raise SystemExit("runtime must quote MySQL `rank`")

required_talent = [
    "talent_key,`rank`",
    "`rank`=VALUES(`rank`)",
    "sObjectMgr->GetCreatureTemplate(entry)",
]
for needle in required_talent:
    if needle not in talents:
        raise SystemExit(f"expected safe encyclopedia server code missing: {needle}")

creature_block = talents.split("static void CreatureInfo", 1)[1].split("static void Request", 1)[0]
if "WorldDatabase.PQuery" in creature_block or "FROM creature_template" in creature_block:
    raise SystemExit("CreatureInfo must not issue ad-hoc world DB queries; use ObjectMgr CreatureTemplate")

if "WorldDatabase" in runtime:
    raise SystemExit("companion runtime must not query WorldDatabase")
if "KnowledgeManaBonus(knowledgeTotal)" not in runtime:
    raise SystemExit("runtime must grant +1 max mana per 10 total knowledge")
if "RegenBasisPoints(rank)" not in runtime:
    raise SystemExit("runtime must use the capped percentage mana regen policy")

required_companion = [
    "CompanionChassisEntry = WORLD_TRIGGER",
    "GetFirstVisibleModel()",
    "SetDisplayId(displayId, true)",
    "SummonCreature(CompanionChassisEntry, spawnPos",
    "MoveFollow(player",
    "SetCanFly(true)",
    "SetDisableGravity(true)",
    "SetHover(true)",
    "CastSpell(player, SpellBookShield, false)",
    "CastSpell(player, SpellBookHeal, false)",
]
for needle in required_companion:
    if needle not in runtime:
        raise SystemExit(f"native companion runtime missing: {needle}")

if "SummonCreature(appearanceEntry" in runtime:
    raise SystemExit("appearance donor NPC must never be spawned as the companion chassis")

on_damage = runtime.split("void OnDamage", 1)[1].split("class Players", 1)[0]
if "PQuery(" in on_damage or "DirectPExecute(" in on_damage:
    raise SystemExit("OnDamage hot path must not perform synchronous DB queries")
if "ModifyHealth" in on_damage:
    raise SystemExit("native companion runtime must not heal directly inside OnDamage")
if "damage -=" in on_damage or "barrier" in on_damage.lower():
    raise SystemExit("native companion runtime must not implement a hidden C++ absorb in OnDamage")

print("Encyclopedia SQL/ObjectMgr/native-companion safety lint passed")
