Optional<PlayerSpellTrait> Player::GetTraitInfoForSpell(uint32 spellId) const
{
    // Native class configurations always take precedence.
    if (PlayerSpell const* spell = Trinity::Containers::MapGetValuePtr(m_spells, spellId))
        return spell->Trait;
    if (auto it = m_foreverAdvancementTraits.find(spellId); it != m_foreverAdvancementTraits.end())
        return it->second;
    return {};
}

void Player::SetForeverAdvancementTrait(uint32 spell, int32 definition, int32 rank)
{
    if (definition > 0 && definition <= 0x7fffff && rank > 0 && rank <= 127 && !HasSpell(spell))
        m_foreverAdvancementTraits[spell] = PlayerSpellTrait{definition, rank};
    else
        m_foreverAdvancementTraits.erase(spell);
}
