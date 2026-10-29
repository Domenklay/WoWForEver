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
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace ForeverEncyclopediaTalentServer
{
using Clock = std::chrono::steady_clock;
using ForeverEncyclopedia::Talents::All;
using ForeverEncyclopedia::Talents::AppearanceThreshold;
using ForeverEncyclopedia::Talents::Cost;
using ForeverEncyclopedia::Talents::Find;
using ForeverEncyclopedia::Talents::TalentDef;

constexpr char RequestPrefix[] = "FET1";
constexpr char ResponsePrefix[] = "FTR1";
constexpr uint32 BaseMaxMana = 100;
static std::mutex PurchaseMutex;
static std::mutex RuntimeMutex;

struct Progress
{
    uint64 total = 0;
    uint64 spent = 0;
};

using RankMap = std::unordered_map<std::string, uint16>;

struct RuntimeState
{
    bool loaded = false;
    uint32 account = 0;
    RankMap ranks;
    uint32 mana = BaseMaxMana;
    uint32 maxMana = BaseMaxMana;
    uint32 shieldThreshold = 80;
    uint32 healThreshold = 50;
    uint32 manaReserve = 0;
    bool shieldEnabled = true;
    bool healEnabled = true;
    uint64 barrier = 0;
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

static void Error(Player* player, std::string const& text)
{
    Send(player, "ERROR|" + text);
}

static Progress LoadProgress(uint32 account)
{
    Progress p;
    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT knowledge_total,knowledge_spent FROM forever_encyclopedia_account WHERE account_id={}", account))
    {
        Field* f = row->Fetch();
        p.total = f[0].GetUInt64();
        p.spent = f[1].GetUInt64();
    }
    return p;
}

static RankMap LoadRanks(uint32 account)
{
    RankMap ranks;
    if (QueryResult rows = CharacterDatabase.PQuery(
            "SELECT talent_key,rank FROM forever_encyclopedia_talent WHERE account_id={}", account))
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

static uint16 Rank(RankMap const& ranks, std::string_view key)
{
    auto it = ranks.find(std::string(key));
    return it == ranks.end() ? 0 : it->second;
}

static uint32 AbilityMask(RankMap const& ranks)
{
    uint32 mask = 0;
    if (Rank(ranks, "aegis_unlock")) mask |= 1;
    if (Rank(ranks, "mend_unlock")) mask |= 2;
    if (Rank(ranks, "insight_unlock")) mask |= 4;
    return mask;
}

static uint32 InformationLevel(RankMap const& ranks)
{
    static char const* chain[] = {
        "identify_name", "identify_rank", "identify_stats", "identify_abilities",
        "identify_resists", "identify_loot", "identify_locations", "identify_rares"
    };
    uint32 level = 0;
    for (char const* key : chain)
    {
        if (!Rank(ranks, key))
            break;
        ++level;
    }
    return level;
}

static uint32 MaxMana(RankMap const& ranks)
{
    return BaseMaxMana + Rank(ranks, "mana_capacity") * 10 + Rank(ranks, "wisdom_mastery") * 2;
}

static uint32 ApplyConservation(RankMap const& ranks, uint32 cost)
{
    uint32 pct = std::min<uint32>(20, Rank(ranks, "mana_conservation") * 3);
    return std::max<uint32>(1, cost - (cost * pct / 100));
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
    if (player->IsPvP() || player->IsFFAPvP() || player->InBattleground() || player->InArena() || player->duel)
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
    state.maxMana = MaxMana(state.ranks);
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
    state.lastRegen = Clock::now();
    state.lastPersist = state.lastRegen;
    return state;
}

static RuntimeState& GetRuntimeLocked(Player* player)
{
    uint64 guid = Guid(player);
    auto it = Runtime.find(guid);
    if (it == Runtime.end() || !it->second.loaded)
        it = Runtime.insert_or_assign(guid, LoadRuntime(player)).first;
    return it->second;
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

static std::string SelectedAppearance(Player* player)
{
    if (!player)
        return "living_book";
    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT appearance_key FROM forever_encyclopedia_appearance_selection WHERE character_guid={}", Guid(player)))
        return row->Fetch()[0].GetString();
    return "living_book";
}

static void SendBook(Player* player, RuntimeState const& state)
{
    Send(player, Trinity::StringFormat("BOOK|{}|{}|{}|{}|{}|{}|{}|{}",
        AbilityMask(state.ranks), state.mana, state.maxMana, InformationLevel(state.ranks),
        CooldownRemaining(state.shieldReady), CooldownRemaining(state.healReady),
        CooldownRemaining(state.supportReady), state.barrier));
}

static void Snapshot(Player* player)
{
    uint32 account = Account(player);
    if (!account)
    {
        Error(player, "no account");
        return;
    }

    Progress p = LoadProgress(account);
    RankMap ranks = LoadRanks(account);
    uint64 available = p.total >= p.spent ? p.total - p.spent : 0;

    Send(player, Trinity::StringFormat("POINTS|{}|{}|{}", p.total, p.spent, available));
    for (TalentDef const& def : All())
    {
        uint16 rank = Rank(ranks, def.key);
        if (rank)
            Send(player, Trinity::StringFormat("RANK|{}|{}", std::string(def.key), rank));
    }

    {
        std::lock_guard<std::mutex> guard(RuntimeMutex);
        RuntimeState& runtime = GetRuntimeLocked(player);
        runtime.ranks = ranks;
        runtime.maxMana = MaxMana(ranks);
        runtime.mana = std::min(runtime.mana, runtime.maxMana);
        SendBook(player, runtime);
    }

    static char const* appearances[] = {"living_book", "archivist", "knowledge_spirit", "small_construct", "runekeeper"};
    for (char const* key : appearances)
        Send(player, Trinity::StringFormat("APPEARANCE|{}|{}|{}", key,
            p.total >= AppearanceThreshold(key) ? 1 : 0, AppearanceThreshold(key)));
    Send(player, "SELECTED|" + SelectedAppearance(player));
    Send(player, "END");
}

static bool PrerequisiteMet(TalentDef const& def, RankMap const& ranks)
{
    return def.prerequisite.empty() || Rank(ranks, def.prerequisite) >= def.prerequisiteRank;
}

static void Buy(Player* player, std::string const& key)
{
    TalentDef const* def = Find(key);
    if (!def)
    {
        Error(player, "unknown talent");
        return;
    }

    uint32 account = Account(player);
    if (!account)
    {
        Error(player, "no account");
        return;
    }

    std::lock_guard<std::mutex> guard(PurchaseMutex);
    Progress p = LoadProgress(account);
    RankMap ranks = LoadRanks(account);
    uint16 current = Rank(ranks, def->key);
    if (current >= def->maxRank)
    {
        Error(player, "max rank");
        return;
    }
    if (!PrerequisiteMet(*def, ranks))
    {
        Error(player, "prerequisite");
        return;
    }

    uint64 cost = Cost(*def, current);
    uint64 available = p.total >= p.spent ? p.total - p.spent : 0;
    if (available < cost)
    {
        Error(player, "not enough knowledge");
        return;
    }

    std::string talentKey(def->key);
    CharacterDatabaseTransaction tx = CharacterDatabase.BeginTransaction();
    tx->PAppend("UPDATE forever_encyclopedia_account SET knowledge_spent=knowledge_spent+{} WHERE account_id={}", cost, account);
    tx->PAppend(
        "INSERT INTO forever_encyclopedia_talent (account_id,talent_key,rank) VALUES ({},'{}',{}) "
        "ON DUPLICATE KEY UPDATE rank=VALUES(rank)",
        account, talentKey, uint32(current + 1));
    CharacterDatabase.DirectCommitTransaction(tx);

    {
        std::lock_guard<std::mutex> runtimeGuard(RuntimeMutex);
        RuntimeState& runtime = GetRuntimeLocked(player);
        runtime.ranks[talentKey] = current + 1;
        uint32 oldMax = runtime.maxMana;
        runtime.maxMana = MaxMana(runtime.ranks);
        if (runtime.maxMana > oldMax)
        {
            runtime.mana = std::min(runtime.maxMana, runtime.mana + (runtime.maxMana - oldMax));
            runtime.dirty = true;
        }
    }

    Send(player, Trinity::StringFormat("BOUGHT|{}|{}|{}", talentKey, current + 1, cost));
    Snapshot(player);
}

static void SelectAppearance(Player* player, std::string const& key)
{
    uint32 account = Account(player);
    uint32 threshold = AppearanceThreshold(key);
    if (!account || threshold == UINT32_MAX)
    {
        Error(player, "unknown appearance");
        return;
    }
    Progress p = LoadProgress(account);
    if (p.total < threshold)
    {
        Error(player, "appearance locked");
        return;
    }

    CharacterDatabase.DirectPExecute(
        "INSERT INTO forever_encyclopedia_appearance_selection (character_guid,appearance_key) VALUES ({},'{}') "
        "ON DUPLICATE KEY UPDATE appearance_key=VALUES(appearance_key)", Guid(player), key);
    Send(player, "SELECTED|" + key);
}

static void CreatureInfo(Player* player, uint32 entry)
{
    if (!entry)
    {
        Error(player, "invalid creature");
        return;
    }
    RankMap ranks = LoadRanks(Account(player));
    uint32 info = InformationLevel(ranks);
    Send(player, Trinity::StringFormat("CREATURE|{}|{}", entry, info));
    if (info == 0)
    {
        Send(player, "CEND");
        return;
    }

    if (QueryResult row = WorldDatabase.PQuery(
            "SELECT name,type,Classification,minlevel,maxlevel FROM creature_template WHERE entry={}", entry))
    {
        Field* f = row->Fetch();
        std::string name = f[0].GetString();
        for (char& c : name)
            if (c == '|' || c == '\r' || c == '\n') c = ' ';
        Send(player, Trinity::StringFormat("CBASE|{}|{}|{}|{}|{}", name,
            f[1].GetUInt32(), f[2].GetUInt32(), f[3].GetUInt32(), f[4].GetUInt32()));
    }
    Send(player, "CEND");
}

static uint32 ShieldManaCost(RuntimeState const& state)
{
    uint32 cost = 30;
    cost -= std::min<uint32>(10, Rank(state.ranks, "aegis_efficiency") * 2);
    return ApplyConservation(state.ranks, std::max<uint32>(15, cost));
}

static uint32 HealManaCost(RuntimeState const& state)
{
    uint32 cost = 35;
    cost -= std::min<uint32>(10, Rank(state.ranks, "mend_efficiency") * 2);
    return ApplyConservation(state.ranks, std::max<uint32>(20, cost));
}

static uint32 SupportManaCost(RuntimeState const& state)
{
    uint32 cost = 25;
    cost -= std::min<uint32>(10, Rank(state.ranks, "insight_efficiency") * 2);
    return ApplyConservation(state.ranks, std::max<uint32>(12, cost));
}

static uint32 ShieldCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(20, 30 - std::min<uint32>(10, Rank(state.ranks, "aegis_reflex") * 2));
}

static uint32 HealCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(15, 25 - std::min<uint32>(10, Rank(state.ranks, "mend_reflex") * 2));
}

static uint32 SupportCooldownSeconds(RuntimeState const& state)
{
    return std::max<uint32>(30, 45 - std::min<uint32>(15, Rank(state.ranks, "insight_reflex") * 3));
}

static uint64 ShieldAmount(Player* player, RuntimeState const& state)
{
    uint32 basisPoints = 1200 + Rank(state.ranks, "aegis_strength") * 200 + Rank(state.ranks, "aegis_overcharge") * 200 + Rank(state.ranks, "aegis_mastery") * 10;
    basisPoints = std::min<uint32>(3000, basisPoints);
    return player->GetMaxHealth() * uint64(basisPoints) / 10000;
}

static uint64 HealAmount(Player* player, RuntimeState const& state)
{
    uint32 deep = Rank(state.ranks, "mend_deep");
    uint32 basisPoints = 800 + Rank(state.ranks, "mend_power") * 200 + deep * 400 + Rank(state.ranks, "mend_mastery") * 20;
    uint32 cap = deep == 0 ? 2500 : std::min<uint32>(4000, 2500 + deep * 500);
    basisPoints = std::min(basisPoints, cap);
    return player->GetMaxHealth() * uint64(basisPoints) / 10000;
}

static void ClearForbidden(RuntimeState& state)
{
    state.barrier = 0;
    state.barrierExpires = Clock::time_point{};
    state.insightExpires = Clock::time_point{};
}

class Combat final : public UnitScript
{
public:
    Combat() : UnitScript("forever_encyclopedia_combat") { }

    void OnDamage(Unit* attacker, Unit* victim, uint32& damage) override
    {
        if (!damage)
            return;

        // Incoming protection/healing for a player. Player-controlled damage is
        // always excluded so encyclopedia support cannot affect PvP.
        if (victim && victim->GetTypeId() == TYPEID_PLAYER)
        {
            Player* player = static_cast<Player*>(victim);
            if (!IsPlayerControlled(attacker) && AllowedPvE(player))
            {
                bool changed = false;
                {
                    std::lock_guard<std::mutex> guard(RuntimeMutex);
                    RuntimeState& state = GetRuntimeLocked(player);
                    auto now = Clock::now();

                    if (state.barrier && state.barrierExpires <= now)
                        state.barrier = 0;

                    if (state.barrier)
                    {
                        uint32 absorbed = uint32(std::min<uint64>(state.barrier, damage));
                        damage -= absorbed;
                        state.barrier -= absorbed;
                        changed = absorbed != 0;
                    }

                    uint64 predicted = player->GetHealth() > damage ? player->GetHealth() - damage : 0;
                    uint32 predictedPct = player->GetMaxHealth() ? uint32(predicted * 100 / player->GetMaxHealth()) : 0;

                    if (!state.barrier && state.shieldEnabled && Rank(state.ranks, "aegis_unlock") && now >= state.shieldReady && predictedPct <= state.shieldThreshold)
                    {
                        uint32 manaCost = ShieldManaCost(state);
                        if (state.mana >= manaCost && state.mana - manaCost >= std::min(state.manaReserve, state.maxMana))
                        {
                            state.mana -= manaCost;
                            state.barrier = ShieldAmount(player, state);
                            state.barrierExpires = now + std::chrono::seconds(12);
                            state.shieldReady = now + std::chrono::seconds(ShieldCooldownSeconds(state));
                            state.dirty = true;
                            uint32 absorbed = uint32(std::min<uint64>(state.barrier, damage));
                            damage -= absorbed;
                            state.barrier -= absorbed;
                            changed = true;
                            predicted = player->GetHealth() > damage ? player->GetHealth() - damage : 0;
                            predictedPct = player->GetMaxHealth() ? uint32(predicted * 100 / player->GetMaxHealth()) : 0;
                        }
                    }

                    if (state.healEnabled && Rank(state.ranks, "mend_unlock") && now >= state.healReady && predictedPct <= state.healThreshold)
                    {
                        uint32 manaCost = HealManaCost(state);
                        if (state.mana >= manaCost && state.mana - manaCost >= std::min(state.manaReserve, state.maxMana))
                        {
                            state.mana -= manaCost;
                            uint64 heal = HealAmount(player, state);
                            if (heal)
                                player->ModifyHealth(int64(heal));
                            state.healReady = now + std::chrono::seconds(HealCooldownSeconds(state));
                            state.dirty = true;
                            changed = true;
                        }
                    }

                    if (changed)
                        SendBook(player, state);
                }
            }
        }

        // Outgoing tactical insight. This is deliberately small and bounded:
        // 3% base damage, rising only to 6% at full late mastery.
        Player* source = attacker ? attacker->GetCharmerOrOwnerPlayerOrPlayerItself() : nullptr;
        if (!source || !AllowedPvE(source) || (victim && IsPlayerControlled(victim)))
            return;

        std::lock_guard<std::mutex> guard(RuntimeMutex);
        RuntimeState& state = GetRuntimeLocked(source);
        if (!Rank(state.ranks, "insight_unlock"))
            return;

        auto now = Clock::now();
        bool activated = false;
        if (state.insightExpires <= now && state.supportReady <= now)
        {
            uint32 manaCost = SupportManaCost(state);
            if (state.mana >= manaCost && state.mana - manaCost >= std::min(state.manaReserve, state.maxMana))
            {
                state.mana -= manaCost;
                uint32 duration = 6 + Rank(state.ranks, "insight_duration") * 2;
                state.insightExpires = now + std::chrono::seconds(duration);
                state.supportReady = now + std::chrono::seconds(SupportCooldownSeconds(state));
                state.dirty = true;
                activated = true;
            }
        }

        if (state.insightExpires > now)
        {
            uint32 basisPoints = std::min<uint32>(600, 300 + Rank(state.ranks, "insight_mastery") * 20);
            uint64 bonus = uint64(damage) * basisPoints / 10000;
            damage = uint32(std::min<uint64>(uint64(UINT32_MAX), uint64(damage) + bonus));
        }
        if (activated)
            SendBook(source, state);
    }
};

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_talent_players") { }

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
        if (type == CHAT_MSG_WHISPER && prefix == RequestPrefix && receiver == player)
        {
            std::istringstream in(text);
            std::string cmd;
            in >> cmd;
            if (cmd.empty() || cmd == "status") { Snapshot(player); return; }
            if (cmd == "buy")
            {
                std::string key, extra;
                if (!(in >> key) || (in >> extra)) { Error(player, "invalid buy"); return; }
                Buy(player, key); return;
            }
            if (cmd == "appearance")
            {
                std::string key, extra;
                if (!(in >> key) || (in >> extra)) { Error(player, "invalid appearance"); return; }
                SelectAppearance(player, key); return;
            }
            if (cmd == "creature")
            {
                uint32 entry = 0; std::string extra;
                if (!(in >> entry) || (in >> extra)) { Error(player, "invalid creature"); return; }
                CreatureInfo(player, entry); return;
            }
            Error(player, "unknown command");
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
            RuntimeState& state = GetRuntimeLocked(player);

            if (!AllowedPvE(player))
            {
                if (state.barrier || state.insightExpires > now)
                {
                    ClearForbidden(state);
                    sendUpdate = true;
                }
            }
            else if (state.barrier && state.barrierExpires <= now)
            {
                state.barrier = 0;
                sendUpdate = true;
            }

            if (now - state.lastRegen >= std::chrono::seconds(5))
            {
                uint32 gain = player->IsInCombat()
                    ? 1 + Rank(state.ranks, "mana_combat_regen")
                    : 5 + Rank(state.ranks, "mana_rest_regen") * 2;
                uint32 oldMana = state.mana;
                state.mana = std::min(state.maxMana, state.mana + gain);
                state.lastRegen = now;
                if (state.mana != oldMana)
                {
                    state.dirty = true;
                    sendUpdate = true;
                }
            }

            if (state.dirty && now - state.lastPersist >= std::chrono::seconds(30))
                PersistRuntimeLocked(player, state);
            if (sendUpdate)
                SendBook(player, state);
        }
    }

private:
    uint32 _elapsed = 0;
};
}

void AddSC_forever_encyclopedia_talents()
{
    new ForeverEncyclopediaTalentServer::Players();
    new ForeverEncyclopediaTalentServer::Combat();
    new ForeverEncyclopediaTalentServer::RuntimeTicker();
}
