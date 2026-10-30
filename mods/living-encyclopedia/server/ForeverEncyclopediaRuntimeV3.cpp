#include "ScriptMgr.h"
#include "Player.h"
#include "Creature.h"
#include "Unit.h"
#include "Group.h"
#include "World.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
#include "ObjectAccessor.h"
#include "ObjectMgr.h"
#include "MotionMaster.h"
#include "TalentRules.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace ForeverEncyclopediaRuntime
{
using Clock = std::chrono::steady_clock;
using ForeverEncyclopedia::Talents::KnowledgeManaBonus;
using ForeverEncyclopedia::Talents::Rank;
using ForeverEncyclopedia::Talents::RegenBasisPoints;

constexpr char RequestPrefix[] = "FEB1";
constexpr char ResponsePrefix[] = "FBR1";
constexpr uint32 BaseMaxMana = 100;

// Existing client/server creature entries used by the appearance collection.
constexpr uint32 EntryLivingBook = 171120;
constexpr uint32 EntryArchivist = 205781;
constexpr uint32 EntryKnowledgeSpirit = 161896;
constexpr uint32 EntrySmallConstruct = 183783;
constexpr uint32 EntryRunekeeper = 130946;

// First native-spell pass. These are deliberately ordinary game spells so the
// companion uses the same cast system, animations and aura/heal presentation as NPCs.
constexpr uint32 SpellBookShield = 35944; // Power Word: Shield (NPC variant)
constexpr uint32 SpellBookHeal = 2061;    // Flash Heal

static std::mutex RuntimeMutex;
using RankMap = std::unordered_map<std::string, uint16>;

struct RuntimeState
{
    uint32 account = 0;
    uint64 knowledgeTotal = 0;
    RankMap ranks;
    uint32 mana = BaseMaxMana;
    uint32 maxMana = BaseMaxMana;
    uint32 shieldThreshold = 80;
    uint32 healThreshold = 50;
    uint32 manaReserve = 0;
    bool shieldEnabled = true;
    bool healEnabled = true;
    bool wantShield = false;
    bool wantHeal = false;
    uint32 regenCarry = 0;
    uint32 appearanceEntry = EntryLivingBook;
    ObjectGuid companionGuid;
    Clock::time_point shieldReady{};
    Clock::time_point healReady{};
    Clock::time_point supportReady{};
    Clock::time_point lastRegen = Clock::now();
    Clock::time_point lastPersist = Clock::now();
    Clock::time_point lastFollow = Clock::now();
    bool dirty = false;
};

static std::unordered_map<uint64, RuntimeState> Runtime;

static uint32 Account(Player* player)
{
    return player && player->GetSession() ? player->GetSession()->GetAccountId() : 0;
}

static uint64 Guid(Player* player)
{
    return player ? player->GetGUID().GetCounter() : 0;
}

static void Send(Player* player, std::string const& text)
{
    if (!player || !player->GetSession())
        return;
    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER, LANG_ADDON, player, player, text, 0, "", LOCALE_enUS, ResponsePrefix);
    player->GetSession()->SendPacket(packet.Write());
}

static void SendEvent(Player* player, char const* kind, uint64 amount = 0, uint64 extra = 0)
{
    Send(player, Trinity::StringFormat("EVENT|{}|{}|{}", kind, amount, extra));
}

static RankMap LoadRanks(uint32 account)
{
    RankMap ranks;
    if (QueryResult rows = CharacterDatabase.PQuery(
            "SELECT talent_key,`rank` FROM forever_encyclopedia_talent WHERE account_id={}", account))
    {
        do
        {
            Field* f = rows->Fetch();
            ranks[f[0].GetString()] = uint16(f[1].GetUInt32());
        }
        while (rows->NextRow());
    }
    return ranks;
}

static uint16 GetRank(RankMap const& ranks, std::string_view key)
{
    return Rank(ranks, key);
}

static uint64 KnowledgeTotal(uint32 account)
{
    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT knowledge_total FROM forever_encyclopedia_account WHERE account_id={}", account))
        return row->Fetch()[0].GetUInt64();
    return 0;
}

static uint32 AppearanceEntry(Player* player)
{
    if (!player)
        return EntryLivingBook;

    std::string key = "living_book";
    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT appearance_key FROM forever_encyclopedia_appearance_selection WHERE character_guid={}", Guid(player)))
        key = row->Fetch()[0].GetString();

    if (key == "archivist") return EntryArchivist;
    if (key == "knowledge_spirit") return EntryKnowledgeSpirit;
    if (key == "small_construct") return EntrySmallConstruct;
    if (key == "runekeeper") return EntryRunekeeper;
    return EntryLivingBook;
}

