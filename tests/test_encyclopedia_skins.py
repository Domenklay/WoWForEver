#!/usr/bin/env python3
"""Regression contract for the 70658 flying-book test models."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
module = root / "mods/living-encyclopedia"
lua = (module / "addon/ForeverEncyclopedia/ForeverEncyclopediaTalentData.lua").read_text()
v21 = (module / "addon/ForeverEncyclopedia/ForeverEncyclopediaV21.lua").read_text()
legacy = (module / "addon/ForeverEncyclopedia/ForeverEncyclopediaLegacy.lua").read_text()
defs = (module / "server/AppearanceSkins.h").read_text()
rules = (module / "server/TalentRules.h").read_text()
talents = (module / "server/ForeverEncyclopediaTalents.cpp").read_text()
runtime = (module / "server/ForeverEncyclopediaRuntimeV5.cpp").read_text()
injector = (module / "server/inject.py").read_text()

expected = {
    "living_book": (171120, 0),
    "archivist": (205781, 100),
    "knowledge_spirit": (161896, 500),
    "small_construct": (183783, 1500),
    "runekeeper": (130946, 5000),
    "test_lofty_libram": (68806, 0),
    "test_animated_tome": (171120, 0),
    "test_gusting_grimoire": (69208, 0),
    "test_agitated_tome": (101633, 0),
    "test_troubled_tome": (198511, 0),
    "test_chromies_codex": (227052, 0),
}
assert len(expected) == 11

lua_rows = dict(
    (key, (int(threshold), int(creature)))
    for key, threshold, creature in re.findall(
        r'key="([^"]+)",\s*name="[^"]+",\s*threshold=(\d+),\s*creature=(\d+)',
        lua,
    )
)
assert set(lua_rows) == set(expected), f"client models: {lua_rows}"
for key, (creature, threshold) in expected.items():
    assert lua_rows[key] == (threshold, creature), (key, lua_rows[key])

server_rows = dict(
    (key, (int(creature), int(threshold)))
    for key, creature, threshold in re.findall(
        r'\{"([^"]+)",\s*(\d+),\s*(\d+),\s*\d+\}',
        defs,
    )
)
assert server_rows == expected, f"server/client skin IDs differ: {server_rows}"
for key, (creature, threshold) in expected.items():
    assert f'if (key == "{key}") return {threshold};' in rules, key
    if key.startswith("test_"):
        assert f'key="{key}"' in lua and "testing=true" in lua

assert "for (auto const& skin : ForeverEncyclopedia::Skins::All)" in talents
assert '"SELECTED|" + key' in talents
assert "Send(player, Trinity::StringFormat(\"APPEARANCE|" in talents
assert '("AppearanceSkins.h", "AppearanceSkins.h")' in injector
assert '#include "AppearanceSkins.h"' in runtime

# A selected skin must become the flying companion's actual native model,
# not just a client-side appearance preview.
assert 'state.appearanceKey = SelectedAppearance(player)' in runtime
assert 'companion->SetDisplayId(display,true)' in runtime
assert "ApplySkin(player,state,companion)" in runtime
assert 'if (cmd == "skin")' in runtime
assert 'std::string selected=SelectedAppearance(player)' in runtime
assert 'if (state->appearanceKey!=selected)' in runtime
assert '"SKIN_MISSING"' in runtime and '"SKIN_APPLIED"' in runtime
assert '"FET1"' not in runtime or 'RequestPrefix[] = "FEB1"' in runtime
assert 'Send(player,"SELECTED|' not in runtime
assert 'if (changed) send(RUNTIME_REQ,"skin") end' in v21
assert 'notifyNative("appearance")' in v21
assert "test_lofty_libram" in lua and "test_chromies_codex" in lua
assert 'Только просмотр: нужен новый worldserver' in legacy
assert 'Тестовая модель' in legacy

print("FOREVER ENCYCLOPEDIA 11 SKINS / LIVE COMPANION PROTOCOL VERIFIED")
