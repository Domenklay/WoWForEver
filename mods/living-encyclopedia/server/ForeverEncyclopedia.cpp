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
#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace ForeverEncyclopedia
{
using Clock = std::chrono::steady_clock;
constexpr char RequestPrefix[] = "FEC1";
constexpr char ResponsePrefix[] = "FER1";
constexpr uint32 CatalogPageSize = 8;

enum Kind : uint8
{
    KIND_CREATURE = 1,
    KIND_ITEM = 2,
    KIND_ZONE = 3
};

static std::atomic<bool> Ready{false};
static std::mutex RequestMutex;
static std::unordered_map<uint64, Clock::time_point> LastRequest;
static std::mutex CatalogMutex;

struct CatalogCreature
{
    uint32 entry = 0;
    uint32 type = 0;
    uint32 classification = 0;
    std::string name;
};

static std::unordered_map<uint64, std::vector<CatalogCreature>> CatalogCache;

static uint32 Account(Player* player)
{
    return player && player->GetSession() ? player->GetSession()->GetAccountId() : 0;
}

static uint64 CatalogKey(uint32 mapId, uint32 zoneId)
{
    return (uint64(mapId) << 32) | uint64(zoneId);
}

static uint32 RewardFor(Kind kind)
{
    switch (kind)
    {
        case KIND_CREATURE: return 1;
        case KIND_ITEM: return 1;
        case KIND_ZONE: return 3;
        default: return 0;
    }
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

static std::string ProtocolText(std::string value)
{
    for (char& c : value)
    {
        unsigned char uc = static_cast<unsigned char>(c);
        if (c == '|' || c == '\r' || c == '\n' || uc < 32)
            c = ' ';
    }
    if (value.size() > 180)
        value.resize(180);
    return value;
}

static void Record(Player* player, Kind kind, uint32 entry)
{
    if (!Ready || !player || !entry)
        return;

    uint32 account = Account(player);
    uint32 reward = RewardFor(kind);
    if (!account || !reward)
        return;

    uint32 mapId = player->GetMapId();
    uint32 zoneId = player->GetZoneId();
    CharacterDatabaseTransaction tx = CharacterDatabase.BeginTransaction();

    tx->PAppend(
        "INSERT IGNORE INTO forever_encyclopedia_discovery "
        "(account_id,kind,entry,first_map,first_zone) VALUES ({},{},{},{},{})",
        account, uint32(kind), entry, mapId, zoneId);
    tx->PAppend(
        "INSERT INTO forever_encyclopedia_account "
        "(account_id,knowledge_total,knowledge_spent,discoveries) "
        "SELECT {},{},0,1 WHERE ROW_COUNT()=1 "
        "ON DUPLICATE KEY UPDATE "
        "knowledge_total=knowledge_total+VALUES(knowledge_total), "
        "discoveries=discoveries+VALUES(discoveries)",
        account, reward);

    CharacterDatabase.DirectCommitTransaction(tx);
}

struct Counts
{
    uint32 creatures = 0;
    uint32 items = 0;
    uint32 zones = 0;
    uint32 total = 0;
};

struct Progress
{
    uint64 total = 0;
    uint64 spent = 0;
    uint32 discoveries = 0;
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

static Progress LoadProgress(Player* player)
{
    Progress progress;
    uint32 account = Account(player);
    if (!account)
        return progress;

    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT knowledge_total,knowledge_spent,discoveries "
            "FROM forever_encyclopedia_account WHERE account_id={}", account))
    {
        Field* f = row->Fetch();
        progress.total = f[0].GetUInt64();
        progress.spent = f[1].GetUInt64();
        progress.discoveries = f[2].GetUInt32();
    }
    return progress;
}

static void Snapshot(Player* player)
{
    Counts c = LoadCounts(player);
    Progress p = LoadProgress(player);
    uint64 available = p.total >= p.spent ? p.total - p.spent : 0;
    Send(player, Trinity::StringFormat("STATE {} {} {} {}", c.total, c.creatures, c.items, c.zones));
    Send(player, Trinity::StringFormat("KNOW {} {} {} {}", p.total, p.spent, available, p.discoveries));
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

static std::unordered_set<uint32> LoadKnownCreatures(uint32 account)
{
    std::unordered_set<uint32> known;
    if (!account)
        return known;

    if (QueryResult rows = CharacterDatabase.PQuery(
            "SELECT entry FROM forever_encyclopedia_discovery WHERE account_id={} AND kind={}",
            account, uint32(KIND_CREATURE)))
    {
        do
        {
            known.insert(rows->Fetch()[0].GetUInt32());
        }
        while (rows->NextRow());
    }
    return known;
}

static std::vector<CatalogCreature> BuildZoneCreatures(Player* player)
{
    std::vector<CatalogCreature> result;
    if (!player || !player->GetMap())
        return result;

    uint32 mapId = player->GetMapId();
    uint32 zoneId = player->GetZoneId();
    uint32 areaId = player->GetAreaId();
    Map* map = player->GetMap();

    std::unordered_map<uint32, CatalogCreature> unique;
    if (QueryResult rows = WorldDatabase.PQuery(
            "SELECT c.id,ct.name,ct.type,ct.Classification,c.zoneId,c.areaId," 
            "c.position_x,c.position_y,c.position_z "
            "FROM creature c INNER JOIN creature_template ct ON ct.entry=c.id "
            "WHERE c.map={} AND c.id<>0 ORDER BY c.id",
            mapId))
    {
        do
        {
            Field* f = rows->Fetch();
            uint32 entry = f[0].GetUInt32();
            uint32 storedZone = f[4].GetUInt32();
            uint32 storedArea = f[5].GetUInt32();
            float x = f[6].GetFloat();
            float y = f[7].GetFloat();
            float z = f[8].GetFloat();

            bool inZone = storedZone == zoneId || (storedZone == 0 && storedArea == areaId);
            if (!inZone)
            {
                uint32 actualZone = map->GetZoneId(player->GetPhaseShift(), x, y, z);
                inZone = actualZone == zoneId;
            }

            if (!inZone || unique.find(entry) != unique.end())
                continue;

            CatalogCreature creature;
            creature.entry = entry;
            creature.name = f[1].GetString();
            creature.type = f[2].GetUInt32();
            creature.classification = f[3].GetUInt32();
            unique.emplace(entry, std::move(creature));
        }
        while (rows->NextRow());
    }

    result.reserve(unique.size());
    for (auto& pair : unique)
        result.push_back(std::move(pair.second));

    std::sort(result.begin(), result.end(), [](CatalogCreature const& left, CatalogCreature const& right)
    {
        return left.entry < right.entry;
    });
    return result;
}

static std::vector<CatalogCreature> LoadZoneCreatures(Player* player)
{
    if (!player)
        return {};

    uint64 key = CatalogKey(player->GetMapId(), player->GetZoneId());
    {
        std::lock_guard<std::mutex> guard(CatalogMutex);
        auto it = CatalogCache.find(key);
        if (it != CatalogCache.end())
            return it->second;
    }

    std::vector<CatalogCreature> built = BuildZoneCreatures(player);
    {
        std::lock_guard<std::mutex> guard(CatalogMutex);
        auto [it, inserted] = CatalogCache.emplace(key, built);
        return it->second;
    }
}

static void Catalog(Player* player, uint32 page)
{
    uint32 account = Account(player);
    if (!account)
    {
        Error(player, "no account");
        return;
    }

    std::vector<CatalogCreature> creatures = LoadZoneCreatures(player);
    std::unordered_set<uint32> known = LoadKnownCreatures(account);

    uint32 knownInZone = 0;
    for (CatalogCreature const& creature : creatures)
        if (known.find(creature.entry) != known.end())
            ++knownInZone;

    uint32 total = uint32(creatures.size());
    uint32 pages = std::max<uint32>(1, (total + CatalogPageSize - 1) / CatalogPageSize);
    if (page < 1)
        page = 1;
    if (page > pages)
        page = pages;

    Send(player, Trinity::StringFormat("CATHEAD|{}|{}|{}|{}|{}",
        player->GetZoneId(), page, pages, total, knownInZone));

    size_t begin = size_t(page - 1) * CatalogPageSize;
    size_t end = std::min(creatures.size(), begin + size_t(CatalogPageSize));
    for (size_t i = begin; i < end; ++i)
    {
        CatalogCreature const& creature = creatures[i];
        bool discovered = known.find(creature.entry) != known.end();
        std::string name = discovered ? ProtocolText(creature.name) : std::string();
        uint32 type = discovered ? creature.type : 0;
        uint32 classification = discovered ? creature.classification : 0;
        Send(player, Trinity::StringFormat("CAT|{}|{}|{}|{}|{}",
            creature.entry, discovered ? 1 : 0, type, classification, name));
    }

    Send(player, "CATEND");
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

    if (command == "catalog")
    {
        uint32 page = 1;
        std::string extra;
        if (input >> page)
        {
            if (input >> extra)
            {
                Error(player, "invalid catalog request");
                return;
            }
        }
        Catalog(player, page);
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

        bool discoverySchema = bool(CharacterDatabase.Query("SELECT COUNT(*) FROM forever_encyclopedia_discovery"));
        bool accountSchema = bool(CharacterDatabase.Query("SELECT COUNT(*) FROM forever_encyclopedia_account"));
        if (!discoverySchema || !accountSchema)
        {
            TC_LOG_ERROR("scripts", "ForeverEncyclopedia schema missing; feature disabled");
            return;
        }

        Ready = true;
        TC_LOG_INFO("scripts", "ForeverEncyclopedia ready: discovery, knowledge and coordinate-resolved zone catalog enabled");
    }
};
} // namespace ForeverEncyclopedia

void AddSC_forever_encyclopedia()
{
    new ForeverEncyclopedia::Startup();
    new ForeverEncyclopedia::Players();
}
