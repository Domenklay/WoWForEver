#include "ScriptMgr.h"
#include "Player.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "ChatPackets.h"
#include "WorldSession.h"
#include "ObjectMgr.h"
#include "CreatureData.h"
#include "SpellMgr.h"
#include "SpellInfo.h"
#include "Map.h"
#include <algorithm>
#include <sstream>
#include <string>
#include <unordered_set>
#include <vector>

namespace ForeverEncyclopediaAbilities
{
constexpr char RequestPrefix[] = "FEB1";
constexpr char ResponsePrefix[] = "FBR1";

struct AbilityRow
{
    uint32 id = 0;
    uint32 schoolMask = 0;
    uint32 recovery = 0;
    uint32 categoryRecovery = 0;
    bool channeled = false;
    bool positive = false;
};

static uint32 Account(Player* player)
{
    return player && player->GetSession() ? player->GetSession()->GetAccountId() : 0;
}

static void Send(Player* player, std::string const& text)
{
    if (!player || !player->GetSession())
        return;

    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER, LANG_ADDON, player, player, text, 0, "", LOCALE_enUS, ResponsePrefix);
    player->GetSession()->SendPacket(packet.Write());
}

static bool HasAbilityKnowledge(Player* player)
{
    uint32 account = Account(player);
    if (!account)
        return false;

    if (QueryResult row = CharacterDatabase.PQuery(
            "SELECT `rank` FROM forever_encyclopedia_talent "
            "WHERE account_id={} AND talent_key='identify_abilities' LIMIT 1", account))
        return row->Fetch()[0].GetUInt32() > 0;

    return false;
}

static SpellInfo const* ResolveSpell(Player* player, uint32 spellId)
{
    if (!spellId)
        return nullptr;

    if (player && player->GetMap())
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId, player->GetMap()->GetDifficultyID()))
            return info;

    return sSpellMgr->GetSpellInfo(spellId, DIFFICULTY_NONE);
}

static void Inspect(Player* player, uint32 entry)
{
    if (!player || !entry || !HasAbilityKnowledge(player))
        return;

    CreatureTemplate const* creature = sObjectMgr->GetCreatureTemplate(entry);
    if (!creature || (creature->flags_extra & CREATURE_FLAG_EXTRA_TRIGGER))
    {
        Send(player, Trinity::StringFormat("BSTART|{}|0", entry));
        Send(player, Trinity::StringFormat("BEND|{}", entry));
        return;
    }

    std::vector<AbilityRow> abilities;
    std::unordered_set<uint32> seen;
    for (uint32 spellId : creature->spells)
    {
        if (!spellId || !seen.insert(spellId).second)
            continue;

        SpellInfo const* spell = ResolveSpell(player, spellId);
        if (!spell || spell->IsPassive())
            continue;

        AbilityRow row;
        row.id = spellId;
        row.schoolMask = spell->SchoolMask;
        row.recovery = spell->RecoveryTime;
        row.categoryRecovery = spell->CategoryRecoveryTime;
        row.channeled = spell->IsChanneled();
        row.positive = spell->IsPositive();
        abilities.push_back(row);
    }

    Send(player, Trinity::StringFormat("BSTART|{}|{}", entry, abilities.size()));
    for (AbilityRow const& row : abilities)
        Send(player, Trinity::StringFormat("BSPELL|{}|{}|{}|{}|{}|{}|{}", entry, row.id,
            row.schoolMask, row.recovery, row.categoryRecovery, row.channeled ? 1 : 0, row.positive ? 1 : 0));
    Send(player, Trinity::StringFormat("BEND|{}", entry));
}

class Players final : public PlayerScript
{
public:
    Players() : PlayerScript("forever_encyclopedia_abilities_players") { }

    void OnAddonMessageSent(Player* player, uint32 type, std::string const& prefix,
        std::string const& text, Player* receiver) override
    {
        if (type != CHAT_MSG_WHISPER || prefix != RequestPrefix || receiver != player)
            return;
        if (!sConfigMgr->GetBoolDefault("ForeverEncyclopedia.Enable", false))
            return;

        std::istringstream in(text);
        std::string cmd, extra;
        uint32 entry = 0;
        if (!(in >> cmd) || cmd != "inspect" || !(in >> entry) || (in >> extra))
            return;

        Inspect(player, entry);
    }
};
}

void AddSC_forever_encyclopedia_abilities()
{
    new ForeverEncyclopediaAbilities::Players();
}
