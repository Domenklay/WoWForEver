#!/usr/bin/env python3
"""Copy the adapter into a TrinityCore source checkout before CMake collects scripts."""
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


def adapt_server_source(module):
    source=(module/'server/ForeverSubclass.cpp').read_text()

    include_anchor='#include "ScriptMgr.h"\n'
    if source.count(include_anchor)!=1:
        raise ValueError('ForeverSubclass ScriptMgr include anchor was not found exactly once')
    source=source.replace(include_anchor,include_anchor+'#include "Chat.h"\n#include "ChatCommand.h"\n',1)

    # Push initial state on login and make sure even non-Hunter primary classes
    # have a stable container before the subclass pet system touches Pet.cpp.
    old_login='void OnLogin(Player* p,bool) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);State(p); } }'
    new_login='void OnLogin(Player* p,bool) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);p->GetOrInitPetStable();auto& e=State(p);Snapshot(p,e); } }'
    if source.count(old_login)!=1:
        raise ValueError('ForeverSubclass login hook anchor was not found exactly once')
    source=source.replace(old_login,new_login,1)

    # The stock Tame Beast spell is hard restricted to primary Hunter. Our
    # subclass route uses the same pet creation path, but must retain the normal
    # CreatureTemplate tameability rules and initialize the stable explicitly.
    old_tame='Creature* creature=p->GetSelectedUnit()?p->GetSelectedUnit()->ToCreature():nullptr;\n    if(!creature||creature->IsPet()||!creature->GetCreatureTemplate()||creature->GetCreatureTemplate()->type!=CREATURE_TYPE_BEAST) {\n        error="select a tameable beast";return false;\n    }'
    new_tame='Creature* creature=p->GetSelectedUnit()?p->GetSelectedUnit()->ToCreature():nullptr;\n    CreatureTemplate const* creatureTemplate=creature?creature->GetCreatureTemplate():nullptr;\n    CreatureDifficulty const* creatureDifficulty=creature?creature->GetCreatureDifficulty():nullptr;\n    if(!creature||creature->IsPet()||!creatureTemplate||!creatureDifficulty||!creatureTemplate->IsTameable(false,creatureDifficulty)) {\n        error="select a tameable beast";return false;\n    }\n    p->GetOrInitPetStable();'
    if source.count(old_tame)!=1:
        raise ValueError('ForeverSubclass tame hook anchor was not found exactly once')
    source=source.replace(old_tame,new_tame,1)

    old_call='if(p->GetPet()) { error="pet already active";return false; }\n    Pet* pet=new Pet(p,HUNTER_PET);'
    new_call='if(p->GetPet()) { error="pet already active";return false; }\n    p->GetOrInitPetStable();\n    Pet* pet=new Pet(p,HUNTER_PET);'
    # This pattern occurs only in CallHunterPet after the tame path has already
    # been rewritten above.
    if source.count(old_call)!=1:
        raise ValueError('ForeverSubclass pet call hook anchor was not found exactly once')
    source=source.replace(old_call,new_call,1)

    # WoW Forever 70532 does not reliably deliver AddOn whispers sent to the same
    # character. Provide a normal TrinityCore command path that forwards into the
    # exact same server-authoritative Request() implementation.
    class_anchor='} // namespace ForeverSubclass\n\nclass spell_forever_subclass final'
    if source.count(class_anchor)!=1:
        raise ValueError('ForeverSubclass spell class anchor was not found exactly once')
    source=source.replace(class_anchor,'} // namespace ForeverSubclass\n\n'+COMMAND_SCRIPT+'\nclass spell_forever_subclass final',1)

    registration_pattern=(
        r'new ForeverSubclass::Startup\(\);\s*'
        r'new ForeverSubclass::Players\(\);\s*'
        r'new ForeverSubclass::Damage\(\);\s*'
        r'RegisterSpellScript\(spell_forever_subclass\);'
    )
    replacement=(
        'new ForeverSubclass::Startup();new ForeverSubclass::Players();new ForeverSubclass::Damage();\n'
        '    new ForeverSubclassCommandScript();\n'
        '    RegisterSpellScript(spell_forever_subclass);'
    )
    source,count=re.subn(registration_pattern,replacement,source,count=1)
    if count!=1:
        raise ValueError('ForeverSubclass AddSC registration anchor was not found exactly once')
    return source


def inject(core, module):
    core=Path(core).resolve();module=Path(module).resolve()
    loader=core/'src/server/scripts/Custom/custom_script_loader.cpp'
    text=loader.read_text()
    declaration='void AddSC_forever_subclass();'
    if declaration not in text:
        pattern=r'(^void AddCustomScripts\(\)\s*\{)'
        if len(re.findall(pattern,text,re.M))!=1:
            raise ValueError('Custom loader layout is not recognized')
        text=re.sub(pattern,declaration+'\n\n'+r'\1'+'\n    AddSC_forever_subclass();',text,count=1,flags=re.M)
    elif text.count('    AddSC_forever_subclass();')!=1:
        raise ValueError('Inconsistent subclass loader registration')
    target=loader.parent/'ForeverSubclass';target.mkdir(exist_ok=True)
    (target/'forever_subclass').mkdir(exist_ok=True)
    (target/'ForeverSubclass.cpp').write_text(adapt_server_source(module))
    shutil.copy2(module/'vendor/src/SubclassSystem.cpp',target/'SubclassSystem.cpp')

    # Keep the vendored prototype pristine, but adapt the copy compiled into our
    # Forever server. This lets the original prototype tests continue to describe
    # the source archive while our deployed rules unlock subclasses at level 10.
    source_header=module/'vendor/include/forever_subclass/SubclassSystem.hpp'
    header=source_header.read_text()
    pattern=r'(subclassUnlockPrimaryLevel\s*=\s*)40(\s*;)'
    header,count=re.subn(pattern,rf'\g<1>{UNLOCK_LEVEL}\g<2>',header,count=1)
    if count!=1:
        raise ValueError('Subclass unlock-level declaration was not found exactly once')
    (target/'forever_subclass/SubclassSystem.hpp').write_text(header)
    loader.write_text(text)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core',type=Path)
    parser.add_argument('--module',type=Path,default=Path(__file__).resolve().parents[1]/'mods/forever-subclass')
    args=parser.parse_args();inject(args.core,args.module)
