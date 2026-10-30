#!/usr/bin/env python3
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
talents = (root / "server/ForeverEncyclopediaTalents.cpp").read_text()
runtime = (root / "server/ForeverEncyclopediaRuntimeV5.cpp").read_text()

for source_name, source in (("talents", talents), ("runtime-v5", runtime)):
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
    "sObjectMgr->GetCreatureClassicLevel(entry)",
    "creature->BaseAttackTime",
    "creature->RangeAttackTime",
]
for needle in required_talent:
    if needle not in talents:
        raise SystemExit(f"expected safe encyclopedia server code missing: {needle}")

creature_block = talents.split("static void CreatureInfo", 1)[1].split("static void Request", 1)[0]
if "WorldDatabase.PQuery" in creature_block or "FROM creature_template" in creature_block:
    raise SystemExit("CreatureInfo must not issue ad-hoc world DB queries; use ObjectMgr CreatureTemplate")
if "|0|0" in creature_block:
    raise SystemExit("CreatureInfo must not send the old hard-coded 0-0 level range")

if "WorldDatabase" in runtime:
    raise SystemExit("companion runtime must not query WorldDatabase")
if "KnowledgeManaBonus(knowledgeTotal)" not in runtime:
    raise SystemExit("runtime must grant +1 max mana per 10 total knowledge")
if "RegenBasisPoints(rank)" not in runtime:
    raise SystemExit("runtime must use the capped percentage mana regen policy")

required_runtime = [
    "SafeCompanionEntry = 1933",
    "CompanionFollowDistance = 1.0f",
    "bool companionEnabled = false",
    "bool castsEnabled = false",
    'cmd == "companion"',
    'cmd == "casts"',
    'cmd == "test"',
    "SummonCreature(SafeCompanionEntry, spawnPos",
    "MoveFollow(player, CompanionFollowDistance",
    "SetCanFly(true)",
    "SetDisableGravity(true)",
    "SetHover(true)",
    "sSpellMgr->GetSpellInfo(spellId, difficulty)",
    "SPELL_AURA_SCHOOL_ABSORB",
    "CastSpellExtraArgs args(CompanionCastFlags())",
    "void OnHeal(Unit* healer, Unit* receiver, uint32& gain) override",
    "state->mana -= allowed; // strict 1 mana == 1 actually healed HP",
    "state.mana -= amount; // strict 1 mana == 1 absorb HP",
    "absorb->ChangeAmount(SpellEffectValue(amount))",
]
for needle in required_runtime:
    if needle not in runtime:
        raise SystemExit(f"runtime v5 missing required safety/balance rule: {needle}")

for forbidden in (
    "ShieldManaCost(",
    "HealManaCost(",
    "ApplyConservation(",
):
    if forbidden in runtime:
        raise SystemExit(f"runtime v5 must not discount 1:1 shield/heal mana costs: {forbidden}")

if "SetDisplayId(" in runtime or "GetFirstVisibleModel()" in runtime:
    raise SystemExit("v5 diagnostic runtime must not substitute unverified display models")

on_damage = runtime.split("void OnDamage", 1)[1].split("void OnHeal", 1)[0]
if "PQuery(" in on_damage or "DirectPExecute(" in on_damage:
    raise SystemExit("OnDamage hot path must not perform synchronous DB queries")
if "ModifyHealth" in on_damage:
    raise SystemExit("native companion runtime must not heal directly inside OnDamage")
if "damage -=" in on_damage or "barrier" in on_damage.lower():
    raise SystemExit("native companion runtime must not implement a hidden C++ absorb in OnDamage")

status_block = runtime.split('if (cmd.empty() || cmd == "status")', 1)[1].split('if (cmd == "companion")', 1)[0]
if "EnsureCompanion" in status_block:
    raise SystemExit("status/login path must not auto-spawn the diagnostic companion")

print("Encyclopedia SQL/ObjectMgr/native-spell 1:1 mana + bestiary data lint passed")
