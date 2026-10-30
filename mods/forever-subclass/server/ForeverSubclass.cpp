/* Forever subclass adapter for TrinityCore Forever.
 * Primary class, health, armor proficiency and native primary spells stay in the core.
 */
#include "ScriptMgr.h"
#include "SpellScript.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "Spell.h"
#include "SpellAuras.h"
#include "SpellAuraEffects.h"
#include "Player.h"
#include "Creature.h"
#include "Pet.h"
#include "Map.h"
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
#include <limits>
#include <map>
#include <mutex>
#include <sstream>
#include <vector>

namespace ForeverSubclass
{
using Class = forever::ClassId;
using Clock = std::chrono::steady_clock;
constexpr char RequestPrefix[] = "FSC1";
constexpr char ResponsePrefix[] = "FSR1";
constexpr char SpellScriptName[] = "spell_forever_subclass";
constexpr uint32 HunterTameSpell = 1515;
constexpr uint32 FreepickManaShield = 1463;
constexpr char CustomShieldSpellScript[] = "spell_forever_custom_mana_shield";
constexpr char CustomShieldAuraScript[] = "aura_forever_custom_mana_shield";

struct RootSpell
{
    uint32 id;
    uint8 owner;
    uint8 level;
    Powers power;
    int32 minimumCost;
    double intellectCoefficient;
};

// One selectable entry per native rank chain. BestRank() upgrades it automatically.
static RootSpell const Roots[] = {
    {6673,1,1,POWER_RAGE,10,0},
    {635,2,1,POWER_MANA,35,0.714},
    {3044,3,6,POWER_MANA,25,0.15},
    {1752,4,1,POWER_ENERGY,45,0},
    {585,5,1,POWER_MANA,20,0.714},
    {2050,5,1,POWER_MANA,30,0.429},
    {2054,5,16,POWER_MANA,100,0.857},
    {2060,5,40,POWER_MANA,200,0.857},
    {2061,5,20,POWER_MANA,100,0.429},
    {403,7,1,POWER_MANA,30,0.714},
    {331,7,1,POWER_MANA,35,0.857},
    {116,8,4,POWER_MANA,25,0.814},
    {2136,8,6,POWER_MANA,40,0.429},
    {686,9,1,POWER_MANA,25,0.857},
    {5176,11,1,POWER_MANA,20,0.571},
    {5185,11,1,POWER_MANA,35,1.0},
    // Druid forms are required before rage/energy attacks are useful to a non-druid primary class.
    {5487,11,10,POWER_MANA,0,0},
    {768,11,20,POWER_MANA,0,0},
    {6807,11,10,POWER_RAGE,15,0},
    {1082,11,20,POWER_ENERGY,45,0}
};

struct Definition { RootSpell root; uint8 level; };
struct TalentDef { uint16 id; uint8 maxRank; uint8 tier; };
static TalentDef const Talents[] = {
    {1001,5,0}, // Mastery: +2% subclass effectiveness/rank
    {1002,5,0}, // Reserve: +5% secondary resource maximum/rank
    {2001,5,1}, // Efficiency: -3% resource cost/rank
    {2002,5,1}, // Recovery: +10% mana/energy regeneration/rank
    {3001,5,2}, // Expertise: +3% subclass effectiveness/rank
    {3002,5,2}, // Battle rhythm: +5% regeneration/rage generation/rank
};

struct CastTag { };
struct CustomCastTag { uint32 spell; };
struct Entry
{
    forever::CharacterState state;
    std::map<Powers,forever::ResourcePool> pools;
    std::map<uint8,std::map<uint16,uint8>> talents;
    Clock::time_point updated = Clock::now(), request{};
    double manaFraction = 0, energyFraction = 0;
    bool valid = true;
};

static forever::SystemConfig MakePolicyConfig()
{
    forever::SystemConfig cfg;
    cfg.subclassUnlockPrimaryLevel = 10;
    cfg.subclassAbilitySlots = 8;
    cfg.requireRestAreaToSwitchSubclass = true;
    cfg.allowSwitchInCombat = false;
    return cfg;
}

static std::recursive_mutex Mutex;
static std::map<uint64,Entry> Entries;
static std::map<uint32,Definition> Definitions;
static std::map<uint32,uint32> CustomShieldRanks;
static forever::SubclassSystem Policy(MakePolicyConfig());
static std::atomic<bool> Ready{false};

static bool Freepick() { return Policy.config().freepickMode; }
static void CancelCustomManaShield(Player* p);

static bool IsNativeManaShield(SpellInfo const* info)
{
    return info&&info->GetFirstRankSpell()->Id==FreepickManaShield;
}

static uint32 CustomShieldRank(Player* p)
{
    uint32 best=FreepickManaShield,bestLevel=0;
    for(auto const& [id,level]:CustomShieldRanks)
        if(level<=p->GetLevel()&&(level>bestLevel||(level==bestLevel&&id>best))) { best=id;bestLevel=level; }
    return best;
}

static void RemoveRuntimeShields(Player* p)
{
    std::vector<Aura*> auras;
    for(auto effect:p->GetAuraEffectsByType(SPELL_AURA_MANA_SHIELD))
        if(IsNativeManaShield(effect->GetSpellInfo())&&effect->GetBase()->GetCasterGUID()==p->GetGUID()&&effect->GetBase()->IsScriptOwned())
            auras.push_back(effect->GetBase());
    for(auto aura:auras) aura->Remove();
}

static bool ValidClass(uint32 id) { return id==1||id==2||id==3||id==4||id==5||id==7||id==8||id==9||id==11; }

static std::vector<Powers> ClassPowers(Class id)
{
    if (id==Class::Warrior) return {POWER_RAGE};
    if (id==Class::Rogue) return {POWER_ENERGY};
    if (id==Class::Druid) return {POWER_MANA,POWER_RAGE,POWER_ENERGY};
    return {POWER_MANA};
}

static bool HasClassPower(Class id,Powers power)
{
    for (Powers candidate:ClassPowers(id)) if (candidate==power) return true;
    return false;
}

static uint32 RootId(uint32 spell)
{
    auto i=Definitions.find(spell);
    return i==Definitions.end()?spell:i->second.root.id;
}

static bool Selected(Entry const& e,uint32 spell)
{
    uint32 root=RootId(spell);
    return e.state.selectedSubclassSpells.count(root)||e.state.selectedSubclassSpells.count(spell);
}

static uint32 BestRank(Entry const& e,uint32 spellOrRoot)
{
    uint32 root=RootId(spellOrRoot);
    if (Freepick())
    {
        uint32 best=root;uint8 bestLevel=0;
        auto primary=e.state.classes.find(e.state.primaryClass);
        if(primary==e.state.classes.end()) return root;
        for(auto const& [id,d]:Definitions)
            if(d.root.id==root&&d.level<=primary->second.level&&(d.level>bestLevel||(d.level==bestLevel&&id>best)))
                { best=id;bestLevel=d.level; }
        return best;
    }
    if (!e.state.activeSubclass) return root;
    auto progress=e.state.classes.find(*e.state.activeSubclass);
    if (progress==e.state.classes.end()) return root;
    uint8 owner=uint8(*e.state.activeSubclass),level=progress->second.level,bestLevel=0;
    uint32 best=0;
    for (auto const& [id,d]:Definitions)
        if (d.root.id==root&&d.root.owner==owner&&d.level<=level&&(!best||d.level>bestLevel||(d.level==bestLevel&&id>best)))
            { best=id;bestLevel=d.level; }
    return best?best:root;
}

static TalentDef const* FindTalent(uint16 id)
{
    for (auto const& t:Talents) if (t.id==id) return &t;
    return nullptr;
}

static uint8 TalentRank(Entry const& e,Class cls,uint16 id)
{
    auto c=e.talents.find(uint8(cls));if(c==e.talents.end()) return 0;
    auto t=c->second.find(id);return t==c->second.end()?0:t->second;
}

static uint32 TalentTotalPoints(Entry const& e,Class cls)
{
    auto p=e.state.classes.find(cls);
    if (p==e.state.classes.end()||p->second.level<10) return 0;
    // One point at level 10, then one every two subclass levels. The tree has 30 ranks total.
    return std::min<uint32>(30,1+(uint32(p->second.level)-10)/2);
}

static uint32 TalentSpent(Entry const& e,Class cls)
{
    uint32 total=0;auto c=e.talents.find(uint8(cls));if(c==e.talents.end()) return 0;
    for (auto const& [id,rank]:c->second) total+=rank;
    return total;
}

static double Effectiveness(Entry const& e,Class cls)
{
    double bonus=0.02*TalentRank(e,cls,1001)+0.03*TalentRank(e,cls,3001);
    return Policy.effectivenessFor(e.state,cls)*(1.0+bonus);
}
static double RegenMultiplier(Entry const& e,Class cls) { return 1.0+0.10*TalentRank(e,cls,2002)+0.05*TalentRank(e,cls,3002); }
static double ResourceMaximumMultiplier(Entry const& e,Class cls) { return 1.0+0.05*TalentRank(e,cls,1002); }
static double CostMultiplier(Entry const& e,Class cls) { return std::max(0.50,1.0-0.03*TalentRank(e,cls,2001)); }

static void Send(Player* p,std::string const& text)
{
    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER,LANG_ADDON,p,p,text,0,"",LOCALE_enUS,ResponsePrefix);
    p->GetSession()->SendPacket(packet.Write());
}
static void Error(Player* p,std::string const& text) { Send(p,"ERROR "+text); }
static bool Resting(Player* p) { return p->GetRestMgr().HasRestFlag(REST_FLAG_IN_TAVERN)||p->GetRestMgr().HasRestFlag(REST_FLAG_IN_CITY); }