static uint32 ValidAppearanceEntry(uint32 preferred)
{
    if (sObjectMgr->GetCreatureTemplate(preferred))
        return preferred;
    for (uint32 entry : { EntryLivingBook, EntryArchivist, EntryKnowledgeSpirit, EntrySmallConstruct, EntryRunekeeper })
        if (sObjectMgr->GetCreatureTemplate(entry))
            return entry;
    return 0;
}

static uint32 MaxMana(uint64 knowledgeTotal, RankMap const& ranks)
{
    uint64 value = uint64(BaseMaxMana) + KnowledgeManaBonus(knowledgeTotal);
    value += uint64(GetRank(ranks, "mana_capacity")) * 10;
    value += uint64(GetRank(ranks, "mana_overflow")) * 15;
    value += uint64(GetRank(ranks, "wisdom_mastery")) * 2;
    return uint32(std::min<uint64>(value, UINT32_MAX));
}

static uint32 AbilityMask(RankMap const& ranks)
{
    uint32 mask = 0;
    if (GetRank(ranks, "aegis_unlock")) mask |= 1;
    if (GetRank(ranks, "mend_unlock")) mask |= 2;
    // Support is intentionally withheld from the live mask until it has a proper
    // native spell instead of a hidden damage modifier.
    return mask;
}

static uint32 ApplyConservation(RankMap const& ranks, uint32 cost)
{
    uint32 pct = std::min<uint32>(20, GetRank(ranks, "mana_conservation") * 4);
    return std::max<uint32>(1, cost - cost * pct / 100);
}

static uint32 ShieldManaCost(RuntimeState const& state)
{
    uint32 cost = 25 + state.maxMana * 2 / 100;
    cost -= std::min<uint32>(10, GetRank(state.ranks, "aegis_efficiency") * 2);
    return ApplyConservation(state.ranks, std::max<uint32>(15, cost));
}

static uint32 HealManaCost(RuntimeState const& state)
{
    uint32 cost = 30 + state.maxMana * 25 / 1000;
    cost -= std::min<uint32>(10, GetRank(state.ranks, "mend_efficiency") * 2);
    return ApplyConservation(state.ranks, std::max<uint32>(18, cost));
}

static uint32 ShieldCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(20, 30 - std::min<uint32>(10, GetRank(state.ranks, "aegis_reflex") * 2));
}

static uint32 HealCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(15, 25 - std::min<uint32>(10, GetRank(state.ranks, "mend_reflex") * 2));
}

static uint32 CooldownRemaining(Clock::time_point ready)
{
    auto now = Clock::now();
    if (ready <= now)
        return 0;
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(ready - now).count();
    return uint32((ms + 999) / 1000);
}

static bool AllowedPvE(Player* player)
{
    if (!player || !player->IsAlive())
        return false;
    if (player->InBattleground() || player->InArena() || player->duel)
        return false;
    if (Group const* group = player->GetGroup())
        if (group->isRaidGroup() || group->GetMembersCount() >= 5)
            return false;
    return true;
}

static bool IsPlayerControlled(Unit* unit)
{
    return unit && unit->GetCharmerOrOwnerPlayerOrPlayerItself() != nullptr;
}

static Creature* Companion(Player* player, RuntimeState const& state)
{
    if (!player || state.companionGuid.IsEmpty())
        return nullptr;
    return ObjectAccessor::GetCreature(*player, state.companionGuid);
}

static void DespawnCompanion(Player* player, RuntimeState& state)
{
    if (Creature* companion = Companion(player, state))
        companion->DespawnOrUnsummon();
    state.companionGuid.Clear();
}

static float CompanionScale(uint32 entry)
{
    if (entry == EntryLivingBook) return 0.72f;
    if (entry == EntryKnowledgeSpirit) return 0.65f;
    return 0.55f;
}

