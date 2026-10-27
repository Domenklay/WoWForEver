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

TEMPORARY_SPELL_HELPERS = r'''
static std::map<uint64,std::set<uint32>> TemporarySubclassSpells;

static void SyncTemporarySubclassSpells(Player* p,Entry& e)
{
    uint64 guid=p->GetGUID().GetCounter();
    std::set<uint32> desired;
    if(e.state.activeSubclass)
    {
        uint8 owner=uint8(*e.state.activeSubclass);
        for(uint32 selected:e.state.selectedSubclassSpells)
        {
            uint32 best=BestRank(e,selected);
            auto found=Definitions.find(best);
            if(found!=Definitions.end()&&found->second.root.owner==owner&&found->second.level<=e.state.classes[*e.state.activeSubclass].level)
                desired.insert(best);
        }
    }

    auto& current=TemporarySubclassSpells[guid];
    for(uint32 oldSpell:current)
        if(!desired.count(oldSpell))
            p->RemoveTemporarySpell(oldSpell);
    for(uint32 newSpell:desired)
        if(!current.count(newSpell))
            p->AddTemporarySpell(newSpell);
    current=std::move(desired);
}

static void SyncHiddenSubclassPowers(Player* p,Entry& e)
{
    if(!e.state.activeSubclass) return;
    for(Powers power:ClassPowers(*e.state.activeSubclass))
    {
        if(power==p->GetPowerType()) continue;
        auto found=e.pools.find(power);
        if(found==e.pools.end()) continue;
        int32 scale=power==POWER_RAGE?10:1;
        int32 maximum=std::max(1,found->second.maximum);
        p->SetMaxPower(power,maximum*scale);
        p->SetPower(power,std::clamp(found->second.current,0,maximum)*scale);
    }
}

static void CaptureHiddenSubclassPower(Player* p,Entry& e,Powers power)
{
    if(power==p->GetPowerType()) return;
    auto found=e.pools.find(power);if(found==e.pools.end()) return;
    int32 scale=power==POWER_RAGE?10:1;
    found->second.current=std::clamp(p->GetPower(power)/scale,0,found->second.maximum);
}
'''

NATIVE_SPELL_SCRIPT = r'''class spell_forever_subclass final : public SpellScript {
    PrepareSpellScript(spell_forever_subclass);
    bool _secondary=false,_manual=false;double _factor=1,_intellectBonus=0;Powers _power=POWER_MANA;
    bool Load() override {
        using namespace ForeverSubclass;if(!Ready) return false;Player* p=GetCaster()->ToPlayer();auto i=Definitions.find(GetSpellInfo()->Id);
        return Ready&&p&&i!=Definitions.end()&&p->GetClass()!=i->second.root.owner;
    }
    SpellCastResult Check() {
        using namespace ForeverSubclass;
        _manual=std::any_cast<CastTag>(&GetSpell()->m_customArg)!=nullptr;
        std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);uint32 id=GetSpellInfo()->Id;
        if(BestRank(e,id)!=id) return SPELL_FAILED_NOT_KNOWN;
        return Allowed(p,e,id)?SPELL_CAST_OK:SPELL_FAILED_NO_POWER;
    }
    void Pay() {
        using namespace ForeverSubclass;std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);uint32 id=GetSpellInfo()->Id;
        if(!Allowed(p,e,id)) { FinishCast(SPELL_FAILED_NO_POWER);return; }
        auto const& def=Definitions.at(id);int32 cost=Cost(p,e,id,def);_power=def.root.power;
        // FSC1 fallback casts ignore native power payment, so pay the virtual pool here.
        // Ordinary action-bar casts use the synchronized hidden Player power and TrinityCore pays it normally.
        if(_manual) {
            if(def.root.power==p->GetPowerType()) p->ModifyPower(def.root.power,-cost*(def.root.power==POWER_RAGE?10:1));
            else e.pools[def.root.power].current=std::max(0,e.pools[def.root.power].current-cost);
            SyncHiddenSubclassPowers(p,e);
        }
        _secondary=true;_factor=Effectiveness(e,Class(def.root.owner));double coefficient=def.root.intellectCoefficient;
        for(auto const& effect:GetSpellInfo()->GetEffects()) if((effect.Effect==SPELL_EFFECT_SCHOOL_DAMAGE||effect.Effect==SPELL_EFFECT_HEAL)&&effect.BonusCoefficient>0) coefficient=effect.BonusCoefficient;
        _intellectBonus=std::max(0,e.state.stats.intellect)*coefficient;
    }
    void CapturePower() {
        using namespace ForeverSubclass;if(!_secondary||_manual) return;
        std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);CaptureHiddenSubclassPower(p,e,_power);
    }
    void Scale() {
        if(!_secondary) return;auto scale=[this](int32 value) { return int32(std::clamp((value+_intellectBonus)*_factor,0.0,double(std::numeric_limits<int32>::max()))); };
        if(GetHitDamage()>0) SetHitDamage(scale(GetHitDamage()));if(GetHitHeal()>0) SetHitHeal(scale(GetHitHeal()));
    }
    void Register() override {
        OnCheckCast+=SpellCheckCastFn(spell_forever_subclass::Check);OnCast+=SpellCastFn(spell_forever_subclass::Pay);
        AfterCast+=SpellCastFn(spell_forever_subclass::CapturePower);OnHit+=SpellHitFn(spell_forever_subclass::Scale);
    }
};
'''


