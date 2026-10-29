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
        "    if (type == CHAT_MSG_WHISPER && prefix == \"FSC1\")\n"
        "    {\n"
        "        sScriptMgr->OnPlayerAddonMessageSent(sender, type, prefix, text, sender);\n"
        "        return;\n"
        "    }\n"
        "}\n"
    )

    cmd = ["python3", str(module / "server/inject.py"), str(core), "--module", str(module)]
    subprocess.run(cmd, check=True)
    subprocess.run(cmd, check=True)

    loader_text = loader.read_text()
    chat_text = chat.read_text()
    assert loader_text.count("void AddSC_forever_encyclopedia();") == 1
    assert loader_text.count("    AddSC_forever_encyclopedia();") == 1
    assert chat_text.count('prefix == "FSC1"') == 1
    assert chat_text.count('prefix == "FEC1"') == 1
    assert (custom / "ForeverEncyclopedia/ForeverEncyclopedia.cpp").is_file()
print("Encyclopedia injector test passed")
