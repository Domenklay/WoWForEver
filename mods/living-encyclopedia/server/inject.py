#!/usr/bin/env python3
import argparse
import re
import shutil
import tempfile
from pathlib import Path


def extend_addon_transport(core: Path) -> None:
    """Install dedicated FEC1 + FET1 server-bound addon endpoints.

    FEC1 is the encyclopedia/catalog protocol. FET1 is the talent/appearance
    protocol. Both are self-whispers and are routed through the same ScriptMgr
    callback without depending on ForeverAdvancement or other modules.
    """
    chat = core / "src/server/game/Handlers/ChatHandler.cpp"
    text = chat.read_text()

    if 'prefix == "FEC1"' in text and 'prefix == "FET1"' in text:
        return

    # Upgrade an older encyclopedia injection in place.
    old = re.compile(r'prefix\s*==\s*"FEC1"')
    matches = list(old.finditer(text))
    if len(matches) == 1 and 'prefix == "FET1"' not in text:
        m = matches[0]
        text = text[:m.start()] + '(prefix == "FEC1" || prefix == "FET1")' + text[m.end():]
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
    block = (
        m.group(0)
        + "\n\n"
        + indent + '// ForeverEncyclopedia: server-bound client protocols.\n'
        + indent + 'if (type == CHAT_MSG_WHISPER && (prefix == "FEC1" || prefix == "FET1"))\n'
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

    target = loader.parent / "ForeverEncyclopedia"
    target.mkdir(exist_ok=True)
    for name in ("ForeverEncyclopedia.cpp", "ForeverEncyclopediaTalents.cpp", "TalentRules.h"):
        source = module / "server" / name
        if not source.is_file():
            raise ValueError(f"missing encyclopedia server source: {source}")
        shutil.copy2(source, target / name)
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
        server.joinpath("TalentRules.h").write_text("// rules test\n")

        inject(core, module)
        inject(core, module)

        loader_text = loader.read_text()
        chat_text = chat.read_text()
        assert loader_text.count("void AddSC_forever_encyclopedia();") == 1
        assert loader_text.count("    AddSC_forever_encyclopedia();") == 1
        assert loader_text.count("void AddSC_forever_encyclopedia_talents();") == 1
        assert loader_text.count("    AddSC_forever_encyclopedia_talents();") == 1
        assert chat_text.count('prefix == "FEC1"') == 1
        assert chat_text.count('prefix == "FET1"') == 1
        assert chat_text.count('text.length() > 255') == 1
        assert (loader.parent / "ForeverEncyclopedia/ForeverEncyclopedia.cpp").read_text() == "// main test\n"
        assert (loader.parent / "ForeverEncyclopedia/ForeverEncyclopediaTalents.cpp").read_text() == "// talent test\n"
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
