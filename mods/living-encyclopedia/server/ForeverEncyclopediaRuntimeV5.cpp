#include "ScriptMgr.h"
#include "Player.h"
#include "Creature.h"
#include "TemporarySummon.h"
#include "Unit.h"
#include "Group.h"
#include "World.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
#include "ObjectAccessor.h"
#include "MotionMaster.h"
#include "SpellMgr.h"
#include "SpellInfo.h"
#include "SpellDefines.h"
#include "SpellAuras.h"
#include "SpellAuraEffects.h"
#include "Map.h"
#include "TalentRules.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <initializer_list>
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
constexpr float CompanionFollowDistance = 1.0f;
constexpr float CompanionFollowAngle = 1.65f;
constexpr uint32 SafeCompanionEntry = 1933; // stable diagnostic shell until book display is client-verified

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
    bool companionEnabled = false;
    bool castsEnabled = false;
    bool wantShield = false;
    bool wantHeal = false;
    uint32 regenCarry = 0;
    ObjectGuid companionGuid;

    bool shieldPending = false;
    uint32 pendingShieldSpell = 0;
    uint8 pendingShieldEffect = 0;
    uint32 pendingShieldAmount = 0;
    Clock::time_point pendingShieldStarted{};

    Clock::time_point shieldReady{};
    Clock::time_point healReady{};
    Clock::time_point supportReady{};
    Clock::time_point lastRegen = Clock::now();
    Clock::time_point lastPersist = Clock::now();
    Clock::time_point lastFollow = Clock::now();
    bool dirty = false;
};

static std::unordered_map<uint64, RuntimeState> Runtime;

struct ShieldSpell
{
    uint32 Id = 0;
    uint8 EffectIndex = 0;
    explicit operator bool() const { return Id != 0; }
};

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
    return mask;
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

static void ClearPendingShield(RuntimeState& state)
{
    state.shieldPending = false;
    state.pendingShieldSpell = 0;
    state.pendingShieldEffect = 0;
    state.pendingShieldAmount = 0;
    state.pendingShieldStarted = Clock::time_point{};
}

static void DespawnCompanion(Player* player, RuntimeState& state)
{
    if (Creature* companion = Companion(player, state))
        companion->DespawnOrUnsummon();
    state.companionGuid.Clear();
    ClearPendingShield(state);
}

static uint32 SpendableMana(RuntimeState const& state)
{
    uint32 reserve = std::min(state.manaReserve, state.maxMana);
    return state.mana > reserve ? state.mana - reserve : 0;
}

static uint32 ShieldCapPct(RuntimeState const& state)
{
    // 12% baseline, early ranks matter immediately, absolute cap remains 30% max HP.
    uint32 pct = 12;
    pct += std::min<uint32>(10, GetRank(state.ranks, "aegis_strength") * 2);
    pct += std::min<uint32>(5, GetRank(state.ranks, "aegis_efficiency"));
    pct += std::min<uint32>(4, GetRank(state.ranks, "aegis_overcharge"));
    return std::min<uint32>(30, pct);
}

static uint32 HealCapPct(RuntimeState const& state)
{
    // User rule retained: ordinary heal cannot exceed 25%; late specialization raises it to 40%.
    uint32 pct = 25 + std::min<uint32>(15, GetRank(state.ranks, "mend_deep") * 5);
    return std::min<uint32>(40, pct);
}

static uint32 EffectiveHealThreshold(RuntimeState const& state)
{
    // "mend_efficiency" no longer discounts mana (1 mana must always equal 1 HP).
    // It instead lets the book react a little earlier.
    return std::min<uint32>(80, state.healThreshold + GetRank(state.ranks, "mend_efficiency") * 4);
}

static uint32 ResolveHealSpell(Player* player)
{
    if (!player || !player->GetMap())
        return 0;

    Difficulty difficulty = player->GetMap()->GetDifficultyID();
    for (uint32 spellId : { 2061u, 9472u, 9473u, 9474u, 10915u, 10916u, 10917u })
        if (sSpellMgr->GetSpellInfo(spellId, difficulty))
            return spellId;
    return 0;
}

static ShieldSpell ResolveShieldSpell(Player* player)
{
    if (!player || !player->GetMap())
        return {};

    Difficulty difficulty = player->GetMap()->GetDifficultyID();
    for (uint32 spellId : { 17u, 592u, 600u, 3747u, 6065u, 6066u, 10898u, 10899u, 10900u, 10901u, 25217u, 25218u, 48065u, 48066u })
    {
        SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId, difficulty);
        if (!info)
            continue;

        for (SpellEffectInfo const& effect : info->GetEffects())
            if (effect.IsAura(SPELL_AURA_SCHOOL_ABSORB))
                return { spellId, uint8(effect.EffectIndex) };
    }
    return {};
}

