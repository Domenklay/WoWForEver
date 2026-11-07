#pragma once
#include <array>
#include <cstdint>
#include <string_view>

namespace ForeverEncyclopedia::Skins
{
// Creature IDs are models to preview. They are NOT display IDs.
// Classic five keys/thresholds must remain stable for saved characters.
// Test entries are all unlocked so their client compatibility can be checked.
// Missing creatures/models are safely displayed using the existing shell.
struct Skin
{
    std::string_view key;
    std::uint32_t creature;
    std::uint32_t threshold;
    std::uint32_t displayFallback;
};

inline constexpr std::array<Skin, 11> All = {{
    {"living_book", 171120, 0, 0},
    {"archivist", 205781, 100, 0},
    {"knowledge_spirit", 161896, 500, 0},
    {"small_construct", 183783, 1500, 0},
    {"runekeeper", 130946, 5000, 0},
    {"test_lofty_libram", 68806, 0, 46938},
    {"test_animated_tome", 171120, 0, 0},
    {"test_gusting_grimoire", 69208, 0, 47348},
    {"test_agitated_tome", 101633, 0, 0},
    {"test_troubled_tome", 198511, 0, 0},
    {"test_chromies_codex", 227052, 0, 0}
}};

inline Skin const* Find(std::string_view key)
{
    for (auto const& skin : All)
        if (skin.key == key)
            return &skin;
    return nullptr;
}
} // namespace ForeverEncyclopedia::Skins
