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
#include "ObjectMgr.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace ForeverEncyclopedia
{
using Clock = std::chrono::steady_clock;
constexpr char RequestPrefix[] = "FEC1";
constexpr char ResponsePrefix[] = "FER1";
constexpr uint32 CatalogPageSize = 8;
constexpr uint32 BaseMaxMana = 100;

enum Kind : uint8 { KIND_CREATURE = 1, KIND_ITEM = 2, KIND_ZONE = 3 };

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

static uint32 Account(Player* p) { return p && p->GetSession() ? p->GetSession()->GetAccountId() : 0; }
static uint64 CatalogKey(uint32 mapId, uint32 zoneId) { return (uint64(mapId) << 32) | zoneId; }
static uint32 RewardFor(Kind kind) { return kind == KIND_ZONE ? 3 : (kind == KIND_CREATURE || kind == KIND_ITEM ? 1 : 0); }

static void Send(Player* p, std::string const& text)
{
    if (!p || !p->GetSession()) return;
    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER, LANG_ADDON, p, p, text, 0, "", LOCALE_enUS, ResponsePrefix);
    p->GetSession()->SendPacket(packet.Write());
}

static void Error(Player* p, std::string const& text) { Send(p, "ERROR " + text); }

static std::string ProtocolText(std::string value)
{
    for (char& c : value)
    {
        unsigned char uc = static_cast<unsigned char>(c);
        if (c == '|' || c == '\r' || c == '\n' || uc < 32) c = ' ';
    }
    if (value.size() > 180) value.resize(180);
    return value;
}

static void Record(Player* p, Kind kind, uint32 entry)
{
    if (!Ready || !p || !entry) return;
    uint32 account = Account(p), reward = RewardFor(kind);
    if (!account || !reward) return;

    CharacterDatabaseTransaction tx = CharacterDatabase.BeginTransaction();
    tx->PAppend("INSERT IGNORE INTO forever_encyclopedia_discovery (account_id,kind,entry,first_map,first_zone) VALUES ({},{},{},{},{})",
        account, uint32(kind), entry, p->GetMapId(), p->GetZoneId());
    tx->PAppend("INSERT INTO forever_encyclopedia_account (account_id,knowledge_total,knowledge_spent,discoveries) "
        "SELECT {},{},0,1 WHERE ROW_COUNT()=1 ON DUPLICATE KEY UPDATE "
        "knowledge_total=knowledge_total+VALUES(knowledge_total),discoveries=discoveries+VALUES(discoveries)", account, reward);
    CharacterDatabase.DirectCommitTransaction(tx);
}

struct Counts { uint32 creatures=0, items=0, zones=0, total=0; };
struct Progress { uint64 total=0, spent=0; uint32 discoveries=0; };

static Counts LoadCounts(Player* p)
{
    Counts c; uint32 account = Account(p); if (!account) return c;
    if (QueryResult rows = CharacterDatabase.PQuery("SELECT kind,COUNT(*) FROM forever_encyclopedia_discovery WHERE account_id={} GROUP BY kind", account))
    {
        do
        {
            Field* f = rows->Fetch(); uint32 kind=f[0].GetUInt32(), count=f[1].GetUInt32(); c.total += count;
            if (kind==KIND_CREATURE) c.creatures=count; else if (kind==KIND_ITEM) c.items=count; else if (kind==KIND_ZONE) c.zones=count;
        } while (rows->NextRow());
    }
    return c;
}

static Progress LoadProgress(Player* p)
{
    Progress v; uint32 account=Account(p); if (!account) return v;
    if (QueryResult row = CharacterDatabase.PQuery("SELECT knowledge_total,knowledge_spent,discoveries FROM forever_encyclopedia_account WHERE account_id={}", account))
    { Field* f=row->Fetch(); v.total=f[0].GetUInt64(); v.spent=f[1].GetUInt64(); v.discoveries=f[2].GetUInt32(); }
    return v;
}

static uint32 LoadMana(Player* p)
{
    if (!p) return BaseMaxMana;
    uint64 guid=p->GetGUID().GetCounter();
    CharacterDatabase.DirectPExecute("INSERT IGNORE INTO forever_encyclopedia_character (character_guid,mana,shield_enabled,heal_enabled,shield_threshold,heal_threshold,mana_reserve) VALUES ({},{},1,1,80,50,0)", guid, BaseMaxMana);
    if (QueryResult row=CharacterDatabase.PQuery("SELECT mana FROM forever_encyclopedia_character WHERE character_guid={}", guid)) return row->Fetch()[0].GetUInt32();
    return BaseMaxMana;
}

static void Snapshot(Player* p)
{
    Counts c=LoadCounts(p); Progress v=LoadProgress(p); uint64 available=v.total>=v.spent?v.total-v.spent:0;
    Send(p, Trinity::StringFormat("STATE {} {} {} {}", c.total,c.creatures,c.items,c.zones));
    Send(p, Trinity::StringFormat("KNOW {} {} {} {}", v.total,v.spent,available,v.discoveries));
    Send(p, Trinity::StringFormat("CURRENT {} {} {}", p->GetMapId(),p->GetZoneId(),p->GetAreaId()));
    Send(p, Trinity::StringFormat("BOOK {} {} 0 0 0 0", std::min(LoadMana(p),BaseMaxMana),BaseMaxMana));
    Send(p,"END");
}

