// Transient CLASS skill lines organize native spellbook entries. Never grant
// rewarded spells or persist forbidden foreign skills in character_skills.
void Player::SyncForeverAdvancementClassSkills(std::set<uint32> const& desired)
{
    auto previous = m_foreverAdvancementClassSkills;
    for (uint32 skill : previous)
        if (!desired.count(skill))
        {
            SetSkill(skill, 0, 0, 0, true);
            if (auto it = mSkillStatus.find(skill); it != mSkillStatus.end())
                it->second.uState = SKILL_UNCHANGED;
            m_foreverAdvancementClassSkills.erase(skill);
        }
    for (uint32 skill : desired)
    {
        auto entry = sSkillLineStore.LookupEntry(skill);
        if (!entry || entry->CategoryID != SKILL_CATEGORY_CLASS || entry->ParentSkillLineID || HasSkill(skill))
            continue;
        SetSkill(skill, 0, 1, 1, true);
        if (HasSkill(skill))
            m_foreverAdvancementClassSkills.insert(skill);
    }
}
