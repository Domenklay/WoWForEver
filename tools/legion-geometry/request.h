// Tools-only override: one explicit map/WDT pair, never a client table patch.
#pragma once
#include <charconv>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace WoWForeverGeometry
{
    struct Request { std::uint32_t MapId; std::uint32_t WdtId; };
    inline std::optional<Request> RequestFromEnvironment()
    {
        auto id = std::getenv("WOWFOREVER_GEOMETRY_MAP_ID");
        auto wdt = std::getenv("WOWFOREVER_GEOMETRY_WDT_ID");
        if (!id && !wdt)
            return std::nullopt;
        auto number = [](char const* value)
        {
            if (!value)
                throw std::runtime_error("Both geometry map and WDT IDs are required");
            std::string_view text(value);
            std::uint32_t result = 0;
            auto parsed = std::from_chars(text.data(), text.data() + text.size(), result);
            if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || !result)
                throw std::runtime_error("Geometry IDs must be positive decimal uint32 values");
            return result;
        };
        Request result{number(id), number(wdt)};
        if (result.MapId > 65535 || result.WdtId < 0x00F00000 || result.WdtId >= 0x00FFFF00)
            throw std::runtime_error("Geometry override requires a map ID and private WDT ID in the supported ranges");
        return result;
    }
}
