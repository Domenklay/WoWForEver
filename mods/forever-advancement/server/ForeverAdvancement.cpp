#include "ScriptMgr.h"
#include "Chat.h"
#include "ChatCommand.h"
#include "ChatPackets.h"
#include "Config.h"
#include "DB2Stores.h"
#include "DatabaseEnv.h"
#include "Log.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "RestMgr.h"
#include "Spell.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "SpellPackets.h"
#include "SpellScript.h"
#include "WorldSession.h"
#include "Util.h"
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
struct TalentDefinition { uint32 entry,owner,spell,rank,level,cost,investment,tab; };
struct Pool { int32 current=0,maximum=0;double fraction=0; };
struct State
{
    std::set<uint32> learned;
    std::map<uint32,uint32> talents;
    std::set<uint32> ownedAuras;
    std::set<uint32> bookSpells;
    bool syncing=false;
    std::map<Powers,Pool> pools;
    Clock::time_point updated=Clock::now(),request{};
};
static std::recursive_mutex Mutex;
static std::map<uint64,State> States;
static std::map<uint32,std::vector<Definition>> Catalog;
static std::map<uint32,std::vector<TalentDefinition>> TalentCatalog;
static uint32 TalentCap=71;
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
static void SyncTalents(Player* p,State& s);
static void SyncSpellbook(Player* p,State& s);
static State& Get(Player* p)
{
    uint64 guid=p->GetGUID().GetCounter();auto [it,inserted]=States.try_emplace(guid);auto& s=it->second;
    if(inserted)
    {
        if(auto rows=CharacterDatabase.PQuery("SELECT entry_id FROM forever_advancement_spells WHERE guid={}",guid))
            do { s.learned.insert(rows->Fetch()[0].GetUInt32()); } while(rows->NextRow());
        if(auto rows=CharacterDatabase.PQuery("SELECT entry_id,rank_value FROM forever_advancement_talents WHERE guid={}",guid))
            do { auto f=rows->Fetch();s.talents[f[0].GetUInt32()]=f[1].GetUInt32(); } while(rows->NextRow());
        if(auto rows=CharacterDatabase.PQuery("SELECT power_type,current_value FROM forever_advancement_resources WHERE guid={}",guid))
            do { auto f=rows->Fetch();uint32 id=f[0].GetUInt32();if(id==0||id==1||id==3) s.pools[Powers(id)]={int32(std::min<uint32>(f[1].GetUInt32(),1000000)),1000000,0}; } while(rows->NextRow());
    }
    SyncTalents(p,s);SyncSpellbook(p,s);Refresh(p,s);return s;
}
static void Save(Player* p,State const& s)
{
    auto tx=CharacterDatabase.BeginTransaction();uint64 guid=p->GetGUID().GetCounter();
    tx->PAppend("DELETE FROM forever_advancement_spells WHERE guid={}",guid);
    for(auto id:s.learned) tx->PAppend("INSERT INTO forever_advancement_spells VALUES ({},{})",guid,id);
    tx->PAppend("DELETE FROM forever_advancement_talents WHERE guid={}",guid);
    for(auto const& [id,rank]:s.talents) if(rank) tx->PAppend("INSERT INTO forever_advancement_talents VALUES ({},{},{})",guid,id,rank);
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
static bool TemporaryBookSpell(Player* p,uint32 spell)
{
    auto const& spells=p->GetSpellMap();auto it=spells.find(spell);
    return it!=spells.end()&&it->second.state==PLAYERSPELL_TEMPORARY;
}
static void SyncSpellbook(Player* p,State& s)
{
    std::set<uint32> desired;
    for(auto entry:s.learned)
        if(auto d=Best(entry,p->GetLevel());d&&d->owner!=p->GetClass()) desired.insert(d->spell);
    std::vector<uint32> removed,added;std::set<uint32> release;
    for(auto spell:s.bookSpells)
        if(!desired.count(spell)||!TemporaryBookSpell(p,spell))
        {
            p->RemoveTemporarySpell(spell);if(!p->HasSpell(spell)) removed.push_back(spell);release.insert(spell);
        }
    for(auto spell:release) s.bookSpells.erase(spell);
    for(auto spell:desired)
        if(!p->HasSpell(spell))
        {
            // Temporary native entries never auto-learn class skills or dependent spells.
            // The authoritative purchase is persisted in our own table and restored on login.
            p->AddTemporarySpell(spell);
            if(p->HasSpell(spell)) { s.bookSpells.insert(spell);added.push_back(spell); }
        }
    if(p->IsInWorld())
    {
        if(!removed.empty())
        {
            WorldPackets::Spells::UnlearnedSpells packet;packet.SpellID=removed;p->SendDirectMessage(packet.Write());
        }
        if(!added.empty())
        {
            WorldPackets::Spells::LearnedSpells packet;
            for(auto spell:added) { auto& entry=packet.ClientLearnedSpellData.emplace_back();entry.SpellID=spell;entry.Favorite=false; }
            packet.SuppressMessaging=true;p->SendDirectMessage(packet.Write());
        }
    }
}
static uint32 BookEntry(Player* p,State const& s,uint32 spell)
{
    if(!s.bookSpells.count(spell)||!TemporaryBookSpell(p,spell)) return 0;
    for(auto entry:s.learned) if(auto d=Best(entry,p->GetLevel());d&&d->spell==spell&&d->owner!=p->GetClass()) return entry;
    return 0;
}
static uint32 Used(State const& s)
{
    uint32 n=0;for(auto id:s.learned) { auto it=Catalog.find(id);if(it!=Catalog.end()) ++n; }return n;
}
static int32 Cost(Player* p,SpellInfo const* info,Powers power)
{
    auto cost=info->CalcPowerCost(power,false,p,info->GetSchoolMask());
    if(power==POWER_MANA&&!Native(p,power))
        for(auto source:info->PowerCosts)
            if(source&&source->PowerType==POWER_MANA&&source->PowerCostPct>0)
            {
                uint32 base=0;sObjectMgr->GetPlayerClassLevelInfo(CLASS_PRIEST,p->GetLevel(),base);
                auto adjusted=*source;
                adjusted.ManaCost+=int32(double(base)*adjusted.PowerCostPct/100.0);
                adjusted.PowerCostPct=0;
                cost=info->CalcPowerCost(&adjusted,false,p,info->GetSchoolMask());
                break;
            }
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
            cost->OptionalCost||cost->OptionalCostPct||cost->RequiredAuraSpellID||
            (cost->PowerCostPct&&(cost->PowerType!=POWER_MANA||cost->PowerCostPct<0))||
            cost->PowerCostMaxPct||cost->ManaCost<0||cost->ManaCostPerLevel<0) return false;
    }
    return true;
}
static TalentDefinition const* Talent(uint32 id,uint32 rank)
{
    auto it=TalentCatalog.find(id);
    return it!=TalentCatalog.end()&&rank>0&&rank<=it->second.size()?&it->second[rank-1]:nullptr;
}
static uint32 TalentBudget(Player* p) { return p->GetLevel()<10?0:std::min<uint32>(TalentCap,p->GetLevel()-9); }
static uint32 TalentSpent(State const& s)
{
    uint32 spent=0;
    for(auto const& [id,rank]:s.talents) if(auto d=Talent(id,rank)) spent+=rank*d->cost;
    return spent;
}
static uint32 LowerTierSpent(State const& s,TalentDefinition const& node)
{
    uint32 spent=0;
    for(auto const& [id,rank]:s.talents)
        if(auto d=Talent(id,rank);d&&d->owner==node.owner&&d->tab==node.tab&&d->investment<node.investment) spent+=rank*d->cost;
    return spent;
}
static bool TalentBuildValid(Player* p,State const& s)
{
    if(TalentSpent(s)>TalentBudget(p)) return false;
    for(auto const& [id,rank]:s.talents)
        if(auto d=Talent(id,rank);d&&(d->owner==p->GetClass()||d->level>p->GetLevel()||LowerTierSpent(s,*d)<d->investment)) return false;
    return true;
}
static void SyncTalents(Player* p,State& s)
{
    if(s.syncing) return;
    s.syncing=true;
    std::set<uint32> desired;
    if(TalentBuildValid(p,s))
        for(auto const& [id,rank]:s.talents) if(auto d=Talent(id,rank)) desired.insert(d->spell);
    for(auto it=s.ownedAuras.begin();it!=s.ownedAuras.end();)
        if(!desired.count(*it)) { p->RemoveAurasDueToSpell(*it,p->GetGUID());it=s.ownedAuras.erase(it); }
        else ++it;
    if(p->IsAlive()) for(auto spell:desired)
        if(!p->HasAura(spell)&&!p->HasSpell(spell)&&p->AddAura(spell,p)) s.ownedAuras.insert(spell);
    s.syncing=false;
}
static bool CompatibleTalent(SpellInfo const* info)
{
    if(!info->IsPassive()||!info->IsPositive()) return false;
    bool aura=false;
    for(auto const& effect:info->GetEffects())
    {
        if(!effect.IsEffect()) continue;
        if(effect.Effect!=SPELL_EFFECT_APPLY_AURA) return false;
        switch(effect.ApplyAuraName)
        {
            case SPELL_AURA_MOD_STAT: case SPELL_AURA_MOD_TOTAL_STAT_PERCENTAGE:
            case SPELL_AURA_MOD_INCREASE_HEALTH: case SPELL_AURA_MOD_INCREASE_HEALTH_PERCENT:
            case SPELL_AURA_MOD_DAMAGE_DONE: case SPELL_AURA_MOD_DAMAGE_PERCENT_DONE:
            case SPELL_AURA_MOD_HEALING_DONE: case SPELL_AURA_MOD_HEALING_DONE_PERCENT:
            case SPELL_AURA_ADD_FLAT_MODIFIER: case SPELL_AURA_ADD_PCT_MODIFIER:
            case SPELL_AURA_ADD_FLAT_MODIFIER_BY_SPELL_LABEL: case SPELL_AURA_ADD_PCT_MODIFIER_BY_SPELL_LABEL:
            case SPELL_AURA_MOD_SPELL_CRIT_CHANCE: case SPELL_AURA_MOD_CRIT_PCT:
            case SPELL_AURA_MOD_DODGE_PERCENT: case SPELL_AURA_MOD_PARRY_PERCENT:
            case SPELL_AURA_MOD_BLOCK_PERCENT: case SPELL_AURA_MOD_RESISTANCE:
            case SPELL_AURA_MOD_RESISTANCE_PCT: case SPELL_AURA_MOD_CASTING_SPEED_NOT_STACK:
                aura=true;break;
            default:return false;
        }
    }
    return aura;
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
    Send(p,"PROTOCOL 2");
    Send(p,Trinity::StringFormat("STATE {} {} {} {}",p->GetClass(),p->GetLevel(),Used(s),Limit));
    for(auto power:PowersList)
        Send(p,Trinity::StringFormat("POWER {} {} {}",uint32(power),Available(p,s,power),Native(p,power)?p->GetMaxPower(power)/Scale(power):s.pools.at(power).maximum));
    double regen=std::max(0.0,double(p->GetStat(STAT_SPIRIT)))*0.2;
    Send(p,Trinity::StringFormat("REGEN {} {}",regen,regen*0.3));
    if(includeCatalog) Send(p,"CATALOG");
    if(includeCatalog) for(auto const& [id,definitions]:Catalog)
    {
        auto const* d=Best(id,p->GetLevel());if(!d) d=&definitions.front();
        Send(p,Trinity::StringFormat("ENTRY {} {} {} {} {}",id,d->spell,d->level,s.learned.count(id)?1:0,d->owner));
    }
    if(!includeCatalog) for(auto id:s.learned)
        if(auto d=Best(id,p->GetLevel())) Send(p,Trinity::StringFormat("ENTRY {} {} {} 1 {}",id,d->spell,d->level,d->owner));
    if(includeCatalog) for(auto const& [id,ranks]:TalentCatalog)
    {
        auto const& d=ranks.front();
        Send(p,Trinity::StringFormat("TENTRY {} {} {} {} {} {}",id,ranks.size(),d.level,d.cost,d.investment,d.owner));
    }
    uint32 spent=TalentSpent(s),budget=TalentBudget(p);
    Send(p,Trinity::StringFormat("TPOINTS {} {} {}",spent<budget?budget-spent:0,spent,budget));
    for(auto const& [id,rank]:s.talents) Send(p,Trinity::StringFormat("TALENT {} {}",id,rank));
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
    bool argument=command=="learn"||command=="unlearn"||command=="cast"||command=="talent"||command=="untalent";
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
    if(command=="talent"||command=="untalent")
    {
        uint32 rank=s.talents.count(arg)?s.talents.at(arg):0;
        uint32 next=command=="talent"?rank+1:rank?rank-1:0;
        if(next==rank||!Talent(arg,command=="talent"?next:rank)) { Error(p,"talent_unavailable");return; }
        auto candidate=s;candidate.talents[arg]=next;if(!next) candidate.talents.erase(arg);
        if(!TalentBuildValid(p,candidate)) { Error(p,"talent_requirements");return; }
        s.talents=std::move(candidate.talents);SyncTalents(p,s);Refresh(p,s);
    }
    else if(command=="learn")
    {
        auto d=Best(arg,p->GetLevel());if(!d||d->owner==p->GetClass()) { Error(p,"incompatible_or_level");return; }
        if(s.learned.count(arg)) { Error(p,"already_learned");return; }
        if(Used(s)>=Limit) { Error(p,"ability_limit");return; }
        s.learned.insert(arg);
    }
    else if(command=="unlearn") s.learned.erase(arg);
    else { Error(p,"invalid_request");return; }
    SyncSpellbook(p,s);Save(p,s);Snapshot(p,s);
}
class Players final:public PlayerScript
{
public:
    Players():PlayerScript("forever_advancement_players") { }
    void OnLogin(Player* p,bool) override { if(Ready&&SupportedClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> lock(Mutex);Get(p); } }
    void OnSave(Player* p) override { if(Ready&&SupportedClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> lock(Mutex);Save(p,Get(p)); } }
    void OnLogout(Player* p) override { std::lock_guard<std::recursive_mutex> lock(Mutex);auto it=States.find(p->GetGUID().GetCounter());if(it!=States.end()) { Save(p,it->second);for(auto spell:it->second.ownedAuras) p->RemoveAurasDueToSpell(spell,p->GetGUID());States.erase(it); } }
    void OnDelete(ObjectGuid guid,uint32) override
    {
        if(!Ready) return;std::lock_guard<std::recursive_mutex> lock(Mutex);States.erase(guid.GetCounter());auto tx=CharacterDatabase.BeginTransaction();
        for(char const* table:{"forever_advancement_spells","forever_advancement_resources","forever_advancement_talents"}) tx->Append(Trinity::StringFormat("DELETE FROM {} WHERE guid={}",table,guid.GetCounter()).c_str());
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
static std::wstring NameKey(char const* name)
{
    std::wstring key;
    if(!name||!Utf8toWStr(name,key)) return {};
    wstrToLower(key);return key;
}
static bool SourceNameMatches(SpellInfo const* info,std::array<char const*,9> const& names)
{
    if(!info->SpellName) return false;
    for(auto native:info->SpellName->Str)
    {
        auto key=NameKey(native);if(key.empty()) continue;
        for(auto source:names) if(key==NameKey(source)) return true;
    }
    return false;
}
static std::string NativeNames(SpellInfo const* info)
{
    if(!info||!info->SpellName) return "<missing>";
    std::string out;
    for(uint32 locale=0;locale<TOTAL_LOCALES;++locale)
        if(auto name=info->SpellName->Str[locale];name&&name[0])
            out+=std::to_string(locale)+":"+name+";";
    return out.empty()?"<empty all locales>":out;
}
// A classic ID can be absent or reused in Forever. Never trust an ID alone.
static uint32 ClassFamily(uint32 owner)
{
    switch(owner) { case 1:return 4;case 2:return 10;case 3:return 9;case 4:return 8;
        case 5:return 6;case 7:return 11;case 8:return 3;case 9:return 5;case 11:return 7;default:return 0; }
}
using NameIndex=std::map<std::wstring,std::vector<SpellInfo const*>>;
static SpellInfo const* ResolveSpell(uint32 source,uint32 owner,uint32 rank,std::array<char const*,9> const& names,NameIndex const& index)
{
    auto family=ClassFamily(owner);
    auto direct=sSpellMgr->GetSpellInfo(source,DIFFICULTY_NONE);
    if(direct&&direct->SpellFamilyName==family&&SourceNameMatches(direct,names)) return direct;
    std::set<uint32> candidates;
    for(auto name:names)
    {
        if(!name||!name[0]) continue;
        auto it=index.find(NameKey(name));if(it==index.end()) continue;
        for(auto info:it->second)
            if(info->SpellFamilyName==family&&std::max<uint32>(1,sSpellMgr->GetSpellRank(info->Id))==rank)
                candidates.insert(info->Id);
    }
    // Multiple effects with the same name require an explicit reviewed mapping.
    return candidates.size()==1?sSpellMgr->GetSpellInfo(*candidates.begin(),DIFFICULTY_NONE):nullptr;
}
class Startup final:public WorldScript
{
public:
    Startup():WorldScript("forever_advancement_startup") { }
    void OnWorldInitialized() override
    {
        if(!sConfigMgr->GetBoolDefault("ForeverAdvancement.Enable",false)) return;
        TalentCap=std::clamp(sConfigMgr->GetIntDefault("ForeverAdvancement.MaxTalentEssence",71),0,1000);
        Limit=std::clamp(sConfigMgr->GetIntDefault("ForeverAdvancement.MaxAbilities",8),1,100);
        for(auto table:{"forever_advancement_spells","forever_advancement_resources","forever_advancement_talents"})
            if(!CharacterDatabase.Query(Trinity::StringFormat("SELECT COUNT(*) FROM {}",table).c_str())) { TC_LOG_ERROR("scripts","ForeverAdvancement schema missing: {}",table);return; }
        uint32 script=sObjectMgr->GetScriptId("spell_forever_advancement");std::set<uint32> claimed;
        if(!script) { TC_LOG_ERROR("scripts","ForeverAdvancement script registration missing");return; }
        NameIndex names;uint32 remapped=0;std::set<uint32> examples;
        std::array<uint32,TOTAL_LOCALES> localeCounts={};
        for(auto entry:sSpellNameStore)
            if(auto info=sSpellMgr->GetSpellInfo(entry->ID,DIFFICULTY_NONE))
                for(uint32 locale=0;locale<TOTAL_LOCALES;++locale)
                    if(auto name=entry->Name.Str[locale];name&&name[0]) { names[NameKey(name)].push_back(info);++localeCounts[locale]; }
        for(uint32 locale=0;locale<TOTAL_LOCALES;++locale)
            if(localeCounts[locale]) TC_LOG_INFO("scripts","ForeverAdvancement catalog locale: {} named spells={}",locale,localeCounts[locale]);
        std::array<uint32,5> rejected={};
        for(auto const& row:AscensionSourceEntries)
        {
            auto info=ResolveSpell(row.spell,row.owner,row.rank,row.names,names);
            if(!info&&examples.size()<12&&!examples.count(row.id))
            {
                examples.insert(row.id);auto native=sSpellMgr->GetSpellInfo(row.spell,DIFFICULTY_NONE);
                TC_LOG_INFO("scripts","ForeverAdvancement unresolved: entry={} source={} expected={} sourceRU={} native={} family={} expectedFamily={}",
                    row.id,row.spell,row.names[0],row.names[6],NativeNames(native),native?native->SpellFamilyName:0,ClassFamily(row.owner));
            }
            if(!info) { ++rejected[0];continue; }
            if(!CompatibleCosts(info)) { ++rejected[1];continue; }
            if(info->IsPassive()) { ++rejected[2];continue; }
            if(!SourceNameMatches(info,row.names)) { ++rejected[3];continue; }
            sObjectMgr->RegisterForeverAdvancementBinding(info->Id,script);
            bool bound=false;auto bounds=sObjectMgr->GetSpellScriptsBounds(info->Id);
            for(auto it=bounds.first;it!=bounds.second;++it) if(it->second.first==script&&it->second.second) bound=true;
            if(!bound) { ++rejected[4];continue; }
            if(claimed.count(info->Id)) continue;
            if(info->Id!=row.spell) ++remapped;
            Catalog[row.id].push_back({row.id,row.owner,info->Id,std::max(row.level,info->SpellLevel)});claimed.insert(info->Id);
        }
        std::set<uint32> talentSpells;
        for(auto const& row:AscensionTalentSourceEntries)
        {
            auto info=ResolveSpell(row.spell,row.owner,row.rank,row.names,names);
            if(!info||!CompatibleTalent(info)||!SourceNameMatches(info,row.names)) continue;
            auto it=TalentCatalog.find(row.id);uint32 expected=it==TalentCatalog.end()?1:it->second.size()+1;
            if(row.rank!=expected||talentSpells.count(info->Id)) continue;
            TalentCatalog[row.id].push_back({row.id,row.owner,info->Id,row.rank,std::max(row.level,info->SpellLevel),row.cost,row.investment,row.tab});
            talentSpells.insert(info->Id);
        }
        TC_LOG_INFO("scripts","ForeverAdvancement catalog rows rejected: missing={}, costs={}, passive={}, names={}, binding={}",rejected[0],rejected[1],rejected[2],rejected[3],rejected[4]);
        TC_LOG_INFO("scripts","ForeverAdvancement catalog remapped: {} abilities by case-folded name, class family and native rank",remapped);
        if(Catalog.empty()) { TC_LOG_ERROR("scripts","ForeverAdvancement compatible catalog empty; disabled");return; }
        Ready=true;TC_LOG_INFO("scripts","ForeverAdvancement ready: {} compatible Ascension abilities; {} passive talents; {} slots",Catalog.size(),TalentCatalog.size(),Limit);
    }
};
}
class spell_forever_advancement final:public SpellScript
{
    PrepareSpellScript(spell_forever_advancement);
    bool Load() override
    {
        using namespace ForeverAdvancement;
        auto p=GetCaster()->ToPlayer();if(!p) return false;
        auto spell=GetSpell();
        if(!Ready||spell->m_customArg.has_value()||spell->IsTriggered()||spell->m_CastItem) return true;
        std::lock_guard<std::recursive_mutex> lock(Mutex);auto& s=Get(p);
        if(auto entry=BookEntry(p,s,GetSpellInfo()->Id))
        {
            spell->m_customArg=CastTag{entry};spell->IgnorePowerCostForForeverAdvancement();
        }
        return true;
    }
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
