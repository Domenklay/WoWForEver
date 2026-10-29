#!/usr/bin/env python3
import argparse
import re
import shutil
import tempfile
from pathlib import Path


def extend_addon_transport(core: Path) -> None:
    """Install a dedicated FEC1 server-bound addon endpoint.

    This deliberately does not depend on ForeverSubclass / ForeverAdvancement
    transport prefixes. It inserts after TrinityCore's stable addon-message
    length check inside ChatHandler.cpp and is idempotent.
    """
    chat = core / "src/server/game/Handlers/ChatHandler.cpp"
    text = chat.read_text()
    if 'prefix == "FEC1"' in text:
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
    block = (
        m.group(0)
        + "\n\n"
        + indent + '// ForeverEncyclopedia: server-bound client protocol; keep independent of other modules.\n'
        + indent + 'if (type == CHAT_MSG_WHISPER && prefix == "FEC1")\n'
        + indent + '{\n'
        + indent + '    sScriptMgr->OnPlayerAddonMessageSent(sender, type, prefix, text, sender);\n'
        + indent + '    return;\n'
        + indent + '}'
    )
    text = text[:m.start()] + block + text[m.end():]
    chat.write_text(text)


def inject(core: Path, module: Path) -> None:
    extend_addon_transport(core)

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
        server.joinpath("ForeverEncyclopedia.cpp").write_text("// test\n")

        inject(core, module)
        inject(core, module)

        loader_text = loader.read_text()
        chat_text = chat.read_text()
        assert loader_text.count("void AddSC_forever_encyclopedia();") == 1
        assert loader_text.count("    AddSC_forever_encyclopedia();") == 1
        assert chat_text.count('prefix == "FEC1"') == 1
        assert chat_text.count('text.length() > 255') == 1
        assert (loader.parent / "ForeverEncyclopedia/ForeverEncyclopedia.cpp").read_text() == "// test\n"
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
