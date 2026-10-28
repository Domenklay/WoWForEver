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
TPOINTS FREE SPENT TOTAL
TALENT TALENT_ID RANK MAX_RANK TIER
FEATURE FEATURE_NAME ...
END
```

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
