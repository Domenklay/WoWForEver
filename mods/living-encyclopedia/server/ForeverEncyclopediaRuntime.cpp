#include "ScriptMgr.h"
#include "Player.h"
#include "Unit.h"
#include "Group.h"
#include "World.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
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
using ForeverEncyclopedia::Talents::Rank;

constexpr char RequestPrefix[] = "FEB1";
constexpr char ResponsePrefix[] = "FBR1";
constexpr uint32 BaseMaxMana = 100;
static std::mutex RuntimeMutex;

using RankMap = std::unordered_map<std::string, uint16>;

struct RuntimeState
{
    bool loaded = false;
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
    uint64 barrier = 0;
    uint32 regenCarry = 0; // basis-point fractional carry; denominator 10000
    Clock::time_point barrierExpires{};
    Clock::time_point shieldReady{};
    Clock::time_point healReady{};
    Clock::time_point supportReady{};
    Clock::time_point insightExpires{};
    Clock::time_point lastRegen = Clock::now();
    Clock::time_point lastPersist = Clock::now();
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
    auto it = ranks.find(std::string(key));
    return it == ranks.end() ? 0 : it->second;
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
    // Permanent stat progression: every 10 knowledge grants +1 maximum mana.
    uint64 value = uint64(BaseMaxMana) + knowledgeTotal / 10;
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
    if (GetRank(ranks, "insight_unlock")) mask |= 4;
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

static uint32 SupportManaCost(RuntimeState const& state)
{
    uint32 cost = 20 + state.maxMana * 15 / 1000;
    cost -= std::min<uint32>(8, GetRank(state.ranks, "insight_efficiency") * 2);
    return ApplyConservation(state.ranks, std::max<uint32>(12, cost));
}

static uint32 ShieldCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(20, 30 - std::min<uint32>(10, GetRank(state.ranks, "aegis_reflex") * 2));
}

static uint32 HealCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(15, 25 - std::min<uint32>(10, GetRank(state.ranks, "mend_reflex") * 2));
}

static uint32 SupportCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(30, 45 - std::min<uint32>(15, GetRank(state.ranks, "insight_reflex") * 3));
}

static uint64 ShieldAmount(Player* player, RuntimeState const& state)
{
    uint32 bp = 1200 + GetRank(state.ranks, "aegis_strength") * 200
        + GetRank(state.ranks, "aegis_overcharge") * 200
        + GetRank(state.ranks, "aegis_mastery") * 10;
    bp = std::min<uint32>(3000, bp); // absolute 30% max-HP cap
    return player->GetMaxHealth() * uint64(bp) / 10000;
}

static uint64 HealAmount(Player* player, RuntimeState const& state)
{
    uint32 deep = GetRank(state.ranks, "mend_deep");
    uint32 bp = 800 + GetRank(state.ranks, "mend_power") * 200 + deep * 400
        + GetRank(state.ranks, "mend_mastery") * 20;
    uint32 cap = deep == 0 ? 2500 : std::min<uint32>(4000, 2500 + deep * 500);
    bp = std::min(bp, cap);
    return player->GetMaxHealth() * uint64(bp) / 10000;
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

static RuntimeState LoadRuntime(Player* player)
{
    RuntimeState state;
    state.loaded = true;
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
    uint32 account = Account(player);
    RankMap ranks = LoadRanks(account);
    uint64 knowledge = KnowledgeTotal(account);
    uint32 oldMax = state.maxMana;
    state.account = account;
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
        "UPDATE forever_encyclopedia_character SET mana={} WHERE character_guid={}",
        state.mana, Guid(player));
    state.dirty = false;
    state.lastPersist = Clock::now();
}

static void SendBook(Player* player, RuntimeState const& state)
{
    Send(player, Trinity::StringFormat("BOOK|{}|{}|{}|{}|{}|{}|{}",
        AbilityMask(state.ranks), state.mana, state.maxMana,
        CooldownRemaining(state.shieldReady), CooldownRemaining(state.healReady),
        CooldownRemaining(state.supportReady), state.barrier));
}

static void ClearForbidden(RuntimeState& state)
{
    state.barrier = 0;
    state.barrierExpires = Clock::time_point{};
    state.insightExpires = Clock::time_point{};
}

static uint32 RegenGain(Player* player, RuntimeState& state)
{
    bool combat = player->IsInCombat();
    uint32 base = combat ? 1 : 5;
    uint32 rank = combat ? GetRank(state.ranks, "mana_combat_regen") : GetRank(state.ranks, "mana_rest_regen");
    uint32 bonusBp = std::min<uint32>(100, rank * 20); // 0.2% per rank; 1% / 5 sec max
    uint64 numerator = uint64(state.maxMana) * bonusBp + state.regenCarry;
    uint32 bonus = uint32(numerator / 10000);
    state.regenCarry = uint32(numerator % 10000);
    return base + bonus;
}

