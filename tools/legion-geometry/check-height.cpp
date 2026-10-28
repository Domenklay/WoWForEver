// Probe staged collision through the pinned server's real VMAP manager.
#include "VMapManager.h"
#include <charconv>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <string_view>

int main(int argc, char** argv)
{
    if (argc != 5)
        return 2;
    auto number = [](char const* value)
    {
        std::string_view text(value);
        uint32 result = 0;
        auto parsed = std::from_chars(text.data(), text.data() + text.size(), result);
        if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size())
            throw std::runtime_error("Invalid probe argument");
        return result;
    };
    try
    {
        auto map = number(argv[2]), gx = number(argv[3]), gy = number(argv[4]);
        if (!map || map > 65535 || gx >= 64 || gy >= 64)
            return 2;
        VMAP::VMapManager manager;
        auto status = manager.loadMap(argv[1], map, gx, gy);
        if (status != VMAP::LoadResult::Success)
        {
            std::printf("{\"load_success\":false,\"load_result\":%u}\n", unsigned(status));
            return 1;
        }
        std::printf("{\"load_success\":true,\"map_id\":%u,\"tile\":[%u,%u],\"samples\":[", map, gx, gy);
        bool first = true;
        uint32 found = 0;
        constexpr float tileSize = 1600.0f / 3.0f;
        for (int ix = 1; ix < 12; ++ix)
            for (int iy = 1; iy < 12; ++iy)
            {
                float x = (31.0f - gx + ix / 12.0f) * tileSize;
                float y = (31.0f - gy + iy / 12.0f) * tileSize;
                float height = manager.getHeight(map, x, y, 2000.0f, 5000.0f);
                if (!std::isfinite(height) || height < 500.0f || height > 1500.0f)
                    continue;
                std::printf("%s{\"x\":%.6f,\"y\":%.6f,\"height\":%.6f}", first ? "" : ",", x, y, height);
                first = false;
                ++found;
            }
        std::printf("],\"city_collision_samples\":%u,\"player_spawn_verified\":false}\n", found);
        manager.unloadMap(map);
        return found ? 0 : 1;
    }
    catch (std::exception const& error)
    {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
