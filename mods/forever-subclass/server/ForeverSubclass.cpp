/* Experimental adapter for the user-supplied SubclassSystem 0.2.0.
 * Adapter changes are GPL-2.0-or-later, matching TrinityCore.
 * Primary class, health, armor proficiency and native spells stay in the core.
 */
#include "ScriptMgr.h"
#include "SpellScript.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "Spell.h"
#include "Player.h"
#include "RestMgr.h"
#include "ObjectMgr.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
#include "World.h"
#include "Log.h"
#include "forever_subclass/SubclassSystem.hpp"
#include <atomic>
#include <chrono>
#include <cmath>
#include <map>
#include <mutex>
#include <sstream>
#include <limits>
#include <vector>

namespace ForeverSubclass
{
using Class = forever::ClassId;
using Clock = std::chrono::steady_clock;
constexpr char RequestPrefix[] = "FSC1";
constexpr char ResponsePrefix[] = "FSR1";
constexpr char SpellScriptName[] = "spell_forever_subclass";
struct RootSpell { uint32 id; uint8 owner; uint8 level; Powers power; int32 minimumCost; double intellectCoefficient; };
// Whitelisted class abilities only. Rank chains are discovered from the client's spell data at startup.
static RootSpell const Roots[] = {
    {6673,1,1,POWER_RAGE,10,0}, {635,2,1,POWER_MANA,35,0.714},
    {3044,3,6,POWER_MANA,25,0.15}, {1752,4,1,POWER_ENERGY,45,0},
    {585,5,1,POWER_MANA,20,0.714}, {2050,5,1,POWER_MANA,30,0.429},
    {2054,5,16,POWER_MANA,100,0.857}, {2060,5,40,POWER_MANA,200,0.857},
    {2061,5,20,POWER_MANA,100,0.429}, {403,7,1,POWER_MANA,30,0.714},
    {331,7,1,POWER_MANA,35,0.857}, {116,8,4,POWER_MANA,25,0.814},
    {2136,8,6,POWER_MANA,40,0.429}, {686,9,1,POWER_MANA,25,0.857},
    {5176,11,1,POWER_MANA,20,0.571}, {5185,11,1,POWER_MANA,35,1.0},
    // Druid feral resources. Native form/range/target checks are intentionally preserved.
    {6807,11,10,POWER_RAGE,15,0}, {1082,11,20,POWER_ENERGY,45,0}
};
struct Definition { RootSpell root; uint8 level; };
struct CastTag { }; // Server-only marker; clients cannot supply std::any cast arguments.
struct Entry {
    forever::CharacterState state;
    std::map<Powers,forever::ResourcePool> pools;
    Clock::time_point updated=Clock::now(), request{};
    double manaFraction=0,energyFraction=0;
    bool valid=true;
};
static std::recursive_mutex Mutex;
static std::map<uint64,Entry> Entries;
static std::map<uint32,Definition> Definitions;
static forever::SubclassSystem Policy;
static std::atomic<bool> Ready{false};

static bool ValidClass(uint32 id) { return id==1||id==2||id==3||id==4||id==5||id==7||id==8||id==9||id==11; }
static std::vector<Powers> ClassPowers(Class id) {
    if(id==Class::Warrior) return {POWER_RAGE};
    if(id==Class::Rogue) return {POWER_ENERGY};
    // A druid keeps mana while feral forms use their own rage/energy pools.
    if(id==Class::Druid) return {POWER_MANA,POWER_RAGE,POWER_ENERGY};
    return {POWER_MANA}; // Forever hunter currently uses mana in this prototype.
}
static bool HasClassPower(Class id,Powers power) {
    for(Powers candidate:ClassPowers(id)) if(candidate==power) return true;
    return false;
}
static uint32 RootId(uint32 spell) {
    auto i=Definitions.find(spell);
    return i==Definitions.end()?spell:i->second.root.id;
}
static bool Selected(Entry const& e,uint32 spell) {
    uint32 root=RootId(spell);
    return e.state.selectedSubclassSpells.count(root)||e.state.selectedSubclassSpells.count(spell);
}
static uint32 BestRank(Entry const& e,uint32 spellOrRoot) {
    uint32 root=RootId(spellOrRoot);
    if(!e.state.activeSubclass) return root;
    uint8 owner=uint8(*e.state.activeSubclass);
    auto progress=e.state.classes.find(*e.state.activeSubclass);
    if(progress==e.state.classes.end()) return root;
    uint8 level=progress->second.level;
    uint32 best=0;uint8 bestLevel=0;
    for(auto const& [id,d]:Definitions) if(d.root.id==root&&d.root.owner==owner&&d.level<=level)
        if(!best||d.level>bestLevel||(d.level==bestLevel&&id>best)) { best=id;bestLevel=d.level; }
    return best?best:root;
}
static void Send(Player* p,std::string const& text) {
    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER,LANG_ADDON,p,p,text,0,"",LOCALE_enUS,ResponsePrefix);
    p->GetSession()->SendPacket(packet.Write());
}
static void Error(Player* p,std::string const& text) { Send(p,"ERROR "+text); }
static bool Resting(Player* p) {
    return p->GetRestMgr().HasRestFlag(REST_FLAG_IN_TAVERN)||p->GetRestMgr().HasRestFlag(REST_FLAG_IN_CITY);
}
static void Save(Entry const& e) {
    if(!e.valid) return;
    auto const& c=e.state;
    CharacterDatabaseTransaction tx=CharacterDatabase.BeginTransaction();
    tx->PAppend("DELETE FROM forever_character_class_progress WHERE guid={}",c.guid);
    for(auto const& [id,progress]:c.classes)
        tx->PAppend("INSERT INTO forever_character_class_progress VALUES ({},{},{},{})",c.guid,uint8(id),progress.level,progress.xp);
    tx->PAppend("REPLACE INTO forever_character_subclass_state VALUES ({},{},{},{})",c.guid,uint8(c.primaryClass),
        c.activeSubclass?std::to_string(uint8(*c.activeSubclass)):"NULL",
        c.xpTargetClass?std::to_string(uint8(*c.xpTargetClass)):"NULL");
    tx->PAppend("DELETE FROM forever_character_subclass_spells WHERE guid={}",c.guid);
    for(auto id:c.selectedSubclassSpells)
        tx->PAppend("INSERT INTO forever_character_subclass_spells VALUES ({},{})",c.guid,id);
    tx->PAppend("DELETE FROM forever_character_subclass_resources WHERE guid={}",c.guid);
    for(auto const& [power,pool]:e.pools)
        tx->PAppend("INSERT INTO forever_character_subclass_resources VALUES ({},{},{})",c.guid,int(power),std::max(0,pool.current));
    CharacterDatabase.DirectCommitTransaction(tx);
}
static int32 PowerMaximum(Player* p,Entry const& e,Powers power) {
    if(power!=POWER_MANA) return 100;
    if(!e.state.activeSubclass) return 1;
    uint32 base=0;
    auto progress=e.state.classes.find(*e.state.activeSubclass);
    uint8 level=progress==e.state.classes.end()?1:progress->second.level;
    sObjectMgr->GetPlayerClassLevelInfo(uint8(*e.state.activeSubclass),level,base);
    return int32(std::clamp(double(base)+p->GetManaBonusFromIntellect(),1.0,1000000.0));
}
static void Refresh(Player* p,Entry& e) {
    auto& c=e.state;
    c.classes[c.primaryClass].level=p->GetLevel();
    c.classes[c.primaryClass].xp=p->GetXP();
    c.inCombat=p->IsInCombat();c.inRestArea=Resting(p);
    c.stats={int32(p->GetStat(STAT_STRENGTH)),int32(p->GetStat(STAT_AGILITY)),int32(p->GetStat(STAT_STAMINA)),
             int32(p->GetStat(STAT_INTELLECT)),int32(p->GetStat(STAT_SPIRIT)),0};
    auto now=Clock::now();double seconds=std::min(60.0,std::chrono::duration<double>(now-e.updated).count());e.updated=now;
    if(!c.activeSubclass) return;
    for(Powers power:ClassPowers(*c.activeSubclass)) {
        if(power==p->GetPowerType()) continue; // Share the native pool instead of regenerating it twice.
        int32 maximum=PowerMaximum(p,e,power);
        int32 initial=power==POWER_RAGE?0:maximum;
        auto [it,inserted]=e.pools.try_emplace(power,forever::ResourcePool{initial,maximum});
        auto& pool=it->second;pool.maximum=maximum;pool.current=std::clamp(pool.current,0,maximum);
        if(p->IsAlive()&&(power==POWER_MANA||power==POWER_ENERGY)) {
            double& fraction=power==POWER_MANA?e.manaFraction:e.energyFraction;
            double rate=power==POWER_MANA?std::max(0,c.stats.spirit)*0.20*(c.inCombat?0.30:1.0):10.0;
            double gained=fraction+rate*seconds;
            int32 whole=int32(std::min(double(maximum-pool.current),std::floor(gained)));
            fraction=pool.current+whole==maximum?0:gained-whole;
            pool.current=std::min(maximum,pool.current+whole);
        }
    }
}
static Entry& State(Player* p) {
    uint64 guid=p->GetGUID().GetCounter();auto it=Entries.find(guid);
    if(it!=Entries.end()) { Refresh(p,it->second);return it->second; }
    Entry e;e.state=Policy.createCharacter(guid,Class(p->GetClass()),p->GetLevel());
    if(auto result=CharacterDatabase.PQuery("SELECT primary_class_id,active_subclass_id,xp_target_class_id FROM forever_character_subclass_state WHERE guid={}",guid)) {
        Field* f=result->Fetch();
        if(f[0].GetUInt8()!=p->GetClass()) { e.valid=false;TC_LOG_ERROR("scripts","Subclass primary class mismatch for guid {}",guid); }
        else {
            if(auto rows=CharacterDatabase.PQuery("SELECT class_id,class_level,class_xp FROM forever_character_class_progress WHERE guid={}",guid)) do {
                Field* v=rows->Fetch();uint8 id=v[0].GetUInt8();
                if(ValidClass(id)&&id!=p->GetClass()) e.state.classes[Class(id)]={std::clamp<uint8>(v[1].GetUInt8(),1,80),v[2].GetUInt64()};
            } while(rows->NextRow());
            if(!f[1].IsNull()&&e.state.classes.count(Class(f[1].GetUInt8()))&&f[1].GetUInt8()!=p->GetClass()) e.state.activeSubclass=Class(f[1].GetUInt8());
            if(!f[2].IsNull()&&e.state.classes.count(Class(f[2].GetUInt8()))) e.state.xpTargetClass=Class(f[2].GetUInt8());
            if(auto rows=CharacterDatabase.PQuery("SELECT spell_id FROM forever_character_subclass_spells WHERE guid={}",guid)) do {
                uint32 saved=rows->Fetch()[0].GetUInt32();uint32 root=RootId(saved);
                std::string ignored;Policy.selectSubclassSpell(e.state,root,&ignored);
            } while(rows->NextRow());
            if(auto rows=CharacterDatabase.PQuery("SELECT power_type,current_value FROM forever_character_subclass_resources WHERE guid={}",guid)) do {
                Field* v=rows->Fetch();uint8 power=v[0].GetUInt8();
                if(power==POWER_MANA||power==POWER_RAGE||power==POWER_ENERGY) e.pools[Powers(power)]={int32(std::min<uint32>(v[1].GetUInt32(),1000000)),1000000};
            } while(rows->NextRow());
        }
    }
    auto& value=Entries.emplace(guid,std::move(e)).first->second;Refresh(p,value);return value;
}
static int32 Cost(Player* p,uint32 spell,Definition const& def) {
    int32 value=def.root.minimumCost;
    if(auto info=sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE))
        if(auto native=info->CalcPowerCost(def.root.power,false,p,info->GetSchoolMask())) {
            int32 amount=native->Amount;
            if(def.root.power==POWER_RAGE) amount=(amount+9)/10;
            value=std::max(value,amount);
        }
    return value;
}
static int32 Available(Player* p,Entry& e,Powers power) {
    if(power==p->GetPowerType()) return power==POWER_RAGE?p->GetPower(power)/10:p->GetPower(power);
    return e.pools.count(power)?e.pools[power].current:0;
}
static bool Allowed(Player* p,Entry& e,uint32 spell) {
    auto found=Definitions.find(spell);if(found==Definitions.end()||!e.valid) return false;
    auto const& d=found->second;
    return e.state.activeSubclass&&uint8(*e.state.activeSubclass)==d.root.owner&&Selected(e,spell)&&
        e.state.classes[*e.state.activeSubclass].level>=d.level&&HasClassPower(*e.state.activeSubclass,d.root.power)&&
        Available(p,e,d.root.power)>=Cost(p,spell,d);
}
static void Snapshot(Player* p,Entry& e) {
    auto const& c=e.state;
    uint32 efficiency=c.activeSubclass?uint32(std::lround(Policy.effectivenessFor(c,*c.activeSubclass)*10000.0)):0;
    Send(p,Trinity::StringFormat("STATE {} {} {} {} {} {}",uint8(c.primaryClass),c.activeSubclass?uint8(*c.activeSubclass):0,
        c.xpTargetClass?uint8(*c.xpTargetClass):uint8(c.primaryClass),Policy.usedSubclassSlots(c),Policy.config().subclassAbilitySlots,efficiency));
    for(auto const& [id,v]:c.classes) Send(p,Trinity::StringFormat("CLASS {} {} {} {}",uint8(id),v.level,v.xp,sObjectMgr->GetXPForLevel(v.level)));
    if(c.activeSubclass) {
        for(Powers power:ClassPowers(*c.activeSubclass)) {
            int32 max=power==p->GetPowerType()?p->GetMaxPower(power):PowerMaximum(p,e,power);
            if(power==POWER_RAGE&&power==p->GetPowerType()) max/=10;
            Send(p,Trinity::StringFormat("POWER {} {} {}",int(power),Available(p,e,power),max));
        }
        struct Choice { uint32 first=0,best=0;uint8 firstLevel=255,bestLevel=0; };
        std::map<uint32,Choice> roots;
        uint8 active=uint8(*c.activeSubclass);uint8 level=c.classes.at(*c.activeSubclass).level;
        for(auto const& [id,d]:Definitions) if(d.root.owner==active) {
            auto& choice=roots[d.root.id];
            if(!choice.first||d.level<choice.firstLevel||(d.level==choice.firstLevel&&id<choice.first)) { choice.first=id;choice.firstLevel=d.level; }
            if(d.level<=level&&(!choice.best||d.level>choice.bestLevel||(d.level==choice.bestLevel&&id>choice.best))) { choice.best=id;choice.bestLevel=d.level; }
        }
        for(auto const& [root,choice]:roots) {
            uint32 id=choice.best?choice.best:choice.first;auto const& d=Definitions.at(id);
            Send(p,Trinity::StringFormat("SPELL {} {} {} {} {} {}",id,root,d.level,Selected(e,root)?1:0,Cost(p,id,d),int(d.root.power)));
        }
        if(*c.activeSubclass==Class::Hunter)
            Send(p,Trinity::StringFormat("FEATURE HUNTER_PET 10 {}",level>=10?1:0));
        if(*c.activeSubclass==Class::Druid)
            Send(p,"FEATURE DRUID_MULTI_POWER 1 1");
    }
    Send(p,"END");
}
static void Request(Player* p,std::string const& text) {
    std::lock_guard<std::recursive_mutex> guard(Mutex);
    if(!Ready||!ValidClass(p->GetClass())) { Error(p,"module disabled or unsupported primary class");return; }
    auto& e=State(p);if(!e.valid) { Error(p,"saved primary class mismatch");return; }
    if(text.size()>96) return;
    auto now=Clock::now();if(now-e.request<std::chrono::milliseconds(150)) return;e.request=now;
    std::istringstream input(text);std::string command,extra;uint32 arg=0,debugLevel=0;input>>command;
    bool needsArg=command=="learn"||command=="active"||command=="xp"||command=="select"||command=="remove"||command=="cast";
    if(command=="debuglevel") {
        if(!(input>>arg>>debugLevel)||(input>>extra)) { Error(p,"invalid command");return; }
        if(p->GetSession()->GetSecurity()<SEC_GAMEMASTER) { Error(p,"GM only");return; }
    } else {
        if(needsArg&&(!(input>>arg)||(input>>extra))) { Error(p,"invalid command");return; }
        if(!needsArg&&(input>>extra)) { Error(p,"invalid command");return; }
    }
    if(command=="status") { Snapshot(p,e);return; }
    if(command=="cast") {
        arg=BestRank(e,arg);
        if(!p->IsAlive()||!Allowed(p,e,arg)) { Error(p,"spell unavailable or not enough power");return; }
        auto info=sSpellMgr->GetSpellInfo(arg,DIFFICULTY_NONE);
        Unit* target=p->GetSelectedUnit();if(!target&&info->IsPositive()) target=p;
        if(!target) { Error(p,"select a target");return; }
        // Only virtual resource payment is delegated. GCD, cast time, cooldown,
        // movement, range, target, reagent, form and equipment checks remain native.
        SpellCastResult result=p->CastSpell(target,arg,CastSpellExtraArgs(TRIGGERED_IGNORE_POWER_COST).SetCustomArg(CastTag{}));
        if(result!=SPELL_CAST_OK) Error(p,Trinity::StringFormat("native cast rejected: {}",uint32(result)));
        return;
    }
    if(p->IsInCombat()||p->HasUnitState(UNIT_STATE_CASTING)||!p->IsAlive()) { Error(p,"cannot edit in combat or while casting");return; }
    std::string error;bool changed=false;
    if(command=="debuglevel") {
        if(!ValidClass(arg)||arg==uint8(e.state.primaryClass)||!e.state.classes.count(Class(arg))||
            debugLevel<1||debugLevel>std::min<uint32>(p->GetLevel(),sWorld->getIntConfig(CONFIG_MAX_PLAYER_LEVEL))) {
            Error(p,"invalid learned secondary class or level");return;
        }
        e.state.classes[Class(arg)]={uint8(debugLevel),0};
        if(e.state.activeSubclass==Class(arg)) e.state.selectedSubclassSpells.clear();
        Refresh(p,e);
        for(auto& [type,pool]:e.pools) pool.current=type==POWER_RAGE?0:pool.maximum;
        changed=true;
    } else if(command=="learn"||command=="active"||command=="xp") {
        if(!ValidClass(arg)) { Error(p,"unsupported class");return; }
        if(command=="learn") changed=Policy.learnClass(e.state,Class(arg),&error);
        if(command=="active") changed=Policy.setActiveSubclass(e.state,Class(arg),&error);
        if(command=="xp") changed=Policy.setXpTarget(e.state,Class(arg),&error);
    } else if(command=="clear") changed=Policy.clearActiveSubclass(e.state,&error);
    else if(command=="select") {
        auto def=Definitions.find(arg);if(def==Definitions.end()) { Error(p,"unknown subclass spell");return; }
        changed=Policy.selectSubclassSpell(e.state,def->second.root.id,&error);
    } else if(command=="remove") {
        uint32 root=RootId(arg);changed=Policy.unselectSubclassSpell(e.state,root);
    } else { Error(p,"unknown command");return; }
    if(!changed) { Error(p,error.empty()?"selection unchanged":error);return; }
    Refresh(p,e);Save(e);Snapshot(p,e);
}