class Combat final : public UnitScript
{
public:
    Combat() : UnitScript("forever_encyclopedia_combat") { }

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
                if (state)
                {
                    bool changed = false;
                    auto now = Clock::now();
                    if (state->barrier && state->barrierExpires <= now)
                        state->barrier = 0;

                    if (state->barrier)
                    {
                        uint32 absorbed = uint32(std::min<uint64>(state->barrier, damage));
                        damage -= absorbed;
                        state->barrier -= absorbed;
                        changed = absorbed != 0;
                    }

                    uint64 predicted = player->GetHealth() > damage ? player->GetHealth() - damage : 0;
                    uint32 predictedPct = player->GetMaxHealth() ? uint32(predicted * 100 / player->GetMaxHealth()) : 0;

                    if (!state->barrier && state->shieldEnabled && GetRank(state->ranks, "aegis_unlock")
                        && now >= state->shieldReady && predictedPct <= state->shieldThreshold)
                    {
                        uint32 cost = ShieldManaCost(*state);
                        if (state->mana >= cost && state->mana - cost >= std::min(state->manaReserve, state->maxMana))
                        {
                            state->mana -= cost;
                            state->barrier = ShieldAmount(player, *state);
                            state->barrierExpires = now + std::chrono::seconds(12);
                            state->shieldReady = now + std::chrono::seconds(ShieldCooldownSeconds(*state));
                            state->dirty = true;
                            uint32 absorbed = uint32(std::min<uint64>(state->barrier, damage));
                            damage -= absorbed;
                            state->barrier -= absorbed;
                            changed = true;
                            predicted = player->GetHealth() > damage ? player->GetHealth() - damage : 0;
                            predictedPct = player->GetMaxHealth() ? uint32(predicted * 100 / player->GetMaxHealth()) : 0;
                        }
                    }

                    if (state->healEnabled && GetRank(state->ranks, "mend_unlock")
                        && now >= state->healReady && predictedPct <= state->healThreshold)
                    {
                        uint32 cost = HealManaCost(*state);
                        if (state->mana >= cost && state->mana - cost >= std::min(state->manaReserve, state->maxMana))
                        {
                            state->mana -= cost;
                            uint64 heal = HealAmount(player, *state);
                            if (heal)
                                player->ModifyHealth(int64(heal));
                            state->healReady = now + std::chrono::seconds(HealCooldownSeconds(*state));
                            state->dirty = true;
                            changed = true;
                        }
                    }

                    if (changed)
                        SendBook(player, *state);
                }
            }
        }

        Player* source = attacker ? attacker->GetCharmerOrOwnerPlayerOrPlayerItself() : nullptr;
        if (!source || !AllowedPvE(source) || (victim && IsPlayerControlled(victim)))
            return;

        std::lock_guard<std::mutex> guard(RuntimeMutex);
        RuntimeState* state = FindRuntimeLocked(source);
        if (!state || !GetRank(state->ranks, "insight_unlock"))
            return;

        auto now = Clock::now();
        bool activated = false;
        if (state->insightExpires <= now && state->supportReady <= now)
        {
            uint32 cost = SupportManaCost(*state);
            if (state->mana >= cost && state->mana - cost >= std::min(state->manaReserve, state->maxMana))
            {
                state->mana -= cost;
                uint32 duration = 6 + GetRank(state->ranks, "insight_duration") * 2;
                state->insightExpires = now + std::chrono::seconds(duration);
                state->supportReady = now + std::chrono::seconds(SupportCooldownSeconds(*state));
                state->dirty = true;
                activated = true;
            }
        }

        if (state->insightExpires > now)
        {
            uint32 bp = std::min<uint32>(600, 300 + GetRank(state->ranks, "insight_mastery") * 20);
            uint64 bonus = uint64(damage) * bp / 10000;
            damage = uint32(std::min<uint64>(UINT32_MAX, uint64(damage) + bonus));
        }
        if (activated)
            SendBook(source, *state);
    }
};

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_runtime_players") { }

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
        if (it != Runtime.end())
        {
            PersistRuntimeLocked(player, it->second);
            Runtime.erase(it);
        }
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
            SendBook(player, *state);
        }
    }
};

class RuntimeTicker final : public WorldScript
{
public:
    RuntimeTicker() : WorldScript("forever_encyclopedia_runtime") { }

    void OnUpdate(uint32 diff) override
    {
        _elapsed += diff;
        if (_elapsed < 1000)
            return;
        _elapsed = 0;

        auto now = Clock::now();
        for (auto const& pair : sWorld->GetAllSessions())
        {
            WorldSession* session = pair.second;
            Player* player = session ? session->GetPlayer() : nullptr;
            if (!player)
                continue;

            bool sendUpdate = false;
            std::lock_guard<std::mutex> guard(RuntimeMutex);
            RuntimeState* state = FindRuntimeLocked(player);
            if (!state)
                continue;

            if (!AllowedPvE(player))
            {
                if (state->barrier || state->insightExpires > now)
                {
                    ClearForbidden(*state);
                    sendUpdate = true;
                }
            }
            else if (state->barrier && state->barrierExpires <= now)
            {
                state->barrier = 0;
                sendUpdate = true;
            }

            if (now - state->lastRegen >= std::chrono::seconds(5))
            {
                uint32 gain = RegenGain(player, *state);
                uint32 oldMana = state->mana;
                state->mana = std::min(state->maxMana, state->mana + gain);
                state->lastRegen = now;
                if (state->mana != oldMana)
                {
                    state->dirty = true;
                    sendUpdate = true;
                }
            }

            if (state->dirty && now - state->lastPersist >= std::chrono::seconds(30))
                PersistRuntimeLocked(player, *state);
            if (sendUpdate)
                SendBook(player, *state);
        }
    }

private:
    uint32 _elapsed = 0;
};
}

void AddSC_forever_encyclopedia_runtime()
{
    new ForeverEncyclopediaRuntime::Players();
    new ForeverEncyclopediaRuntime::Combat();
    new ForeverEncyclopediaRuntime::RuntimeTicker();
}
