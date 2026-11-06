#!/usr/bin/env python3
"""Ensure the client catalogue cannot silently drift from server talent costs/gates."""
from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parents[1]
header = (root / "server" / "TalentRules.h").read_text(encoding="utf-8")
catalog = (root / "addon" / "ForeverEncyclopedia" / "ForeverEncyclopediaTalentData.lua").read_text(encoding="utf-8")
overrides = (root / "addon" / "ForeverEncyclopedia" / "ForeverEncyclopediaTalentOverrides.lua").read_text(encoding="utf-8")
runtime = (root / "server" / "ForeverEncyclopediaRuntimeV5.cpp").read_text(encoding="utf-8")
purchases = (root / "server" / "ForeverEncyclopediaTalents.cpp").read_text(encoding="utf-8")

server_rows = {}
pattern = re.compile(
    r'\{"([a-z_]+)", "([a-z_]+)", (\d+), (\d+), (\d+), (\d+), "([a-z_]*)", (\d+)\}'
)
for match in pattern.finditer(header):
    key, branch, maximum, base, step, quad, required, req_rank = match.groups()
    assert key not in server_rows, key
    server_rows[key] = (
        branch, int(maximum), int(base), int(step), int(quad), required, int(req_rank)
    )

def field(line, name, default=None):
    match = re.search(r"\b" + name + r'=(?:"([^"]*)"|(\d+))', line)
    if match is None:
        return default
    return match.group(1) if match.group(1) is not None else int(match.group(2))

client_rows = {}
for line in catalog.splitlines():
    key = field(line, "key")
    if not key or field(line, "branch") is None:
        continue
    assert key not in client_rows, key
    client_rows[key] = (
        field(line, "branch"),
        field(line, "max"),
        field(line, "base"),
        field(line, "step"),
        field(line, "quad"),
        field(line, "req", ""),
        field(line, "reqRank", 0),
    )

assert len(server_rows) >= 35, len(server_rows)
assert server_rows.keys() == client_rows.keys(), (
    "Talent keys differ", set(server_rows) ^ set(client_rows)
)
for key, server_value in server_rows.items():
    client_value = client_rows[key]
    if key == "mana_overflow":
        # New prerequisite is assigned by TalentOverrides.lua on addon load.
        assert client_value[:5] == server_value[:5]
        assert 'node.req = "mana_capacity"' in overrides
        assert "node.reqRank = 10" in overrides
    else:
        assert server_value == client_value, (key, server_value, client_value)

server_implemented_body = header.split("inline bool Implemented(", 1)[1].split("inline uint32_t ShieldPercent", 1)[0]
lua_implemented_body = overrides.split("local implemented = {", 1)[1].split("\n}", 1)[0]
server_implemented = set(re.findall(r'"([a-z_]+)"', server_implemented_body))
client_implemented = set(re.findall(r"([a-z_]+)\s*=\s*true", lua_implemented_body))
assert server_implemented == client_implemented, (
    "Client/server functional talent lists differ",
    server_implemented ^ client_implemented,
)
assert server_implemented <= server_rows.keys()
assert "if (!Implemented(key))" in purchases
assert "node.implemented = implemented[node.key] == true" in overrides
assert "if not n.implemented then" in (
    root / "addon" / "ForeverEncyclopedia" / "ForeverEncyclopediaV21.lua"
).read_text(encoding="utf-8")

# Audit the critical 1:1 rule and that emergency shields can use reserved mana.
assert "state->mana -= allowed;" in runtime
assert "state.mana -= amount;" in runtime
assert "uint32 amount = std::min(state.mana, cap);" in runtime
assert "uint32 amount = std::min(state.pendingShieldAmount, state.mana);" in runtime
assert "uint32 spendable = SpendableMana(*state);" in runtime
assert "Talents::AmplifiedHeal" in runtime
# The stable channel keeps 0.9.8, while the explicit test channel pins this pack.
repo = root.parents[1]
stable = json.loads((repo / "app/src-tauri/addons/forever-encyclopedia.json").read_text(encoding="utf-8"))
manifest = json.loads((repo / "app/src-tauri/addons/forever-encyclopedia-test.json").read_text(encoding="utf-8"))
assert stable["version"] == "0.9.8-v2.1-smartai-abilities"
assert manifest["sourceCommit"] != stable["sourceCommit"]
toc_version = re.search(r"^## Version: (.+)$", (
    root / "addon/ForeverEncyclopedia/ForeverEncyclopedia.toc"
).read_text(encoding="utf-8"), re.MULTILINE).group(1)
assert manifest["version"] == toc_version == "0.9.9-v2.1-talent-mana"
for item in manifest["files"]:
    body = (root / "addon/ForeverEncyclopedia" / item["name"]).read_bytes()
    assert len(body) == item["size"], item["name"]
    assert hashlib.sha256(body).hexdigest() == item["sha256"], item["name"]
addon = (repo / "app/src-tauri/src/addon.rs").read_text(encoding="utf-8")
assert "TEST_CATALOG_URL" in addon and "fetch_testing_catalog" in addon
testing = json.loads((repo / "app/src-tauri/addons/testing-catalog.json").read_text(encoding="utf-8"))
assert testing["channel"] == "testing"
assert {item["manifest"]["name"] for item in testing["addons"]} >= {"ForeverAscension", "ForeverEncyclopedia"}
book = next(item["manifest"] for item in testing["addons"] if item["manifest"]["name"] == "ForeverEncyclopedia")
assert book["version"] == toc_version
assert book["sourceCommit"] == manifest["sourceCommit"]
assert f"BOOK_VERSION = '{toc_version}'" in (repo / "scripts/enable-clean-gameplay.py").read_text(encoding="utf-8")

print(f"Encyclopedia tooltip/server policy synced: {len(server_rows)} talents, "
      f"{len(server_implemented)} active")