static void Save(Entry const& e)
{
    if (!e.valid) return;
    auto const& c=e.state;
    if (Freepick())
    {
        // Never write legacy subclass tables in Freepick mode.
        CharacterDatabaseTransaction tx=CharacterDatabase.BeginTransaction();
        tx->PAppend("REPLACE INTO forever_character_freepick_state VALUES ({},{},{})",c.guid,uint8(c.primaryClass),c.activeSubclass?uint8(*c.activeSubclass):0);
        tx->PAppend("DELETE FROM forever_character_freepick_spells WHERE guid={}",c.guid);
        for(auto id:c.selectedSubclassSpells) tx->PAppend("INSERT INTO forever_character_freepick_spells VALUES ({},{})",c.guid,id);
        tx->PAppend("DELETE FROM forever_character_freepick_resources WHERE guid={}",c.guid);
        for(auto const& [power,pool]:e.pools) tx->PAppend("INSERT INTO forever_character_freepick_resources VALUES ({},{},{})",c.guid,int(power),std::max(0,pool.current));
        CharacterDatabase.DirectCommitTransaction(tx);return;
    }
    CharacterDatabaseTransaction tx=CharacterDatabase.BeginTransaction();
    tx->PAppend("DELETE FROM forever_character_class_progress WHERE guid={}",c.guid);
    for (auto const& [id,progress]:c.classes)
        tx->PAppend("INSERT INTO forever_character_class_progress VALUES ({},{},{},{})",c.guid,uint8(id),progress.level,progress.xp);
    tx->PAppend("REPLACE INTO forever_character_subclass_state VALUES ({},{},{},{})",c.guid,uint8(c.primaryClass),
        c.activeSubclass?std::to_string(uint8(*c.activeSubclass)):"NULL",
        c.xpTargetClass?std::to_string(uint8(*c.xpTargetClass)):"NULL");
    tx->PAppend("DELETE FROM forever_character_subclass_spells WHERE guid={}",c.guid);
    for (auto id:c.selectedSubclassSpells) tx->PAppend("INSERT INTO forever_character_subclass_spells VALUES ({},{})",c.guid,id);
    tx->PAppend("DELETE FROM forever_character_subclass_resources WHERE guid={}",c.guid);
    for (auto const& [power,pool]:e.pools)
        tx->PAppend("INSERT INTO forever_character_subclass_resources VALUES ({},{},{})",c.guid,int(power),std::max(0,pool.current));
    tx->PAppend("DELETE FROM forever_character_subclass_talents WHERE guid={}",c.guid);
    for (auto const& [classId,ranks]:e.talents)
        for (auto const& [talentId,rank]:ranks)
            if (rank) tx->PAppend("INSERT INTO forever_character_subclass_talents VALUES ({},{},{},{})",c.guid,classId,talentId,rank);
    CharacterDatabase.DirectCommitTransaction(tx);
}

static int32 PowerMaximum(Player* p,Entry const& e,Powers power)
{
    if (Freepick())
    {
        if(power!=POWER_MANA) return 100;
        uint32 base=0;sObjectMgr->GetPlayerClassLevelInfo(uint8(Class::Priest),p->GetLevel(),base);
        return int32(std::clamp(double(base)+p->GetManaBonusFromIntellect(),1.0,1000000.0));
    }
    if (!e.state.activeSubclass) return 1;
    int32 base=100;
    if (power==POWER_MANA)
    {
        uint32 manaBase=0;auto progress=e.state.classes.find(*e.state.activeSubclass);
        uint8 level=progress==e.state.classes.end()?1:progress->second.level;
        sObjectMgr->GetPlayerClassLevelInfo(uint8(*e.state.activeSubclass),level,manaBase);
        base=int32(std::clamp(double(manaBase)+p->GetManaBonusFromIntellect(),1.0,1000000.0));
    }
    return int32(std::clamp(double(base)*ResourceMaximumMultiplier(e,*e.state.activeSubclass),1.0,1000000.0));
}

