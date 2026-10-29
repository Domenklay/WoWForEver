#include "ScriptMgr.h"
#include "Player.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
#include "TalentRules.h"
#include <algorithm>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace ForeverEncyclopediaTalentServer
{
using ForeverEncyclopedia::Talents::All;
using ForeverEncyclopedia::Talents::AppearanceThreshold;
using ForeverEncyclopedia::Talents::Cost;
using ForeverEncyclopedia::Talents::Find;
using ForeverEncyclopedia::Talents::TalentDef;

constexpr char RequestPrefix[] = "FET1";
constexpr char ResponsePrefix[] = "FTR1";
constexpr uint32 BaseMaxMana = 100;
static std::mutex PurchaseMutex;

struct Progress
{
    uint64 total = 0;
    uint64 spent = 0;
};

using RankMap = std::unordered_map<std::string, uint16>;

static uint32 Account(Player* player)
{
    return player && player->GetSession() ? player->GetSession()->GetAccountId() : 0;
}

static void Send(Player* player, std::string const& text)
{
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
            ranks[f[0].GetString()] = f[1].GetUInt16();
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
    uint32 capacity = Rank(ranks, "mana_capacity");
    uint32 mastery = Rank(ranks, "wisdom_mastery");
    return BaseMaxMana + capacity * 10 + mastery * 2;
}

static std::string SelectedAppearance(Player* player)
{
    if (!player)
        return "living_book";
    uint64 guid = player->GetGUID().GetCounter();
    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT appearance_key FROM forever_encyclopedia_appearance_selection WHERE character_guid={}", guid))
        return row->Fetch()[0].GetString();
    return "living_book";
}

static uint32 CurrentMana(Player* player, uint32 maxMana)
{
    if (!player)
        return maxMana;
    uint64 guid = player->GetGUID().GetCounter();
    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT mana FROM forever_encyclopedia_character WHERE character_guid={}", guid))
        return std::min(row->Fetch()[0].GetUInt32(), maxMana);
    return maxMana;
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
    uint32 maxMana = MaxMana(ranks);
    uint32 mana = CurrentMana(player, maxMana);

    Send(player, Trinity::StringFormat("POINTS|{}|{}|{}", p.total, p.spent, available));
    for (TalentDef const& def : All())
    {
        uint16 rank = Rank(ranks, def.key);
        if (rank)
            Send(player, Trinity::StringFormat("RANK|{}|{}", def.key, rank));
    }

    Send(player, Trinity::StringFormat("BOOK|{}|{}|{}|{}", AbilityMask(ranks), mana, maxMana, InformationLevel(ranks)));

    static char const* appearances[] = {"living_book", "archivist", "knowledge_spirit", "small_construct", "runekeeper"};
    for (char const* key : appearances)
        Send(player, Trinity::StringFormat("APPEARANCE|{}|{}|{}", key,
            p.total >= AppearanceThreshold(key) ? 1 : 0, AppearanceThreshold(key)));
    Send(player, "SELECTED|" + SelectedAppearance(player));
    Send(player, "END");
}

static bool PrerequisiteMet(TalentDef const& def, RankMap const& ranks)
{
    if (def.prerequisite.empty())
        return true;
    return Rank(ranks, def.prerequisite) >= def.prerequisiteRank;
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

    CharacterDatabaseTransaction tx = CharacterDatabase.BeginTransaction();
    tx->PAppend("UPDATE forever_encyclopedia_account SET knowledge_spent=knowledge_spent+{} WHERE account_id={}", cost, account);
    tx->PAppend(
        "INSERT INTO forever_encyclopedia_talent (account_id,talent_key,rank) VALUES ({},'{}',{}) "
        "ON DUPLICATE KEY UPDATE rank=VALUES(rank)",
        account, def->key, uint32(current + 1));
    CharacterDatabase.DirectCommitTransaction(tx);

    Send(player, Trinity::StringFormat("BOUGHT|{}|{}|{}", def->key, current + 1, cost));
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

    uint64 guid = player->GetGUID().GetCounter();
    CharacterDatabase.DirectPExecute(
        "INSERT INTO forever_encyclopedia_appearance_selection (character_guid,appearance_key) VALUES ({},'{}') "
        "ON DUPLICATE KEY UPDATE appearance_key=VALUES(appearance_key)", guid, key);
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

static void Request(Player* player, std::string const& text)
{
    if (!sConfigMgr->GetBoolDefault("ForeverEncyclopedia.Enable", false))
    {
        Error(player, "disabled");
        return;
    }

    std::istringstream in(text);
    std::string cmd;
    in >> cmd;
    if (cmd.empty() || cmd == "status")
    {
        Snapshot(player);
        return;
    }
    if (cmd == "buy")
    {
        std::string key, extra;
        if (!(in >> key) || (in >> extra)) { Error(player, "invalid buy"); return; }
        Buy(player, key);
        return;
    }
    if (cmd == "appearance")
    {
        std::string key, extra;
        if (!(in >> key) || (in >> extra)) { Error(player, "invalid appearance"); return; }
        SelectAppearance(player, key);
        return;
    }
    if (cmd == "creature")
    {
        uint32 entry = 0;
        std::string extra;
        if (!(in >> entry) || (in >> extra)) { Error(player, "invalid creature"); return; }
        CreatureInfo(player, entry);
        return;
    }
    Error(player, "unknown command");
}

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_talent_players") { }

    void OnAddonMessageSent(Player* player, uint32 type, std::string const& prefix,
        std::string const& text, Player* receiver) override
    {
        if (type == CHAT_MSG_WHISPER && prefix == RequestPrefix && receiver == player)
            Request(player, text);
    }
};
}

void AddSC_forever_encyclopedia_talents()
{
    new ForeverEncyclopediaTalentServer::Players();
}