class Players final : public PlayerScript {
public:
    Players():PlayerScript("forever_subclass_players") { }
    void OnLogin(Player* p,bool) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);State(p); } }
    void OnSave(Player* p) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);Save(State(p)); } }
    void OnLogout(Player* p) override {
        std::lock_guard<std::recursive_mutex> g(Mutex);auto i=Entries.find(p->GetGUID().GetCounter());
        if(i!=Entries.end()) { Save(i->second);Entries.erase(i); }
    }
    void OnDelete(ObjectGuid guid,uint32) override {
        if(!Ready) return;
        std::lock_guard<std::recursive_mutex> g(Mutex);Entries.erase(guid.GetCounter());
        CharacterDatabaseTransaction tx=CharacterDatabase.BeginTransaction();
        for(char const* table:{"forever_character_class_progress","forever_character_subclass_state","forever_character_subclass_spells","forever_character_subclass_resources"})
            tx->Append(Trinity::StringFormat("DELETE FROM {} WHERE guid={}",table,guid.GetCounter()).c_str());
        CharacterDatabase.DirectCommitTransaction(tx);
    }
    void OnAddonMessageSent(Player* p,uint32 type,std::string const& prefix,std::string const& text,Player* receiver) override {
        if(type==CHAT_MSG_WHISPER&&prefix==RequestPrefix&&receiver==p) Request(p,text);
    }
    void OnGiveXP(Player* p,uint32& amount,Unit*) override {
        if(!Ready||!ValidClass(p->GetClass())) return;std::lock_guard<std::recursive_mutex> g(Mutex);auto& e=State(p);auto& c=e.state;
        if(!e.valid||!c.xpTargetClass||*c.xpTargetClass==c.primaryClass) return;
        auto& progress=c.classes[*c.xpTargetClass];uint64 remaining=amount;amount=0;
        uint8 cap=std::min<uint32>(p->GetLevel(),sWorld->getIntConfig(CONFIG_MAX_PLAYER_LEVEL));
        while(remaining&&progress.level<cap) {
            uint64 need=sObjectMgr->GetXPForLevel(progress.level);if(!need) break;
            progress.xp=std::min(progress.xp,need-1);uint64 take=std::min(remaining,need-progress.xp);
            progress.xp+=take;remaining-=take;
            if(progress.xp==need) { ++progress.level;progress.xp=0; }
        }
        Refresh(p,e);Save(e);
    }
};
class Damage final : public UnitScript {
public:
    Damage():UnitScript("forever_subclass_resources") { }
    void OnDamage(Unit* attacker,Unit* victim,uint32& damage) override {
        if(!Ready||!damage) return;std::lock_guard<std::recursive_mutex> g(Mutex);
        auto grant=[](Unit* unit) {
            Player* p=unit?unit->ToPlayer():nullptr;if(!p||p->GetPowerType()==POWER_RAGE) return;
            auto i=Entries.find(p->GetGUID().GetCounter());if(i==Entries.end()) return;
            auto& e=i->second;
            if(e.state.activeSubclass&&HasClassPower(*e.state.activeSubclass,POWER_RAGE)) {
                Refresh(p,e);auto& pool=e.pools[POWER_RAGE];pool.current=std::min(pool.maximum,pool.current+6);
            }
        };
        grant(attacker);if(victim!=attacker) grant(victim);
    }
};
class Startup final : public WorldScript {
public:
    Startup():WorldScript("forever_subclass_startup") { }
    void OnWorldInitialized() override {
        if(!sConfigMgr->GetBoolDefault("ForeverSubclass.Enable",false)) return;
        for(char const* table:{"forever_character_class_progress","forever_character_subclass_state","forever_character_subclass_spells","forever_character_subclass_resources"})
            if(!CharacterDatabase.Query(Trinity::StringFormat("SELECT COUNT(*) FROM {}",table).c_str())) {
                TC_LOG_ERROR("scripts","Subclass schema missing: {}. Feature disabled.",table);return;
            }
        uint32 scriptId=sObjectMgr->GetScriptId(SpellScriptName);
        for(auto const& root:Roots) {
            auto info=sSpellMgr->GetSpellInfo(root.id,DIFFICULTY_NONE);uint32 count=0;
            for(;info&&count++<64;info=info->GetNextRankSpell()) {
                auto bounds=sObjectMgr->GetSpellScriptsBounds(info->Id);uint32 matches=0;
                for(auto i=bounds.first;i!=bounds.second;++i) if(i->second.first==scriptId&&i->second.second) ++matches;
                if(matches!=1) { TC_LOG_ERROR("scripts","Subclass spell {} requires exactly one validated script binding",info->Id);continue; }
                uint32 required=std::max<uint32>(root.level,info->SpellLevel);
                if(required>80) continue;
                uint8 level=uint8(std::max<uint32>(1,required));
                if(Definitions.emplace(info->Id,Definition{root,level}).second)
                    Policy.registerSpell({info->Id,std::to_string(info->Id),Class(root.owner),level,1,
                        root.power==POWER_MANA?forever::PowerType::Mana:root.power==POWER_RAGE?forever::PowerType::Rage:forever::PowerType::Energy,
                        root.minimumCost,true});
            }
        }
        if(Definitions.empty()) { TC_LOG_ERROR("scripts","Subclass catalogue empty. Feature disabled.");return; }
        Ready=true;TC_LOG_INFO("scripts","ForeverSubclass ready: {} supported spell ranks",Definitions.size());
    }
};
} // namespace ForeverSubclass

