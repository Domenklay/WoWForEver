#!/usr/bin/env python3
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = (root / "server/ForeverEncyclopediaTalents.cpp").read_text()

bad_patterns = [
    r"SELECT\s+talent_key\s*,\s*rank\b",
    r"\(account_id\s*,\s*talent_key\s*,\s*rank\b",
    r"UPDATE\s+rank\s*=",
    r"VALUES\s*\(\s*rank\s*\)",
]
for pattern in bad_patterns:
    if re.search(pattern, source, re.IGNORECASE):
        raise SystemExit(f"unsafe MySQL reserved identifier usage: {pattern}")

required = [
    "SELECT talent_key,`rank`",
    "talent_key,`rank`",
    "`rank`=VALUES(`rank`)",
    "sObjectMgr->GetCreatureTemplate(entry)",
]
for needle in required:
    if needle not in source:
        raise SystemExit(f"expected safe encyclopedia server code missing: {needle}")

creature_block = source.split("static void CreatureInfo", 1)[1].split("static void Request", 1)[0]
if "WorldDatabase.PQuery" in creature_block or "FROM creature_template" in creature_block:
    raise SystemExit("CreatureInfo must not issue ad-hoc world DB queries; use ObjectMgr CreatureTemplate")

print("Encyclopedia SQL/ObjectMgr safety lint passed")