static void Recent(Player* p, uint32 kind)
{
    if (kind < KIND_CREATURE || kind > KIND_ZONE) { Error(p,"invalid kind"); return; }
    uint32 account=Account(p); if (!account) { Error(p,"no account"); return; }
    if (QueryResult rows=CharacterDatabase.PQuery("SELECT entry,first_map,first_zone FROM forever_encyclopedia_discovery WHERE account_id={} AND kind={} ORDER BY first_seen DESC LIMIT 12", account,kind))
        do { Field* f=rows->Fetch(); Send(p,Trinity::StringFormat("REC {} {} {} {}",kind,f[0].GetUInt32(),f[1].GetUInt32(),f[2].GetUInt32())); } while (rows->NextRow());
    Send(p,Trinity::StringFormat("RECEND {}",kind));
}

static std::unordered_set<uint32> LoadKnownCreatures(uint32 account)
{
    std::unordered_set<uint32> known;
    if (account)
        if (QueryResult rows=CharacterDatabase.PQuery("SELECT entry FROM forever_encyclopedia_discovery WHERE account_id={} AND kind={}", account,uint32(KIND_CREATURE)))
            do { known.insert(rows->Fetch()[0].GetUInt32()); } while (rows->NextRow());
    return known;
}

static bool IsCatalogCreature(uint32 entry)
{
    CreatureTemplate const* t=sObjectMgr->GetCreatureTemplate(entry);
    return t && !(t->flags_extra & CREATURE_FLAG_EXTRA_TRIGGER);
}

static std::vector<CatalogCreature> BuildZoneCreatures(Player* p)
{
    std::vector<CatalogCreature> result; if (!p || !p->GetMap()) return result;
    uint32 mapId=p->GetMapId(), zoneId=p->GetZoneId(), areaId=p->GetAreaId(); Map* map=p->GetMap();
    std::unordered_map<uint32,CatalogCreature> unique;
    if (QueryResult rows=WorldDatabase.PQuery("SELECT c.id,ct.name,ct.type,ct.Classification,c.zoneId,c.areaId,c.position_x,c.position_y,c.position_z "
        "FROM creature c INNER JOIN creature_template ct ON ct.entry=c.id WHERE c.map={} AND c.id<>0 ORDER BY c.id", mapId))
    {
        do
        {
            Field* f=rows->Fetch(); uint32 entry=f[0].GetUInt32();
            if (!IsCatalogCreature(entry) || unique.find(entry)!=unique.end()) continue;
            uint32 storedZone=f[4].GetUInt32(), storedArea=f[5].GetUInt32();
            float x=f[6].GetFloat(), y=f[7].GetFloat(), z=f[8].GetFloat();
            bool inZone=storedZone==zoneId || (storedZone==0 && storedArea==areaId);
            if (!inZone) inZone=map->GetZoneId(p->GetPhaseShift(),x,y,z)==zoneId;
            if (!inZone) continue;
            CatalogCreature c; c.entry=entry; c.name=f[1].GetString(); c.type=f[2].GetUInt32(); c.classification=f[3].GetUInt32(); unique.emplace(entry,std::move(c));
        } while (rows->NextRow());
    }
    result.reserve(unique.size()); for (auto& pair:unique) result.push_back(std::move(pair.second));
    std::sort(result.begin(),result.end(),[](CatalogCreature const& a,CatalogCreature const& b){ return a.entry<b.entry; });
    return result;
}

static std::vector<CatalogCreature> LoadZoneCreatures(Player* p)
{
    if (!p) return {};
    uint64 key=CatalogKey(p->GetMapId(),p->GetZoneId());
    { std::lock_guard<std::mutex> g(CatalogMutex); auto it=CatalogCache.find(key); if (it!=CatalogCache.end()) return it->second; }
    auto built=BuildZoneCreatures(p);
    { std::lock_guard<std::mutex> g(CatalogMutex); auto [it,inserted]=CatalogCache.emplace(key,built); return it->second; }
}

static bool Matches(CatalogCreature const& c,bool discovered,uint32 knownFilter,uint32 typeFilter,int32 classFilter)
{
    if (knownFilter==1 && !discovered) return false; if (knownFilter==2 && discovered) return false;
    if (typeFilter && c.type!=typeFilter) return false; if (classFilter>=0 && int32(c.classification)!=classFilter) return false; return true;
}

