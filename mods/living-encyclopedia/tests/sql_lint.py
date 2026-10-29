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
]
for needle in required:
    if needle not in source:
        raise SystemExit(f"expected quoted rank SQL missing: {needle}")

print("Encyclopedia SQL reserved-word lint passed")
