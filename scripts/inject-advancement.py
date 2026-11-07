#!/usr/bin/env python3
"""Register the new advancement server; remove the obsolete generated subclass adapter."""
import argparse
from pathlib import Path
import re
import shutil


def inject(core,module=None):
    core=Path(core).resolve();module=Path(module or Path(__file__).parents[1]/'mods/forever-advancement').resolve()
    loader=core/'src/server/scripts/Custom/custom_script_loader.cpp'
    text=loader.read_text()
    text=text.replace('void AddSC_forever_subclass();\n','').replace('    AddSC_forever_subclass();\n','')
    declaration='void AddSC_forever_advancement();'
    if declaration not in text:
        text,count=re.subn(r'(^void AddCustomScripts\(\)\s*\{)',declaration+'\n\n'+r'\1'+'\n    AddSC_forever_advancement();',text,count=1,flags=re.M)
        if count!=1:raise ValueError('Unknown Custom loader layout')
    if text.count('    AddSC_forever_advancement();')!=1:raise ValueError('Inconsistent advancement registration')
    target=loader.parent/'ForeverAdvancement'
    if target.is_symlink() or (loader.parent/'ForeverSubclass').is_symlink():raise ValueError('Symlinked module path')
    target.mkdir(exist_ok=True)
    for name in ['ForeverAdvancement.cpp','AscensionCatalog.h','AscensionCustomCatalog.h','CustomAbilityRules.h','ExperienceShare.h']:
        shutil.copy2(module/'server'/name,target/name)
    legacy=loader.parent/'ForeverSubclass'
    if legacy.exists():shutil.rmtree(legacy)
    manager=core/'src/server/game/Globals/ObjectMgr.h'
    if manager.exists():
        original=manager.read_text()
        signature='        void RegisterForeverAdvancementBinding(uint32 spellId, uint32 scriptId)'
        if signature not in original:
            anchor='        SpellScriptsBounds GetSpellScriptsBounds(uint32 spellId);'
            if original.count(anchor)!=1:raise ValueError('Unknown ObjectMgr binding layout')
            original=original.replace(anchor,anchor+"\n"+signature+"\n        {\n            auto bounds = _spellScriptsStore.equal_range(spellId);\n            for (auto it = bounds.first; it != bounds.second; ++it)\n                if (it->second.first == scriptId) { it->second.second = true; return; }\n            _spellScriptsStore.emplace(spellId, std::make_pair(scriptId, true));\n        }\n")
            manager.write_text(original)
    spell_header=core/'src/server/game/Spells/Spell.h'
    if spell_header.exists():
        original=spell_header.read_text()
        signature='        void IgnorePowerCostForForeverAdvancement()'
        if signature not in original:
            anchor='        std::any m_customArg;'
            if original.count(anchor)!=1:raise ValueError('Unknown Spell custom argument layout')
            original=original.replace(anchor,signature+' { _triggeredCastFlags = TriggerCastFlags(_triggeredCastFlags | TRIGGERED_IGNORE_POWER_COST); }\n'+anchor)
            spell_header.write_text(original)
    player_header=core/'src/server/game/Entities/Player/Player.h'
    player_source=core/'src/server/game/Entities/Player/Player.cpp'
    if player_header.exists() and player_source.exists():
        header=player_header.read_text();source=player_source.read_text()
        # The pinned core's existing profession declaration relies on its PCH
        # for this type. Keep Player.h valid during standalone compilation too.
        if 'IsClassicProfessionChildSkill' in header and 'struct SkillLineEntry;' not in header:
            marker='struct SkillRaceClassInfoEntry;'
            if header.count(marker)!=1:raise ValueError('Unknown player skill forward declarations')
            header=header.replace(marker,'struct SkillLineEntry;\n'+marker)
            player_header.write_text(header)
        declaration='        void SetSkill(uint32 id, uint16 step, uint16 newVal, uint16 maxVal);'
        if 'SyncForeverAdvancementClassSkills' not in header:
            if header.count(declaration)!=1:raise ValueError('Unknown Player skill declaration')
            header=header.replace(declaration,'        void SetSkill(uint32 id, uint16 step, uint16 newVal, uint16 maxVal, bool advancementEdit = false);\n        void SyncForeverAdvancementClassSkills(std::set<uint32> const& desired);')
            marker='        SkillStatusMap mSkillStatus;'
            if header.count(marker)!=1:raise ValueError('Unknown Player skill storage')
            header=header.replace(marker,marker+'\n        std::set<uint32> m_foreverAdvancementClassSkills;')
            begin=source.index('void Player::SetSkill(uint32 id, uint16 step, uint16 newVal, uint16 maxVal)')
            end=source.index('\nbool Player::IsClassicProfessionChildSkill',begin)
            body=source[begin:end]
            body=body.replace('uint16 maxVal)','uint16 maxVal, bool advancementEdit)',1)
            if body.count('LearnSkillRewardedSpells(id, newVal, Races(GetRace()));')!=2:raise ValueError('Unknown skill reward layout')
            body=body.replace('LearnSkillRewardedSpells(id, newVal, Races(GetRace()));','if (!advancementEdit) LearnSkillRewardedSpells(id, newVal, Races(GetRace()));')
            body=body.replace('if (std::vector<SkillLineAbilityEntry const*> const* skillLineAbilities = sDB2Manager.GetSkillLineAbilitiesBySkill(id))','if (!advancementEdit) if (std::vector<SkillLineAbilityEntry const*> const* skillLineAbilities = sDB2Manager.GetSkillLineAbilitiesBySkill(id))')
            source=source[:begin]+body+source[end:]
            save=source.index('void Player::_SaveSkills(')
            guard=source.index('        if (itr->second.uState == SKILL_UNCHANGED)',save)
            source=source[:guard]+source[guard:].replace('if (itr->second.uState == SKILL_UNCHANGED)','if (m_foreverAdvancementClassSkills.count(itr->first) || itr->second.uState == SKILL_UNCHANGED)',1)
            source+='\n'+(module/'server/PlayerBookSchools.inc').read_text()
            player_header.write_text(header);player_source.write_text(source)
        source=player_source.read_text()
        reward='void Player::LearnSkillRewardedSpells(uint32 skillId, uint32 skillValue, Races race)\n{'
        guard='    if (m_foreverAdvancementClassSkills.count(skillId) || m_foreverAdvancementEquipmentSkills.count(skillId)) return; // transient spellbook school'
        if guard not in source:
            if source.count(reward)!=1:raise ValueError('Unknown skill reward function')
            player_source.write_text(source.replace(reward,reward+'\n'+guard))
    if player_header.exists() and player_source.exists():
        header=player_header.read_text();source=player_source.read_text()
        declaration='        void SetForeverAdvancementTrait(uint32 spell, int32 definition, int32 rank);'
        if declaration not in header:
            marker='        Optional<PlayerSpellTrait> GetTraitInfoForSpell(uint32 spellId) const;'
            if header.count(marker)!=1:raise ValueError('Unknown native trait accessor declaration')
            header=header.replace(marker,marker+'\n'+declaration)
            marker='        std::set<uint32> m_foreverAdvancementClassSkills;'
            header=header.replace(marker,marker+'\n        std::map<uint32, PlayerSpellTrait> m_foreverAdvancementTraits;')
            marker='Optional<PlayerSpellTrait> Player::GetTraitInfoForSpell(uint32 spellId) const\n{'
            if source.count(marker)!=1:raise ValueError('Unknown native trait accessor')
            begin=source.index(marker);end=source.index('\nvoid Player::SetReputation(',begin)
            source=source[:begin]+(module/'server/PlayerTraits.inc').read_text().rstrip()+'\n'+source[end:]
            player_header.write_text(header);player_source.write_text(source)
        else:
            marker='Optional<PlayerSpellTrait> Player::GetTraitInfoForSpell(uint32 spellId) const'
            source=player_source.read_text();begin=source.index(marker)
            end=source.index('\nvoid Player::SetReputation(',begin)
            replacement=(module/'server/PlayerTraits.inc').read_text().rstrip()+'\n'
            if source[begin:end]!=replacement:player_source.write_text(source[:begin]+replacement+source[end:])
    # Reuse native trait validation with the subclass level, without changing player class/spec.
    trait_header=core/'src/server/game/Spells/TraitMgr.h'
    if trait_header.exists() and player_source.exists():
        h=trait_header.read_text();old='PlayerDataAccessor(Player const* player) : _player(player) { }'
        new='PlayerDataAccessor(Player const* player, int32 advancementLevel = -1) : _player(player), _advancementLevel(advancementLevel) { }'
        if old in h:
            h=h.replace(old,new).replace('    Player const* _player;','    Player const* _player;\n    int32 _advancementLevel = -1;');trait_header.write_text(h)
        elif new not in h:raise ValueError('Unknown trait player accessor')
        text_player=player_source.read_text()
        old='int32 TraitMgr::PlayerDataAccessor::GetLevel() const\n{\n    return _player->GetLevel();'
        new='int32 TraitMgr::PlayerDataAccessor::GetLevel() const\n{\n    if (_advancementLevel >= 0) return _advancementLevel;\n    return _player->GetLevel();'
        if old in text_player:text_player=text_player.replace(old,new)
        elif new not in text_player:raise ValueError('Unknown trait level accessor')
        marker='int32 TraitMgr::PlayerDataAccessor::GetClassicTalentedStartLevel() const\n{'
        added='\n    if (_advancementLevel >= 0) return 10; // foreign class never borrows primary legacy perks'
        if marker+added not in text_player:
            if marker not in text_player:raise ValueError('Unknown classic trait point accessor')
            text_player=text_player.replace(marker,marker+added)
        player_source.write_text(text_player)
    if player_header.exists() and player_source.exists():
        h=player_header.read_text();src=player_source.read_text()
        signature='        void SyncForeverAdvancementEquipment(uint32 owner, std::set<uint32> const& skills, uint16 value, uint32 weapons, uint32 armor);'
        if signature not in h:
            marker='        void SyncForeverAdvancementClassSkills(std::set<uint32> const& desired);'
            h=h.replace(marker,marker+'\n'+signature+'\n        uint32 GetForeverAdvancementClass() const { return m_foreverAdvancementOwner; }')
            marker='        std::set<uint32> m_foreverAdvancementClassSkills;'
            h=h.replace(marker,marker+'\n        std::set<uint32> m_foreverAdvancementEquipmentSkills;\n        uint32 m_foreverAdvancementOwner=0, m_foreverAdvancementWeapons=0, m_foreverAdvancementArmor=0;')
            src+='\n'+(module/'server/PlayerEquipment.inc').read_text()
        save_guard='m_foreverAdvancementClassSkills.count(itr->first) ||'
        src=src.replace(save_guard,'m_foreverAdvancementEquipmentSkills.count(itr->first) || '+save_guard) if 'm_foreverAdvancementEquipmentSkills.count(itr->first)' not in src else src
        src=src.replace('if (m_foreverAdvancementClassSkills.count(skillId)) return;', 'if (m_foreverAdvancementClassSkills.count(skillId) || m_foreverAdvancementEquipmentSkills.count(skillId)) return;')
        player_header.write_text(h);player_source.write_text(src)
    # Taming is the only hard class gate in the native effect; its native script still validates the beast.
    effects=core/'src/server/game/Spells/SpellEffects.cpp'
    if effects.exists():
        e=effects.read_text();old='if (unitCaster->GetClass() != CLASS_HUNTER)\n        return;'
        new='if (unitCaster->GetClass() != CLASS_HUNTER && !(unitCaster->ToPlayer() && unitCaster->ToPlayer()->GetForeverAdvancementClass() == CLASS_HUNTER))\n        return;'
        if old in e:e=e.replace(old,new,1)
        elif new not in e:raise ValueError('Unknown native taming class gate')
        effects.write_text(e)
    db2_source=core/'src/server/game/DataStores/DB2Stores.cpp'
    if db2_source.exists():
        original=db2_source.read_text()
        marker='void DB2Manager::InsertNewHotfix(uint32 tableHash, uint32 recordId)\n{\n    HotfixRecord hotfixRecord;'
        valid='    hotfixRecord.HotfixStatus = HotfixRecord::Status::Valid;'
        if marker+'\n'+valid not in original:
            if original.count(marker)!=1:raise ValueError('Unknown generated hotfix layout')
            db2_source.write_text(original.replace(marker,marker+'\n'+valid))
    db2_header=core/'src/server/game/DataStores/DB2Stores.h'
    hotfix_handler=core/'src/server/game/Handlers/HotfixHandler.cpp'
    if db2_header.exists() and db2_source.exists() and hotfix_handler.exists():
        header=db2_header.read_text();source=db2_source.read_text();handler=hotfix_handler.read_text()
        if 'PublishForeverAdvancementBookSchool' not in header:
            anchor='    DB2StorageBase const* GetStorage(uint32 type) const;'
            if header.count(anchor)!=1:raise ValueError('Unknown DB2 storage accessor')
            header=header.replace(anchor,anchor+'\n    void PublishForeverAdvancementBookSchool(uint32 recordId);\n    void WriteForeverAdvancementClientRecord(DB2StorageBase const* storage, uint32 recordId, LocaleConstant locale, ByteBuffer& buffer) const;')
            anchor='    int32 _maxHotfixId = 0;'
            if header.count(anchor)!=1:raise ValueError('Unknown DB2 hotfix storage')
            header=header.replace(anchor,'    std::set<uint32> _foreverAdvancementBookSchools;\n'+anchor)
            db2_header.write_text(header)
        marker='// Client-only class-school visibility.'
        if marker in source:source=source[:source.index(marker)].rstrip()+'\n'
        if '#include "ByteBuffer.h"' not in source:source=source.replace('#include "DB2Stores.h"','#include "DB2Stores.h"\n#include "ByteBuffer.h"')
        db2_source.write_text(source+'\n'+(module/'server/DB2BookSchools.inc').read_text())
        for old,new in [
            ('store->WriteRecord(record.RecordID, GetSessionDbcLocale(), dbReply.Data);','sDB2Manager.WriteForeverAdvancementClientRecord(store, record.RecordID, GetSessionDbcLocale(), dbReply.Data);'),
            ('storage->WriteRecord(uint32(hotfixRecord.RecordID), GetSessionDbcLocale(), hotfixQueryResponse.HotfixContent);','sDB2Manager.WriteForeverAdvancementClientRecord(storage, uint32(hotfixRecord.RecordID), GetSessionDbcLocale(), hotfixQueryResponse.HotfixContent);')]:
            if old in handler:handler=handler.replace(old,new)
            elif new not in handler:raise ValueError('Unknown hotfix record serialization')
        hotfix_handler.write_text(handler)
    loader.write_text(text)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('core',type=Path);parser.add_argument('--module',type=Path)
    args=parser.parse_args();inject(args.core,args.module)