static void Refresh(Player* p,Entry& e)
{
    auto& c=e.state;
    c.classes[c.primaryClass].level=p->GetLevel();c.classes[c.primaryClass].xp=p->GetXP();
    c.inCombat=p->IsInCombat();c.inRestArea=Resting(p);
    c.stats={int32(p->GetStat(STAT_STRENGTH)),int32(p->GetStat(STAT_AGILITY)),int32(p->GetStat(STAT_STAMINA)),
             int32(p->GetStat(STAT_INTELLECT)),int32(p->GetStat(STAT_SPIRIT)),0};
    auto now=Clock::now();double seconds=std::min(60.0,std::chrono::duration<double>(now-e.updated).count());e.updated=now;
    if (Freepick())
    {
        // Class cards are catalogue filters, not independently levelled classes.
        for(auto& [id,progress]:c.classes) if(id!=c.primaryClass) progress={uint8(p->GetLevel()),0};
        c.xpTargetClass=c.primaryClass;
        if(p->GetPowerIndex(POWER_MANA)<MAX_POWERS_PER_CLASS) { e.pools.erase(POWER_MANA);return; }
        int32 maximum=PowerMaximum(p,e,POWER_MANA);
        auto [it,inserted]=e.pools.try_emplace(POWER_MANA,forever::ResourcePool{maximum,maximum});
        auto& pool=it->second;pool.maximum=maximum;pool.current=std::clamp(pool.current,0,maximum);
        if(p->IsAlive())
        {
            double gained=e.manaFraction+std::max(0,c.stats.spirit)*0.20*(c.inCombat?0.30:1.0)*seconds;
            int32 whole=int32(std::min(double(maximum-pool.current),std::floor(gained)));
            e.manaFraction=pool.current+whole==maximum?0:gained-whole;pool.current+=whole;
        }
        return;
    }
    if (!c.activeSubclass) return;
    for (Powers power:ClassPowers(*c.activeSubclass))
    {
        if (power==p->GetPowerType()) continue;
        int32 maximum=PowerMaximum(p,e,power),initial=power==POWER_RAGE?0:maximum;
        auto [it,inserted]=e.pools.try_emplace(power,forever::ResourcePool{initial,maximum});
        auto& pool=it->second;pool.maximum=maximum;pool.current=std::clamp(pool.current,0,maximum);
        if (p->IsAlive()&&(power==POWER_MANA||power==POWER_ENERGY))
        {
            double& fraction=power==POWER_MANA?e.manaFraction:e.energyFraction;
            double rate=power==POWER_MANA?std::max(0,c.stats.spirit)*0.20*(c.inCombat?0.30:1.0):10.0;
            rate*=RegenMultiplier(e,*c.activeSubclass);
            double gained=fraction+rate*seconds;
            int32 whole=int32(std::min(double(maximum-pool.current),std::floor(gained)));
            fraction=pool.current+whole==maximum?0:gained-whole;
            pool.current=std::min(maximum,pool.current+whole);
        }
    }
}

static Entry& State(Player* p)
{
    uint64 guid=p->GetGUID().GetCounter();auto it=Entries.find(guid);
    if (it!=Entries.end()) { Refresh(p,it->second);return it->second; }
    Entry e;e.state=Policy.createCharacter(guid,Class(p->GetClass()),p->GetLevel());
    if (Freepick())
    {
        for(uint8 id:{1,2,3,4,5,7,8,9,11}) if(id!=p->GetClass()) e.state.classes[Class(id)]={uint8(p->GetLevel()),0};
        e.state.activeSubclass=p->GetClass()==5?Class::Mage:Class::Priest;
        if(auto row=CharacterDatabase.PQuery("SELECT primary_class_id,catalogue_class_id FROM forever_character_freepick_state WHERE guid={}",guid))
        {
            Field* f=row->Fetch();e.valid=f[0].GetUInt8()==p->GetClass();
            if(ValidClass(f[1].GetUInt8())&&f[1].GetUInt8()!=p->GetClass()) e.state.activeSubclass=Class(f[1].GetUInt8());
        }
        if(e.valid)
        {
            std::vector<uint32> purchases;
            if(auto rows=CharacterDatabase.PQuery("SELECT spell_id FROM forever_character_freepick_spells WHERE guid={} ORDER BY spell_id",guid)) do
            {
                purchases.push_back(rows->Fetch()[0].GetUInt32());
            } while(rows->NextRow());
            std::string error;
            if(!Policy.restoreSubclassSpells(e.state,purchases,&error))
            { e.valid=false;TC_LOG_ERROR("scripts","Freepick saved purchases rejected for guid {}: {}",guid,error); }
            if(auto rows=CharacterDatabase.PQuery("SELECT power_type,current_value FROM forever_character_freepick_resources WHERE guid={}",guid)) do
            {
                Field* v=rows->Fetch();if(v[0].GetUInt8()==POWER_MANA) e.pools[POWER_MANA]={int32(std::min<uint32>(v[1].GetUInt32(),1000000)),1000000};
            } while(rows->NextRow());
        }
        auto& value=Entries.emplace(guid,std::move(e)).first->second;Refresh(p,value);return value;
    }
    if (auto result=CharacterDatabase.PQuery("SELECT primary_class_id,active_subclass_id,xp_target_class_id FROM forever_character_subclass_state WHERE guid={}",guid))
    {
        Field* f=result->Fetch();
        if (f[0].GetUInt8()!=p->GetClass()) { e.valid=false;TC_LOG_ERROR("scripts","Subclass primary class mismatch for guid {}",guid); }
        else
        {
            if (auto rows=CharacterDatabase.PQuery("SELECT class_id,class_level,class_xp FROM forever_character_class_progress WHERE guid={}",guid)) do
            {
                Field* v=rows->Fetch();uint8 id=v[0].GetUInt8();
                if (ValidClass(id)&&id!=p->GetClass()) e.state.classes[Class(id)]={std::clamp<uint8>(v[1].GetUInt8(),1,80),v[2].GetUInt64()};
            } while(rows->NextRow());
            if (!f[1].IsNull()&&e.state.classes.count(Class(f[1].GetUInt8()))&&f[1].GetUInt8()!=p->GetClass()) e.state.activeSubclass=Class(f[1].GetUInt8());
            if (!f[2].IsNull()&&e.state.classes.count(Class(f[2].GetUInt8()))) e.state.xpTargetClass=Class(f[2].GetUInt8());
            if (auto rows=CharacterDatabase.PQuery("SELECT spell_id FROM forever_character_subclass_spells WHERE guid={}",guid)) do
            {
                uint32 saved=rows->Fetch()[0].GetUInt32();std::string ignored;Policy.selectSubclassSpell(e.state,RootId(saved),&ignored);
            } while(rows->NextRow());
            if (auto rows=CharacterDatabase.PQuery("SELECT power_type,current_value FROM forever_character_subclass_resources WHERE guid={}",guid)) do
            {
                Field* v=rows->Fetch();uint8 power=v[0].GetUInt8();
                if (power==POWER_MANA||power==POWER_RAGE||power==POWER_ENERGY) e.pools[Powers(power)]={int32(std::min<uint32>(v[1].GetUInt32(),1000000)),1000000};
            } while(rows->NextRow());
            if (auto rows=CharacterDatabase.PQuery("SELECT class_id,talent_id,rank FROM forever_character_subclass_talents WHERE guid={}",guid)) do
            {
                Field* v=rows->Fetch();uint8 classId=v[0].GetUInt8();uint16 talentId=v[1].GetUInt16();uint8 rank=v[2].GetUInt8();
                auto def=FindTalent(talentId);if (ValidClass(classId)&&def&&rank<=def->maxRank) e.talents[classId][talentId]=rank;
            } while(rows->NextRow());
        }
    }
    auto& value=Entries.emplace(guid,std::move(e)).first->second;Refresh(p,value);return value;
}

static int32 Cost(Player* p,Entry const& e,uint32 spell,Definition const& def)
{
    int32 value=def.root.minimumCost;
    if (auto info=sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE))
        if (auto native=info->CalcPowerCost(def.root.power,false,p,info->GetSchoolMask()))
        {
            int32 amount=native->Amount;if (def.root.power==POWER_RAGE) amount=(amount+9)/10;value=std::max(value,amount);
        }
    if (!Freepick()&&e.state.activeSubclass) value=int32(std::ceil(value*CostMultiplier(e,*e.state.activeSubclass)));
    return std::max(0,value);
}

