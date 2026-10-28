#include "ScriptMgr.h"
#include "Chat.h"
#include "ChatCommand.h"
#include "ChatPackets.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "Log.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "RestMgr.h"
#include "Spell.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "SpellScript.h"
#include "WorldSession.h"
#include "AscensionCatalog.h"
#include <array>
#include <chrono>
#include <map>
#include <mutex>
#include <set>
#include <sstream>

namespace ForeverAdvancement
{
using Clock=std::chrono::steady_clock;
constexpr std::array<Powers,3> PowersList={POWER_MANA,POWER_RAGE,POWER_ENERGY};
struct Definition { uint32 entry,owner,spell,level; };
struct CastTag { uint32 entry; };
struct Pool { int32 current=0,maximum=0;double fraction=0; };
struct State
{
    std::set<uint32> learned;
    std::map<Powers,Pool> pools;
    Clock::time_point updated=Clock::now(),request{};
};
static std::recursive_mutex Mutex;
static std::map<uint64,State> States;
static std::map<uint32,std::vector<Definition>> Catalog;
static bool Ready=false;
static uint32 Limit=8;

static bool SupportedClass(uint32 id) { return id==1||id==2||id==3||id==4||id==5||id==7||id==8||id==9||id==11; }
static bool Native(Player* p,Powers power) { return p->GetPowerIndex(power)<MAX_POWERS_PER_CLASS&&p->GetMaxPower(power)>0; }
static int32 Scale(Powers power) { return power==POWER_RAGE?10:1; }
static void Send(Player* p,std::string const& text)
{
    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER,LANG_ADDON,p,p,text,0,"",LOCALE_enUS,"FAR1");
    p->GetSession()->SendPacket(packet.Write());
}
static void Error(Player* p,char const* text) { Send(p,std::string("ERROR ")+text); }
static void Refresh(Player* p,State& state)
{
    auto now=Clock::now();double seconds=std::clamp(std::chrono::duration<double>(now-state.updated).count(),0.0,60.0);state.updated=now;
    for(auto power:PowersList)
    {
        if(Native(p,power)) { state.pools.erase(power);continue; }
        int32 maximum=100;
        if(power==POWER_MANA)
        {
            uint32 base=0;sObjectMgr->GetPlayerClassLevelInfo(CLASS_PRIEST,p->GetLevel(),base);
            maximum=int32(std::clamp(double(base)+p->GetManaBonusFromIntellect(),1.0,1000000.0));
        }
        auto [it,inserted]=state.pools.try_emplace(power,Pool{power==POWER_RAGE?0:maximum,maximum,0});
        auto& pool=it->second;pool.maximum=maximum;pool.current=std::clamp(pool.current,0,maximum);
        if(!p->IsAlive()) continue;
        double rate=power==POWER_ENERGY?10.0:power==POWER_MANA?std::max(0.0,double(p->GetStat(STAT_SPIRIT)))*0.2*(p->IsInCombat()?0.3:1.0):p->IsInCombat()?0.0:-3.0;
        double change=rate*seconds+pool.fraction;int32 whole=int32(change);pool.fraction=change-whole;
        pool.current=std::clamp(pool.current+whole,0,maximum);
        if(pool.current==0||pool.current==maximum) pool.fraction=0;
    }
}
static State& Get(Player* p)
{
    uint64 guid=p->GetGUID().GetCounter();auto [it,inserted]=States.try_emplace(guid);auto& s=it->second;
    if(inserted)
    {
        if(auto rows=CharacterDatabase.PQuery("SELECT entry_id FROM forever_advancement_spells WHERE guid={}",guid))
            do { s.learned.insert(rows->Fetch()[0].GetUInt32()); } while(rows->NextRow());
        if(auto rows=CharacterDatabase.PQuery("SELECT power_type,current_value FROM forever_advancement_resources WHERE guid={}",guid))
            do { auto f=rows->Fetch();uint32 id=f[0].GetUInt32();if(id==0||id==1||id==3) s.pools[Powers(id)]={int32(std::min<uint32>(f[1].GetUInt32(),1000000)),1000000,0}; } while(rows->NextRow());
    }
    Refresh(p,s);return s;
}
static void Save(Player* p,State const& s)
{
    auto tx=CharacterDatabase.BeginTransaction();uint64 guid=p->GetGUID().GetCounter();
    tx->PAppend("DELETE FROM forever_advancement_spells WHERE guid={}",guid);
    for(auto id:s.learned) tx->PAppend("INSERT INTO forever_advancement_spells VALUES ({},{})",guid,id);
    tx->PAppend("DELETE FROM forever_advancement_resources WHERE guid={}",guid);
    for(auto const& [power,pool]:s.pools) tx->PAppend("INSERT INTO forever_advancement_resources VALUES ({},{},{})",guid,uint32(power),pool.current);
    CharacterDatabase.DirectCommitTransaction(tx);
}
static int32 Available(Player* p,State const& s,Powers power)
{ return Native(p,power)?p->GetPower(power)/Scale(power):s.pools.at(power).current; }
static Definition const* Best(uint32 entry,uint32 level)
{
    auto it=Catalog.find(entry);if(it==Catalog.end()) return nullptr;
    Definition const* best=nullptr;
    for(auto const& d:it->second) if(d.level<=level&&(!best||d.level>best->level)) best=&d;
    return best;
}
static uint32 Used(State const& s)
{
    uint32 n=0;for(auto id:s.learned) { auto it=Catalog.find(id);if(it!=Catalog.end()) ++n; }return n;
}
static int32 Cost(Player* p,SpellInfo const* info,Powers power)
{
    auto cost=info->CalcPowerCost(power,false,p,info->GetSchoolMask());
    return cost?std::max(0,(cost->Amount+Scale(power)-1)/Scale(power)):0;
}
static bool CompatibleCosts(SpellInfo const* info)
{
    if(info->HasAttribute(SPELL_ATTR1_USE_ALL_MANA)) return false;
    std::set<int> seen;
    for(auto cost:info->PowerCosts)
    {
        if(!cost) continue;
        if(std::find(PowersList.begin(),PowersList.end(),Powers(cost->PowerType))==PowersList.end()) return false;
        if(!seen.insert(cost->PowerType).second||cost->ManaPerSecond||cost->PowerPctPerSecond||
            cost->OptionalCost||cost->OptionalCostPct||cost->RequiredAuraSpellID||cost->PowerCostPct||
            cost->PowerCostMaxPct||cost->ManaCost<0||cost->ManaCostPerLevel<0) return false;
    }
    return true;
}
static bool CanCast(Player* p,State const& s,Definition const& d)
{
    if(d.owner==p->GetClass()||!s.learned.count(d.entry)||d.level>p->GetLevel()||!p->IsAlive()) return false;
    auto info=sSpellMgr->GetSpellInfo(d.spell,DIFFICULTY_NONE);if(!info||!CompatibleCosts(info)) return false;
    for(auto power:PowersList) if(Available(p,s,power)<Cost(p,info,power)) return false;
    return true;
}
static void Snapshot(Player* p,State& s,bool includeCatalog=false)
{
    Send(p,Trinity::StringFormat("STATE {} {} {} {}",p->GetClass(),p->GetLevel(),Used(s),Limit));
    for(auto power:PowersList)
        Send(p,Trinity::StringFormat("POWER {} {} {}",uint32(power),Available(p,s,power),Native(p,power)?p->GetMaxPower(power)/Scale(power):s.pools.at(power).maximum));
    if(includeCatalog) Send(p,"CATALOG");
    if(includeCatalog) for(auto const& [id,definitions]:Catalog)
    {
        auto const* d=Best(id,p->GetLevel());if(!d) d=&definitions.front();
        Send(p,Trinity::StringFormat("ENTRY {} {} {} {} {}",id,d->spell,d->level,s.learned.count(id)?1:0,d->owner));
    }
    for(auto id:s.learned) Send(p,Trinity::StringFormat("LEARNED {}",id));
    Send(p,"END");
}
static void Request(Player* p,std::string const& payload)
{
    std::lock_guard<std::recursive_mutex> lock(Mutex);
    if(!Ready||!SupportedClass(p->GetClass())) { Error(p,"disabled");return; }
    if(payload.size()>96) return;
    auto& s=Get(p);auto now=Clock::now();if(now-s.request<std::chrono::milliseconds(150)) return;s.request=now;
    std::istringstream input(payload);std::string command,extra;uint32 arg=0;input>>command;
    bool argument=command=="learn"||command=="unlearn"||command=="cast";
    if((argument&&!(input>>arg))||(input>>extra)) { Error(p,"invalid_request");return; }
    if(command=="status") { Snapshot(p,s,true);return; }
    if(command=="poll") { Snapshot(p,s);return; }
    if(command=="cast")
    {
        auto d=Best(arg,p->GetLevel());if(!d||!CanCast(p,s,*d)) { Error(p,"unavailable_or_power");return; }
        auto info=sSpellMgr->GetSpellInfo(d->spell,DIFFICULTY_NONE);Unit* target=p->GetSelectedUnit();if(!target&&info->IsPositive()) target=p;
        if(!target) { Error(p,"select_target");return; }
        auto result=p->CastSpell(target,d->spell,CastSpellExtraArgs(TRIGGERED_IGNORE_POWER_COST).SetCustomArg(CastTag{arg}));
        if(result!=SPELL_CAST_OK) Send(p,Trinity::StringFormat("ERROR native_cast_{}",uint32(result)));
        return;
    }
    if(p->IsInCombat()||!p->IsAlive()||p->HasUnitState(UNIT_STATE_CASTING)) { Error(p,"cannot_edit_now");return; }
    if(command=="learn")
    {
        auto d=Best(arg,p->GetLevel());if(!d||d->owner==p->GetClass()) { Error(p,"incompatible_or_level");return; }
        if(s.learned.count(arg)) { Error(p,"already_learned");return; }
        if(Used(s)>=Limit) { Error(p,"ability_limit");return; }
        s.learned.insert(arg);
    }
    else if(command=="unlearn") s.learned.erase(arg);
    else { Error(p,"invalid_request");return; }
    Save(p,s);Snapshot(p,s);
}
class Players final:public PlayerScript
{
public:
    Players():PlayerScript("forever_advancement_players") { }
    void OnLogin(Player* p,bool) override { if(Ready&&SupportedClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> lock(Mutex);Get(p); } }
    void OnSave(Player* p) override { if(Ready&&SupportedClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> lock(Mutex);Save(p,Get(p)); } }
    void OnLogout(Player* p) override { std::lock_guard<std::recursive_mutex> lock(Mutex);auto it=States.find(p->GetGUID().GetCounter());if(it!=States.end()) { Save(p,it->second);States.erase(it); } }
    void OnDelete(ObjectGuid guid,uint32) override
    {
        if(!Ready) return;std::lock_guard<std::recursive_mutex> lock(Mutex);States.erase(guid.GetCounter());auto tx=CharacterDatabase.BeginTransaction();
        for(char const* table:{"forever_advancement_spells","forever_advancement_resources"}) tx->Append(Trinity::StringFormat("DELETE FROM {} WHERE guid={}",table,guid.GetCounter()).c_str());
        CharacterDatabase.DirectCommitTransaction(tx);
    }
    void OnAddonMessageSent(Player* p,uint32 type,std::string const& prefix,std::string const& text,Player* receiver) override
    { if(type==CHAT_MSG_WHISPER&&prefix=="FAC1"&&receiver==p) Request(p,text); }
};
class Damage final:public UnitScript
{
public:
    Damage():UnitScript("forever_advancement_resources") { }
    void OnDamage(Unit* attacker,Unit* victim,uint32& damage) override
    {
        if(!Ready||!damage) return;std::lock_guard<std::recursive_mutex> lock(Mutex);
        auto grant=[](Unit* unit) { auto p=unit?unit->ToPlayer():nullptr;if(!p||!SupportedClass(p->GetClass())||p->GetPowerType()==POWER_RAGE) return;
            auto& s=Get(p);if(Native(p,POWER_RAGE)) p->ModifyPower(POWER_RAGE,60);else s.pools[POWER_RAGE].current=std::min(s.pools[POWER_RAGE].maximum,s.pools[POWER_RAGE].current+6); };
        grant(attacker);if(victim!=attacker) grant(victim);
    }
};
class Startup final:public WorldScript
{
public:
    Startup():WorldScript("forever_advancement_startup") { }
    void OnWorldInitialized() override
    {
        if(!sConfigMgr->GetBoolDefault("ForeverAdvancement.Enable",false)) return;
        Limit=std::clamp(sConfigMgr->GetIntDefault("ForeverAdvancement.MaxAbilities",8),1,100);
        for(auto table:{"forever_advancement_spells","forever_advancement_resources"})
            if(!CharacterDatabase.Query(Trinity::StringFormat("SELECT COUNT(*) FROM {}",table).c_str())) { TC_LOG_ERROR("scripts","ForeverAdvancement schema missing: {}",table);return; }
        uint32 script=sObjectMgr->GetScriptId("spell_forever_advancement");std::set<uint32> claimed;
        for(auto const& row:AscensionSourceEntries)
        {
            auto info=sSpellMgr->GetSpellInfo(row.spell,DIFFICULTY_NONE);
            if(!info||!CompatibleCosts(info)||info->IsPassive()||!info->SpellName||!info->SpellName->Str[LOCALE_enUS]||std::string(info->SpellName->Str[LOCALE_enUS])!=row.name) continue;
            bool bound=false;auto bounds=sObjectMgr->GetSpellScriptsBounds(row.spell);
            for(auto it=bounds.first;it!=bounds.second;++it) if(it->second.first==script&&it->second.second) bound=true;
            if(!bound||claimed.count(row.spell)) continue;
            Catalog[row.id].push_back({row.id,row.owner,row.spell,std::max(row.level,info->SpellLevel)});claimed.insert(row.spell);
        }
        if(Catalog.empty()) { TC_LOG_ERROR("scripts","ForeverAdvancement compatible catalog empty; disabled");return; }
        Ready=true;TC_LOG_INFO("scripts","ForeverAdvancement ready: {} compatible Ascension abilities; {} slots",Catalog.size(),Limit);
    }
};
}
class spell_forever_advancement final:public SpellScript
{
    PrepareSpellScript(spell_forever_advancement);
    bool Load() override { return GetCaster()->ToPlayer()!=nullptr; }
    SpellCastResult Check()
    {
        using namespace ForeverAdvancement;auto tag=std::any_cast<CastTag>(&GetSpell()->m_customArg);if(!tag) return SPELL_CAST_OK;
        std::lock_guard<std::recursive_mutex> lock(Mutex);auto p=GetCaster()->ToPlayer();auto& s=Get(p);auto d=Best(tag->entry,p->GetLevel());
        return d&&d->spell==GetSpellInfo()->Id&&CanCast(p,s,*d)?SPELL_CAST_OK:SPELL_FAILED_NO_POWER;
    }
    void Pay()
    {
        using namespace ForeverAdvancement;auto tag=std::any_cast<CastTag>(&GetSpell()->m_customArg);if(!tag) return;
        std::lock_guard<std::recursive_mutex> lock(Mutex);auto p=GetCaster()->ToPlayer();auto& s=Get(p);auto d=Best(tag->entry,p->GetLevel());
        if(!d||d->spell!=GetSpellInfo()->Id||!CanCast(p,s,*d)) { FinishCast(SPELL_FAILED_NO_POWER);return; }
        for(auto power:PowersList) { int32 cost=Cost(p,GetSpellInfo(),power);if(Native(p,power)) p->ModifyPower(power,-cost*Scale(power));else s.pools[power].current-=cost; }
        Save(p,s);Snapshot(p,s);
    }
    void Register() override { OnCheckCast+=SpellCheckCastFn(spell_forever_advancement::Check);OnCast+=SpellCastFn(spell_forever_advancement::Pay); }
};
void AddSC_forever_advancement()
{
    new ForeverAdvancement::Startup();new ForeverAdvancement::Players();new ForeverAdvancement::Damage();RegisterSpellScript(spell_forever_advancement);
}
