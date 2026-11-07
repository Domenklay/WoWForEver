#!/usr/bin/env python3
"""Static coverage for Forever 70658's fourth native Legacy page."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "mods/living-encyclopedia/addon/ForeverEncyclopedia"
toc = (ADDON / "ForeverEncyclopedia.toc").read_text(encoding="utf-8")
legacy = (ADDON / "ForeverEncyclopediaLegacy.lua").read_text(encoding="utf-8")
v21 = (ADDON / "ForeverEncyclopediaV21.lua").read_text(encoding="utf-8")
source = (ADDON / "ForeverEncyclopediaTalentData.lua").read_text(encoding="utf-8")
overrides = (ADDON / "ForeverEncyclopediaTalentOverrides.lua").read_text(encoding="utf-8")

version = re.search(r"^## Version: (.+)$", toc, re.MULTILINE)
assert version and version.group(1) == "0.9.13-v2.1-legacy-book", version
assert "## Interface: 16001" in toc
entries = [line for line in toc.splitlines() if line and not line.startswith("#")]
assert len(entries) == len(set(entries)), "Duplicate TOC file"
assert "ForeverEncyclopediaLegacy.lua" in entries
assert "ForeverDungeonFinder.lua" in entries
assert entries.index("ForeverEncyclopediaTalentData.lua") < entries.index("ForeverEncyclopediaTalentOverrides.lua")
assert entries.index("ForeverEncyclopediaTalentOverrides.lua") < entries.index("ForeverEncyclopediaV21.lua")
assert entries.index("ForeverEncyclopediaV21.lua") < entries.index("ForeverEncyclopediaLegacy.lua")
assert all((ADDON / f).is_file() for f in entries), "Missing addon source file"

for needle in (
    'LegacySystemFrame', 'LegacySystemTabTemplate',
    'ForeverEncyclopediaLegacyTab', 'ForeverEncyclopediaLegacyPage',
    'table.insert(host.Tabs,tab)', 'table.insert(host.Pages,page)',
    'host:SelectPage(4)', 'host.LegacyTreeTab', 'SetCustomOnMouseUpHandler',
    'bridge.BuyTalent(n.key)', 'bridge.RequestCatalog(', 'bridge.RequestZones()',
    'state.creatures', 'state.items', 'state.zones', 'state.knowledgeAvailable',
    'state.knowledgeTotal', 'state.ranks[n.key]',
    'n.implemented', 'checkPrereq(n)', 'ForeverEncyclopediaTalentCost',
    'GameTooltip:AddLine(', 'ForeverEncyclopediaTalentData',
):
    if needle != 'ForeverEncyclopediaTalentData':
        assert needle in legacy, needle
assert "collectionStat" in legacy
assert "Статус прогресса" not in legacy
assert "StatusBar" not in legacy, "Knowledge must be shown as cards, not a reward bar"
assert 'CreateFrame("Frame","ForeverEncyclopediaLegacyTab",UIParent' not in legacy
assert 'LegacySystemFrame.Pages=' not in legacy, "Must append native pages, never replace them"
assert 'LegacySystemFrame.Tabs=' not in legacy
assert 'ToggleLegacySystemUI()' not in legacy, "Direct native page, no duplicate tab toggles"
assert 'local notifyNative' in v21 and 'notifyNative=function(kind)' in v21
assert '_G.ForeverEncyclopediaUIBridge' in v21
assert 'SlashCmdList["FOREVERENCYCLOPEDIAV21"]=toggleEncyclopedia' in v21
assert "bridge.RequestCreatureInfo(rec.entry)" in legacy
for key in ("protection", "healing", "support", "wisdom", "knowledge"):
    assert key in source
assert "node.implemented" in overrides
assert '0.9.13-v2.1-legacy-book' not in source, "Server talents must remain version-independent"
print("ENCYCLOPEDIA 0.9.13 NATIVE LEGACY RELEASE CHECK PASSED")
