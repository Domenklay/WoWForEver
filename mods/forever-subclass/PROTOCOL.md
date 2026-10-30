# AddOn protocol v1

The client sends `FSC1` addon messages as a whisper to itself. The server only
accepts a player-to-that-same-player whisper, at most one request per 150 ms,
with a 96-byte payload limit. It never accepts another character's GUID.
All authoritative state, permissions, talent ranks and resource accounting stay
on the server.

Requests (numeric arguments are decimal IDs):

```text
status
learn CLASS
active CLASS
clear
xp CLASS
select SPELL
remove SPELL
cast SPELL
talent TALENT_ID
talentreset
tame
petcall
petdismiss
debuglevel CLASS LEVEL
```

`debuglevel` requires `SEC_GAMEMASTER`; it only changes a learned secondary class
on the requesting character. No protocol operation grants account privileges.
Talent editing/reset follows the server's rest-area restriction. Hunter pet
commands are available only while Hunter is the active subclass and its
subclass level is high enough.

Responses use prefix `FSR1`, from/to the same player. A snapshot is a sequence:

```text
STATE PRIMARY ACTIVE XP_TARGET USED_SLOTS SLOT_BUDGET EFFECTIVENESS_BASIS_POINTS
CLASS CLASS_ID LEVEL XP XP_TO_NEXT_LEVEL
POWER POWER_ID CURRENT MAXIMUM
SPELL SPELL_ID ROOT_SPELL_ID REQUIRED_LEVEL SELECTED COST POWER_ID
CUSTOM SPELL_ID REQUIRED_LEVEL SELECTED AE_COST REQUIRED_MAGIC_COUNT MAGIC_COUNT REQUIRED_CLASS_MASK CLASS_MASK IMPLEMENTED
TPOINTS FREE SPENT TOTAL
TALENT TALENT_ID RANK MAX_RANK TIER
FEATURE FEATURE_NAME ...
END
```

`CUSTOM` is an additive Freepick-only catalogue record. Old clients may ignore it.
Class masks use `1 << ClassId` (Priest=32, Warlock=512). `CLASS_MASK` includes the
permanent primary class and owners of purchased ordinary abilities, never all
learned classes or the current catalogue filter. Distinct magical classes are
Paladin, Priest, Shaman, Mage, Warlock and Druid. Custom abilities contribute no
class. A required class mask is an all-of requirement.

`IMPLEMENTED=0` means that the Freepick record has been reviewed but has no
available Forever implementation. Such records are displayed only in the
«Кастомное» page, cannot be purchased or dragged, and both `select` and `cast`
are rejected by the server without spending AE or mana. They are not `SPELL`
records: their IDs must not be looked up or cast as arbitrary native Forever
spells. Mana Shield 1463 is an explicit native-backed implementation: it uses
a dedicated spell tag, two validated bindings, a runtime-owned aura and the
shared Freepick mana pool. Its `IMPLEMENTED` flag reflects startup validation;
the other three Mystic Enchant candidates remain unavailable. Native casts
of a main-class ability are distinct from the custom action-bar macro.
The class policy rechecks
requirements on purchase and cast, and disallows refunds that would invalidate
an implemented dependent custom purchase. Login restores ordinary purchases
before custom dependencies, and preserves disabled owned records for refunds.
Script-owned shields are not persisted as native character auras or stolen.

`CLASS`, `POWER`, `SPELL`, `TALENT` and `FEATURE` may repeat. `POWER`, `SPELL`,
`TPOINTS`, `TALENT` and class-specific `FEATURE` records are omitted without an
active subclass. `ACTIVE=0` means disabled; `SELECTED` is 0 or 1.

Power IDs use native WoW values: mana 0, rage 1, energy 3. Rage is normalized to
a visible 0–100 scale. A Druid subclass can therefore return three `POWER`
records at once. The client hides a returned resource if the current native
player power already represents it and renders the remaining pools separately.
Local HUD spend prediction is cosmetic only; every authoritative value is
corrected by the next server snapshot.

Spell selection is stored by `ROOT_SPELL_ID`, not by a particular rank. The
server resolves the highest rank allowed by the active subclass level before a
cast and sends that rank as `SPELL_ID` in the snapshot. A player therefore does
not need to remove/reselect an ability when a new native rank becomes available.

Current talent snapshot records are:

```text
TPOINTS FREE SPENT TOTAL
TALENT TALENT_ID RANK MAX_RANK TIER
```

The first subclass talent point is awarded at subclass level 10, then one every
two subclass levels, capped by the current 30-rank tree. A tier requires five
spent points per tier index.

Current class feature records are:

```text
FEATURE HUNTER_PET REQUIRED_LEVEL UNLOCKED ACTIVE
FEATURE DRUID_MULTI_POWER VERSION ENABLED
```

Hunter pet storage uses TrinityCore's normal pet/stable persistence. The
subclass adapter performs the class-specific eligibility checks and then uses
the core pet construction/save/load APIs; it does not change the player's
primary class.

An error is `ERROR TEXT`. Native cast failures include the numeric core result.

Subclass spell casts carry a server-only `std::any` marker created by the
adapter. The bound SpellScript requires that marker for off-class spells,
validates the active class/loadout/level/resource again and charges once in
`OnCast`. Only native resource payment is bypassed for adapter casts. Ordinary
primary-class and NPC casts skip this adapter. Native movement, target, range,
form, equipment, cooldown and other spell checks remain in force.

The catalogue is built from the pinned core's actual rank chains and requires
validated `spell_script_names` bindings. Numeric IDs from the client cannot add
new abilities, classes, resources, talents or spell bindings to that catalogue.

## Opt-in Freepick ability prototype

`ForeverSubclass.Freepick=1` adds `MODE FREEPICK 1` immediately after `STATE`.
The `active` field is a catalogue filter; it does not restrict purchased spells.
`used/budget` are spent/total AE (8 total, 1 per supported root chain).
`xpTarget` is always the native primary class. `CLASS` levels for catalogue
classes mirror the primary level and do not represent secondary XP progression.
`SPELL` includes all purchased chains plus available entries for the filtered
class, so changing filters preserves action-bar entries and server ownership.
The initial supported chains are 2050 and 116, upgraded to the best available
native rank for the primary level. Both use the same `POWER 0` pool.

`select` buys a root chain and `remove` refunds it, in a rest area outside combat
at primary level 10+. Native primary chains cannot be purchased. `active`
changes only the filter and never clears purchases; `clear` clears only the
filter. `xp` for a foreign class, talent/debug-level and hunter-pet commands are
rejected in this prototype. No `TPOINTS`, `TALENT` or pet features are sent.
Normal mode retains its existing protocol and persistence tables.