static int32 Available(Player* p,Entry& e,Powers power)
{
    if (power==p->GetPowerType()) return power==POWER_RAGE?p->GetPower(power)/10:p->GetPower(power);
    return e.pools.count(power)?e.pools[power].current:0;
}

static bool Allowed(Player* p,Entry& e,uint32 spell)
{
    auto found=Definitions.find(spell);if(found==Definitions.end()||!e.valid) return false;auto const& d=found->second;
    if(Freepick()) return d.root.owner!=p->GetClass()&&Selected(e,spell)&&p->GetLevel()>=d.level&&
        p->GetLevel()>=Policy.config().subclassUnlockPrimaryLevel&&Available(p,e,d.root.power)>=Cost(p,e,spell,d);
    return e.state.activeSubclass&&uint8(*e.state.activeSubclass)==d.root.owner&&Selected(e,spell)&&
        e.state.classes[*e.state.activeSubclass].level>=d.level&&HasClassPower(*e.state.activeSubclass,d.root.power)&&
        Available(p,e,d.root.power)>=Cost(p,e,spell,d);
}

static int32 CustomShieldCost(Player* p,Entry const& e)
{
    int32 maximum=p->GetPowerIndex(POWER_MANA)<MAX_POWERS_PER_CLASS?p->GetMaxPower(POWER_MANA):PowerMaximum(p,e,POWER_MANA);
    // The reviewed Freepick rank costs 7% mana. Non-mana primaries use the shared Freepick pool.
    return int32((int64(std::max(0,maximum))*7+99)/100);
}

static bool CanUseCustomShield(Player* p,Entry const& e)
{
    auto spell=Policy.getSpell(FreepickManaShield);
    return Freepick()&&e.valid&&spell&&spell->implementationAvailable&&p->IsAlive()&&
        p->GetLevel()>=spell->requiredClassLevel&&e.state.selectedSubclassSpells.count(FreepickManaShield)&&
        Policy.meetsCustomRequirements(e.state,*spell);
}

static bool HunterFeatureReady(Entry const& e)
{
    if (Freepick()) return false;
    if (!e.state.activeSubclass||*e.state.activeSubclass!=Class::Hunter) return false;
    auto it=e.state.classes.find(Class::Hunter);return it!=e.state.classes.end()&&it->second.level>=10;
}

static bool SpendTalent(Entry& e,uint16 id,std::string& error)
{
    if (Freepick()) { error="Freepick talents are not enabled in this prototype";return false; }
    if (!e.state.activeSubclass) { error="no active subclass";return false; }
    TalentDef const* def=FindTalent(id);if(!def) { error="unknown subclass talent";return false; }
    Class cls=*e.state.activeSubclass;uint32 total=TalentTotalPoints(e,cls),spent=TalentSpent(e,cls);
    if (spent>=total) { error="no subclass talent points";return false; }
    if (spent<uint32(def->tier)*5) { error="subclass talent tier locked";return false; }
    uint8& rank=e.talents[uint8(cls)][id];if(rank>=def->maxRank) { error="subclass talent is max rank";return false; }
    ++rank;return true;
}

static bool TameHunterPet(Player* p,Entry& e,std::string& error)
{
    if (!HunterFeatureReady(e)) { error="hunter pet requires hunter subclass level 10";return false; }
    if (p->GetPet()) { error="pet already active";return false; }
    Creature* creature=p->GetSelectedUnit()?p->GetSelectedUnit()->ToCreature():nullptr;
    if (!creature||!creature->IsAlive()||creature->IsPet()||!creature->GetCreatureTemplate()||creature->GetCreatureTemplate()->type!=CREATURE_TYPE_BEAST)
        { error="select a tameable beast";return false; }
    if (!creature->HasFlag(CREATURE_STATIC_FLAG_TAMEABLE)||creature->HasFlag(CREATURE_STATIC_FLAG_3_TAMEABLE_EXOTIC))
        { error="selected beast is not tameable by this subclass";return false; }
    if (creature->GetLevel()>e.state.classes.at(Class::Hunter).level) { error="beast level exceeds hunter subclass level";return false; }

    // Native Tame Beast rejects non-Hunter primary classes before it reaches the pet construction code.
    // Use the same public Unit API the core calls after that class check; never mutate the player's primary class.
    Pet* pet=p->CreateTamedPetFrom(creature,HunterTameSpell);
    if (!pet) { error="could not create hunter pet";return false; }
    creature->DespawnOrUnsummon();
    pet->GetMap()->AddToMap(pet->ToCreature());
    pet->SendNewlyTamed();
    p->SetMinion(pet,true);
    pet->SavePetToDB(PET_SAVE_AS_CURRENT);
    p->PetSpellInitialize();
    return true;
}

static bool CallHunterPet(Player* p,Entry& e,std::string& error)
{
    if (!HunterFeatureReady(e)) { error="hunter pet requires hunter subclass level 10";return false; }
    if (p->GetPet()) { error="pet already active";return false; }
    p->GetOrInitPetStable();
    Pet* pet=new Pet(p,HUNTER_PET);
    if (!pet->LoadPetFromDB(p,0,0,true)) { delete pet;error="no saved hunter pet";return false; }
    p->PetSpellInitialize();return true;
}

static bool DismissHunterPet(Player* p,Entry& e,std::string& error)
{
    if (!HunterFeatureReady(e)) { error="hunter pet requires hunter subclass level 10";return false; }
    Pet* pet=p->GetPet();if(!pet) { error="no active hunter pet";return false; }
    p->RemovePet(pet,PET_SAVE_AS_CURRENT);return true;
}

static void SnapshotFreepick(Player* p,Entry& e)
{
    auto const& c=e.state;
    Send(p,Trinity::StringFormat("STATE {} {} {} {} {} 10000",uint8(c.primaryClass),c.activeSubclass?uint8(*c.activeSubclass):0,uint8(c.primaryClass),Policy.usedSubclassSlots(c),Policy.config().subclassAbilitySlots));
    Send(p,"MODE FREEPICK 1"); // AE = used/budget from STATE; TE deliberately unavailable in v1.
    for(auto const& [id,v]:c.classes) Send(p,Trinity::StringFormat("CLASS {} {} {} {}",uint8(id),v.level,v.xp,sObjectMgr->GetXPForLevel(v.level)));
    for(Powers power:ClassPowers(c.primaryClass))
    {
        int32 scale=power==POWER_RAGE?10:1;
        Send(p,Trinity::StringFormat("BASEPOWER {} {} {}",int(power),p->GetPower(power)/scale,p->GetMaxPower(power)/scale));
    }
    int32 maximum=p->GetPowerIndex(POWER_MANA)<MAX_POWERS_PER_CLASS?p->GetMaxPower(POWER_MANA):PowerMaximum(p,e,POWER_MANA);
    Send(p,Trinity::StringFormat("POWER {} {} {}",int(POWER_MANA),Available(p,e,POWER_MANA),maximum));
    for(auto const& root:Roots)
    {
        if(root.owner==p->GetClass()||!Definitions.count(root.id)) continue;
        if(!Selected(e,root.id)&&(!c.activeSubclass||uint8(*c.activeSubclass)!=root.owner)) continue;
        uint32 id=BestRank(e,root.id);auto const& d=Definitions.at(id);
        Send(p,Trinity::StringFormat("SPELL {} {} {} {} {} {}",id,root.id,d.level,Selected(e,root.id)?1:0,Cost(p,e,id,d),int(d.root.power)));
    }
    for(auto const& record:forever::customSpellCatalog())
    {
        auto const& spell=*Policy.getSpell(record.spellId);
        Send(p,Trinity::StringFormat("CUSTOM {} {} {} {} {} {} {} {} {}",spell.spellId,
            spell.requiredClassLevel,c.selectedSubclassSpells.count(spell.spellId)?1:0,spell.slotCost,
            spell.requiredMagicClasses,Policy.representedMagicClasses(c),spell.requiredClassMask,
            Policy.representedClassMask(c),spell.implementationAvailable?1:0));
    }
    Send(p,"END");
}

