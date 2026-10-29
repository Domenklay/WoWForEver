#include "ScriptMgr.h"
#include "Player.h"
#include "Creature.h"
#include "Item.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
#include "Log.h"
#include "Map.h"
#include <atomic>
#include <chrono>
#include <mutex>
#include <sstream>
#include <unordered_map>

namespace ForeverEncyclopedia
{
using Clock = std::chrono::steady_clock;
constexpr char RequestPrefix[] = "FEC1";
constexpr char ResponsePrefix[] = "FER1";

enum Kind : uint8
{
    KIND_CREATURE = 1,
    KIND_ITEM = 2,
    KIND_ZONE = 3
};

static std::atomic<bool> Ready{false};
static std::mutex RequestMutex;
static std::unordered_map<uint64, Clock::time_point> LastRequest;

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
    Send(player, "ERROR " + text);
}

static void Record(Player* player, Kind kind, uint32 entry)
{
    if (!Ready || !player || !entry)
        return;

    uint32 account = Account(player);
    if (!account)
        return;

    uint32 mapId = player->GetMapId();
    uint32 zoneId = player->GetZoneId();
    CharacterDatabaseTransaction tx = CharacterDatabase.BeginTransaction();
    tx->PAppend(
        "INSERT IGNORE INTO forever_encyclopedia_discovery "
        "(account_id,kind,entry,first_map,first_zone) VALUES ({},{},{},{},{})",
        account, uint32(kind), entry, mapId, zoneId);
    CharacterDatabase.DirectCommitTransaction(tx);
}

struct Counts
{
    uint32 creatures = 0;
    uint32 items = 0;
    uint32 zones = 0;
    uint32 total = 0;
};

static Counts LoadCounts(Player* player)
{
    Counts counts;
    uint32 account = Account(player);
    if (!account)
        return counts;

    if (QueryResult rows = CharacterDatabase.PQuery(
            "SELECT kind,COUNT(*) FROM forever_encyclopedia_discovery WHERE account_id={} GROUP BY kind",
            account))
    {
        do
        {
            Field* f = rows->Fetch();
            uint32 kind = f[0].GetUInt32();
            uint32 count = f[1].GetUInt32();
            counts.total += count;
            if (kind == KIND_CREATURE) counts.creatures = count;
            else if (kind == KIND_ITEM) counts.items = count;
            else if (kind == KIND_ZONE) counts.zones = count;
        }
        while (rows->NextRow());
    }
    return counts;
}

static void Snapshot(Player* player)
{
    Counts c = LoadCounts(player);
    Send(player, Trinity::StringFormat("STATE {} {} {} {}", c.total, c.creatures, c.items, c.zones));
    Send(player, Trinity::StringFormat("CURRENT {} {} {}", player->GetMapId(), player->GetZoneId(), player->GetAreaId()));
    Send(player, "END");
}

static bool ValidKind(uint32 kind)
{
    return kind >= KIND_CREATURE && kind <= KIND_ZONE;
}

static void Recent(Player* player, uint32 kind)
{
    if (!ValidKind(kind))
    {
        Error(player, "invalid kind");
        return;
    }

    uint32 account = Account(player);
    if (!account)
    {
        Error(player, "no account");
        return;
    }

    if (QueryResult rows = CharacterDatabase.PQuery(
            "SELECT entry,first_map,first_zone FROM forever_encyclopedia_discovery "
            "WHERE account_id={} AND kind={} ORDER BY first_seen DESC LIMIT 12",
            account, kind))
    {
        do
        {
            Field* f = rows->Fetch();
            Send(player, Trinity::StringFormat("REC {} {} {} {}", kind,
                f[0].GetUInt32(), f[1].GetUInt32(), f[2].GetUInt32()));
        }
        while (rows->NextRow());
    }

    Send(player, Trinity::StringFormat("RECEND {}", kind));
}

static void Request(Player* player, std::string const& text)
{
    if (!Ready)
    {
        Error(player, "module disabled");
        return;
    }
    if (text.size() > 96)
        return;

    {
        std::lock_guard<std::mutex> guard(RequestMutex);
        auto now = Clock::now();
        uint64 guid = player->GetGUID().GetCounter();
        auto it = LastRequest.find(guid);
        if (it != LastRequest.end() && now - it->second < std::chrono::milliseconds(150))
            return;
        LastRequest[guid] = now;
    }

    std::istringstream input(text);
    std::string command;
    input >> command;

    if (command.empty() || command == "status")
    {
        std::string extra;
        if (input >> extra)
        {
            Error(player, "invalid command");
            return;
        }
        Snapshot(player);
        return;
    }

    if (command == "recent")
    {
        uint32 kind = 0;
        std::string extra;
        if (!(input >> kind) || (input >> extra))
        {
            Error(player, "invalid recent request");
            return;
        }
        Recent(player, kind);
        return;
    }

    Error(player, "unknown command");
}

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_players") { }

    void OnLogin(Player* player, bool) override
    {
        if (Ready)
            Record(player, KIND_ZONE, player->GetZoneId());
    }

    void OnLogout(Player* player) override
    {
        std::lock_guard<std::mutex> guard(RequestMutex);
        LastRequest.erase(player->GetGUID().GetCounter());
    }

    void OnCreatureKill(Player* killer, Creature* killed) override
    {
        if (killed)
            Record(killer, KIND_CREATURE, killed->GetEntry());
    }

    void OnLootItem(Player* player, Item* item) override
    {
        if (item)
            Record(player, KIND_ITEM, item->GetEntry());
    }

    void OnUpdateZone(Player* player, uint32 newZone, uint32) override
    {
        Record(player, KIND_ZONE, newZone);
    }

    void OnAddonMessageSent(Player* player, uint32 type, std::string const& prefix,
        std::string const& text, Player* receiver) override
    {
        if (type == CHAT_MSG_WHISPER && prefix == RequestPrefix && receiver == player)
            Request(player, text);
    }
};

class Startup final : public WorldScript
{
public:
    Startup() : WorldScript("forever_encyclopedia_startup") { }

    void OnWorldInitialized() override
    {
        if (!sConfigMgr->GetBoolDefault("ForeverEncyclopedia.Enable", false))
            return;

        if (!CharacterDatabase.Query("SELECT COUNT(*) FROM forever_encyclopedia_discovery"))
        {
            TC_LOG_ERROR("scripts", "ForeverEncyclopedia schema missing; feature disabled");
            return;
        }

        Ready = true;
        TC_LOG_INFO("scripts", "ForeverEncyclopedia ready: account-wide creature/item/zone discovery enabled");
    }
};
} // namespace ForeverEncyclopedia

void AddSC_forever_encyclopedia()
{
    new ForeverEncyclopedia::Startup();
    new ForeverEncyclopedia::Players();
}
