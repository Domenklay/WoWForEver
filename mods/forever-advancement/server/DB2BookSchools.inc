// Client-only class-school visibility. Keep the original DB2 entries intact:
// server creation, trainers and skill rewards must retain their class masks.
void DB2Manager::PublishForeverAdvancementBookSchool(uint32 recordId)
{
    auto row = sSkillRaceClassInfoStore.LookupEntry(recordId);
    auto skill = row ? sSkillLineStore.LookupEntry(row->SkillID) : nullptr;
    if (!row || !row->ClassMask || !skill || skill->CategoryID != SKILL_CATEGORY_CLASS || skill->ParentSkillLineID)
        return;
    _foreverAdvancementBookSchools.insert(recordId);
    InsertNewHotfix(sSkillRaceClassInfoStore.GetTableHash(), recordId);
}

void DB2Manager::WriteForeverAdvancementClientRecord(DB2StorageBase const* storage, uint32 recordId, LocaleConstant locale, ByteBuffer& buffer) const
{
    std::size_t start = buffer.size();
    storage->WriteRecord(recordId, locale, buffer);
    if (storage->GetTableHash() != sSkillRaceClassInfoStore.GetTableHash() || !_foreverAdvancementBookSchools.count(recordId))
        return;
    // Pinned SkillRaceClassInfo layout: ID is external; uint16 SkillID,
    // int32 ClassMask, Flags, Availability, int8 MinLevel, int16 SkillTierID,
    // int32 RaceMask[2]. No string or locale fields. Fail closed on layout drift.
    if (buffer.size() - start != 25)
        return;
    buffer.put<int32>(start + sizeof(uint16), 0);
    // Class schools must also be visible to races that could not originally
    // select that class. This does not change server race eligibility.
    buffer.put<int32>(start + 17, 0);
    buffer.put<int32>(start + 21, 0);
}