static void Snapshot(Player* p,Entry& e)
{
    if(Freepick()) { SnapshotFreepick(p,e);return; }
    auto const& c=e.state;uint32 efficiency=c.activeSubclass?uint32(std::lround(Effectiveness(e,*c.activeSubclass)*10000.0)):0;
    Send(p,Trinity::StringFormat("STATE {} {} {} {} {} {}",uint8(c.primaryClass),c.activeSubclass?uint8(*c.activeSubclass):0,
        c.xpTargetClass?uint8(*c.xpTargetClass):uint8(c.primaryClass),Policy.usedSubclassSlots(c),Policy.config().subclassAbilitySlots,efficiency));
    for (auto const& [id,v]:c.classes) Send(p,Trinity::StringFormat("CLASS {} {} {} {}",uint8(id),v.level,v.xp,sObjectMgr->GetXPForLevel(v.level)));
    if (c.activeSubclass)
    {
        for (Powers power:ClassPowers(*c.activeSubclass))
        {
            int32 max=power==p->GetPowerType()?p->GetMaxPower(power):PowerMaximum(p,e,power);
            if (power==POWER_RAGE&&power==p->GetPowerType()) max/=10;
            Send(p,Trinity::StringFormat("POWER {} {} {}",int(power),Available(p,e,power),max));
        }
        struct Choice { uint32 first=0,best=0;uint8 firstLevel=255,bestLevel=0; };std::map<uint32,Choice> roots;
        uint8 active=uint8(*c.activeSubclass),level=c.classes.at(*c.activeSubclass).level;
        for (auto const& [id,d]:Definitions) if(d.root.owner==active)
        {
            auto& choice=roots[d.root.id];
            if(!choice.first||d.level<choice.firstLevel||(d.level==choice.firstLevel&&id<choice.first)) { choice.first=id;choice.firstLevel=d.level; }
            if(d.level<=level&&(!choice.best||d.level>choice.bestLevel||(d.level==choice.bestLevel&&id>choice.best))) { choice.best=id;choice.bestLevel=d.level; }
        }
        for (auto const& [root,choice]:roots)
        {
            uint32 id=choice.best?choice.best:choice.first;auto const& d=Definitions.at(id);
            Send(p,Trinity::StringFormat("SPELL {} {} {} {} {} {}",id,root,d.level,Selected(e,root)?1:0,Cost(p,e,id,d),int(d.root.power)));
        }
        uint32 total=TalentTotalPoints(e,*c.activeSubclass),spent=TalentSpent(e,*c.activeSubclass);
        Send(p,Trinity::StringFormat("TPOINTS {} {} {}",total-spent,spent,total));
        for (auto const& t:Talents) Send(p,Trinity::StringFormat("TALENT {} {} {} {}",t.id,TalentRank(e,*c.activeSubclass,t.id),t.maxRank,t.tier));
        if (*c.activeSubclass==Class::Hunter)
            Send(p,Trinity::StringFormat("FEATURE HUNTER_PET 10 {} {}",level>=10?1:0,p->GetPet()?1:0));
        if (*c.activeSubclass==Class::Druid) Send(p,"FEATURE DRUID_MULTI_POWER 1 1");
    }
    Send(p,"END");
}