def adapt_server_source(module):
    source=(module/'server/ForeverSubclass.cpp').read_text()

    include_anchor='#include "ScriptMgr.h"\n'
    if source.count(include_anchor)!=1:
        raise ValueError('ForeverSubclass ScriptMgr include anchor was not found exactly once')
    source=source.replace(include_anchor,include_anchor+'#include "Chat.h"\n#include "ChatCommand.h"\n',1)
    vector_anchor='#include <vector>\n'
    if source.count(vector_anchor)!=1:
        raise ValueError('ForeverSubclass vector include anchor was not found exactly once')
    source=source.replace(vector_anchor,vector_anchor+'#include <set>\n',1)

    # Push initial state on login and make sure even non-Hunter primary classes
    # have a stable container before the subclass pet system touches Pet.cpp.
    old_login='void OnLogin(Player* p,bool) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);State(p); } }'
    new_login='void OnLogin(Player* p,bool) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);p->GetOrInitPetStable();auto& e=State(p);Snapshot(p,e); } }'
    if source.count(old_login)!=1:
        raise ValueError('ForeverSubclass login hook anchor was not found exactly once')
    source=source.replace(old_login,new_login,1)

    # The stock Tame Beast spell is hard restricted to primary Hunter. Our
    # subclass route uses the same pet creation path, but retains the normal
    # CreatureTemplate tameability rules and initializes the stable explicitly.
    old_tame='Creature* creature=p->GetSelectedUnit()?p->GetSelectedUnit()->ToCreature():nullptr;\n    if(!creature||creature->IsPet()||!creature->GetCreatureTemplate()||creature->GetCreatureTemplate()->type!=CREATURE_TYPE_BEAST) {\n        error="select a tameable beast";return false;\n    }'
    new_tame='Creature* creature=p->GetSelectedUnit()?p->GetSelectedUnit()->ToCreature():nullptr;\n    CreatureTemplate const* creatureTemplate=creature?creature->GetCreatureTemplate():nullptr;\n    CreatureDifficulty const* creatureDifficulty=creature?creature->GetCreatureDifficulty():nullptr;\n    if(!creature||creature->IsPet()||!creatureTemplate||!creatureDifficulty||!creatureTemplate->IsTameable(false,creatureDifficulty)) {\n        error="select a tameable beast";return false;\n    }\n    p->GetOrInitPetStable();'
    if source.count(old_tame)!=1:
        raise ValueError('ForeverSubclass tame hook anchor was not found exactly once')
    source=source.replace(old_tame,new_tame,1)

    old_call='if(p->GetPet()) { error="pet already active";return false; }\n    Pet* pet=new Pet(p,HUNTER_PET);'
    new_call='if(p->GetPet()) { error="pet already active";return false; }\n    p->GetOrInitPetStable();\n    Pet* pet=new Pet(p,HUNTER_PET);'
    if source.count(old_call)!=1:
        raise ValueError('ForeverSubclass pet call hook anchor was not found exactly once')
    source=source.replace(old_call,new_call,1)

    # Deploy selected best ranks as true temporary Player spells. They appear in
    # the normal spellbook/action bars but are never persisted as primary-class spells.
    snapshot_anchor='static void Snapshot(Player* p,Entry& e) {'
    if source.count(snapshot_anchor)!=1:
        raise ValueError('ForeverSubclass Snapshot anchor was not found exactly once')
    source=source.replace(snapshot_anchor,TEMPORARY_SPELL_HELPERS+'\n'+snapshot_anchor+'\n    SyncTemporarySubclassSpells(p,e);SyncHiddenSubclassPowers(p,e);',1)

    logout_anchor='void OnLogout(Player* p) override { std::lock_guard<std::recursive_mutex> g(Mutex);auto i=Entries.find(p->GetGUID().GetCounter());if(i!=Entries.end()) { Save(i->second);Entries.erase(i); } }'
    logout_replace='void OnLogout(Player* p) override { std::lock_guard<std::recursive_mutex> g(Mutex);uint64 guid=p->GetGUID().GetCounter();TemporarySubclassSpells.erase(guid);auto i=Entries.find(guid);if(i!=Entries.end()) { Save(i->second);Entries.erase(i); } }'
    if source.count(logout_anchor)!=1:
        raise ValueError('ForeverSubclass logout anchor was not found exactly once')
    source=source.replace(logout_anchor,logout_replace,1)

    # Replace the adapter SpellScript with a dual path: native temporary spells
    # use normal TrinityCore cast/GCD/cooldown/payment; FSC1 remains a safe fallback.
    spell_pattern=r'class spell_forever_subclass final : public SpellScript \{.*?\n\};\nvoid AddSC_forever_subclass\(\)'
    match=re.search(spell_pattern,source,re.S)
    if not match:
        raise ValueError('ForeverSubclass SpellScript block was not found')
    source=source[:match.start()]+NATIVE_SPELL_SCRIPT+'void AddSC_forever_subclass()'+source[match.end():]

    # WoW Forever 70532 does not reliably deliver AddOn whispers sent to the same
    # character. Provide a normal TrinityCore command path into the same Request().
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
