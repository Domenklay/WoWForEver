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
assert version and version.group(1) == "0.9.23-v2.1-fdf-diagnostics", version
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
assert "bridge.RequestCreatureInfo(selected.entry)" in legacy
for key in ("protection", "healing", "support", "wisdom", "knowledge"):
    assert key in source
assert "node.implemented" in overrides
assert '0.9.22-v2.1-loot-preview' not in source, "Server talents must remain version-independent"
# Archive UX must use the entire current-zone catalogue, not legacy pages.
creature_view=legacy.split("local function drawCreatureView()",1)[1].split("local function drawZoneView()",1)[0]
assert 'local list=frame(base,16,39,390,395,BROWN)' in creature_view
assert 'local detail=frame(base,418,39,439,395,BROWN)' in creature_view
assert 'CreateFrame("EditBox"' in creature_view
assert 'dropdown(list,9,40,178,creatureType,MONSTER_TYPES' in creature_view
assert 'dropdown(list,195,40,184,creatureLocation,options' in creature_view
assert 'filteredArchiveRecords(allRows)' in creature_view
assert 'local rowSize=30' in creature_view, "Compact rows must show more monsters"
assert 'local viewHeight=286' in creature_view, "List must reclaim wasted vertical space"
assert 'button(base,16,5,135,28,"К коллекции"' in creature_view
assert 'modelPreview(detail,12,39,182,233' in creature_view
assert 'drawCreatureLoot(detail,selected)' in creature_view
assert 'local panel=frame(parent,202,39,223,233,BROWN)' in legacy
assert 'GameTooltip:SetHyperlink("item:"..item.entry)' in legacy
assert 'rawChanceLabel(item)' in legacy
assert 'lootItemPresentation(item.entry)' in legacy
assert 'Interface\\\\DialogFrame\\\\UI-DialogBox-Border' in legacy
assert 'Interface\\\\AchievementFrame\\\\UI-Achievement-AchievementBackground' in legacy
assert 'BackdropTemplate' in legacy
assert 'infoBody=scrollArea(detail,13,283,412,103' in creature_view
assert 'font(list,11,265' not in creature_view, "No reserved footer space"
assert 'currentName.." v"' in legacy, "Dropdown symbols must be readable in client 70658"
assert 'archiveRecordName(item)' in creature_view
assert 'selectedCreatureEntry' in creature_view
assert 'OnVerticalScroll' in creature_view and 'OnMouseWheel' in creature_view
assert 'prev=button' not in creature_view and 'nextPage=button' not in creature_view
assert 'bridge.RequestFullCatalog()' in legacy
assert 'bridge.RequestFullArchive()' in legacy
assert 'archiveRecords' in legacy and 'state.archiveAll' in legacy
assert 'state.catalogAll' in legacy and 'state.catalogAllZone' in legacy
assert 'locationChoices' in legacy and 'filteredArchiveRecords' in legacy
assert 'catalogAllGeneration' in v21 and 'catalogAllSeen' in v21
assert 'archiveGeneration' in v21 and 'archiveSeen' in v21
assert 'state.archiveSupported=true' in v21
assert 'state.lootSupported=true' in v21
assert '"LHEAD|"' in v21 and '"LITEM|"' in v21 and '"LEND|"' in v21
assert 'RequestCreatureLoot=requestCreatureLoot' in v21
assert '"ARHEAD|"' in v21 and '"AREND"' in v21
assert 'queueCatalogRequest' in v21, "Server FEC1 is rate limited"
assert '0.27,pump' in v21, "Pace all catalogue requests above server 150ms"
# Account-wide source is opt-in; never fake other-zone unknown mobs.
server=(ROOT / "mods/living-encyclopedia/server/ForeverEncyclopedia.cpp").read_text(encoding="utf-8")
assert 'Send(p,"CAPS ARCHIVE1")' in server
assert 'static void Archive(Player* p, uint32 page)' in server
assert 'first_map,first_zone FROM forever_encyclopedia_discovery' in server
assert 'WHERE account_id={} AND kind={}' in server
assert 'if (cmd=="archive")' in server
assert 'ARHEAD|' in server and 'AREND' in server
assert 'first_zone is the place of first discovery' in server
assert 'Send(p,"CAPS LOOT1")' in server
assert 'static void LootPreview(Player* p, uint32 entry, uint32 page)' in server
assert 'creature_template_difficulty' in server and 'creature_loot_template' in server
assert 'ItemType=0 AND Item<>0' in server
assert 'creature not discovered' in server
assert 'LITEM|' in server and 'LHEAD|' in server and 'LEND|' in server

print("ENCYCLOPEDIA 0.9.21 LOOT PANEL / HOVER / SERVER CAPABILITIES CHECK PASSED")