static void Request(Player* p,std::string const& text)
{
    std::lock_guard<std::recursive_mutex> guard(Mutex);
    if (!Ready||!ValidClass(p->GetClass())) { Error(p,"module disabled or unsupported primary class");return; }
    auto& e=State(p);if(!e.valid) { Error(p,"saved primary class mismatch");return; }
    if (text.size()>96) return;
    auto now=Clock::now();if(now-e.request<std::chrono::milliseconds(150)) return;e.request=now;
    std::istringstream input(text);std::string command,extra;uint32 arg=0,debugLevel=0;input>>command;
    bool needsArg=command=="learn"||command=="active"||command=="xp"||command=="select"||command=="remove"||command=="cast"||command=="talent";
    if (Freepick()&&(command=="debuglevel"||command=="talent"||command=="talentreset"||command=="tame"||command=="petcall"||command=="petdismiss"))
        { Error(p,"command unavailable in Freepick ability prototype");return; }
    if (command=="debuglevel")
    {
        if(!(input>>arg>>debugLevel)||(input>>extra)) { Error(p,"invalid command");return; }
        if(p->GetSession()->GetSecurity()<SEC_GAMEMASTER) { Error(p,"GM only");return; }
    }
    else
    {
        if(needsArg&&(!(input>>arg)||(input>>extra))) { Error(p,"invalid command");return; }
        if(!needsArg&&(input>>extra)) { Error(p,"invalid command");return; }
    }
    if (command=="status") { Snapshot(p,e);return; }
    if (command=="cast")
    {
        auto custom=Policy.getSpell(arg);
        if(custom&&custom->custom)
        {
            std::string error;
            if(!Policy.meetsCustomRequirements(e.state,*custom,&error)) { Error(p,error);return; }
            if(arg!=FreepickManaShield||!custom->implementationAvailable) { Error(p,"custom ability requires a Forever implementation");return; }
            if(!CanUseCustomShield(p,e)) { Error(p,"spell unavailable or not enough power");return; }
            SpellCastResult result=p->CastSpell(p,CustomShieldRank(p),CastSpellExtraArgs(TRIGGERED_IGNORE_POWER_COST).SetCustomArg(CustomCastTag{arg}));
            if(result!=SPELL_CAST_OK) Error(p,Trinity::StringFormat("native cast rejected: {}",uint32(result)));
            return;
        }
        arg=BestRank(e,arg);if(!p->IsAlive()||!Allowed(p,e,arg)) { Error(p,"spell unavailable or not enough power");return; }
        auto info=sSpellMgr->GetSpellInfo(arg,DIFFICULTY_NONE);Unit* target=p->GetSelectedUnit();if(!target&&info->IsPositive()) target=p;
        if(!target) { Error(p,"select a target");return; }
        SpellCastResult result=p->CastSpell(target,arg,CastSpellExtraArgs(TRIGGERED_IGNORE_POWER_COST).SetCustomArg(CastTag{}));
        if(result!=SPELL_CAST_OK) Error(p,Trinity::StringFormat("native cast rejected: {}",uint32(result)));
        return;
    }
    if (command=="tame"||command=="petcall"||command=="petdismiss")
    {
        if(p->IsInCombat()||!p->IsAlive()) { Error(p,"cannot manage hunter pet in combat or while dead");return; }
        std::string error;bool changed=command=="tame"?TameHunterPet(p,e,error):command=="petcall"?CallHunterPet(p,e,error):DismissHunterPet(p,e,error);
        if(!changed) { Error(p,error);return; } Snapshot(p,e);return;
    }
    if (p->IsInCombat()||p->HasUnitState(UNIT_STATE_CASTING)||!p->IsAlive()) { Error(p,"cannot edit in combat or while casting");return; }
    std::string error;bool changed=false;
    if (command=="debuglevel")
    {
        if(!ValidClass(arg)||arg==uint8(e.state.primaryClass)||!e.state.classes.count(Class(arg))||
            debugLevel<1||debugLevel>std::min<uint32>(p->GetLevel(),sWorld->getIntConfig(CONFIG_MAX_PLAYER_LEVEL)))
            { Error(p,"invalid learned secondary class or level");return; }
        e.state.classes[Class(arg)]={uint8(debugLevel),0};if(e.state.activeSubclass==Class(arg)) e.state.selectedSubclassSpells.clear();
        Refresh(p,e);for(auto& [type,pool]:e.pools) pool.current=type==POWER_RAGE?0:pool.maximum;changed=true;
    }
    else if(command=="learn"||command=="active"||command=="xp")
    {
        if(!ValidClass(arg)) { Error(p,"unsupported class");return; }
        Class previous=e.state.activeSubclass.value_or(Class::Unknown);
        if(command=="learn") changed=Policy.learnClass(e.state,Class(arg),&error);
        if(command=="active") changed=Policy.setActiveSubclass(e.state,Class(arg),&error);
        if(command=="xp") changed=Policy.setXpTarget(e.state,Class(arg),&error);
        if(changed&&command=="active"&&previous==Class::Hunter&&Class(arg)!=Class::Hunter&&p->GetPet()) p->RemovePet(p->GetPet(),PET_SAVE_AS_CURRENT);
    }
    else if(command=="clear")
    {
        if(e.state.activeSubclass==Class::Hunter&&p->GetPet()) p->RemovePet(p->GetPet(),PET_SAVE_AS_CURRENT);
        changed=Policy.clearActiveSubclass(e.state,&error);
    }
    else if(command=="select")
    {
        auto custom=Policy.getSpell(arg);
        if(custom&&custom->custom)
        {
            if(!Policy.selectSubclassSpell(e.state,arg,&error)) Error(p,error);
            else { Refresh(p,e);Save(e);Snapshot(p,e); }
            return;
        }
        auto def=Definitions.find(arg);if(def==Definitions.end()) { Error(p,"unknown subclass spell");return; }
        changed=Policy.selectSubclassSpell(e.state,def->second.root.id,&error);
    }
    else if(command=="remove") changed=Policy.unselectSubclassSpell(e.state,RootId(arg),&error);
    else if(command=="talent")
    {
        if(!Resting(p)) { Error(p,"subclass talents can only be changed in a rest area");return; }
        changed=SpendTalent(e,uint16(arg),error);
    }
    else if(command=="talentreset")
    {
        if(!Resting(p)||!e.state.activeSubclass) { Error(p,"subclass talents can only be reset in a rest area");return; }
        changed=e.talents.erase(uint8(*e.state.activeSubclass))>0;if(!changed) error="subclass talents already empty";
    }
    else { Error(p,"unknown command");return; }
    if(!changed) { Error(p,error.empty()?"selection unchanged":error);return; }
    if(Freepick()) CancelCustomManaShield(p);
    Refresh(p,e);Save(e);Snapshot(p,e);
}

class Players final : public PlayerScript
{
public:
    Players():PlayerScript("forever_subclass_players") { }
    void OnLogin(Player* p,bool) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);State(p); } }
    void OnSave(Player* p) override { if(Ready&&ValidClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> g(Mutex);Save(State(p)); } }
    void OnLogout(Player* p) override
    {
        std::lock_guard<std::recursive_mutex> g(Mutex);auto i=Entries.find(p->GetGUID().GetCounter());
        if(i!=Entries.end()) { Save(i->second);Entries.erase(i); }
    }
    void OnDelete(ObjectGuid guid,uint32) override
    {
        if(!Ready) return;std::lock_guard<std::recursive_mutex> g(Mutex);Entries.erase(guid.GetCounter());
        CharacterDatabaseTransaction tx=CharacterDatabase.BeginTransaction();
        for(char const* table:{"forever_character_class_progress","forever_character_subclass_state","forever_character_subclass_spells","forever_character_subclass_resources","forever_character_subclass_talents"})
            tx->Append(Trinity::StringFormat("DELETE FROM {} WHERE guid={}",table,guid.GetCounter()).c_str());
        for(char const* table:{"forever_character_freepick_state","forever_character_freepick_spells","forever_character_freepick_resources"})
            tx->Append(Trinity::StringFormat("DELETE FROM {} WHERE guid={}",table,guid.GetCounter()).c_str());
        CharacterDatabase.DirectCommitTransaction(tx);
    }
    void OnAddonMessageSent(Player* p,uint32 type,std::string const& prefix,std::string const& text,Player* receiver) override
    {
        if(type==CHAT_MSG_WHISPER&&prefix==RequestPrefix&&receiver==p) Request(p,text);
    }
    void OnGiveXP(Player* p,uint32& amount,Unit*) override
    {
        if(!Ready||!ValidClass(p->GetClass())) return;std::lock_guard<std::recursive_mutex> g(Mutex);auto& e=State(p);auto& c=e.state;
        if(Freepick()) return; // Native main-class XP is never diverted.
        if(!e.valid||!c.xpTargetClass||*c.xpTargetClass==c.primaryClass) return;
        auto& progress=c.classes[*c.xpTargetClass];uint64 remaining=amount;amount=0;
        uint8 cap=std::min<uint32>(p->GetLevel(),sWorld->getIntConfig(CONFIG_MAX_PLAYER_LEVEL));
        while(remaining&&progress.level<cap)
        {
            uint64 need=sObjectMgr->GetXPForLevel(progress.level);if(!need) break;
            progress.xp=std::min(progress.xp,need-1);uint64 take=std::min(remaining,need-progress.xp);progress.xp+=take;remaining-=take;
            if(progress.xp==need) { ++progress.level;progress.xp=0; }
        }
        Refresh(p,e);Save(e);
    }
};

class Damage final : public UnitScript
{
public:
    Damage():UnitScript("forever_subclass_resources") { }
    void OnDamage(Unit* attacker,Unit* victim,uint32& damage) override
    {
        if(!Ready||!damage) return;std::lock_guard<std::recursive_mutex> g(Mutex);
        auto grant=[](Unit* unit)
        {
            Player* p=unit?unit->ToPlayer():nullptr;if(!p||p->GetPowerType()==POWER_RAGE) return;
            auto i=Entries.find(p->GetGUID().GetCounter());if(i==Entries.end()) return;auto& e=i->second;
            if(e.state.activeSubclass&&HasClassPower(*e.state.activeSubclass,POWER_RAGE))
            {
                Refresh(p,e);auto& pool=e.pools[POWER_RAGE];int32 gain=int32(std::lround(6.0*RegenMultiplier(e,*e.state.activeSubclass)));
                pool.current=std::min(pool.maximum,pool.current+std::max(1,gain));
            }
        };
        grant(attacker);if(victim!=attacker) grant(victim);
    }
};