static Creature* EnsureCompanion(Player* player, RuntimeState& state)
{
    if (!player || !player->IsAlive() || !player->IsInWorld())
        return nullptr;

    if (Creature* existing = Companion(player, state))
    {
        if (existing->GetEntry() == state.appearanceEntry && existing->GetMap() == player->GetMap())
            return existing;
        DespawnCompanion(player, state);
    }

    uint32 entry = ValidAppearanceEntry(state.appearanceEntry);
    if (!entry)
    {
        SendEvent(player, "COMPANION_MISSING");
        return nullptr;
    }
    state.appearanceEntry = entry;

    Creature* companion = player->SummonCreature(entry, *player, TEMPSUMMON_MANUAL_DESPAWN);
    if (!companion)
        return nullptr;

    companion->SetReactState(REACT_PASSIVE);
    companion->SetFaction(player->GetFaction());
    companion->SetImmuneToAll(true);
    companion->SetUninteractible(true);
    companion->SetLevel(player->GetLevel());
    companion->SetObjectScale(CompanionScale(entry));
    companion->SetCanFly(true);
    companion->SetDisableGravity(true);
    companion->SetPowerType(POWER_MANA);
    companion->SetMaxPower(POWER_MANA, 100000);
    companion->SetPower(POWER_MANA, 100000);
    companion->GetMotionMaster()->MoveFollow(player, 2.2f, 1.65f);

    state.companionGuid = companion->GetGUID();
    state.lastFollow = Clock::now();
    SendEvent(player, "COMPANION", entry, 1);
    return companion;
}

static RuntimeState LoadRuntime(Player* player)
{
    RuntimeState state;
    state.account = Account(player);
    state.ranks = LoadRanks(state.account);
    state.knowledgeTotal = KnowledgeTotal(state.account);
    state.maxMana = MaxMana(state.knowledgeTotal, state.ranks);
    state.mana = state.maxMana;
    state.appearanceEntry = AppearanceEntry(player);

    uint64 guid = Guid(player);
    CharacterDatabase.DirectPExecute(
        "INSERT IGNORE INTO forever_encyclopedia_character "
        "(character_guid,mana,shield_enabled,heal_enabled,shield_threshold,heal_threshold,mana_reserve) "
        "VALUES ({},{},1,1,80,50,0)", guid, state.maxMana);

    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT mana,shield_enabled,heal_enabled,shield_threshold,heal_threshold,mana_reserve "
            "FROM forever_encyclopedia_character WHERE character_guid={}", guid))
    {
        Field* f = row->Fetch();
        state.mana = std::min(f[0].GetUInt32(), state.maxMana);
        state.shieldEnabled = f[1].GetUInt32() != 0;
        state.healEnabled = f[2].GetUInt32() != 0;
        state.shieldThreshold = std::clamp<uint32>(f[3].GetUInt32(), 1, 100);
        state.healThreshold = std::clamp<uint32>(f[4].GetUInt32(), 1, 100);
        state.manaReserve = f[5].GetUInt32();
    }

    uint32 talentReserve = state.maxMana * std::min<uint32>(25, GetRank(state.ranks, "mana_reserve") * 5) / 100;
    state.manaReserve = std::max(state.manaReserve, talentReserve);
    state.lastRegen = Clock::now();
    state.lastPersist = state.lastRegen;
    return state;
}

static void RefreshRuntimeLocked(Player* player, RuntimeState& state)
{
    uint32 account = Account(player);
    RankMap ranks = LoadRanks(account);
    uint64 knowledge = KnowledgeTotal(account);
    uint32 oldMax = state.maxMana;
    uint32 oldAppearance = state.appearanceEntry;

    state.account = account;
    state.ranks = std::move(ranks);
    state.knowledgeTotal = knowledge;
    state.maxMana = MaxMana(knowledge, state.ranks);
    state.appearanceEntry = AppearanceEntry(player);

    if (state.maxMana > oldMax)
    {
        state.mana = std::min(state.maxMana, state.mana + (state.maxMana - oldMax));
        state.dirty = true;
    }
    else
        state.mana = std::min(state.mana, state.maxMana);

    uint32 talentReserve = state.maxMana * std::min<uint32>(25, GetRank(state.ranks, "mana_reserve") * 5) / 100;
    state.manaReserve = std::max(state.manaReserve, talentReserve);

    if (oldAppearance != state.appearanceEntry)
        DespawnCompanion(player, state);
}

static RuntimeState* FindRuntimeLocked(Player* player)
{
    auto it = Runtime.find(Guid(player));
    return it == Runtime.end() ? nullptr : &it->second;
}

