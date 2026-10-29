#!/usr/bin/env python3
import argparse
import re
import shutil
from pathlib import Path


def inject(core: Path, module: Path) -> None:
    loader = core / "src/server/scripts/Custom/custom_script_loader.cpp"
    text = loader.read_text()
    declaration = "void AddSC_forever_encyclopedia();"
    call = "    AddSC_forever_encyclopedia();"

    if declaration not in text:
        pattern = r"(^void AddCustomScripts\(\)\s*\{)"
        if len(re.findall(pattern, text, re.M)) != 1:
            raise ValueError("Custom loader layout is not recognized")
        text = re.sub(
            pattern,
            declaration + "\n\n" + r"\1" + "\n" + call,
            text,
            count=1,
            flags=re.M,
        )
    elif text.count(call) != 1:
        raise ValueError("Inconsistent encyclopedia loader registration")

    target = loader.parent / "ForeverEncyclopedia"
    target.mkdir(exist_ok=True)
    shutil.copy2(module / "server/ForeverEncyclopedia.cpp", target / "ForeverEncyclopedia.cpp")
    loader.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject ForeverEncyclopedia into a pinned TrinityCore checkout")
    parser.add_argument("core", type=Path)
    parser.add_argument("--module", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    inject(args.core, args.module)