class Startup final : public WorldScript
{
public:
    Startup():WorldScript("forever_subclass_startup") { }
    void OnWorldInitialized() override
    {
        if(!sConfigMgr->GetBoolDefault("ForeverSubclass.Enable",false)) return;
        for(char const* table:{"forever_character_class_progress","forever_character_subclass_state","forever_character_subclass_spells","forever_character_subclass_resources","forever_character_subclass_talents"})
            if(!CharacterDatabase.Query(Trinity::StringFormat("SELECT COUNT(*) FROM {}",table).c_str()))
                { TC_LOG_ERROR("scripts","Subclass schema missing: {}. Feature disabled.",table);return; }
        if(sConfigMgr->GetBoolDefault("ForeverSubclass.Freepick",false))
        {
            for(char const* table:{"forever_character_freepick_state","forever_character_freepick_spells","forever_character_freepick_resources"})
                if(!CharacterDatabase.Query(Trinity::StringFormat("SELECT COUNT(*) FROM {}",table).c_str()))
                { TC_LOG_ERROR("scripts","Freepick schema missing: {}. Feature disabled.",table);return; }
            auto cfg=MakePolicyConfig();cfg.freepickMode=true;Policy=forever::SubclassSystem(cfg);
            auto backend=sSpellMgr->GetSpellInfo(FreepickManaShield,DIFFICULTY_NONE);
            uint32 rankCount=0;
            for(auto info=backend;info&&rankCount++<64;info=info->GetNextRankSpell())
            {
                bool valid=!info->GetEffects().empty()&&info->GetEffect(EFFECT_0).ApplyAuraName==SPELL_AURA_MANA_SHIELD&&
                    info->GetEffect(EFFECT_0).MiscValue==SPELL_SCHOOL_MASK_ALL&&info->IsPositive()&&!info->IsChanneled();
                if(valid)
                {
                    float ratio=info->GetEffect(EFFECT_0).CalcValueMultiplier(nullptr);
                    valid=std::isfinite(ratio)&&ratio>0;
                }
                for(auto const& effect:info->GetEffects())
                    if(effect.EffectIndex!=EFFECT_0&&effect.IsEffect()) valid=false;
                for(char const* name:{CustomShieldSpellScript,CustomShieldAuraScript})
                {
                    uint32 matches=0;auto bounds=sObjectMgr->GetSpellScriptsBounds(info->Id);
                    for(auto i=bounds.first;i!=bounds.second;++i) if(i->second.first==sObjectMgr->GetScriptId(name)&&i->second.second) ++matches;
                    valid=valid&&matches==1;
                }
                if(valid) CustomShieldRanks[info->Id]=info->SpellLevel;
            }
            bool shieldReady=CustomShieldRanks.count(FreepickManaShield)>0;
            for(auto spell:forever::customSpellCatalog())
            {
                if(spell.spellId==FreepickManaShield) spell.implementationAvailable=shieldReady;
                Policy.registerSpell(spell);
            }
        }
        uint32 scriptId=sObjectMgr->GetScriptId(SpellScriptName);
        for(auto const& root:Roots)
        {
            // First vertical slice: priest Lesser Heal and mage Frostbolt, including native rank chains.
            if(Freepick()&&root.id!=2050&&root.id!=116) continue;
            auto info=sSpellMgr->GetSpellInfo(root.id,DIFFICULTY_NONE);uint32 count=0;
            for(;info&&count++<64;info=info->GetNextRankSpell())
            {
                auto bounds=sObjectMgr->GetSpellScriptsBounds(info->Id);uint32 matches=0;
                for(auto i=bounds.first;i!=bounds.second;++i) if(i->second.first==scriptId&&i->second.second) ++matches;
                if(matches!=1) { TC_LOG_ERROR("scripts","Subclass spell {} requires exactly one validated script binding",info->Id);continue; }
                uint32 required=std::max<uint32>(root.level,info->SpellLevel);if(required>80) continue;uint8 level=uint8(std::max<uint32>(1,required));
                if(Definitions.emplace(info->Id,Definition{root,level}).second)
                    Policy.registerSpell({info->Id,std::to_string(info->Id),Class(root.owner),level,1,
                        root.power==POWER_MANA?forever::PowerType::Mana:root.power==POWER_RAGE?forever::PowerType::Rage:forever::PowerType::Energy,
                        root.minimumCost,true});
            }
        }
        if(Freepick()&&(!Definitions.count(2050)||!Definitions.count(116)))
            { TC_LOG_ERROR("scripts","Freepick requires both validated chains 2050 and 116. Feature disabled.");return; }
        if(Definitions.empty()) { TC_LOG_ERROR("scripts","Subclass catalogue empty. Feature disabled.");return; }
        if(Freepick()) TC_LOG_INFO("scripts","Freepick custom Mana Shield: {} (native aura 1463 and both script bindings required)",Policy.getSpell(FreepickManaShield)->implementationAvailable?"available":"unavailable");
        if(Freepick()) TC_LOG_INFO("scripts","ForeverSubclass Freepick ability prototype enabled: 8 AE, native primary class and XP, shared mana; talents disabled");
        Ready=true;TC_LOG_INFO("scripts","ForeverSubclass ready: {} supported spell ranks; auto-ranks, multi-resource, talents and hunter pet foundation enabled",Definitions.size());
    }
};
} // namespace ForeverSubclass

class spell_forever_subclass final : public SpellScript
{
    PrepareSpellScript(spell_forever_subclass);
    bool _secondary=false;double _factor=1,_intellectBonus=0;
    bool Load() override
    {
        using namespace ForeverSubclass;if(!Ready) return false;Player* p=GetCaster()->ToPlayer();auto i=Definitions.find(GetSpellInfo()->Id);
        return Ready&&p&&i!=Definitions.end()&&p->GetClass()!=i->second.root.owner;
    }
    SpellCastResult Check()
    {
        using namespace ForeverSubclass;if(!std::any_cast<CastTag>(&GetSpell()->m_customArg)) return SPELL_FAILED_NOT_KNOWN;
        std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);return Allowed(p,e,GetSpellInfo()->Id)?SPELL_CAST_OK:SPELL_FAILED_NO_POWER;
    }
    void Pay()
    {
        using namespace ForeverSubclass;std::lock_guard<std::recursive_mutex> g(Mutex);Player* p=GetCaster()->ToPlayer();auto& e=State(p);uint32 id=GetSpellInfo()->Id;
        if(!Allowed(p,e,id)) { FinishCast(SPELL_FAILED_NO_POWER);return; }
        auto const& def=Definitions.at(id);int32 cost=Cost(p,e,id,def);
        if(def.root.power==p->GetPowerType()) p->ModifyPower(def.root.power,-cost*(def.root.power==POWER_RAGE?10:1));
        else e.pools[def.root.power].current=std::max(0,e.pools[def.root.power].current-cost);
        _secondary=true;_factor=Effectiveness(e,Class(def.root.owner));double coefficient=def.root.intellectCoefficient;
        for(auto const& effect:GetSpellInfo()->GetEffects())
            if((effect.Effect==SPELL_EFFECT_SCHOOL_DAMAGE||effect.Effect==SPELL_EFFECT_HEAL)&&effect.BonusCoefficient>0) coefficient=effect.BonusCoefficient;
        _intellectBonus=std::max(0,e.state.stats.intellect)*coefficient;
    }
    void Scale()
    {
        if(!_secondary) return;auto scale=[this](int32 value) { return int32(std::clamp((value+_intellectBonus)*_factor,0.0,double(std::numeric_limits<int32>::max()))); };
        if(GetHitDamage()>0) SetHitDamage(scale(GetHitDamage()));if(GetHitHeal()>0) SetHitHeal(scale(GetHitHeal()));
    }
    void Register() override
    {
        OnCheckCast+=SpellCheckCastFn(spell_forever_subclass::Check);
        OnCast+=SpellCastFn(spell_forever_subclass::Pay);
        OnHit+=SpellHitFn(spell_forever_subclass::Scale);
    }
};

