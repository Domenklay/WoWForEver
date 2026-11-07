#!/usr/bin/env python3
import subprocess
import tempfile
from pathlib import Path

module = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    core = Path(td) / "core"

    custom = core / "src/server/scripts/Custom"
    custom.mkdir(parents=True)
    loader = custom / "custom_script_loader.cpp"
    loader.write_text("void AddCustomScripts()\n{\n}\n")

    handlers = core / "src/server/game/Handlers"
    handlers.mkdir(parents=True)
    chat = handlers / "ChatHandler.cpp"
    chat.write_text(
        "void WorldSession::HandleChatAddonMessage()\n"
        "{\n"
        "    Player* sender = GetPlayer();\n"
        "    if (text.length() > 255)\n"
        "        return;\n\n"
        "    switch (type) { }\n"
        "}\n"
    )

    scripting = core / "src/server/game/Scripting"
    scripting.mkdir(parents=True)
    header = scripting / "ScriptMgr.h"
    header.write_text(
        "class UnitScript {\n"
        "        virtual void OnHeal(Unit* healer, Unit* reciever, uint32& gain);\n"
        "};\nclass ScriptMgr {\n"
        "        void OnHeal(Unit* healer, Unit* reciever, uint32& gain);\n"
        "};\n"
    )
    cpp = scripting / "ScriptMgr.cpp"
    cpp.write_text(
        "// Unit\nvoid ScriptMgr::OnHeal(Unit* healer, Unit* receiver, uint32& gain) {}\n"
        "void UnitScript::OnHeal(Unit* /*healer*/, Unit* /*reciever*/, uint32& /*gain*/)\n{\n}\n"
    )
    unit = core / "src/server/game/Entities/Unit/Unit.cpp"
    unit.parent.mkdir(parents=True)
    unit.write_text(
        "    if (addhealth)\n        gain = victim->ModifyHealth(int32(addhealth));\n\n"
        "    // Hook for OnHeal Event\n"
    )

    cmd = ["python3", str(module / "server/inject.py"), str(core), "--module", str(module)]
    subprocess.run(cmd, check=True)
    subprocess.run(cmd, check=True)

    loader_text = loader.read_text()
    chat_text = chat.read_text()
    for name in ("forever_encyclopedia", "forever_encyclopedia_talents", "forever_encyclopedia_runtime", "forever_encyclopedia_abilities"):
        assert loader_text.count(f"void AddSC_{name}();") == 1
        assert loader_text.count(f"    AddSC_{name}();") == 1
    for prefix in ("FEC1", "FET1", "FEB1"):
        assert chat_text.count(f'prefix == "{prefix}"') == 1
    assert chat_text.count('text.length() > 255') == 1
    assert header.read_text().count("OnHealBefore(") == 2
    assert cpp.read_text().count("OnHealBefore(") == 3
    unit_text = unit.read_text()
    assert unit_text.index("OnHealBefore(") < unit_text.index("ModifyHealth(")

    assert (custom / "ForeverEncyclopedia/ForeverEncyclopedia.cpp").is_file()
    assert (custom / "ForeverEncyclopedia/ForeverEncyclopediaTalents.cpp").is_file()
    assert (custom / "ForeverEncyclopedia/ForeverEncyclopediaRuntime.cpp").is_file()
    assert (custom / "ForeverEncyclopedia/ForeverEncyclopediaAbilities.cpp").is_file()
    assert (custom / "ForeverEncyclopedia/TalentRules.h").is_file()
print("Encyclopedia injector test passed")