static void Catalog(Player* p,uint32 page,uint32 knownFilter,uint32 typeFilter,int32 classFilter)
{
    uint32 account=Account(p); if (!account) { Error(p,"no account"); return; }
    if (knownFilter>2 || typeFilter>12 || classFilter < -1 || classFilter>4) { Error(p,"invalid catalog filter"); return; }
    auto creatures=LoadZoneCreatures(p); auto known=LoadKnownCreatures(account);
    uint32 zoneKnown=0; std::vector<CatalogCreature const*> filtered; filtered.reserve(creatures.size());
    for (auto const& c:creatures) { bool discovered=known.count(c.entry); if (discovered) ++zoneKnown; if (Matches(c,discovered,knownFilter,typeFilter,classFilter)) filtered.push_back(&c); }
    std::stable_sort(filtered.begin(),filtered.end(),[&known](auto a,auto b){ bool ak=known.count(a->entry),bk=known.count(b->entry); if (ak!=bk) return ak>bk; if (ak&&bk&&a->name!=b->name) return a->name<b->name; return a->entry<b->entry; });
    uint32 matchedKnown=0; for (auto c:filtered) if (known.count(c->entry)) ++matchedKnown;
    uint32 total=uint32(filtered.size()), pages=std::max<uint32>(1,(total+CatalogPageSize-1)/CatalogPageSize); page=std::clamp<uint32>(page,1,pages);
    Send(p,Trinity::StringFormat("CATHEAD|{}|{}|{}|{}|{}|{}|{}",p->GetZoneId(),page,pages,total,matchedKnown,uint32(creatures.size()),zoneKnown));
    size_t begin=size_t(page-1)*CatalogPageSize,end=std::min(filtered.size(),begin+size_t(CatalogPageSize));
    for (size_t i=begin;i<end;++i)
    {
        auto const& c=*filtered[i]; bool discovered=known.count(c.entry); Send(p,Trinity::StringFormat("CAT|{}|{}|{}|{}|{}",c.entry,discovered?1:0,discovered?c.type:0,discovered?c.classification:0,discovered?ProtocolText(c.name):std::string()));
    }
    Send(p,"CATEND");
}

static void Request(Player* p,std::string const& text)
{
    if (!Ready) { Error(p,"module disabled"); return; } if (text.size()>96) return;
    { std::lock_guard<std::mutex> g(RequestMutex); auto now=Clock::now(); uint64 guid=p->GetGUID().GetCounter(); auto it=LastRequest.find(guid); if (it!=LastRequest.end() && now-it->second<std::chrono::milliseconds(150)) return; LastRequest[guid]=now; }
    std::istringstream in(text); std::string cmd; in>>cmd;
    if (cmd.empty() || cmd=="status") { Snapshot(p); return; }
    if (cmd=="recent") { uint32 kind=0; std::string extra; if (!(in>>kind)||(in>>extra)) { Error(p,"invalid recent request"); return; } Recent(p,kind); return; }
    if (cmd=="catalog")
    {
        uint32 page=1,known=0,type=0; int32 cls=-1; std::string extra;
        if (in>>page) { if (!(in>>known)) in.clear(); else if (!(in>>type)) in.clear(); else if (!(in>>cls)) in.clear(); }
        if (in>>extra) { Error(p,"invalid catalog request"); return; } Catalog(p,page,known,type,cls); return;
    }
    Error(p,"unknown command");
}

class Players final : public PlayerScript
{
public:
    Players():PlayerScript("forever_encyclopedia_players"){}
    void OnLogin(Player* p,bool) override { if (Ready) { LoadMana(p); Record(p,KIND_ZONE,p->GetZoneId()); } }
    void OnLogout(Player* p) override { std::lock_guard<std::mutex> g(RequestMutex); LastRequest.erase(p->GetGUID().GetCounter()); }
    void OnCreatureKill(Player* killer,Creature* killed) override { if (killed && IsCatalogCreature(killed->GetEntry())) Record(killer,KIND_CREATURE,killed->GetEntry()); }
    void OnLootItem(Player* p,Item* item) override { if (item) Record(p,KIND_ITEM,item->GetEntry()); }
    void OnUpdateZone(Player* p,uint32 newZone,uint32) override { Record(p,KIND_ZONE,newZone); }
    void OnAddonMessageSent(Player* p,uint32 type,std::string const& prefix,std::string const& text,Player* receiver) override { if (type==CHAT_MSG_WHISPER && prefix==RequestPrefix && receiver==p) Request(p,text); }
};

class Startup final : public WorldScript
{
public:
    Startup():WorldScript("forever_encyclopedia_startup"){}
    void OnWorldInitialized() override
    {
        if (!sConfigMgr->GetBoolDefault("ForeverEncyclopedia.Enable",false)) return;
        bool a=bool(CharacterDatabase.Query("SELECT COUNT(*) FROM forever_encyclopedia_discovery"));
        bool b=bool(CharacterDatabase.Query("SELECT COUNT(*) FROM forever_encyclopedia_account"));
        bool c=bool(CharacterDatabase.Query("SELECT COUNT(*) FROM forever_encyclopedia_character"));
        if (!a||!b||!c) { TC_LOG_ERROR("scripts","ForeverEncyclopedia schema missing; feature disabled"); return; }
        Ready=true; TC_LOG_INFO("scripts","ForeverEncyclopedia ready: technical triggers filtered from catalog");
    }
};
}

void AddSC_forever_encyclopedia(){ new ForeverEncyclopedia::Startup(); new ForeverEncyclopedia::Players(); }