static TriggerCastFlags CompanionCastFlags()
{
    // Preserve native cast time/animation. Ignore only NPC resource/reagent/target-check restrictions.
    return TriggerCastFlags(TRIGGERED_IGNORE_POWER_COST
        | TRIGGERED_IGNORE_REAGENT_COST
        | TRIGGERED_DONT_REPORT_CAST_ERROR
        | TRIGGERED_IGNORE_TARGET_CHECK);
}

static Creature* EnsureCompanion(Player* player, RuntimeState& state)
{
    if (!state.companionEnabled || !player || !player->IsAlive() || !player->IsInWorld())
        return nullptr;

    if (Creature* existing = Companion(player, state))
    {
        if (existing->GetMap() == player->GetMap())
            return existing;
        DespawnCompanion(player, state);
    }

    Position spawnPos = player->GetNearPosition(CompanionFollowDistance, CompanionFollowAngle);
    spawnPos.m_positionZ += 1.0f;
    TempSummon* summoned = player->SummonCreature(SafeCompanionEntry, spawnPos, TEMPSUMMON_MANUAL_DESPAWN);
    if (!summoned)
    {
        SendEvent(player, "COMPANION_FAILED", SafeCompanionEntry, 0);
        return nullptr;
    }

    Creature* companion = summoned;
    companion->SetReactState(REACT_PASSIVE);
    companion->SetFaction(player->GetFaction());
    companion->SetImmuneToAll(true);
    companion->SetUninteractible(true);
    companion->SetLevel(player->GetLevel());
    companion->SetObjectScale(0.55f);
    companion->SetCanFly(true);
    companion->SetDisableGravity(true);
    companion->SetHover(true);
    companion->SetPowerType(POWER_MANA);
    companion->SetMaxPower(POWER_MANA, 100000);
    companion->SetPower(POWER_MANA, 100000);
    companion->GetMotionMaster()->MoveFollow(player, CompanionFollowDistance, CompanionFollowAngle);

    state.companionGuid = companion->GetGUID();
    state.lastFollow = Clock::now();
    SendEvent(player, "COMPANION_ON", SafeCompanionEntry, 0);
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
    RankMap ranks = LoadRanks(Account(player));
    uint64 knowledge = KnowledgeTotal(Account(player));
    uint32 oldMax = state.maxMana;

    state.ranks = std::move(ranks);
    state.knowledgeTotal = knowledge;
    state.maxMana = MaxMana(knowledge, state.ranks);
    if (state.maxMana > oldMax)
    {
        state.mana = std::min(state.maxMana, state.mana + (state.maxMana - oldMax));
        state.dirty = true;
    }
    else
        state.mana = std::min(state.mana, state.maxMana);

    uint32 talentReserve = state.maxMana * std::min<uint32>(25, GetRank(state.ranks, "mana_reserve") * 5) / 100;
    state.manaReserve = std::max(state.manaReserve, talentReserve);
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
    Send(player, Trinity::StringFormat("BOOK|{}|{}|{}|{}|{}|{}|0|{}|{}",
        AbilityMask(state.ranks), state.mana, state.maxMana,
        CooldownRemaining(state.shieldReady), CooldownRemaining(state.healReady),
        CooldownRemaining(state.supportReady), state.companionEnabled ? 1 : 0,
        state.castsEnabled ? 1 : 0));
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

static bool StartShieldCast(Player* player, RuntimeState& state, Creature* companion)
{
    if (!state.castsEnabled || state.shieldPending || !player || !companion || companion->IsNonMeleeSpellCast(false))
        return false;
    if (Clock::now() < state.shieldReady)
        return false;

    uint32 spendable = SpendableMana(state);
    uint32 cap = player->CountPctFromMaxHealth(ShieldCapPct(state));
    uint32 amount = std::min(spendable, cap);
    if (!amount)
        return false;

    ShieldSpell spell = ResolveShieldSpell(player);
    if (!spell)
    {
        state.wantShield = false;
        SendEvent(player, "SPELL_MISSING", 1, 0);
        return false;
    }

    companion->StopMoving();
    companion->SetFacingToObject(player);
    companion->SetPower(POWER_MANA, companion->GetMaxPower(POWER_MANA));

    SpellValueModFloat bp = static_cast<SpellValueModFloat>(static_cast<int32>(SPELLVALUE_BASE_POINT0) + spell.EffectIndex);
    CastSpellExtraArgs args(CompanionCastFlags());
    args.AddSpellMod(bp, SpellEffectValue(amount));
    args.AddSpellMod(SPELLVALUE_CRIT_CHANCE, SpellEffectValue(0));
    companion->CastSpell(player, spell.Id, args);

    state.shieldPending = true;
    state.pendingShieldSpell = spell.Id;
    state.pendingShieldEffect = spell.EffectIndex;
    state.pendingShieldAmount = amount;
    state.pendingShieldStarted = Clock::now();
    state.wantShield = false;
    SendEvent(player, "CAST_SHIELD", spell.Id, amount);
    return true;
}

static bool FinalizeShield(Player* player, RuntimeState& state, Creature* companion)
{
    if (!state.shieldPending || !player || !companion)
        return false;

    auto now = Clock::now();
    if (companion->IsNonMeleeSpellCast(false))
        return false;

    AuraEffect* absorb = player->GetAuraEffect(state.pendingShieldSpell, state.pendingShieldEffect, companion->GetGUID());

    // Some classic PW:S ranks validate the cast but fail to create the aura for a non-priest NPC.
    // After the native cast/animation completes, force the SAME real spell aura as a safe fallback.
    if (!absorb && now - state.pendingShieldStarted >= std::chrono::milliseconds(100))
    {
        companion->AddAura(state.pendingShieldSpell, player);
        absorb = player->GetAuraEffect(state.pendingShieldSpell, state.pendingShieldEffect, companion->GetGUID());
    }

    if (absorb)
    {
        uint32 amount = std::min(state.pendingShieldAmount, SpendableMana(state));
        if (!amount)
        {
            absorb->GetBase()->Remove();
            ClearPendingShield(state);
            return false;
        }

        absorb->ChangeAmount(SpellEffectValue(amount));
        state.mana -= amount; // strict 1 mana == 1 absorb HP
        state.shieldReady = now + std::chrono::seconds(ShieldCooldownSeconds(state));
        state.dirty = true;
        SendEvent(player, "SHIELD_DONE", amount, state.pendingShieldSpell);
        ClearPendingShield(state);
        SendBook(player, state);
        return true;
    }

    if (now - state.pendingShieldStarted >= std::chrono::seconds(2))
    {
        SendEvent(player, "SHIELD_FAILED", state.pendingShieldSpell, 0);
        ClearPendingShield(state);
    }
    return false;
}

static bool StartHealCast(Player* player, RuntimeState& state, Creature* companion)
{
    if (!state.castsEnabled || !player || !companion || companion->IsNonMeleeSpellCast(false))
        return false;
    if (Clock::now() < state.healReady || !SpendableMana(state))
        return false;

    uint32 spellId = ResolveHealSpell(player);
    if (!spellId)
    {
        state.wantHeal = false;
        SendEvent(player, "SPELL_MISSING", 2, 0);
        return false;
    }

    companion->StopMoving();
    companion->SetFacingToObject(player);
    companion->SetPower(POWER_MANA, companion->GetMaxPower(POWER_MANA));

    CastSpellExtraArgs args(CompanionCastFlags());
    args.AddSpellMod(SPELLVALUE_CRIT_CHANCE, SpellEffectValue(0));
    companion->CastSpell(player, spellId, args);

    // Cost/CD are intentionally NOT paid here. UnitScript::OnHeal clamps the real native heal
    // and charges exactly the effective HP amount. Interrupted/failed casts therefore cost 0.
    state.wantHeal = false;
    SendEvent(player, "CAST_HEAL", spellId, SpendableMana(state));
    return true;
}

static void TestCast(Player* player, RuntimeState& state, std::string const& which)
{
    state.companionEnabled = true;
    state.castsEnabled = true;
    Creature* companion = EnsureCompanion(player, state);
    if (!companion)
        return;

    if (which == "shield")
    {
        state.shieldReady = Clock::time_point{};
        state.wantShield = true;
        StartShieldCast(player, state, companion);
    }
    else
    {
        state.healReady = Clock::time_point{};
        state.wantHeal = true;
        StartHealCast(player, state, companion);
    }
    SendBook(player, state);
}

class Combat final : public UnitScript
{
public:
    Combat() : UnitScript("forever_encyclopedia_companion_combat_v5") { }

    void OnDamage(Unit* attacker, Unit* victim, uint32& damage) override
    {
        if (!damage || !victim || victim->GetTypeId() != TYPEID_PLAYER)
            return;

        Player* player = static_cast<Player*>(victim);
        if (IsPlayerControlled(attacker) || !AllowedPvE(player))
            return;

        std::lock_guard<std::mutex> guard(RuntimeMutex);
        RuntimeState* state = FindRuntimeLocked(player);
        if (!state || !state->castsEnabled || !state->companionEnabled)
            return;

        uint64 predicted = player->GetHealth() > damage ? player->GetHealth() - damage : 0;
        uint32 predictedPct = player->GetMaxHealth() ? uint32(predicted * 100 / player->GetMaxHealth()) : 0;
        auto now = Clock::now();

        if (state->shieldEnabled && GetRank(state->ranks, "aegis_unlock")
            && !state->shieldPending && now >= state->shieldReady && predictedPct <= state->shieldThreshold)
            state->wantShield = true;

        if (state->healEnabled && GetRank(state->ranks, "mend_unlock")
            && now >= state->healReady && predictedPct <= EffectiveHealThreshold(*state))
            state->wantHeal = true;
    }

    void OnHeal(Unit* healer, Unit* receiver, uint32& gain) override
    {
        if (!healer || !receiver || receiver->GetTypeId() != TYPEID_PLAYER || !gain)
            return;

        Player* player = static_cast<Player*>(receiver);
        std::lock_guard<std::mutex> guard(RuntimeMutex);
        RuntimeState* state = FindRuntimeLocked(player);
        if (!state || !state->castsEnabled || !state->companionEnabled)
            return;

        Creature* companion = Companion(player, *state);
        if (!companion || healer->GetGUID() != companion->GetGUID())
            return;

        uint32 missing = uint32(std::min<uint64>(UINT32_MAX, player->GetMaxHealth() - player->GetHealth()));
        uint32 cap = player->CountPctFromMaxHealth(HealCapPct(*state));
        uint32 spendable = SpendableMana(*state);
        uint32 allowed = std::min({ gain, missing, cap, spendable });

        gain = allowed;
        if (!allowed)
            return;

        state->mana -= allowed; // strict 1 mana == 1 actually healed HP
        state->healReady = Clock::now() + std::chrono::seconds(HealCooldownSeconds(*state));
        state->dirty = true;
        SendEvent(player, "HEAL_DONE", allowed, 0);
        SendBook(player, *state);
    }
};

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_companion_players_v5") { }

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
        std::string cmd, arg;
        in >> cmd >> arg;
        std::lock_guard<std::mutex> guard(RuntimeMutex);
        RuntimeState* state = FindRuntimeLocked(player);
        if (!state)
            state = &Runtime.insert_or_assign(Guid(player), LoadRuntime(player)).first->second;

        if (cmd.empty() || cmd == "status")
        {
            RefreshRuntimeLocked(player, *state);
            SendBook(player, *state);
            return;
        }

        if (cmd == "companion")
        {
            bool enable = arg == "on" || (arg == "toggle" && !state->companionEnabled);
            state->companionEnabled = enable;
            state->castsEnabled = enable;
            if (!enable)
            {
                state->wantShield = false;
                state->wantHeal = false;
                DespawnCompanion(player, *state);
                SendEvent(player, "COMPANION_OFF", 0, 0);
            }
            else
            {
                EnsureCompanion(player, *state);
                SendEvent(player, "CASTS_ON", 0, 0);
            }
            SendBook(player, *state);
            return;
        }

        if (cmd == "casts")
        {
            bool enable = state->companionEnabled && (arg == "on" || (arg == "toggle" && !state->castsEnabled));
            state->castsEnabled = enable;
            state->wantShield = false;
            state->wantHeal = false;
            if (!enable)
                ClearPendingShield(*state);
            SendEvent(player, enable ? "CASTS_ON" : "CASTS_OFF", 0, 0);
            SendBook(player, *state);
            return;
        }

        if (cmd == "test" && (arg == "shield" || arg == "heal"))
        {
            TestCast(player, *state, arg);
            return;
        }
    }
};

class RuntimeTicker final : public WorldScript
{
public:
    RuntimeTicker() : WorldScript("forever_encyclopedia_companion_runtime_v5") { }

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
            }
            else if (state->companionEnabled)
            {
                Creature* companion = EnsureCompanion(player, *state);
                if (companion)
                {
                    FinalizeShield(player, *state, companion);

                    if (!AllowedPvE(player))
                    {
                        state->wantShield = false;
                        state->wantHeal = false;
                    }
                    else if (state->castsEnabled && !companion->IsNonMeleeSpellCast(false))
                    {
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
                            companion->GetMotionMaster()->MoveFollow(player, CompanionFollowDistance, CompanionFollowAngle);
                        state->lastFollow = now;
                    }
                }
            }

            if (_slowElapsed >= 1000)
            {
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
