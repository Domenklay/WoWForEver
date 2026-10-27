# WoW: Forever — Subclass System Prototype 0.2.0

Standalone C++17 prototype for one-character / multiple-class progression.

## Core rules

- One permanent primary class.
- New classes can be learned once the primary reaches level 40.
- Every learned class stores its own level and XP.
- Any learned non-primary class can become the single active subclass.
- XP can be directed into a selected learned class without changing the primary/world level.
- Active subclass has a limited spell loadout (default 8 slot points).
- Primary spells operate at 100% effectiveness.
- Secondary effectiveness = `secondaryLevel / primaryLevel`.
- Warrior 80 + Priest 60 therefore yields 75% Priest effectiveness.
- Multiple server-side powers are supported simultaneously, e.g. Health + Rage + Mana.
- Armor permission remains tied to the primary class.
- Subclass switching is blocked in combat and, by default, outside rest areas.

## 0.2.0: hybrid stat support

The prototype no longer assumes that a Warrior ignores caster stats just because Warrior is the primary class.
All stats are stored/read independently from class identity.

Default prototype formulas (all configurable in `SystemConfig`):

- Stamina: `+10 max Health` per point.
- Intellect: `+15 max Mana` per point whenever Mana is an active resource.
- Intellect: `+1 Spell Power` per point.
- Spirit: `+0.20 Mana/sec` per point outside combat.
- In combat: Spirit mana regeneration is multiplied by `0.30` by default.
- Flat Spell Power from gear/auras is added normally.
- A secondary-class heal/damage/absorb uses `(base + SpellPower * coefficient) * subclass effectiveness`.

Example Warrior 80 / Priest 60 with 120 Intellect, 100 Spirit and +50 flat Spell Power:

- Priest effectiveness: 75%.
- Priest base Mana at level 60: 5200.
- Intellect adds 1800 Mana -> 7000 max Mana.
- Effective Spell Power: 170.
- Spirit regeneration: 20 Mana/sec out of combat, 6 Mana/sec in combat.
- Flash Heal prototype: `(1000 + 170 * 0.80) * 0.75 = 852` healing.

These are prototype tuning values, not claimed Blizzard/Forever formulas. Once the actual server core is selected, the adapter can replace them with the core's stat/DB2 formulas without changing subclass progression.

## Build

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
./build/forever_subclass_demo
```

## Important

This is still a gameplay/core prototype, not a patch against a specific Forever emulator. `docs/INTEGRATION.md` describes where the chosen server's real stat engine, spell coefficients, resource updates and persistence should connect.
