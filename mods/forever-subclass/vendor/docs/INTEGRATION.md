# Integration map

The prototype intentionally contains no TrinityCore/AzerothCore-specific includes. The future Forever adapter only needs to map these points.

## 1. Character load/save

Map the selected server's character DB hooks to:

- `forever_character_class_progress`
- `forever_character_subclass_state`
- `forever_character_subclass_spells`

`ISubclassPersistence` is the seam for a real SQL repository.

## 2. XP hook

When the core awards character XP:

1. inspect `CharacterState::xpTargetClass`;
2. route XP into `SubclassSystem::grantXp`;
3. keep the visible/world level equal to the primary-class level;
4. do not increase the primary class while another class is the XP target.

The prototype XP curve is fake by design. Replace `xpToNext()` with the actual server XP table/DB2 data.

## 3. Spell validation

Before spell execution, ask `tryCast`/equivalent validation:

- owner class must be primary OR active subclass;
- subclass spell must be in the selected slot loadout;
- subclass class level must satisfy the spell requirement;
- correct resource must exist and have enough points.

In the real core, resource deduction should happen in the core spell pipeline rather than twice. Keep this prototype's deduction only until the adapter is installed.

## 4. Effect scaling

For damage/healing/absorb created by a secondary-class spell, multiply the class contribution by:

`secondary level / primary level * secondaryEffectivenessMultiplier`

Example: Warrior 80 / Priest 60 => 60/80 = 0.75 => 75% secondary effectiveness.

This should be applied at the spell-effect coefficient layer, not by changing tooltip base points.

## 5. Multiple powers

The server-side model supports multiple simultaneous resource pools. Example:

- Warrior 80 => Rage
- active Priest 60 => Mana
- final active pools => Health + Rage + Mana

The main client experiment is whether Forever can display and synchronize both resource bars without UI modification. If not, keep the server resources authoritative and expose the secondary power through an addon/custom UI bar.

## 6. Equipment

`canUseArmorFromClass` deliberately returns true only for the primary class. The subclass grants spells, not armor proficiency. This prevents Mage + low-level Warrior from using plate merely by learning Warrior.

## 7. Switching

Prototype policy:

- cannot switch while in combat;
- can switch only in a rest area;
- changing subclass clears the selected subclass spell loadout.

These are config-driven and can later become trainer/city checks.

## 8. Next adapter files once a core is selected

Recommended adapter boundary:

- `ForeverSubclassPlayerAdapter.cpp`
- `ForeverSubclassSpellAdapter.cpp`
- `ForeverSubclassXpAdapter.cpp`
- `ForeverSubclassRepository.cpp`
- `ForeverSubclassPackets.cpp`

Only these files should depend on the chosen WoW emulator/core.

## 9. Hybrid stats (0.2.0)

The subclass layer must not discard a stat because the primary class normally does not use it.
The real server adapter should feed the character's final post-gear/post-aura stat snapshot into `CharacterState::stats`.

Prototype mappings are configurable:

- Stamina -> max Health.
- Intellect -> max Mana if Mana is currently active.
- Intellect -> Spell Power for damage/healing/absorb coefficients.
- Spirit -> Mana regeneration whenever Mana is active.
- Flat Spell Power from gear/auras stacks with Intellect-derived Spell Power.

Important integration rule: do not duplicate the server's native stat database in the subclass SQL tables. Stats belong to the selected core; the subclass system only consumes their final values.

Recommended update hooks:

- equipment changed;
- aura/stat modifier changed;
- level changed;
- active subclass changed;
- login/world entry;
- shapeshift/form changes if the selected core changes stats/powers there.

For a Warrior 80 / Priest 60, Intellect and Spirit therefore become meaningful as soon as Priest activates Mana, even though Warrior remains the primary class.