class spell_forever_subclass final : public SpellScript {
    PrepareSpellScript(spell_forever_subclass);
    bool _secondary=false;double _factor=1,_intellectBonus=0;
    bool Load() override {
        using namespace ForeverSubclass;
        if(!Ready) return false;
        Player* p=GetCaster()->ToPlayer();auto i=Definitions.find(GetSpellInfo()->Id);
        return Ready&&p&&i!=Definitions.end()&&p->GetClass()!=i->second.root.owner;
    }
    SpellCastResult Check() {
        using namespace ForeverSubclass;
        if(!std::any_cast<CastTag>(&GetSpell()->m_customArg)) return SPELL_FAILED_NOT_KNOWN;
        std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);
        return Allowed(p,e,GetSpellInfo()->Id)?SPELL_CAST_OK:SPELL_FAILED_NO_POWER;
    }
    void Pay() {
        using namespace ForeverSubclass;
        std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);
        uint32 id=GetSpellInfo()->Id;
        if(!Allowed(p,e,id)) { FinishCast(SPELL_FAILED_NO_POWER);return; }
        auto const& def=Definitions.at(id);int32 cost=Cost(p,id,def);
        if(def.root.power==p->GetPowerType()) p->ModifyPower(def.root.power,-cost*(def.root.power==POWER_RAGE?10:1));
        else e.pools[def.root.power].current=std::max(0,e.pools[def.root.power].current-cost);
        _secondary=true;_factor=Policy.effectivenessFor(e.state,Class(def.root.owner));
        double coefficient=def.root.intellectCoefficient;
        for(auto const& effect:GetSpellInfo()->GetEffects())
            if((effect.Effect==SPELL_EFFECT_SCHOOL_DAMAGE||effect.Effect==SPELL_EFFECT_HEAL)&&effect.BonusCoefficient>0)
                coefficient=effect.BonusCoefficient;
        _intellectBonus=std::max(0,e.state.stats.intellect)*coefficient;
    }
    void Scale() {
        if(!_secondary) return;
        auto scale=[this](int32 value) { return int32(std::clamp((value+_intellectBonus)*_factor,0.0,double(std::numeric_limits<int32>::max()))); };
        if(GetHitDamage()>0) SetHitDamage(scale(GetHitDamage()));
        if(GetHitHeal()>0) SetHitHeal(scale(GetHitHeal()));
    }
    void Register() override {
        OnCheckCast+=SpellCheckCastFn(spell_forever_subclass::Check);
        OnCast+=SpellCastFn(spell_forever_subclass::Pay);
        OnHit+=SpellHitFn(spell_forever_subclass::Scale);
    }
};
void AddSC_forever_subclass() {
    new ForeverSubclass::Startup();new ForeverSubclass::Players();new ForeverSubclass::Damage();
    RegisterSpellScript(spell_forever_subclass);
}