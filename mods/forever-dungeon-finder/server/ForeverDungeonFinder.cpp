#include "ScriptMgr.h"
#include "Chat.h"
#include "ChatPackets.h"
#include "DB2Stores.h"
#include "Group.h"
#include "Map.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "WorldSession.h"
#include "Log.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <vector>

namespace ForeverDungeonFinder
{
static constexpr std::string_view AddonPrefix = "FDF";
static constexpr std::string_view AddonPrefixV2 = "FDF1";

static bool IsRequestPrefix(std::string const& prefix)
{
    return prefix == AddonPrefix || prefix == AddonPrefixV2;
}
static constexpr std::string_view SoloPrefix = "SOLO:";
static constexpr std::string_view GroupPrefix = "GROUP:";

// Allow only dungeons listed in the client, not arbitrary instance IDs.
static constexpr std::array<uint32, 19> AllowedDungeons = {
    389, 36, 43, 33, 48, 34, 90, 47, 189, 129,
    70, 209, 349, 109, 230, 229, 429, 289, 329
};

enum class EntryMode
{
    Solo,
    Group
};

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
    static bool const enabled = EnvBool("FOREVER_DUNGEON_FINDER_ENABLED", false);
    return enabled;
}

// A separate addon response is necessary because client 70658 does not reliably
// display server SendNotification messages. This follows the proven FAC1/FAR1
// transport without changing or depending on the dungeon browser addon.
static void Reply(Player* player, std::string const& message)
{
    if (!player || !player->GetSession())
        return;

    WorldPackets::Chat::Chat packet;
    packet.Initialize(CHAT_MSG_WHISPER, LANG_ADDON, player, player, message, 0, "", LOCALE_enUS, "FDFR");
    player->GetSession()->SendPacket(packet.Write());
    TC_LOG_INFO("server", "ForeverDungeonFinder v2 response: player={} result={}", player->GetName(), message);
}

static void Notify(Player* player, char const* message)
{
    if (player && player->GetSession())
    {
        Reply(player, std::string("ERROR ") + message);
        player->GetSession()->SendNotification("%s", message);
    }
}

static bool ParseRequest(std::string_view text, EntryMode& mode, uint32& mapId)
{
    if (text.starts_with(SoloPrefix))
    {
        mode = EntryMode::Solo;
        text.remove_prefix(SoloPrefix.size());
    }
    else if (text.starts_with(GroupPrefix))
    {
        mode = EntryMode::Group;
        text.remove_prefix(GroupPrefix.size());
    }
    else
        return false;

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
    return mapEntry && mapEntry->IsNonRaidDungeon() &&
        std::find(AllowedDungeons.begin(), AllowedDungeons.end(), mapId) != AllowedDungeons.end();
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

static bool CollectGroup(Player* leader, std::vector<Player*>& players)
{
    Group* group = leader->GetGroup();
    if (!group)
    {
        Notify(leader, "Forever: вы не состоите в группе.");
        return false;
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

    if (players.size() != group->GetMembersCount())
    {
        Notify(leader, "Forever: для группового входа все участники должны быть в сети.");
        return false;
    }
    return true;
}

static bool EnterDungeon(Player* requester, uint32 mapId, EntryMode mode)
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
    if (mode == EntryMode::Solo)
        players.push_back(requester);
    else if (!CollectGroup(requester, players))
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
            Notify(requester, "Forever: участники входа должны быть живы, вне боя и не находиться на транспорте.");
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

    TC_LOG_INFO("forever.dungeonfinder", "Direct dungeon entry: requester={} map={} mode={} players={}",
        requester->GetName(), mapId, mode == EntryMode::Solo ? "solo" : "group", players.size());
    Reply(requester, std::string("OK ") + (mode == EntryMode::Solo ? "SOLO:" : "GROUP:") + std::to_string(mapId));
    return true;
}

static bool ParseAddonRequest(Player* player, std::string const& prefix, std::string const& text,
    EntryMode& mode, uint32& mapId)
{
    return player && IsRequestPrefix(prefix) && ParseRequest(text, mode, mapId);
}

class DirectEntryPlayerScript final : public PlayerScript
{
public:
    DirectEntryPlayerScript() : PlayerScript("forever_dungeon_finder_direct_entry") { }

    void OnAddonMessageSent(Player* player, uint32 /*type*/, std::string const& prefix,
        std::string const& text, Player* receiver) override
    {
        // Solo requests are self-whispers. A targeted request may never move a
        // different character, even if another addon sends the FDF prefix.
        if (!player || !IsRequestPrefix(prefix) || receiver != player)
            return;

        // "server" is enabled at INFO in the active 70658 configuration;
        // the custom "forever.dungeonfinder" logger inherits root=ERROR.
        TC_LOG_INFO("server", "ForeverDungeonFinder transport-v2 received: player={} prefix={} channel=WHISPER request={}",
            player->GetName(), prefix, text);
        if (text == "PING")
        {
            Reply(player, "PONG v0.2.1");
            return;
        }

        EntryMode mode = EntryMode::Solo;
        uint32 mapId = 0;
        if (!ParseAddonRequest(player, prefix, text, mode, mapId) || mode != EntryMode::Solo)
        {
            Notify(player, "Forever: некорректная команда одиночного входа.");
            return;
        }

        EnterDungeon(player, mapId, mode);
    }

    void OnAddonMessageSent(Player* player, uint32 /*type*/, std::string const& prefix,
        std::string const& text, Group* group) override
    {
        // Group entry is sent through PARTY and still requires the sender to be
        // the current group's leader inside CollectGroup().
        if (!player || !IsRequestPrefix(prefix) || !group || player->GetGroup() != group)
            return;

        TC_LOG_INFO("server", "ForeverDungeonFinder transport-v2 received: player={} prefix={} channel=PARTY request={}",
            player->GetName(), prefix, text);
        EntryMode mode = EntryMode::Group;
        uint32 mapId = 0;
        if (!ParseAddonRequest(player, prefix, text, mode, mapId) || mode != EntryMode::Group)
        {
            Notify(player, "Forever: некорректная команда группового входа.");
            return;
        }

        EnterDungeon(player, mapId, mode);
    }
};
} // namespace ForeverDungeonFinder

void AddSC_forever_dungeon_finder()
{
    new ForeverDungeonFinder::DirectEntryPlayerScript();
    TC_LOG_INFO("server.loading", "ForeverDungeonFinder: direct-entry-v0.2 registered (enabled={})",
        ForeverDungeonFinder::Enabled());
}
