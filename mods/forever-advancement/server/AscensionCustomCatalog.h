#pragma once
#include <array>
namespace ForeverAdvancementCustom {
struct Rule { unsigned entry,spell,requiredMagicClasses; bool implemented; };
struct Alias { unsigned entry,canonical; };
inline constexpr std::array<Rule,1> Rules = {{
{1300,701463,2,false},
}};
inline constexpr std::array<Alias,2> Aliases = {{
{1300,1300},
{34782,1300},
}};
}
