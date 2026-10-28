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
    """Apply core-integration shims to the maintained adapter source."""
    source = (module / 'server/ForeverSubclass.cpp').read_text()

    include_anchor = '#include "ScriptMgr.h"\n'
    source = replace_once(
        source,
        include_anchor,
        include_anchor + '#include "Chat.h"\n#include "ChatCommand.h"\n',
        'ForeverSubclass ScriptMgr include anchor',
    )

    # `rank` is a reserved MySQL keyword. An unquoted SELECT makes this Forever
    # branch wait ten seconds and abort the worldserver on ER_PARSE_ERROR.
    source = replace_once(
        source,
        'SELECT class_id,talent_id,rank FROM forever_character_subclass_talents WHERE guid={}',
        'SELECT class_id,talent_id,`rank` FROM forever_character_subclass_talents WHERE guid={}',
        'ForeverSubclass talent rank SQL query',
    )

    # Virtual rage is only a fallback for primary classes whose native class DB2
    # has no rage slot. It behaves like warrior rage and decays out of combat.
    source = replace_once(
        source,
        'double manaFraction = 0, energyFraction = 0;',
        'double manaFraction = 0, energyFraction = 0, rageFraction = 0;',
        'ForeverSubclass resource fraction state',
    )
    rage_anchor = '''            pool.current=std::min(maximum,pool.current+whole);\n        }\n'''
    rage_replacement = '''            pool.current=std::min(maximum,pool.current+whole);\n        }\n        else if (p->IsAlive()&&power==POWER_RAGE)\n        {\n            if (c.inCombat) e.rageFraction=0;\n            else if (pool.current>0)\n            {\n                double lost=e.rageFraction+3.0*seconds;\n                int32 whole=int32(std::min(double(pool.current),std::floor(lost)));\n                e.rageFraction=pool.current==whole?0:lost-whole;\n                pool.current=std::max(0,pool.current-whole);\n            }\n        }\n'''
    source = replace_once(
        source,
        rage_anchor,
        rage_replacement,
        'ForeverSubclass virtual rage decay anchor',
    )

    # Native player power slots are authoritative whenever the primary class DB2
    # already exposes that power. This is critical for druids: Mana/Rage/Energy
    # are all real Player powers, even when only one is the current display power.
    powers_anchor = '''static std::vector<Powers> ClassPowers(Class id)\n{\n    if (id==Class::Warrior) return {POWER_RAGE};\n    if (id==Class::Rogue) return {POWER_ENERGY};\n    if (id==Class::Druid) return {POWER_MANA,POWER_RAGE,POWER_ENERGY};\n    return {POWER_MANA};\n}\n'''
    powers_replacement = powers_anchor + '''\nstatic Powers PrimaryClassPower(Class id)\n{\n    if (id==Class::Warrior) return POWER_RAGE;\n    if (id==Class::Rogue) return POWER_ENERGY;\n    return POWER_MANA;\n}\n\nstatic bool HasNativePowerSlot(Player* p,Powers power)\n{\n    return p&&p->GetPowerIndex(power)<MAX_POWERS_PER_CLASS;\n}\n\nstatic int32 NativePowerValue(Player* p,Powers power)\n{\n    int32 value=p->GetPower(power);\n    return power==POWER_RAGE?value/10:value;\n}\n\nstatic int32 NativePowerMaximum(Player* p,Powers power)\n{\n    int32 value=p->GetMaxPower(power);\n    return power==POWER_RAGE?value/10:value;\n}\n'''
    source = replace_once(
        source,
        powers_anchor,
        powers_replacement,
        'ForeverSubclass native power helper anchor',
    )

    # A native slot wins over the old virtual pool even when it is not currently
    # displayed by the client. Stale saved virtual values are discarded.
    source = replace_once(
        source,
        '        if (power==p->GetPowerType()) continue;\n',
        '        if (HasNativePowerSlot(p,power)) { e.pools.erase(power);continue; }\n',
        'ForeverSubclass refresh native power selection',
    )

    available_anchor = '''static int32 Available(Player* p,Entry& e,Powers power)\n{\n    if (power==p->GetPowerType()) return power==POWER_RAGE?p->GetPower(power)/10:p->GetPower(power);\n    return e.pools.count(power)?e.pools[power].current:0;\n}\n'''
    available_replacement = '''static int32 Available(Player* p,Entry& e,Powers power)\n{\n    if (HasNativePowerSlot(p,power)) return NativePowerValue(p,power);\n    return e.pools.count(power)?e.pools[power].current:0;\n}\n'''
    source = replace_once(source, available_anchor, available_replacement, 'ForeverSubclass available power helper')

    snapshot_power_anchor = '''            int32 max=power==p->GetPowerType()?p->GetMaxPower(power):PowerMaximum(p,e,power);\n            if (power==POWER_RAGE&&power==p->GetPowerType()) max/=10;\n            Send(p,Trinity::StringFormat("POWER {} {} {}",int(power),Available(p,e,power),max));\n'''
    snapshot_power_replacement = '''            int32 max=HasNativePowerSlot(p,power)?NativePowerMaximum(p,power):PowerMaximum(p,e,power);\n            Send(p,Trinity::StringFormat("POWER {} {} {}",int(power),Available(p,e,power),max));\n'''
    source = replace_once(source, snapshot_power_anchor, snapshot_power_replacement, 'ForeverSubclass power snapshot')

    pay_anchor = '        if(def.root.power==p->GetPowerType()) p->ModifyPower(def.root.power,-cost*(def.root.power==POWER_RAGE?10:1));\n        else e.pools[def.root.power].current=std::max(0,e.pools[def.root.power].current-cost);\n'
    pay_replacement = '        if(HasNativePowerSlot(p,def.root.power)) p->ModifyPower(def.root.power,-cost*(def.root.power==POWER_RAGE?10:1));\n        else e.pools[def.root.power].current=std::max(0,e.pools[def.root.power].current-cost);\n'
    source = replace_once(source, pay_anchor, pay_replacement, 'ForeverSubclass native power payment')

    damage_anchor = '''            Player* p=unit?unit->ToPlayer():nullptr;if(!p||p->GetPowerType()==POWER_RAGE) return;\n            auto i=Entries.find(p->GetGUID().GetCounter());if(i==Entries.end()) return;auto& e=i->second;\n            if(e.state.activeSubclass&&HasClassPower(*e.state.activeSubclass,POWER_RAGE))\n            {\n                Refresh(p,e);auto& pool=e.pools[POWER_RAGE];int32 gain=int32(std::lround(6.0*RegenMultiplier(e,*e.state.activeSubclass)));\n                pool.current=std::min(pool.maximum,pool.current+std::max(1,gain));\n            }\n'''
    damage_replacement = '''            Player* p=unit?unit->ToPlayer():nullptr;if(!p) return;\n            auto i=Entries.find(p->GetGUID().GetCounter());if(i==Entries.end()) return;auto& e=i->second;\n            if(e.state.activeSubclass&&HasClassPower(*e.state.activeSubclass,POWER_RAGE))\n            {\n                Refresh(p,e);int32 gain=int32(std::lround(6.0*RegenMultiplier(e,*e.state.activeSubclass)));gain=std::max(1,gain);\n                if(HasNativePowerSlot(p,POWER_RAGE))\n                {\n                    // Bear form / warrior already has native rage generation; do not double it.\n                    if(p->GetPowerType()!=POWER_RAGE) p->ModifyPower(POWER_RAGE,gain*10);\n                }\n                else\n                {\n                    auto& pool=e.pools[POWER_RAGE];pool.current=std::min(pool.maximum,pool.current+gain);\n                }\n            }\n'''
    source = replace_once(source, damage_anchor, damage_replacement, 'ForeverSubclass rage generation')

    # The HUD needs the primary-class resource independently of the active form.
    class_snapshot_anchor = '    for (auto const& [id,v]:c.classes) Send(p,Trinity::StringFormat("CLASS {} {} {} {}",uint8(id),v.level,v.xp,sObjectMgr->GetXPForLevel(v.level)));\n'
    class_snapshot_replacement = class_snapshot_anchor + '''    Powers basePower=PrimaryClassPower(c.primaryClass);\n    int32 baseCurrent=NativePowerValue(p,basePower),baseMax=NativePowerMaximum(p,basePower);\n    Send(p,Trinity::StringFormat("BASEPOWER {} {} {}",int(basePower),baseCurrent,baseMax));\n'''
    source = replace_once(
        source,
        class_snapshot_anchor,
        class_snapshot_replacement,
        'ForeverSubclass base power snapshot anchor',
    )

    # Stable initialization is deferred to tame/petcall.
    tame_anchor = 'Pet* pet=p->CreateTamedPetFrom(creature,HunterTameSpell);'
    source = replace_once(
        source,
        tame_anchor,
        'p->GetOrInitPetStable();\n    ' + tame_anchor,
        'ForeverSubclass tame creation anchor',
    )

    # Keep the TrinityCore command path as diagnostic/fallback into Request().
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
