#pragma once
// Standalone deterministic rules. Integration with TrinityCore hooks is pending.
#include <algorithm>
#include <cstdint>
namespace encyclopedia {
struct Config {
    uint32_t combatRegenPer5s = 1;
    uint32_t restRegenPer5s = 5;
    uint32_t healCooldownMs = 20000;
    uint32_t shieldCooldownMs = 30000;
};
struct State {
    uint32_t mana = 0;
    uint32_t maxMana = 0;
    uint64_t lastHealMs = 0;
    uint64_t lastShieldMs = 0;
};
struct Context {
    bool inCombat = false;
    bool inPvp = false;
    bool duel = false;
    bool battleground = false;
    bool arena = false;
    bool raid = false;
    uint32_t groupSize = 1;
};
inline bool Allowed(Context const& c) {
    return !c.inPvp && !c.duel && !c.battleground && !c.arena
        && !c.raid && c.groupSize <= 4;
}
inline uint32_t Regen(State& s, Context const& c, Config const& cfg, uint32_t ticks) {
    if (!Allowed(c)) return 0;
    uint64_t amount = uint64_t(c.inCombat ? cfg.combatRegenPer5s : cfg.restRegenPer5s) * ticks;
    uint32_t old = s.mana;
    s.mana = uint32_t(std::min<uint64_t>(s.maxMana, uint64_t(s.mana) + amount));
    return s.mana - old;
}
inline uint32_t HealCap(uint32_t maxHp, bool fullyUpgraded) {
    return uint32_t(uint64_t(maxHp) * (fullyUpgraded ? 40 : 25) / 100);
}
inline uint32_t ShieldCap(uint32_t maxHp) {
    return uint32_t(uint64_t(maxHp) * 30 / 100);
}
inline uint32_t Heal(State& s, Context const& c, Config const& cfg, uint64_t nowMs,
                     uint32_t hp, uint32_t maxHp, uint32_t proposed, uint32_t cost,
                     bool fullyUpgraded, uint32_t reserve = 0) {
    if (!Allowed(c) || !maxHp || uint64_t(hp) * 100 >= uint64_t(maxHp) * 50
        || s.mana < cost || s.mana - cost < reserve
        || nowMs < s.lastHealMs || nowMs - s.lastHealMs < cfg.healCooldownMs) return 0;
    uint32_t amount = std::min({proposed, HealCap(maxHp, fullyUpgraded), maxHp - hp});
    if (!amount) return 0;
    s.mana -= cost;
    s.lastHealMs = nowMs;
    return amount;
}
inline uint32_t Shield(State& s, Context const& c, Config const& cfg, uint64_t nowMs,
                       uint32_t hp, uint32_t maxHp, uint32_t proposed, uint32_t cost,
                       uint32_t reserve = 0) {
    if (!Allowed(c) || !maxHp || uint64_t(hp) * 100 >= uint64_t(maxHp) * 80
        || s.mana < cost || s.mana - cost < reserve
        || nowMs < s.lastShieldMs || nowMs - s.lastShieldMs < cfg.shieldCooldownMs) return 0;
    uint32_t amount = std::min(proposed, ShieldCap(maxHp));
    if (!amount) return 0;
    s.mana -= cost;
    s.lastShieldMs = nowMs;
    return amount;
}
} // namespace encyclopedia