static void PersistRuntimeLocked(Player* player, RuntimeState& state)
{
    if (!player || !state.dirty)
        return;
    CharacterDatabase.DirectPExecute(
        "UPDATE forever_encyclopedia_character SET mana={} WHERE character_guid={}", state.mana, Guid(player));
    state.dirty = false;
    state.lastPersist = Clock::now();
}

static void SendBook(Player* player, RuntimeState const& state)
{
    Send(player, Trinity::StringFormat("BOOK|{}|{}|{}|{}|{}|{}|0",
        AbilityMask(state.ranks), state.mana, state.maxMana,
        CooldownRemaining(state.shieldReady), CooldownRemaining(state.healReady),
        CooldownRemaining(state.supportReady)));
}

static uint32 RegenGain(Player* player, RuntimeState& state)
{
    uint32 base = player->IsInCombat() ? 1 : 5;
    uint16 rank = player->IsInCombat()
        ? GetRank(state.ranks, "mana_combat_regen")
        : GetRank(state.ranks, "mana_rest_regen");
    uint32 bonusBp = RegenBasisPoints(rank);
    uint64 numerator = uint64(state.maxMana) * bonusBp + state.regenCarry;
    uint32 bonus = uint32(numerator / 10000);
    state.regenCarry = uint32(numerator % 10000);
    return base + bonus;
}

static bool CanSpend(RuntimeState const& state, uint32 cost)
{
    return state.mana >= cost && state.mana - cost >= std::min(state.manaReserve, state.maxMana);
}

static bool StartShieldCast(Player* player, RuntimeState& state, Creature* companion)
{
    if (!player || !companion || companion->IsNonMeleeSpellCast(false))
        return false;
    uint32 cost = ShieldManaCost(state);
    if (!CanSpend(state, cost) || Clock::now() < state.shieldReady)
        return false;

    companion->StopMoving();
    companion->SetFacingToObject(player);
    companion->SetPower(POWER_MANA, companion->GetMaxPower(POWER_MANA));
    companion->CastSpell(player, SpellBookShield, false);

    state.mana -= cost;
    state.shieldReady = Clock::now() + std::chrono::seconds(ShieldCooldownSeconds(state));
    state.wantShield = false;
    state.dirty = true;
    SendEvent(player, "CAST_SHIELD", SpellBookShield, cost);
    SendBook(player, state);
    return true;
}

static bool StartHealCast(Player* player, RuntimeState& state, Creature* companion)
{
    if (!player || !companion || companion->IsNonMeleeSpellCast(false))
        return false;
    uint32 cost = HealManaCost(state);
    if (!CanSpend(state, cost) || Clock::now() < state.healReady)
        return false;

    companion->StopMoving();
    companion->SetFacingToObject(player);
    companion->SetPower(POWER_MANA, companion->GetMaxPower(POWER_MANA));
    companion->CastSpell(player, SpellBookHeal, false);

    state.mana -= cost;
    state.healReady = Clock::now() + std::chrono::seconds(HealCooldownSeconds(state));
    state.wantHeal = false;
    state.dirty = true;
    SendEvent(player, "CAST_HEAL", SpellBookHeal, cost);
    SendBook(player, state);
    return true;
}

class Combat final : public UnitScript
{
public:
    Combat() : UnitScript("forever_encyclopedia_companion_combat") { }