class aura_forever_custom_mana_shield final : public AuraScript
{
    PrepareAuraScript(aura_forever_custom_mana_shield);
    uint32 _source=0;
public:
    void Enable(uint32 source)
    {
        _source=source;
        GetAura()->SetScriptOwned(true);
    }
    bool Enabled() const { return _source!=0; }
private:
    bool Validate(SpellInfo const* info) override
    {
        return info&&!info->GetEffects().empty()&&info->GetEffect(EFFECT_0).ApplyAuraName==SPELL_AURA_MANA_SHIELD;
    }
    void Absorb(AuraEffect* effect,DamageInfo& damage,uint32& amount)
    {
        if(!_source) return;
        PreventDefaultAction();amount=0;
        using namespace ForeverSubclass;
        std::lock_guard<std::recursive_mutex> g(Mutex);
        Player* p=GetTarget()->ToPlayer();
        auto found=p?Entries.find(p->GetGUID().GetCounter()):Entries.end();
        if(found==Entries.end()||damage.GetVictim()!=p||GetCasterGUID()!=p->GetGUID()||!CanUseCustomShield(p,found->second))
        { GetAura()->Remove();return; }
        auto& e=found->second;Refresh(p,e);
        uint32 mana=uint32(std::max(0,Available(p,e,POWER_MANA)));
        uint32 capacity=uint32(std::max(0,effect->GetAmountAsInt()));
        double ratio=effect->GetSpellEffectInfo().CalcValueMultiplier(p);
        auto result=forever::resolveManaShieldAbsorption(damage.GetDamage(),capacity,mana,ratio);
        if(p->GetPowerIndex(POWER_MANA)<MAX_POWERS_PER_CLASS)
        {
            uint32 paid=uint32(-p->ModifyPower(POWER_MANA,-int32(result.manaSpent)));
            if(paid!=result.manaSpent)
            {
                result=forever::resolveManaShieldAbsorption(damage.GetDamage(),capacity,paid,ratio);
                p->ModifyPower(POWER_MANA,int32(paid-result.manaSpent));
            }
        }
        else e.pools[POWER_MANA].current-=int32(result.manaSpent);
        damage.AbsorbDamage(result.absorbed);amount=result.absorbed;
        if(auto application=GetAura()->GetApplicationOfTarget(p->GetGUID()))
        {
            uint32 procAbsorb=amount;
            GetAura()->CallScriptEffectAfterManaShieldHandlers(effect,application,damage,procAbsorb);
        }
        if(!GetAura()->IsRemoved())
        {
            effect->ChangeAmount(int32(result.remaining));
            if(!result.remaining||Available(p,e,POWER_MANA)<=0) GetAura()->Remove();
        }
    }
    void Register() override
    {
        OnEffectManaShield+=AuraEffectManaShieldFn(aura_forever_custom_mana_shield::Absorb,EFFECT_0);
    }
};

class spell_forever_custom_mana_shield final : public SpellScript
{
    PrepareSpellScript(spell_forever_custom_mana_shield);
    uint32 _source=0;
    bool Load() override
    {
        using namespace ForeverSubclass;
        if(!Ready||!Freepick()||!GetCaster()->ToPlayer()) return false;
        if(auto tag=std::any_cast<CustomCastTag>(&GetSpell()->m_customArg)) _source=tag->spell;
        return true;
    }
    SpellCastResult Check()
    {
        using namespace ForeverSubclass;
        std::lock_guard<std::recursive_mutex> g(Mutex);
        Player* p=GetCaster()->ToPlayer();
        Aura* old=p->GetAura(GetSpellInfo()->Id,p->GetGUID());
        if(!_source) return old&&old->IsScriptOwned()?SPELL_FAILED_AURA_BOUNCED:SPELL_CAST_OK;
        if(_source!=FreepickManaShield||!CanUseCustomShield(p,State(p))) return SPELL_FAILED_NOT_KNOWN;
        for(auto effect:p->GetAuraEffectsByType(SPELL_AURA_MANA_SHIELD))
            if(IsNativeManaShield(effect->GetSpellInfo())&&effect->GetBase()->GetCasterGUID()==p->GetGUID()&&!effect->GetBase()->IsScriptOwned())
                return SPELL_FAILED_AURA_BOUNCED;
        auto& e=State(p);
        return Available(p,e,POWER_MANA)>=CustomShieldCost(p,e)?SPELL_CAST_OK:SPELL_FAILED_NO_POWER;
    }
    void PrepareAura()
    {
        if(!_source) return;
        ForeverSubclass::RemoveRuntimeShields(GetCaster()->ToPlayer());
    }
    void Activate()
    {
        if(!_source) return;
        using namespace ForeverSubclass;
        std::lock_guard<std::recursive_mutex> g(Mutex);
        Player* p=GetCaster()->ToPlayer();auto& e=State(p);
        Aura* aura=p->GetAura(GetSpellInfo()->Id,p->GetGUID());
        if(!aura||aura->GetCastId()!=GetSpell()->m_castId) return;
        auto script=aura->GetScript<aura_forever_custom_mana_shield>();
        int32 cost=CustomShieldCost(p,e);
        if(!script||!CanUseCustomShield(p,e)||Available(p,e,POWER_MANA)<cost)
        { aura->Remove();return; }
        script->Enable(_source);
        if(p->GetPowerIndex(POWER_MANA)<MAX_POWERS_PER_CLASS) p->ModifyPower(POWER_MANA,-cost);
        else e.pools[POWER_MANA].current-=cost;
        Save(e);Snapshot(p,e);
    }
    void Register() override
    {
        OnCheckCast+=SpellCheckCastFn(spell_forever_custom_mana_shield::Check);
        OnCast+=SpellCastFn(spell_forever_custom_mana_shield::PrepareAura);
        AfterCast+=SpellCastFn(spell_forever_custom_mana_shield::Activate);
    }
};

void ForeverSubclass::CancelCustomManaShield(Player* p)
{
    auto found=Entries.find(p->GetGUID().GetCounter());
    if(found!=Entries.end()&&CanUseCustomShield(p,found->second)) return;
    RemoveRuntimeShields(p);
}

void AddSC_forever_subclass()
{
    new ForeverSubclass::Startup();new ForeverSubclass::Players();new ForeverSubclass::Damage();RegisterSpellScript(spell_forever_subclass);
    RegisterSpellScript(spell_forever_custom_mana_shield);
    RegisterSpellScript(aura_forever_custom_mana_shield);
}
