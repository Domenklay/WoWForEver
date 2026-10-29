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
    cmd = ["python3", str(module / "server/inject.py"), str(core), "--module", str(module)]
    subprocess.run(cmd, check=True)
    subprocess.run(cmd, check=True)
    text = loader.read_text()
    assert text.count("void AddSC_forever_encyclopedia();") == 1
    assert text.count("    AddSC_forever_encyclopedia();") == 1
    assert (custom / "ForeverEncyclopedia/ForeverEncyclopedia.cpp").is_file()
print("Encyclopedia injector test passed")
