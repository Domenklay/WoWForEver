// Foreign equipment skills/proficiency are transient and never reward additional spells.
void Player::SyncForeverAdvancementEquipment(uint32 owner, std::set<uint32> const& skills, uint16 value, uint32 weapons, uint32 armor)
{
    for (auto skill : m_foreverAdvancementEquipmentSkills)
        if (!skills.count(skill))
        {
            SetSkill(skill,0,0,0,true);
            if (auto it=mSkillStatus.find(skill);it!=mSkillStatus.end()) it->second.uState=SKILL_UNCHANGED;
        }
    std::set<uint32> owned;
    for (auto skill:skills)
        if (m_foreverAdvancementEquipmentSkills.count(skill) || !HasSkill(skill))
        { SetSkill(skill,0,value,value,true);owned.insert(skill); }
    m_foreverAdvancementEquipmentSkills=std::move(owned);
    uint32 permanentWeapons=0,permanentArmor=0;
    for (auto const& [id,spell]:m_spells)
        if (spell.state!=PLAYERSPELL_REMOVED && spell.state!=PLAYERSPELL_TEMPORARY)
            if (auto info=sSpellMgr->GetSpellInfo(id,DIFFICULTY_NONE))
                if (info->HasEffect(SPELL_EFFECT_PROFICIENCY))
                {
                    if(info->EquippedItemClass==ITEM_CLASS_WEAPON) permanentWeapons|=info->EquippedItemSubClassMask;
                    if(info->EquippedItemClass==ITEM_CLASS_ARMOR) permanentArmor|=info->EquippedItemSubClassMask;
                }
    uint32 baseWeapons=(m_WeaponProficiency&~m_foreverAdvancementWeapons)|permanentWeapons;
    uint32 baseArmor=(m_ArmorProficiency&~m_foreverAdvancementArmor)|permanentArmor;
    m_foreverAdvancementWeapons=weapons&~baseWeapons;m_foreverAdvancementArmor=armor&~baseArmor;
    m_WeaponProficiency=baseWeapons|weapons;m_ArmorProficiency=baseArmor|armor;
    m_foreverAdvancementOwner=owner;
    if(IsInWorld()) { SendProficiency(ITEM_CLASS_WEAPON,m_WeaponProficiency);SendProficiency(ITEM_CLASS_ARMOR,m_ArmorProficiency); }
}