    void OnDamage(Unit* attacker, Unit* victim, uint32& damage) override
    {
        if (!damage)
            return;

        if (victim && victim->GetTypeId() == TYPEID_PLAYER)
        {
            Player* player = static_cast<Player*>(victim);
            if (!IsPlayerControlled(attacker) && AllowedPvE(player))
            {
                std::lock_guard<std::mutex> guard(RuntimeMutex);
                RuntimeState* state = FindRuntimeLocked(player);
                if (!state)
                    return;

                uint64 predicted = player->GetHealth() > damage ? player->GetHealth() - damage : 0;
                uint32 predictedPct = player->GetMaxHealth() ? uint32(predicted * 100 / player->GetMaxHealth()) : 0;
                auto now = Clock::now();

                if (state->shieldEnabled && GetRank(state->ranks, "aegis_unlock")
                    && now >= state->shieldReady && predictedPct <= state->shieldThreshold)
                    state->wantShield = true;

                if (state->healEnabled && GetRank(state->ranks, "mend_unlock")
                    && now >= state->healReady && predictedPct <= state->healThreshold)
                    state->wantHeal = true;
            }
        }
    }
};

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_companion_players") { }

    void OnLogin(Player* player, bool) override
    {
        if (!sConfigMgr->GetBoolDefault("ForeverEncyclopedia.Enable", false))
            return;
        std::lock_guard<std::mutex> guard(RuntimeMutex);
        Runtime[Guid(player)] = LoadRuntime(player);
    }

    void OnLogout(Player* player) override
    {
        std::lock_guard<std::mutex> guard(RuntimeMutex);
        auto it = Runtime.find(Guid(player));
        if (it == Runtime.end())
            return;
        DespawnCompanion(player, it->second);
        PersistRuntimeLocked(player, it->second);
        Runtime.erase(it);
    }

    void OnAddonMessageSent(Player* player, uint32 type, std::string const& prefix,
        std::string const& text, Player* receiver) override
    {
        if (type != CHAT_MSG_WHISPER || prefix != RequestPrefix || receiver != player)
            return;

        std::istringstream in(text);
        std::string cmd, extra;
        in >> cmd;
        if ((cmd.empty() || cmd == "status") && !(in >> extra))
        {
            std::lock_guard<std::mutex> guard(RuntimeMutex);
            RuntimeState* state = FindRuntimeLocked(player);
            if (!state)
                state = &Runtime.insert_or_assign(Guid(player), LoadRuntime(player)).first->second;
            else
                RefreshRuntimeLocked(player, *state);
            EnsureCompanion(player, *state);
            SendBook(player, *state);
        }
    }
};

class RuntimeTicker final : public WorldScript
{
public:
    RuntimeTicker() : WorldScript("forever_encyclopedia_companion_runtime") { }

    void OnUpdate(uint32 diff) override
    {
        _fastElapsed += diff;
        _slowElapsed += diff;
        if (_fastElapsed < 100)
            return;
        _fastElapsed = 0;

        auto now = Clock::now();
        for (auto const& pair : sWorld->GetAllSessions())
        {
            WorldSession* session = pair.second;
            Player* player = session ? session->GetPlayer() : nullptr;
            if (!player)
                continue;

            std::lock_guard<std::mutex> guard(RuntimeMutex);
            RuntimeState* state = FindRuntimeLocked(player);
            if (!state)
                continue;

            if (!player->IsAlive())
            {
                DespawnCompanion(player, *state);
                state->wantShield = false;
                state->wantHeal = false;
                continue;
            }

            Creature* companion = EnsureCompanion(player, *state);
            if (!companion)
                continue;

            if (!AllowedPvE(player))
            {
                state->wantShield = false;
                state->wantHeal = false;
            }
            else if (!companion->IsNonMeleeSpellCast(false))
            {
                // Protection gets priority when both are requested. Shield is an
                // instant native spell; the following tick can then begin the heal cast.
                if (state->wantShield)
                    StartShieldCast(player, *state, companion);
                else if (state->wantHeal)
                    StartHealCast(player, *state, companion);
            }

            if (!companion->IsNonMeleeSpellCast(false) && now - state->lastFollow >= std::chrono::seconds(1))
            {
                if (companion->GetDistance(player) > 35.0f)
                {
                    DespawnCompanion(player, *state);
                    EnsureCompanion(player, *state);
                }
                else
                    companion->GetMotionMaster()->MoveFollow(player, 2.2f, 1.65f);
                state->lastFollow = now;
            }

            if (_slowElapsed >= 1000)
            {
                companion->SetPower(POWER_MANA, companion->GetMaxPower(POWER_MANA));

                if (now - state->lastRegen >= std::chrono::seconds(5))
                {
                    uint32 gain = RegenGain(player, *state);
                    uint32 oldMana = state->mana;
                    state->mana = std::min(state->maxMana, state->mana + gain);
                    state->lastRegen = now;
                    if (state->mana != oldMana)
                    {
                        state->dirty = true;
                        SendBook(player, *state);
                    }
                }

                if (state->dirty && now - state->lastPersist >= std::chrono::seconds(30))
                    PersistRuntimeLocked(player, *state);
            }
        }

        if (_slowElapsed >= 1000)
            _slowElapsed = 0;
    }

private:
    uint32 _fastElapsed = 0;
    uint32 _slowElapsed = 0;
};
}

void AddSC_forever_encyclopedia_runtime()
{
    new ForeverEncyclopediaRuntime::Players();
    new ForeverEncyclopediaRuntime::Combat();
    new ForeverEncyclopediaRuntime::RuntimeTicker();
}
