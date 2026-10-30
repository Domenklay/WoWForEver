#!/usr/bin/env python3
import argparse
import re
import shutil
import tempfile
from pathlib import Path


PREFIXES = ("FEC1", "FET1", "FEB1")


def extend_addon_transport(core: Path) -> None:
    """Install dedicated encyclopedia server-bound addon endpoints."""
    chat = core / "src/server/game/Handlers/ChatHandler.cpp"
    text = chat.read_text()

    if all(f'prefix == "{p}"' in text for p in PREFIXES):
        return

    condition = re.compile(r'\((?:prefix\s*==\s*"FE[CTB]1"\s*(?:\|\|\s*)?)+\)')
    candidates = [m for m in condition.finditer(text) if 'prefix == "FEC1"' in m.group(0)]
    if len(candidates) == 1:
        m = candidates[0]
        replacement = '(' + ' || '.join(f'prefix == "{p}"' for p in PREFIXES) + ')'
        text = text[:m.start()] + replacement + text[m.end():]
        chat.write_text(text)
        return

    old = re.compile(r'prefix\s*==\s*"FEC1"')
    matches = list(old.finditer(text))
    if len(matches) == 1:
        m = matches[0]
        replacement = '(' + ' || '.join(f'prefix == "{p}"' for p in PREFIXES) + ')'
        text = text[:m.start()] + replacement + text[m.end():]
        chat.write_text(text)
        return

    pattern = re.compile(
        r'(?m)^(?P<indent>\s*)if\s*\(\s*text\.length\(\)\s*>\s*255\s*\)\s*\n\s*return;\s*$'
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f"addon message length-check anchor not found exactly once in ChatHandler.cpp (found {len(matches)})"
        )

    m = matches[0]
    indent = m.group("indent")
    prefix_condition = ' || '.join(f'prefix == "{p}"' for p in PREFIXES)
    block = (
        m.group(0)
        + "\n\n"
        + indent + '// ForeverEncyclopedia: server-bound client protocols.\n'
        + indent + f'if (type == CHAT_MSG_WHISPER && ({prefix_condition}))\n'
        + indent + '{\n'
        + indent + '    sScriptMgr->OnPlayerAddonMessageSent(sender, type, prefix, text, sender);\n'
        + indent + '    return;\n'
        + indent + '}'
    )
    text = text[:m.start()] + block + text[m.end():]
    chat.write_text(text)


def ensure_loader_registration(text: str, declaration: str, call: str) -> str:
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
        raise ValueError(f"Inconsistent loader registration for {declaration}")
    return text


def inject(core: Path, module: Path) -> None:
    extend_addon_transport(core)

    loader = core / "src/server/scripts/Custom/custom_script_loader.cpp"
    text = loader.read_text()
    text = ensure_loader_registration(text, "void AddSC_forever_encyclopedia();", "    AddSC_forever_encyclopedia();")
    text = ensure_loader_registration(text, "void AddSC_forever_encyclopedia_talents();", "    AddSC_forever_encyclopedia_talents();")
    text = ensure_loader_registration(text, "void AddSC_forever_encyclopedia_runtime();", "    AddSC_forever_encyclopedia_runtime();")

    target = loader.parent / "ForeverEncyclopedia"
    target.mkdir(exist_ok=True)
    copies = (
        ("ForeverEncyclopedia.cpp", "ForeverEncyclopedia.cpp"),
        ("ForeverEncyclopediaTalents.cpp", "ForeverEncyclopediaTalents.cpp"),
        ("ForeverEncyclopediaRuntimeV4.cpp", "ForeverEncyclopediaRuntime.cpp"),
        ("TalentRules.h", "TalentRules.h"),
    )
    for source_name, target_name in copies:
        source = module / "server" / source_name
        if not source.is_file():
            raise ValueError(f"missing encyclopedia server source: {source}")
        shutil.copy2(source, target / target_name)
    loader.write_text(text)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        core = root / "core"
        module = root / "module"

        loader = core / "src/server/scripts/Custom/custom_script_loader.cpp"
        loader.parent.mkdir(parents=True)
        loader.write_text("void AddCustomScripts()\n{\n}\n")

        chat = core / "src/server/game/Handlers/ChatHandler.cpp"
        chat.parent.mkdir(parents=True)
        chat.write_text(
            'void WorldSession::HandleChatAddonMessage()\n{\n'
            '    Player* sender = GetPlayer();\n'
            '    if (text.length() > 255)\n'
            '        return;\n\n'
            '    switch (type) { }\n'
            '}\n'
        )

        server = module / "server"
        server.mkdir(parents=True)
        server.joinpath("ForeverEncyclopedia.cpp").write_text("// main test\n")
        server.joinpath("ForeverEncyclopediaTalents.cpp").write_text("// talent test\n")
        server.joinpath("ForeverEncyclopediaRuntimeV4.cpp").write_text("// runtime v4 test\n")
        server.joinpath("TalentRules.h").write_text("// rules test\n")

        inject(core, module)
        inject(core, module)

        loader_text = loader.read_text()
        chat_text = chat.read_text()
        for name in ("forever_encyclopedia", "forever_encyclopedia_talents", "forever_encyclopedia_runtime"):
            assert loader_text.count(f"void AddSC_{name}();") == 1
            assert loader_text.count(f"    AddSC_{name}();") == 1
        for prefix in PREFIXES:
            assert chat_text.count(f'prefix == "{prefix}"') == 1
        assert chat_text.count('text.length() > 255') == 1
        assert (loader.parent / "ForeverEncyclopedia/ForeverEncyclopedia.cpp").read_text() == "// main test\n"
        assert (loader.parent / "ForeverEncyclopedia/ForeverEncyclopediaTalents.cpp").read_text() == "// talent test\n"
        assert (loader.parent / "ForeverEncyclopedia/ForeverEncyclopediaRuntime.cpp").read_text() == "// runtime v4 test\n"
        assert (loader.parent / "ForeverEncyclopedia/TalentRules.h").read_text() == "// rules test\n"
    print("ForeverEncyclopedia injector self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject ForeverEncyclopedia into a pinned TrinityCore checkout")
    parser.add_argument("core", nargs="?", type=Path)
    parser.add_argument("--module", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.core is None:
            parser.error("core is required unless --self-test is used")
        inject(args.core, args.module)
