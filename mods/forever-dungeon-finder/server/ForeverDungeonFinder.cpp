#include "ScriptMgr.h"
#include "DB2Stores.h"
#include "Group.h"
#include "Map.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "WorldSession.h"
#include "Log.h"

#include <charconv>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <vector>

namespace ForeverDungeonFinder
{
static constexpr std::string_view AddonPrefix = "FDF";
static constexpr std::string_view EnterPrefix = "ENTER:";

static bool EnvBool(char const* name, bool fallback)
{
    char const* raw = std::getenv(name);
    if (!raw || !*raw)
        return fallback;

    return std::strcmp(raw, "1") == 0 || std::strcmp(raw, "true") == 0 || std::strcmp(raw, "TRUE") == 0 ||
           std::strcmp(raw, "yes") == 0 || std::strcmp(raw, "YES") == 0 || std::strcmp(raw, "on") == 0 || std::strcmp(raw, "ON") == 0;
}

static bool Enabled()
{
    static bool const enabled = EnvBool("FOREVER_DUNGEON_FINDER_ENABLED", true);
    return enabled;
}

static void Notify(Player* player, char const* message)
{
    if (player && player->GetSession())
        player->GetSession()->SendNotification("%s", message);
}

static bool ParseMapId(std::string_view text, uint32& mapId)
{
    if (!text.starts_with(EnterPrefix))
        return false;

    text.remove_prefix(EnterPrefix.size());
    if (text.empty())
        return false;

    uint32 value = 0;
    auto [ptr, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (ec != std::errc() || ptr != text.data() + text.size())
        return false;

    mapId = value;
    return true;
}

static bool IsDungeonMap(uint32 mapId)
{
    MapEntry const* mapEntry = sMapStore.LookupEntry(mapId);
    return mapEntry && mapEntry->IsNonRaidDungeon();
}

static bool PlayerReady(Player* player)
{
    if (!player || !player->GetSession())
        return false;

    if (!player->IsAlive() || player->IsInCombat() || player->InBattleground() || player->InArena() || player->GetVehicle())
        return false;

    if (player->IsFalling() || player->HasUnitState(UNIT_STATE_JUMPING))
        return false;

    return true;
}

static bool CollectParty(Player* leader, std::vector<Player*>& players)
{
    Group* group = leader->GetGroup();
    if (!group)
    {
        players.push_back(leader);
        return true;
    }

    if (group->isRaidGroup())
    {
        Notify(leader, "Forever: для подземелья нужна обычная группа, не рейд.");
        return false;
    }

    if (group->GetLeaderGUID() != leader->GetGUID())
    {
        Notify(leader, "Forever: войти с группой может только лидер.");
        return false;
    }

    // Teleport the leader first so TrinityCore establishes the ordinary group
    // instance binding before the remaining members resolve the destination.
    players.push_back(leader);
    for (GroupReference const& reference : group->GetMembers())
    {
        Player* member = reference.GetSource();
        if (!member || member == leader)
            continue;
        players.push_back(member);
    }

    return true;
}

static bool EnterDungeon(Player* requester, uint32 mapId)
{
    if (!Enabled())
    {
        Notify(requester, "Forever: прямой вход в подземелья сейчас отключён.");
        return false;
    }

    if (!IsDungeonMap(mapId))
    {
        Notify(requester, "Forever: выбранная карта не является доступным подземельем.");
        return false;
    }

    AreaTriggerTeleport const* entrance = sObjectMgr->GetMapEntranceTrigger(mapId);
    if (!entrance)
    {
        Notify(requester, "Forever: для этого подземелья не найдена точка входа.");
        TC_LOG_ERROR("forever.dungeonfinder", "No entrance trigger for dungeon map {}", mapId);
        return false;
    }

    std::vector<Player*> players;
    if (!CollectParty(requester, players))
        return false;

    if (players.empty() || players.size() > MAX_GROUP_SIZE)
    {
        Notify(requester, "Forever: недопустимый размер группы для подземелья.");
        return false;
    }

    for (Player* player : players)
    {
        if (!PlayerReady(player))
        {
            Notify(requester, "Forever: все участники должны быть живы, вне боя и не находиться на транспорте.");
            return false;
        }
    }

    for (Player* player : players)
    {
        if (!player->GetMap()->IsDungeon())
            player->SetBattlegroundEntryPoint();

        player->FinishTaxiFlight();
        if (!player->TeleportTo({ .Location = entrance->Loc }))
        {
            Notify(requester, "Forever: не удалось перенести одного из участников в подземелье.");
            TC_LOG_ERROR("forever.dungeonfinder", "Teleport failed for player {} to dungeon map {}", player->GetName(), mapId);
            return false;
        }
    }

    TC_LOG_INFO("forever.dungeonfinder", "Direct dungeon entry: leader={} map={} players={}",
        requester->GetName(), mapId, players.size());
    return true;
}

static void HandleAddonRequest(Player* player, std::string const& prefix, std::string const& text)
{
    if (!player || prefix != AddonPrefix)
        return;

    uint32 mapId = 0;
    if (!ParseMapId(text, mapId))
        return;

    EnterDungeon(player, mapId);
}

class DirectEntryPlayerScript final : public PlayerScript
{
public:
    DirectEntryPlayerScript() : PlayerScript("forever_dungeon_finder_direct_entry") { }

    void OnAddonMessageSent(Player* player, uint32 /*type*/, std::string const& prefix,
        std::string const& text, Player* receiver) override
    {
        // Solo requests are sent as a self whisper. Do not accept a targeted
        // request aimed at another character.
        if (receiver != player)
            return;
        HandleAddonRequest(player, prefix, text);
    }

    void OnAddonMessageSent(Player* player, uint32 /*type*/, std::string const& prefix,
        std::string const& text, Group* group) override
    {
        // Group requests are sent through PARTY so the sender is naturally the
        // current group member. EnterDungeon still requires the sender to be leader.
        if (!group || player->GetGroup() != group)
            return;
        HandleAddonRequest(player, prefix, text);
    }
};
} // namespace ForeverDungeonFinder

void AddSC_forever_dungeon_finder()
{
    new ForeverDungeonFinder::DirectEntryPlayerScript();
    TC_LOG_INFO("server.loading", "ForeverDungeonFinder: direct-entry-v0.1 registered (enabled={})",
        ForeverDungeonFinder::Enabled());
}
