#!/usr/bin/env python3
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
talents = (root / "server/ForeverEncyclopediaTalents.cpp").read_text()
runtime = (root / "server/ForeverEncyclopediaRuntime.cpp").read_text()

for source_name, source in (("talents", talents), ("runtime", runtime)):
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
    raise SystemExit("combat runtime must not query WorldDatabase")
if "knowledgeTotal / 10" not in runtime:
    raise SystemExit("runtime must grant +1 max mana per 10 total knowledge")
if "rank * 20" not in runtime or "std::min<uint32>(100" not in runtime:
    raise SystemExit("runtime regen must be 0.2% per rank with a hard 1% cap")

on_damage = runtime.split("void OnDamage", 1)[1].split("class Players", 1)[0]
if "PQuery(" in on_damage or "DirectPExecute(" in on_damage:
    raise SystemExit("OnDamage hot path must not perform synchronous DB queries")

print("Encyclopedia SQL/ObjectMgr/runtime safety lint passed")
