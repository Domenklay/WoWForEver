#!/usr/bin/env python3
"""Copy the Forever subclass adapter into a TrinityCore source checkout before CMake collects scripts."""
import argparse
import re
import shutil
from pathlib import Path


UNLOCK_LEVEL = 10

COMMAND_SCRIPT = r'''
using namespace Trinity::ChatCommands;

class ForeverSubclassCommandScript final : public CommandScript
{
public:
    ForeverSubclassCommandScript() : CommandScript("forever_subclass_commands") { }

    std::span<ChatCommandBuilder const> GetCommands() const override
    {
        static ChatCommandTable commandTable =
        {
            { "fsub", HandleFsubCommand, rbac::RBAC_PERM_COMMAND_COMMANDS, Console::No },
        };
        return commandTable;
    }

    static bool HandleFsubCommand(ChatHandler* handler, char const* args)
    {
        if (!handler || !handler->GetSession() || !handler->GetSession()->GetPlayer())
            return false;

        std::string text = args ? args : "";
        if (text.empty())
            text = "status";

        ForeverSubclass::Request(handler->GetSession()->GetPlayer(), text);
        return true;
    }
};
'''


def replace_once(source, old, new, description):
    count = source.count(old)
    if count != 1:
        raise ValueError(f'{description} was not found exactly once (found {count})')
    return source.replace(old, new, 1)


def adapt_server_source(module):
    """Apply only small core-integration shims to the maintained adapter source.

    Gameplay logic lives in mods/forever-subclass/server/ForeverSubclass.cpp.
    Keep this injector deliberately small so normal gameplay edits do not break
    Docker builds because of brittle text anchors.
    """
    source = (module / 'server/ForeverSubclass.cpp').read_text()

    include_anchor = '#include "ScriptMgr.h"\n'
    source = replace_once(
        source,
        include_anchor,
        include_anchor + '#include "Chat.h"\n#include "ChatCommand.h"\n',
        'ForeverSubclass ScriptMgr include anchor',
    )

    # `rank` is a reserved MySQL keyword. The maintained adapter intentionally
    # keeps the schema column name for compatibility, so quote it in the runtime
    # SELECT before compiling the source. An unquoted SELECT causes ER_PARSE_ERROR;
    # this TrinityCore branch waits ten seconds and ABORT()s the worldserver.
    source = replace_once(
        source,
        'SELECT class_id,talent_id,rank FROM forever_character_subclass_talents WHERE guid={}',
        'SELECT class_id,talent_id,`rank` FROM forever_character_subclass_talents WHERE guid={}',
        'ForeverSubclass talent rank SQL query',
    )

    # Stable initialization is intentionally deferred to tame/petcall. Doing it
    # for every supported class in PlayerScript::OnLogin caused unnecessary pet
    # subsystem work during login and made disconnect diagnosis harder.
    tame_anchor = 'Pet* pet=p->CreateTamedPetFrom(creature,HunterTameSpell);'
    source = replace_once(
        source,
        tame_anchor,
        'p->GetOrInitPetStable();\n    ' + tame_anchor,
        'ForeverSubclass tame creation anchor',
    )

    # WoW Forever does not reliably relay an AddOn whisper sent to the same
    # character. Keep the normal TrinityCore command path as a diagnostic/fallback
    # into the exact same server-authoritative Request() handler.
    class_anchor = '} // namespace ForeverSubclass\n\nclass spell_forever_subclass final'
    source = replace_once(
        source,
        class_anchor,
        '} // namespace ForeverSubclass\n\n' + COMMAND_SCRIPT + '\nclass spell_forever_subclass final',
        'ForeverSubclass spell class anchor',
    )

    registration_pattern = re.compile(
        r'new ForeverSubclass::Startup\(\);\s*'
        r'new ForeverSubclass::Players\(\);\s*'
        r'new ForeverSubclass::Damage\(\);\s*'
        r'RegisterSpellScript\(spell_forever_subclass\);'
    )
    replacement = (
        'new ForeverSubclass::Startup();new ForeverSubclass::Players();new ForeverSubclass::Damage();\n'
        '    new ForeverSubclassCommandScript();\n'
        '    RegisterSpellScript(spell_forever_subclass);'
    )
    source, count = registration_pattern.subn(replacement, source, count=1)
    if count != 1:
        raise ValueError('ForeverSubclass AddSC registration anchor was not found exactly once')

    # Guard against reintroducing the abandoned temporary-spell experiment.
    for forbidden in ('AddTemporarySpell(', 'RemoveTemporarySpell(', 'TemporarySubclassSpells'):
        if forbidden in source:
            raise ValueError(f'Unsupported temporary-spell API leaked into injected source: {forbidden}')

    return source


def inject(core, module):
    core = Path(core).resolve()
    module = Path(module).resolve()

    loader = core / 'src/server/scripts/Custom/custom_script_loader.cpp'
    text = loader.read_text()
    declaration = 'void AddSC_forever_subclass();'
    if declaration not in text:
        pattern = r'(^void AddCustomScripts\(\)\s*\{)'
        if len(re.findall(pattern, text, re.M)) != 1:
            raise ValueError('Custom loader layout is not recognized')
        text = re.sub(
            pattern,
            declaration + '\n\n' + r'\1' + '\n    AddSC_forever_subclass();',
            text,
            count=1,
            flags=re.M,
        )
    elif text.count('    AddSC_forever_subclass();') != 1:
        raise ValueError('Inconsistent subclass loader registration')

    target = loader.parent / 'ForeverSubclass'
    target.mkdir(exist_ok=True)
    (target / 'forever_subclass').mkdir(exist_ok=True)
    (target / 'ForeverSubclass.cpp').write_text(adapt_server_source(module))
    shutil.copy2(module / 'vendor/src/SubclassSystem.cpp', target / 'SubclassSystem.cpp')

    source_header = module / 'vendor/include/forever_subclass/SubclassSystem.hpp'
    header = source_header.read_text()
    pattern = r'(subclassUnlockPrimaryLevel\s*=\s*)40(\s*;)'
    header, count = re.subn(pattern, rf'\g<1>{UNLOCK_LEVEL}\g<2>', header, count=1)
    if count != 1:
        raise ValueError('Subclass unlock-level declaration was not found exactly once')
    (target / 'forever_subclass/SubclassSystem.hpp').write_text(header)

    loader.write_text(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core', type=Path)
    parser.add_argument('--module', type=Path, default=Path(__file__).resolve().parents[1] / 'mods/forever-subclass')
    args = parser.parse_args()
    inject(args.core, args.module)
