#include "ScriptMgr.h"
#include "Chat.h"
#include "ChatCommand.h"
#include "ChatPackets.h"
#include "Config.h"
#include "DB2Stores.h"
#include "DB2HotfixGenerator.h"
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
#include "SpellAuras.h"
#include "SpellAuraEffects.h"
#include "WorldSession.h"
#include "Util.h"
#include "AscensionCatalog.h"
#include "CustomAbilityRules.h"
#include "ExperienceShare.h"
#include "TraitMgr.h"
#include "TraitPacketsCommon.h"
#include "Item.h"
#include "Pet.h"
#include <array>
#include <chrono>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <fstream>
#include <string_view>

namespace ForeverAdvancement
{
using Clock=std::chrono::steady_clock;
constexpr std::array<Powers,3> PowersList={POWER_MANA,POWER_RAGE,POWER_ENERGY};
struct Definition { uint32 entry,owner,spell,level; };
struct CastTag { uint32 entry; };
struct TalentDefinition { uint32 entry,owner,spell,rank,level,cost,investment,tab;uint32 trait=0,traitEntry=0,node=0,tree=0;int32 x=0,y=0; };
struct Pool { int32 current=0,maximum=0;double fraction=0; };
struct ClassProgress { uint32 level=1;uint64 xp=0; };
struct State
{
    uint32 active=0;
    bool talentStatusDirty=true;
    bool equipmentInitialized=false;uint32 equipmentClass=0,equipmentLevel=0;
    bool experienceEnabled=true;
    uint32 experienceCarry=0;
    std::map<uint32,ClassProgress> classes;
    std::set<uint32> learned;
    std::map<uint32,uint32> talents;
    std::set<uint32> ownedAuras;
    std::map<uint32,std::pair<uint32,uint32>> ownedTraits;
    std::set<uint32> bookSpells,equipmentSpells;
    bool syncing=false;
    std::map<Powers,Pool> pools;
    Clock::time_point updated=Clock::now(),request{};
};
static std::recursive_mutex Mutex;
static std::map<uint64,State> States;
static std::map<uint32,std::vector<Definition>> Catalog;
static std::map<uint32,std::vector<TalentDefinition>> TalentCatalog;
struct NativeMenuRow { uint32 id,owner,spell,level,kind,max,traitEntry; bool available; char const* reason; };
static std::map<uint32,NativeMenuRow> NativeMenu;
static std::map<uint32,uint32> LegacyAbilityIds;
struct Equipment {uint32 skill,spell,level,weapons,armor,mask=0;bool dual=false;};
static std::vector<Equipment> EquipmentCatalog;
static std::map<uint32,std::string> TreeTitles;
static std::map<std::string,std::string> BranchTitles;
static std::map<uint32,std::vector<uint32>> TalentParents;
struct Layout {uint32 node,tree;int32 x,y;float offset=0,col=0,row=0;std::string tag;};
static std::map<uint32,Layout> TalentLayout;
static std::string Hex(std::string const& text)
{static char const* digits="0123456789abcdef";std::string out;for(unsigned char c:text.substr(0,80)) {out+=digits[c>>4];out+=digits[c&15];}return out;}
// Only player class schools: mounts/companions and pet-family skills are also
// category CLASS in Forever, so CategoryID alone is not an ownership check.
static bool PlayerClassSchool(int32 category,uint32 flags)
{
    return category==SKILL_CATEGORY_CLASS&&(flags&0x400)&&!(flags&(0x2|0x800));
}
static uint32 SchoolClassMask(uint32 skill)
{
    uint32 mask=0;for(auto row:sDB2Manager.GetSkillRaceClassInfo(skill)) mask|=uint32(row->ClassMask);
    return mask&0x7ff;
}
static uint32 TalentSchool(uint32 tree,uint32 owner,uint32 spell)
{
    std::set<uint32> roots;
    for(auto link:sSkillLineXTraitTreeStore) if(uint32(link->TraitTreeID)==tree)
        if(auto skill=sSkillLineStore.LookupEntry(link->SkillLineID);skill&&PlayerClassSchool(skill->CategoryID,skill->Flags)&&(SchoolClassMask(skill->ID)&(1u<<(owner-1)))) roots.insert(skill->ID);
    if(roots.size()==1) return *roots.begin();
    std::set<uint32> matches;auto bounds=sSpellMgr->GetSkillLineAbilityMapBounds(spell);
    for(auto it=bounds.first;it!=bounds.second;++it) if(roots.count(it->second->SkillLine)) matches.insert(it->second->SkillLine);
    return matches.size()==1?*matches.begin():0;
}
static std::map<std::string,uint32> BranchSchools,BranchTrees;
static void BuildTalentLayout()
{
    std::map<std::string,std::set<int32>> columns,rows;
    for(auto& [id,l]:TalentLayout)
    {
        auto const& menu=NativeMenu.at(id);uint32 school=TalentSchool(l.tree,menu.owner,menu.spell);
        l.tag=std::to_string(menu.owner)+(school?"-school-":"-tree-")+std::to_string(school?school:l.tree);
        BranchSchools[l.tag]=school;BranchTrees[l.tag]=l.tree;
        columns[l.tag].insert(l.x);rows[l.tag].insert(l.y);
        std::string title;
        if(auto skill=sSkillLineStore.LookupEntry(school)) for(uint32 locale:{8u,0u}) if(auto text=skill->DisplayName.Str[locale];text&&text[0]) {title=text;break;}
        if(title.empty()&&TreeTitles.count(l.tree)) title=TreeTitles[l.tree];
        BranchTitles[l.tag]=title;
    }
    for(auto& [id,l]:TalentLayout)
    {
        auto const& xs=columns[l.tag];auto const& ys=rows[l.tag];
        l.col=std::distance(xs.begin(),xs.find(l.x))+l.offset;
        l.row=std::distance(ys.begin(),ys.find(l.y));
    }
    for(auto edge:sTraitEdgeStore) for(auto const& [child,layout]:TalentLayout)
        if(layout.node==uint32(edge->RightTraitNodeID)) for(auto const& [parent,p]:TalentLayout)
            if(p.node==edge->LeftTraitNodeID&&layout.tag==p.tag) TalentParents[child].push_back(parent);
}
static bool TalentBuildValid(Player* p,State const& s);
static uint32 TalentCap=71;
static bool Ready=false;
static uint32 Limit=8;

static bool SupportedClass(uint32 id) { return id>=1&&id<=11; }
static uint32 ClassLevel(Player* p,State const& s,uint32 owner)
{
    if(owner==p->GetClass()) return p->GetLevel();
    auto it=s.classes.find(owner);
    return std::min<uint32>({40,p->GetLevel(),it==s.classes.end()?1:it->second.level});
}
static uint32 ActiveLevel(Player* p,State const& s) { return s.active?ClassLevel(p,s,s.active):0; }
static void SyncEquipment(Player* p,State& s)
{
    std::set<uint32> skills,spells;uint32 weapons=0,armor=0,level=ActiveLevel(p,s);bool dual=false;
    if(s.equipmentInitialized&&s.equipmentClass==s.active&&s.equipmentLevel==level) return;
    if(s.active) for(auto const& e:EquipmentCatalog)
    {
        if(e.level>level) continue;
        bool allowed=e.mask&&(e.mask&(1u<<(s.active-1)));
        for(auto row:sDB2Manager.GetSkillRaceClassInfo(e.skill))
            if((uint32(row->ClassMask)&(1u<<(s.active-1)))&&uint32(std::max<int32>(0,row->MinLevel))<=level&&row->RaceMask.HasRace(p->GetRace())) allowed=true;
        if(allowed) {if(!e.dual) skills.insert(e.skill);spells.insert(e.spell);weapons|=e.weapons;armor|=e.armor;dual|=e.dual;}
    }
    p->SyncForeverAdvancementEquipment(s.active,skills,uint16(std::min<uint32>(65535,std::max<uint32>(1,level*5))),weapons,armor,dual);
    s.equipmentSpells=std::move(spells);
    s.talentStatusDirty=true;
    s.equipmentInitialized=true;s.equipmentClass=s.active;s.equipmentLevel=level;
}
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
static void SyncBookSchools(Player* p,State const& s);
static State& Get(Player* p)
{
    uint64 guid=p->GetGUID().GetCounter();auto [it,inserted]=States.try_emplace(guid);auto& s=it->second;
    if(inserted)
    {
        if(auto rows=CharacterDatabase.PQuery("SELECT entry_id FROM forever_advancement_spells WHERE guid={}",guid))
            do { s.learned.insert(ForeverAdvancementCustom::Canonical(rows->Fetch()[0].GetUInt32())); } while(rows->NextRow());
        if(auto rows=CharacterDatabase.PQuery("SELECT entry_id,rank_value FROM forever_advancement_talents WHERE guid={}",guid))
            do { auto f=rows->Fetch();s.talents[f[0].GetUInt32()]=f[1].GetUInt32(); } while(rows->NextRow());
        if(auto rows=CharacterDatabase.PQuery("SELECT power_type,current_value FROM forever_advancement_resources WHERE guid={}",guid))
            do { auto f=rows->Fetch();uint32 id=f[0].GetUInt32();if(id==0||id==1||id==3) s.pools[Powers(id)]={int32(std::min<uint32>(f[1].GetUInt32(),1000000)),1000000,0}; } while(rows->NextRow());
        if(auto rows=CharacterDatabase.PQuery("SELECT class_id,level_value,xp_value FROM forever_advancement_class_progress WHERE guid={}",guid))
            do { auto f=rows->Fetch();uint32 owner=f[0].GetUInt32();if(SupportedClass(owner)&&owner!=p->GetClass()) s.classes[owner]={std::clamp<uint32>(f[1].GetUInt32(),1,40),f[2].GetUInt64()}; } while(rows->NextRow());
        if(auto row=CharacterDatabase.PQuery("SELECT xp_enabled,xp_remainder FROM forever_advancement_preferences WHERE guid={}",guid))
        { auto f=row->Fetch();s.experienceEnabled=f[0].GetUInt32()!=0;s.experienceCarry=f[1].GetUInt32()%100; }
        if(auto row=CharacterDatabase.PQuery("SELECT active_class FROM forever_advancement_class_state WHERE guid={}",guid))
        { uint32 owner=row->Fetch()[0].GetUInt32();if(SupportedClass(owner)&&owner!=p->GetClass()) s.active=owner; }
    }
    // Keep old rows for rollback/history; attach only exact native identities to new entries.
    if(inserted) for(auto const& [oldId,nativeId]:LegacyAbilityIds) if(s.learned.count(oldId)) s.learned.insert(nativeId);
    SyncEquipment(p,s);SyncTalents(p,s);SyncBookSchools(p,s);SyncSpellbook(p,s);Refresh(p,s);return s;
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
    tx->PAppend("REPLACE INTO forever_advancement_class_state (guid,active_class) VALUES ({},{})",guid,s.active);
    for(auto const& [owner,progress]:s.classes)
        tx->PAppend("REPLACE INTO forever_advancement_class_progress (guid,class_id,level_value,xp_value) VALUES ({},{},{},{})",guid,owner,progress.level,progress.xp);
    tx->PAppend("REPLACE INTO forever_advancement_preferences (guid,xp_enabled,xp_remainder) VALUES ({},{},{})",guid,s.experienceEnabled?1:0,s.experienceCarry);
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
static Definition const* BestFor(Player* p,State const& s,uint32 entry)
{
    auto it=Catalog.find(entry);if(it==Catalog.end()||it->second.empty()) return nullptr;
    return Best(entry,ClassLevel(p,s,it->second.front().owner));
}
static void SyncBookSchools(Player* p,State const& s)
{
    std::set<uint32> skills;
    for(auto entry:[&] {auto all=s.learned;for(auto const& [id,rank]:s.talents) if(rank) all.insert(id);return all;}())
        if(auto d=BestFor(p,s,entry);d&&d->owner!=p->GetClass()&&d->owner==s.active)
        {
            auto bounds=sSpellMgr->GetSkillLineAbilityMapBounds(d->spell);
            for(auto it=bounds.first;it!=bounds.second;++it)
            {
                auto ability=it->second;auto skill=sSkillLineStore.LookupEntry(ability->SkillLine);
                if(!skill||skill->CategoryID!=SKILL_CATEGORY_CLASS||skill->ParentSkillLineID) continue;
                if(ability->ClassMask&&!(uint32(ability->ClassMask)&(1u<<(d->owner-1)))) continue;
                skills.insert(skill->ID);
            }
        }
    p->SyncForeverAdvancementClassSkills(skills);
}
static bool TemporaryBookSpell(Player* p,uint32 spell)
{
    auto const& spells=p->GetSpellMap();auto it=spells.find(spell);
    return it!=spells.end()&&it->second.state==PLAYERSPELL_TEMPORARY;
}
static void SyncSpellbook(Player* p,State& s)
{
    std::set<uint32> desired=s.equipmentSpells;
    for(auto entry:s.learned)
        if(auto d=BestFor(p,s,entry);d&&d->owner!=p->GetClass()&&d->owner==s.active) desired.insert(d->spell);
    if(TalentBuildValid(p,s)) for(auto const& [id,rank]:s.talents)
        if(auto it=TalentCatalog.find(id);it!=TalentCatalog.end()&&rank&&rank<=it->second.size())
        {auto const& d=it->second[rank-1];if(d.owner==s.active) if(auto info=sSpellMgr->GetSpellInfo(d.spell,DIFFICULTY_NONE);info&&!info->IsPassive()) desired.insert(d.spell);}
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
    for(auto entry:s.learned) if(auto d=BestFor(p,s,entry);d&&d->spell==spell&&d->owner!=p->GetClass()&&d->owner==s.active) return entry;
    for(auto const& [id,rank]:s.talents) if(rank&&TalentCatalog.count(id)&&rank<=TalentCatalog.at(id).size())
        {auto const& d=TalentCatalog.at(id)[rank-1];if(d.owner==s.active&&d.spell==spell) return id;}
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
static uint32 TalentBudget(Player* p,State const& s) { uint32 level=ActiveLevel(p,s);return level<10?0:std::min<uint32>(TalentCap,level-9); }
static uint32 TalentSpent(State const& s)
{
    uint32 spent=0;
    for(auto const& [id,rank]:s.talents) if(auto d=Talent(id,rank);d&&d->owner==s.active) spent+=rank*d->cost;
    return spent;
}
static bool TalentBuildValid(Player* p,State const& s)
{
    if(s.active&&s.active==p->GetClass()) return false;
    if(TalentSpent(s)>TalentBudget(p,s)) return false;
    auto spec=sDB2Manager.GetDefaultChrSpecializationForClass(s.active);if(!spec) return TalentSpent(s)==0;
    WorldPackets::Traits::TraitConfig config;config.Type=TraitConfigType::Combat;config.ChrSpecializationID=spec->ID;
    for(auto const& [id,rank]:s.talents) if(auto d=Talent(id,rank);d&&d->owner==s.active)
    {
        if(!d->node||d->level>ActiveLevel(p,s)) return false;
        WorldPackets::Traits::TraitEntry entry;entry.TraitNodeID=d->node;entry.TraitNodeEntryID=d->traitEntry;entry.Rank=rank;config.Entries.push_back(entry);
    }
    TraitMgr::PlayerDataAccessor accessor(p,ActiveLevel(p,s));
    for(auto const& granted:TraitMgr::GetGrantedTraitEntriesForConfig(config,accessor))
    {
        bool merged=false;for(auto& entry:config.Entries) if(entry.TraitNodeID==granted.TraitNodeID&&entry.TraitNodeEntryID==granted.TraitNodeEntryID)
        {entry.GrantedRanks=granted.GrantedRanks;merged=true;break;}
        if(!merged) config.Entries.emplace_back(granted);
    }
    return TraitMgr::ValidateConfig(config,accessor,false,false)==TraitMgr::LearnResult::Ok;
}

static void SyncTalents(Player* p,State& s)
{
    if(s.syncing) return;
    s.syncing=true;
    std::set<uint32> desired;std::map<uint32,std::pair<uint32,uint32>> traits;
    if(TalentBuildValid(p,s))
        for(auto const& [id,rank]:s.talents) if(auto d=Talent(id,rank);d&&d->owner==s.active)
        {
            if(auto info=sSpellMgr->GetSpellInfo(d->spell,DIFFICULTY_NONE);info&&info->IsPassive()) desired.insert(d->spell);
            if(d->trait) traits[d->spell]={d->trait,d->rank};
        }
    for(auto it=s.ownedAuras.begin();it!=s.ownedAuras.end();)
        if(p->HasSpell(*it)) { it=s.ownedAuras.erase(it); }
        else if(!desired.count(*it)||(s.ownedTraits.count(*it)&&(!traits.count(*it)||traits.at(*it)!=s.ownedTraits.at(*it))))
        { p->RemoveAurasDueToSpell(*it,p->GetGUID());it=s.ownedAuras.erase(it); }
        else ++it;
    for(auto it=s.ownedTraits.begin();it!=s.ownedTraits.end();)
        if(!traits.count(it->first)||traits.at(it->first)!=it->second||(p->HasSpell(it->first)&&!TemporaryBookSpell(p,it->first)))
        { p->SetForeverAdvancementTrait(it->first,0,0);it=s.ownedTraits.erase(it); }
        else ++it;
    for(auto const& [spell,trait]:traits) if((!p->HasSpell(spell)||TemporaryBookSpell(p,spell))&&(!desired.count(spell)||!p->HasAura(spell)||s.ownedAuras.count(spell)))
    { p->SetForeverAdvancementTrait(spell,trait.first,trait.second);s.ownedTraits[spell]=trait; }
    if(p->IsAlive()) for(auto spell:desired)
        if(!p->HasAura(spell)&&!p->HasSpell(spell)&&p->HandlePassiveSpellLearn(sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE)))
        {
            auto trait=traits.find(spell);
            if(trait!=traits.end()) p->SetForeverAdvancementTrait(spell,trait->second.first,trait->second.second);
            if(p->AddAura(spell,p))
            { s.ownedAuras.insert(spell);if(trait!=traits.end()) s.ownedTraits[spell]=trait->second; }
            else if(trait!=traits.end()) p->SetForeverAdvancementTrait(spell,0,0);
        }
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
    if(ForeverAdvancementCustom::Find(d.entry)) return false;
    if(d.owner!=s.active||d.owner==p->GetClass()||!(s.learned.count(d.entry)||(s.talents.count(d.entry)&&s.talents.at(d.entry)>0&&TalentBuildValid(p,s)))||d.level>ClassLevel(p,s,d.owner)||!p->IsAlive()) return false;
    auto info=sSpellMgr->GetSpellInfo(d.spell,DIFFICULTY_NONE);if(!info||!CompatibleCosts(info)) return false;
    for(auto power:PowersList) if(Available(p,s,power)<Cost(p,info,power)) return false;
    return true;
}
static uint32 CustomMagicCount(Player* p,State const& s)
{
    return ForeverAdvancementCustom::MagicCount(p->GetClass(),s.learned,[](uint32 entry)
    {
        auto it=Catalog.find(entry);
        return it==Catalog.end()||it->second.empty()?0u:it->second.front().owner;
    });
}
static void Snapshot(Player* p,State& s,bool includeCatalog=false)
{
    Send(p,"PROTOCOL 3");
    Send(p,Trinity::StringFormat("STATE {} {} {} {}",p->GetClass(),p->GetLevel(),Used(s),Limit));
    Send(p,Trinity::StringFormat("ACTIVE {}",s.active));
    Send(p,Trinity::StringFormat("XP_SHARE {} 90",s.experienceEnabled?1:0));
    Send(p,"TREES");Send(p,"SCHOOLS 1");Send(p,"GEAR 1");
    for(uint32 owner=1;owner<=11;++owner) if(owner!=p->GetClass())
    {
        uint32 level=ClassLevel(p,s,owner);auto it=s.classes.find(owner);
        uint64 xp=it==s.classes.end()?0:it->second.xp;
        Send(p,Trinity::StringFormat("CLASS {} {} {} {}",owner,level,xp,level<std::min<uint32>(40,p->GetLevel())?sObjectMgr->GetXPForLevel(level):0));
    }
    for(auto power:PowersList)
        Send(p,Trinity::StringFormat("POWER {} {} {}",uint32(power),Available(p,s,power),Native(p,power)?p->GetMaxPower(power)/Scale(power):s.pools.at(power).maximum));
    double regen=std::max(0.0,double(p->GetStat(STAT_SPIRIT)))*0.2;
    Send(p,Trinity::StringFormat("REGEN {} {}",regen,regen*0.3));
    if(includeCatalog)
    {
        Send(p,"CATALOG NATIVE");
        for(auto const& [id,row]:NativeMenu)
        {
            auto d=row.kind==0?BestFor(p,s,id):nullptr;
            if(!d&&Catalog.count(id)) d=&Catalog.at(id).front();
            Send(p,Trinity::StringFormat("NATIVE {} {} {} {} {} {} {} {} {}",id,row.owner,d?d->spell:row.spell,d?d->level:row.level,row.kind,row.max,row.traitEntry,row.available?1:0,row.reason));
        }
    }
    if(includeCatalog)
    {
        std::set<std::string> sent;
        for(auto const& [id,l]:TalentLayout)
        {
            if(sent.insert(l.tag).second) Send(p,Trinity::StringFormat("TREE {} {} {} {}",l.tag,Hex(BranchTitles[l.tag]),BranchSchools[l.tag],BranchTrees[l.tag]));
            Send(p,Trinity::StringFormat("TNODE {} {} {} {}",id,l.tag,l.col,l.row));
        }
        for(auto const& [id,parents]:TalentParents) for(auto parent:parents) Send(p,Trinity::StringFormat("TEDGE {} {}",id,parent));
    }
    if(includeCatalog) for(auto const& [id,definitions]:Catalog)
    {
        auto const* d=BestFor(p,s,id);if(!d) d=&definitions.front();
        Send(p,Trinity::StringFormat("ENTRY {} {} {} {} {}",id,d->spell,d->level,s.learned.count(id)?1:0,d->owner));
    }
    if(!includeCatalog) for(auto id:s.learned)
        if(auto d=BestFor(p,s,id)) Send(p,Trinity::StringFormat("ENTRY {} {} {} 1 {}",id,d->spell,d->level,d->owner));
    if(includeCatalog) for(auto const& [id,ranks]:TalentCatalog)
    {
        auto const& d=ranks.front();
        Send(p,Trinity::StringFormat("TENTRY {} {} {} {} {} {} {} {} {}",id,ranks.size(),d.level,d.cost,d.investment,d.owner,d.spell,d.trait,d.traitEntry));
    }
    for(auto const& [id,definitions]:Catalog)
    {
        Definition const* known=nullptr;
        for(auto const& d:definitions) if(p->HasSpell(d.spell)&&(!known||d.level>known->level)) known=&d;
        if(known) Send(p,Trinity::StringFormat("KNOWN {} {}",id,known->spell));
    }
    uint32 spent=TalentSpent(s),budget=TalentBudget(p,s);
    Send(p,Trinity::StringFormat("TPOINTS {} {} {}",spent<budget?budget-spent:0,spent,budget));
    for(auto const& [id,rank]:s.talents) if(auto d=Talent(id,rank))
    {
        Send(p,Trinity::StringFormat("TALENT {} {} {}",id,rank,d->spell));
        if(auto aura=p->GetAura(d->spell,p->GetGUID());aura&&s.ownedAuras.count(d->spell))
            for(auto const& effect:sSpellMgr->GetSpellInfo(d->spell,DIFFICULTY_NONE)->GetEffects())
                if(auto applied=aura->GetEffect(effect.EffectIndex))
                    Send(p,Trinity::StringFormat("TEFFECT {} {} {}",id,effect.EffectIndex,applied->GetAmount()));
    }
    if(includeCatalog||s.talentStatusDirty)
    {
        for(auto const& [id,rows]:TalentCatalog)
        {
            bool learn=false,refund=false;uint32 rank=s.talents.count(id)?s.talents.at(id):0;
            if(rows.front().owner==s.active&&s.active!=p->GetClass())
            {
                auto candidate=s;
                if(rank<rows.size()) {candidate.talents[id]=rank+1;learn=TalentBuildValid(p,candidate);}
                if(rank) {candidate.talents[id]=rank-1;if(rank==1) candidate.talents.erase(id);refund=TalentBuildValid(p,candidate);}
            }
            Send(p,Trinity::StringFormat("TREADY {} {} {}",id,learn?1:0,refund?1:0));
        }
        s.talentStatusDirty=false;
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
    bool argument=command=="learn"||command=="unlearn"||command=="cast"||command=="talent"||command=="untalent"||command=="activate"||command=="xpshare";
    if((argument&&!(input>>arg))||(input>>extra)) { Error(p,"invalid_request");return; }
    if(command=="learn"||command=="unlearn"||command=="cast") arg=ForeverAdvancementCustom::Canonical(arg);
    if(command=="status") { Snapshot(p,s,true);return; }
    if(command=="poll") { Snapshot(p,s);return; }
    if(command=="learn"||command=="cast")
        if(auto rule=ForeverAdvancementCustom::Find(arg))
        {
            if(!ForeverAdvancementCustom::RequirementsMet(*rule,CustomMagicCount(p,s))) Error(p,"custom_class_requirements");
            else Error(p,"custom_requires_port");
            return;
        }
    if(command=="cast")
    {
        auto d=BestFor(p,s,arg);if(!d||!CanCast(p,s,*d)) { Error(p,"unavailable_or_power");return; }
        auto info=sSpellMgr->GetSpellInfo(d->spell,DIFFICULTY_NONE);Unit* target=p->GetSelectedUnit();if(!target&&info->IsPositive()) target=p;
        if(!target) { Error(p,"select_target");return; }
        auto result=p->CastSpell(target,d->spell,CastSpellExtraArgs(TRIGGERED_IGNORE_POWER_COST).SetCustomArg(CastTag{arg}));
        if(result!=SPELL_CAST_OK) Send(p,Trinity::StringFormat("ERROR native_cast_{}",uint32(result)));
        return;
    }
    if(command=="xpshare")
    {
        if(arg>1) { Error(p,"invalid_request");return; }
        s.experienceEnabled=arg!=0;s.experienceCarry=0;Save(p,s);Snapshot(p,s);return;
    }
    if(p->IsInCombat()||!p->IsAlive()||p->HasUnitState(UNIT_STATE_CASTING)) { Error(p,"cannot_edit_now");return; }
    if(command=="activate")
    {
        if(arg&&(!SupportedClass(arg)||arg==p->GetClass())) { Error(p,"invalid_subclass");return; }
        auto previous=s.active;s.active=arg;if(arg) s.classes.try_emplace(arg);SyncEquipment(p,s);SyncSpellbook(p,s);
        for(uint8 slot=EQUIPMENT_SLOT_START;slot<EQUIPMENT_SLOT_END;++slot)
            if(auto item=p->GetItemByPos(INVENTORY_SLOT_BAG_0,slot);item&&(p->CanUseItem(item,false)!=EQUIP_ERR_OK||(slot==EQUIPMENT_SLOT_OFFHAND&&item->GetTemplate()->GetClass()==ITEM_CLASS_WEAPON&&!p->CanDualWield())))
            {s.active=previous;SyncEquipment(p,s);SyncSpellbook(p,s);Error(p,"remove_foreign_equipment");return;}
        if(previous==CLASS_HUNTER&&arg!=CLASS_HUNTER&&p->GetClass()!=CLASS_HUNTER)
            if(auto pet=p->GetPet();pet&&pet->getPetType()==HUNTER_PET) p->RemovePet(pet,PET_SAVE_AS_CURRENT);
        SyncTalents(p,s);SyncBookSchools(p,s);SyncSpellbook(p,s);Refresh(p,s);Save(p,s);Snapshot(p,s,true);return;
    }
    if(command=="talent"||command=="untalent")
    {
        auto node=Talent(arg,1);
        if(!node||!s.active||node->owner!=s.active) { Error(p,"select_subclass");return; }
        uint32 rank=s.talents.count(arg)?s.talents.at(arg):0;
        uint32 next=command=="talent"?rank+1:rank?rank-1:0;
        if(next==rank||!Talent(arg,command=="talent"?next:rank)) { Error(p,"talent_unavailable");return; }
        auto candidate=s;candidate.talents[arg]=next;if(!next) candidate.talents.erase(arg);
        if(!TalentBuildValid(p,candidate)&&!(command=="untalent"&&!TalentBuildValid(p,s))) { Error(p,"talent_requirements");return; }
        s.talents=std::move(candidate.talents);s.talentStatusDirty=true;SyncTalents(p,s);SyncSpellbook(p,s);Refresh(p,s);
    }
    else if(command=="learn")
    {
        auto d=BestFor(p,s,arg);if(!d||d->owner==p->GetClass()) { Error(p,"incompatible_or_level");return; }
        if(s.learned.count(arg)||p->HasSpell(d->spell)) { Error(p,"already_learned");return; }
        if(Used(s)>=Limit) { Error(p,"ability_limit");return; }
        s.learned.insert(arg);
    }
    else if(command=="unlearn")
    {
        auto candidate=s;candidate.learned.erase(arg);
        for(auto const& [oldId,nativeId]:LegacyAbilityIds) if(nativeId==arg) candidate.learned.erase(oldId);
        for(auto entry:s.learned) if(entry!=arg)
            if(auto rule=ForeverAdvancementCustom::Find(entry);rule&&
                ForeverAdvancementCustom::RequirementsMet(*rule,CustomMagicCount(p,s))&&
                !ForeverAdvancementCustom::RequirementsMet(*rule,CustomMagicCount(p,candidate)))
            { Error(p,"refund_custom_first");return; }
        s.learned=std::move(candidate.learned);
    }
    else { Error(p,"invalid_request");return; }
    SyncBookSchools(p,s);SyncSpellbook(p,s);Save(p,s);Snapshot(p,s);
}
static void GrantClassXP(Player* p,State& s,uint32& amount)
{
    if(!s.active||!s.experienceEnabled) return;
    auto& progress=s.classes[s.active];
    amount=ForeverAdvancementExperience::Grant(progress,std::min<uint32>(40,p->GetLevel()),amount,
        s.experienceEnabled,s.experienceCarry,[](uint32 level) { return sObjectMgr->GetXPForLevel(level); });
}
class Players final:public PlayerScript
{
public:
    Players():PlayerScript("forever_advancement_players") { }
    void OnLogin(Player* p,bool) override { if(Ready&&SupportedClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> lock(Mutex);Get(p); } }
    void OnGiveXP(Player* p,uint32& amount,Unit*) override
    {
        if(!Ready||!amount||!SupportedClass(p->GetClass())) return;
        std::lock_guard<std::recursive_mutex> lock(Mutex);auto& s=Get(p);
        if(!s.active) return;
        uint32 previous=ActiveLevel(p,s);GrantClassXP(p,s,amount);SyncEquipment(p,s);
        SyncTalents(p,s);SyncBookSchools(p,s);SyncSpellbook(p,s);Save(p,s);Snapshot(p,s,previous!=ActiveLevel(p,s));
    }
    void OnSave(Player* p) override { if(Ready&&SupportedClass(p->GetClass())) { std::lock_guard<std::recursive_mutex> lock(Mutex);Save(p,Get(p)); } }
    void OnLogout(Player* p) override { std::lock_guard<std::recursive_mutex> lock(Mutex);auto it=States.find(p->GetGUID().GetCounter());if(it!=States.end()) { Save(p,it->second);for(auto spell:it->second.ownedAuras) p->RemoveAurasDueToSpell(spell,p->GetGUID());for(auto const& [spell,trait]:it->second.ownedTraits) p->SetForeverAdvancementTrait(spell,0,0);States.erase(it); } }
    void OnDelete(ObjectGuid guid,uint32) override
    {
        if(!Ready) return;std::lock_guard<std::recursive_mutex> lock(Mutex);States.erase(guid.GetCounter());auto tx=CharacterDatabase.BeginTransaction();
        for(char const* table:{"forever_advancement_spells","forever_advancement_resources","forever_advancement_talents","forever_advancement_class_progress","forever_advancement_class_state","forever_advancement_preferences"}) tx->Append(Trinity::StringFormat("DELETE FROM {} WHERE guid={}",table,guid.GetCounter()).c_str());
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
        case 5:return 6;case 7:return 11;case 8:return 3;case 9:return 5;case 11:return 7;case 6:return 15;case 10:return 53;case 12:return 107;case 13:return 224;default:return 0; }
}
static bool PlayerClassAbility(uint32 owner,uint32 spell,uint32 family,bool mounted)
{
    if(mounted) return false;
    if(family==ClassFamily(owner)) return true;
    if(family!=0) return false;
    // Reviewed generic utility exceptions; generic collection/quest spells
    // never become class abilities just because a broad SkillLine lists them.
    return (owner==3&&(spell==75||spell==883||spell==1515||spell==2641||spell==982||spell==6991||spell==136))||(owner==9&&spell==126);
}
static SpellInfo const* NativeClassSpell(uint32 spell,uint32 owner)
{
    auto info=sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE);
    if(!info||!info->SpellName||(info->SpellFamilyName&&info->SpellFamilyName!=ClassFamily(owner))) return nullptr;
    bool named=false;for(auto name:info->SpellName->Str) if(name&&name[0]) named=true;
    if(!named) return nullptr;
    auto bounds=sSpellMgr->GetSkillLineAbilityMapBounds(spell);
    for(auto it=bounds.first;it!=bounds.second;++it)
    {
        auto ability=it->second;auto skill=sSkillLineStore.LookupEntry(ability->SkillLine);
        if(!skill||skill->CategoryID!=SKILL_CATEGORY_CLASS||skill->ParentSkillLineID) continue;
        if(ability->ClassMask&&!(uint32(ability->ClassMask)&(1u<<(owner-1)))) continue;
        for(auto classInfo:sDB2Manager.GetSkillRaceClassInfo(skill->ID))
            if(uint32(classInfo->ClassMask)&(1u<<(owner-1))) return info;
    }
    return nullptr;
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
using TalentOwners=std::map<uint32,std::set<std::pair<uint32,uint32>>>;
static SpellInfo const* ResolveNativeTalent(uint32 spell,uint32 owner,uint32 rank,TalentOwners const& owners)
{
    auto it=owners.find(spell);
    if(it==owners.end()||!it->second.count({owner,rank})) return nullptr;
    return sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE);
}
struct NativeTrait { uint32 definition,spell,owner,max,entry=0,node=0,tree=0;int32 x=0,y=0,choice=0; };
using NativeTraits=std::map<uint32,std::vector<NativeTrait>>;
static NativeTrait const* ResolveTrait(uint32 first,uint32 owner,uint32 rank,NativeTraits const& traits)
{
    auto it=traits.find(first);if(it==traits.end()) return nullptr;
    NativeTrait const* found=nullptr;
    for(auto const& row:it->second)
        if(row.owner==owner&&rank<=row.max)
        {
            if(found&&(found->definition!=row.definition||found->spell!=row.spell)) return nullptr;
            if(!found||row.max<found->max) found=&row;
        }
    return found;
}
static NativeTraits LoadNativeTraits()
{
    std::map<uint32,uint32> classes;
    for(auto link:sSkillLineXTraitTreeStore)
    {
        auto skill=sSkillLineStore.LookupEntry(link->SkillLineID);
        if(!skill||!PlayerClassSchool(skill->CategoryID,skill->Flags)) continue;
        classes[link->TraitTreeID]|=SchoolClassMask(skill->ID);
    }
    NativeTraits traits;
    for(auto link:sTraitNodeXTraitNodeEntryStore)
    {
        auto node=sTraitNodeStore.LookupEntry(link->TraitNodeID);
        auto entry=sTraitNodeEntryStore.LookupEntry(link->TraitNodeEntryID);
        if(!node||!entry||entry->MaxRanks<=0||entry->MaxRanks>127) continue;
        auto classMask=classes.find(node->TraitTreeID);if(classMask==classes.end()) continue;
        auto definition=sTraitDefinitionStore.LookupEntry(entry->TraitDefinitionID);
        if(!definition||definition->ID>0x7fffff||definition->SpellID<=0) continue;
        for(uint32 owner=1;owner<=11;++owner)
            if(classMask->second&(1u<<(owner-1)))
            {
                NativeTrait trait{definition->ID,uint32(definition->SpellID),owner,uint32(entry->MaxRanks),entry->ID,node->ID,node->TraitTreeID,node->PosX,node->PosY,link->Index};
                traits[trait.spell].push_back(trait);
                if(definition->VisibleSpellID>0&&uint32(definition->VisibleSpellID)!=trait.spell) traits[definition->VisibleSpellID].push_back(trait);
            }
    }
    TC_LOG_INFO("scripts","ForeverAdvancement trait metadata: {} class trees; {} spell keys",classes.size(),traits.size());
    uint32 examples=0;
    for(auto const& [key,records]:traits)
        if(!records.empty()&&examples++<6)
        {
            auto const& row=records.front();
            TC_LOG_INFO("scripts","ForeverAdvancement trait sample: key={} spell={} definition={} owner={} max={} native={}",key,row.spell,row.definition,row.owner,row.max,NativeNames(sSpellMgr->GetSpellInfo(row.spell,DIFFICULTY_NONE)));
        }
    return traits;
}
static void PublishBookMetadata()
{
    std::set<uint32> rows;
    for(auto const& [id,definitions]:Catalog)
        for(auto const& d:definitions)
        {
            auto bounds=sSpellMgr->GetSkillLineAbilityMapBounds(d.spell);
            for(auto it=bounds.first;it!=bounds.second;++it)
            {
                auto ability=it->second;auto skill=sSkillLineStore.LookupEntry(ability->SkillLine);
                if(!skill||skill->CategoryID!=SKILL_CATEGORY_CLASS||skill->ParentSkillLineID||!ability->ClassMask) continue;
                if(uint32(ability->ClassMask)&(1u<<(d.owner-1))) rows.insert(ability->ID);
            }
        }
    DB2HotfixGenerator<SkillLineAbilityEntry> hotfix(sSkillLineAbilityStore);
    for(auto id:rows) hotfix.ApplyHotfix(id,[](SkillLineAbilityEntry* row) { row->ClassMask=0; },true);
    TC_LOG_INFO("scripts","ForeverAdvancement spellbook metadata: {} native class masks published to client",rows.size());
}
static void PublishBookSchoolMetadata()
{
    std::map<uint32,uint32> skills;
    for(auto const& [id,definitions]:Catalog) for(auto const& d:definitions)
    {
        auto bounds=sSpellMgr->GetSkillLineAbilityMapBounds(d.spell);
        for(auto it=bounds.first;it!=bounds.second;++it)
        {
            auto skill=sSkillLineStore.LookupEntry(it->second->SkillLine);
            if(skill&&skill->CategoryID==SKILL_CATEGORY_CLASS&&!skill->ParentSkillLineID&&
                (!it->second->ClassMask||(uint32(it->second->ClassMask)&(1u<<(d.owner-1)))))
                skills[skill->ID]|=1u<<(d.owner-1);
        }
    }
    uint32 count=0;
    for(auto row:sSkillRaceClassInfoStore)
        if(auto it=skills.find(row->SkillID);it!=skills.end()&&(uint32(row->ClassMask)&it->second))
        { sDB2Manager.PublishForeverAdvancementBookSchool(row->ID);++count; }
    TC_LOG_INFO("scripts","ForeverAdvancement book school metadata: {} client-only class records; server masks preserved",count);
}
static NativeTrait const* ResolveNamedTrait(uint32 owner,std::array<char const*,9> const& names,NativeTraits const& traits,NameIndex const& index)
{
    NativeTrait const* found=nullptr;
    for(auto name:names)
    {
        auto key=NameKey(name);if(key.empty()) continue;
        auto it=index.find(key);if(it==index.end()) continue;
        for(auto info:it->second)
        {
            auto candidate=ResolveTrait(info->Id,owner,1,traits);
            if(!candidate) continue;
            if(found&&(found->definition!=candidate->definition||found->spell!=candidate->spell)) return nullptr;
            if(!found||candidate->max<found->max) found=candidate;
        }
    }
    return found;
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
        for(auto table:{"forever_advancement_spells","forever_advancement_resources","forever_advancement_talents","forever_advancement_class_progress","forever_advancement_class_state","forever_advancement_preferences"})
            if(!CharacterDatabase.Query(Trinity::StringFormat("SELECT COUNT(*) FROM {}",table).c_str())) { TC_LOG_ERROR("scripts","ForeverAdvancement schema missing: {}",table);return; }
        uint32 script=sObjectMgr->GetScriptId("spell_forever_advancement");std::set<uint32> claimed;
        if(!script) { TC_LOG_ERROR("scripts","ForeverAdvancement script registration missing");return; }
        std::ofstream audit(sConfigMgr->GetStringDefault("LogsDir","logs")+"/ForeverAdvancement-catalog.tsv");
        if(audit) audit<<"origin\tclass\tspell\tstatus\n";
        auto record=[&](char const* origin,uint32 owner,uint32 spell,char const* status)
        { if(audit) audit<<origin<<'\t'<<owner<<'\t'<<spell<<'\t'<<status<<'\n'; };
        uint32 accepted=0,rejected=0;
        for(auto ability:sSkillLineAbilityStore)
        {
            auto skill=sSkillLineStore.LookupEntry(ability->SkillLine);
            if(!skill||!PlayerClassSchool(skill->CategoryID,skill->Flags)||ability->Spell<=0) continue;
            uint32 schoolMask=SchoolClassMask(skill->ID);
            uint32 mask=ability->ClassMask?(uint32(ability->ClassMask)&schoolMask):schoolMask;
            for(uint32 owner=1;owner<=11;++owner) if(mask&(1u<<(owner-1)))
            {
                uint32 spell=uint32(ability->Spell);
                auto info=sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE);
                char const* reason="available";
                if(!info) reason="missing_spell";
                else if(std::any_of(ForeverAdvancementCustom::Rules.begin(),ForeverAdvancementCustom::Rules.end(),[&](auto const& rule){return rule.spell==spell;})) reason="custom_removed";
                else if(info->HasAura(SPELL_AURA_MOUNTED)) reason="collection_spell";
                else if(!PlayerClassAbility(owner,spell,info->SpellFamilyName,false)) reason="wrong_class";
                else if(info->IsPassive()) reason="passive";
                else if(ability->GetAcquireMethod()==SkillLineAbilityAcquireMethod::NeverLearned&&spell!=75&&spell!=883&&spell!=1515&&spell!=2641&&spell!=982&&spell!=6991&&spell!=136) reason="internal";
                else if(!CompatibleCosts(info)) reason="unsupported_resource";
                bool available=std::string_view(reason)=="available";
                record("native",owner,spell,reason);
                if(!info||std::string_view(reason)=="custom_removed"||std::string_view(reason)=="collection_spell"||std::string_view(reason)=="wrong_class"||std::string_view(reason)=="internal"||info->IsPassive()) continue;
                if(spell>=10000000) continue; // deterministic namespace disjoint from donor IDs
                uint32 first=sSpellMgr->GetFirstSpellInChain(spell);if(!first) first=spell;
                uint32 id=1000000000+owner*10000000+first;
                // A duplicate school must never downgrade a supported record.
                auto it=NativeMenu.find(id);if(it!=NativeMenu.end()&&it->second.available&&!available) continue;
                NativeMenu[id]={id,owner,spell,std::max<uint32>(1,info->SpellLevel),0,1,0,available,reason};
                if(!available) { ++rejected;continue; }
                sObjectMgr->RegisterForeverAdvancementBinding(spell,script);
                bool bound=false;auto bounds=sObjectMgr->GetSpellScriptsBounds(spell);
                for(auto bind=bounds.first;bind!=bounds.second;++bind) if(bind->second.first==script&&bind->second.second) bound=true;
                if(!bound) { NativeMenu[id].available=false;NativeMenu[id].reason="binding_failed";continue; }
                auto& definitions=Catalog[id];
                if(std::none_of(definitions.begin(),definitions.end(),[&](auto const& d){return d.spell==spell;}))
                { definitions.push_back({id,owner,spell,std::max<uint32>(1,info->SpellLevel)});++accepted; }
            }
        }
        for(uint32 spell:{75u,883u,1515u,2641u,982u,6991u,136u})
            if(auto info=sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE);info&&(info->SpellFamilyName==ClassFamily(3)||info->SpellFamilyName==0)&&CompatibleCosts(info)&&!info->HasAura(SPELL_AURA_MOUNTED))
            {
                uint32 id=1030000000+spell;sObjectMgr->RegisterForeverAdvancementBinding(spell,script);
                Catalog[id]={{id,3,spell,std::max<uint32>(1,info->SpellLevel)}};
                NativeMenu[id]={id,3,spell,std::max<uint32>(1,info->SpellLevel),0,1,0,true,"available"};
            }
        for(auto ability:sSkillLineAbilityStore)
            if(auto skill=sSkillLineStore.LookupEntry(ability->SkillLine);skill&&(skill->CategoryID==SKILL_CATEGORY_WEAPON||skill->CategoryID==SKILL_CATEGORY_ARMOR))
                if(auto info=sSpellMgr->GetSpellInfo(ability->Spell,DIFFICULTY_NONE);info&&info->HasEffect(SPELL_EFFECT_PROFICIENCY))
                    EquipmentCatalog.push_back({skill->ID,info->Id,std::max<uint32>(1,info->SpellLevel),info->EquippedItemClass==ITEM_CLASS_WEAPON?uint32(info->EquippedItemSubClassMask):0,info->EquippedItemClass==ITEM_CLASS_ARMOR?uint32(info->EquippedItemSubClassMask):0});
        for(auto ability:sSkillLineAbilityStore)
            if(auto info=sSpellMgr->GetSpellInfo(ability->Spell,DIFFICULTY_NONE);info&&info->HasEffect(SPELL_EFFECT_DUAL_WIELD))
                if(auto skill=sSkillLineStore.LookupEntry(ability->SkillLine);skill&&skill->CategoryID==SKILL_CATEGORY_CLASS)
                {uint32 mask=uint32(ability->ClassMask);if(!mask) for(auto row:sDB2Manager.GetSkillRaceClassInfo(skill->ID)) mask|=uint32(row->ClassMask);
                 EquipmentCatalog.push_back({skill->ID,info->Id,std::max<uint32>(1,info->SpellLevel),0,0,mask,true});}
        for(auto& [id,rows]:Catalog) std::sort(rows.begin(),rows.end(),[](auto const& a,auto const& b){return a.level<b.level;});
        for(auto const& row:AscensionSourceEntries)
        {
            uint32 first=sSpellMgr->GetFirstSpellInChain(row.spell);if(!first) first=row.spell;
            uint32 id=1000000000+row.owner*10000000+first;
            auto info=sSpellMgr->GetSpellInfo(row.spell,DIFFICULTY_NONE);
            if(!ForeverAdvancementCustom::Find(row.id)&&Catalog.count(id)&&info&&SourceNameMatches(info,row.names)) LegacyAbilityIds.emplace(row.id,id);
            record("legacy",row.owner,row.spell,LegacyAbilityIds.count(row.id)?"exact_native":"hidden_no_exact_native");
        }
        // Browse actual class-tree definitions. Legacy purchases remain saved but are not replayed
        // as native talents. Native allocation must use real node/choice/currency/condition rules.
        auto traits=LoadNativeTraits();std::set<std::pair<uint32,uint32>> seenTraits;std::set<uint32> nativeClasses;
        for(auto const& [spell,rows]:traits) for(auto const& row:rows)
        {
            if(!seenTraits.insert({row.owner,row.entry}).second||row.entry>=10000000) continue;
            auto info=sSpellMgr->GetSpellInfo(row.spell,DIFFICULTY_NONE);
            record("trait",row.owner,row.spell,info?"native_rules_required":"missing_spell");
            if(!info||(info->SpellFamilyName&&info->SpellFamilyName!=ClassFamily(row.owner))) continue;
            nativeClasses.insert(row.owner);
            uint32 id=1500000000+row.owner*10000000+row.entry;
            bool supported=CompatibleCosts(info)&&TraitMgr::GetConfigTypeForTree(row.tree)==TraitConfigType::Combat;
            auto safeCost=[](int32 id){auto cost=sTraitCostStore.LookupEntry(id);if(!cost||cost->Amount<=0) return true;auto currency=sTraitCurrencyStore.LookupEntry(cost->TraitCurrencyID);return currency&&currency->GetType()==TraitCurrencyType::TraitSourced;};
            for(auto cost:sTraitTreeXTraitCostStore) if(cost->TraitTreeID==row.tree&&!safeCost(cost->TraitCostID)) supported=false;
            for(auto cost:sTraitNodeXTraitCostStore) if(cost->TraitNodeID==row.node&&!safeCost(cost->TraitCostID)) supported=false;
            for(auto cost:sTraitNodeEntryXTraitCostStore) if(cost->TraitNodeEntryID==row.entry&&!safeCost(cost->TraitCostID)) supported=false;
            for(auto link:sTraitNodeGroupXTraitNodeStore) if(uint32(link->TraitNodeID)==row.node)
                for(auto cost:sTraitNodeGroupXTraitCostStore) if(cost->TraitNodeGroupID==link->TraitNodeGroupID&&!safeCost(cost->TraitCostID)) supported=false;
            if(info->IsPassive()) for(auto const& effect:info->GetEffects()) if(effect.IsEffect()&&!effect.IsAura()) supported=false;
            NativeMenu[id]={id,row.owner,row.spell,10,1,row.max,row.entry,supported,supported?"available":"unsupported_talent_effect"};
            TalentLayout[id]={row.node,row.tree,row.x,row.y,float(row.choice)*0.5f};
            if(auto tree=sTraitTreeStore.LookupEntry(row.tree)) for(uint32 locale:{8u,0u}) if(auto title=tree->TitleText.Str[locale];title&&title[0]) {TreeTitles[row.tree]=title;break;}
            for(uint32 rank=1;rank<=row.max;++rank)
                TalentCatalog[id].push_back({id,row.owner,row.spell,rank,10,1,0,row.tree,row.definition,row.entry,row.node,row.tree,row.x,row.y});
            if(!supported) TalentCatalog.erase(id);
            else if(!info->IsPassive()) {Catalog[id]={{id,row.owner,row.spell,10}};sObjectMgr->RegisterForeverAdvancementBinding(row.spell,script);}
        }
        // Forever may expose stock class talents through Talent.db2 as well as Trait*.
        // Read that client/core store, never the donor's AscensionTalentSourceEntries.
        for(auto talent:sTalentStore)
        {
            uint32 owner=talent->ClassID;if(!SupportedClass(owner)||nativeClasses.count(owner)||talent->ID>=10000000) continue;
            uint32 spell=talent->SpellID,max=0;
            for(auto rank:talent->SpellRank) if(rank) { if(!max) spell=rank;++max; }
            if(!spell) continue;if(!max) max=1;
            auto info=sSpellMgr->GetSpellInfo(spell,DIFFICULTY_NONE);
            record("talent",owner,spell,info?"native_rules_required":"missing_spell");
            if(!info||std::any_of(NativeMenu.begin(),NativeMenu.end(),[&](auto const& pair){return pair.second.kind==1&&pair.second.owner==owner&&pair.second.spell==spell;})) continue;
            uint32 id=1700000000+owner*10000000+talent->ID;
            NativeMenu[id]={id,owner,spell,std::max<uint32>(1,info->SpellLevel),1,max,0,false,"native_rules_required"};
            TalentLayout[id]={0,uint32(talent->TabID),int32(talent->ColumnIndex)*100,int32(talent->TierID)*100};
        }
        if(Catalog.empty()) { TC_LOG_ERROR("scripts","ForeverAdvancement native catalog empty; disabled");return; }
        TC_LOG_INFO("scripts","ForeverAdvancement equipment metadata: {} proficiency skill records",EquipmentCatalog.size());
        BuildTalentLayout();
        for(uint32 owner:{1u,2u,3u,4u,5u,7u,8u,9u,11u})
        {
            std::set<uint32> schools;
            for(auto const& [id,layout]:TalentLayout) if(NativeMenu.at(id).owner==owner&&BranchSchools[layout.tag]) schools.insert(BranchSchools[layout.tag]);
            if(schools.size()!=3) {TC_LOG_ERROR("scripts","ForeverAdvancement player school audit failed: class {} has {} schools, expected 3; original runtime must be retained",owner,schools.size());return;}
        }
        TC_LOG_INFO("scripts","ForeverAdvancement player school audit passed: three native schools for each classic class; pets and collections excluded");
        PublishBookSchoolMetadata();PublishBookMetadata();
        TC_LOG_INFO("scripts","ForeverAdvancement native catalogue: {} supported records; {} resource exclusions; {} native trait entries",accepted,rejected,seenTraits.size());
        TC_LOG_INFO("scripts","ForeverAdvancement catalog audit: {}; legacy talents hidden; no name substitutions",audit?"written to ForeverAdvancement-catalog.tsv":"could not open audit file");
        TC_LOG_INFO("scripts","ForeverAdvancement trait ranks: {} purchasable native nodes; native TraitMgr validation",TalentCatalog.size());
        TC_LOG_INFO("scripts","ForeverAdvancement custom rules: 0 visible abilities; protocol=3; version=1.14.0");
        Ready=true;TC_LOG_INFO("scripts","ForeverAdvancement ready: {} native ability entries; {} native talent nodes; {} slots",Catalog.size(),TalentCatalog.size(),Limit);
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
        std::lock_guard<std::recursive_mutex> lock(Mutex);auto p=GetCaster()->ToPlayer();auto& s=Get(p);auto d=BestFor(p,s,tag->entry);
        return d&&d->spell==GetSpellInfo()->Id&&CanCast(p,s,*d)?SPELL_CAST_OK:SPELL_FAILED_NO_POWER;
    }
    void Pay()
    {
        using namespace ForeverAdvancement;auto tag=std::any_cast<CastTag>(&GetSpell()->m_customArg);if(!tag) return;
        std::lock_guard<std::recursive_mutex> lock(Mutex);auto p=GetCaster()->ToPlayer();auto& s=Get(p);auto d=BestFor(p,s,tag->entry);
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
