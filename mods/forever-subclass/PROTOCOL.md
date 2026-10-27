# AddOn protocol v1

The client sends `FSC1` addon messages as a whisper to itself. The server only
accepts a player-to-that-same-player whisper, at most one request per 150 ms,
with a 96-byte payload limit. It never accepts another character's GUID.
All authoritative state, permissions and resource accounting stay on the server.

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
debuglevel CLASS LEVEL
```

`debuglevel` requires `SEC_GAMEMASTER`; it only changes a learned secondary class
on the requesting character. No protocol operation grants account privileges.

Responses use prefix `FSR1`, from/to the same player. A snapshot is a sequence:

```text
STATE PRIMARY ACTIVE XP_TARGET USED_SLOTS SLOT_BUDGET EFFECTIVENESS_BASIS_POINTS
CLASS CLASS_ID LEVEL XP XP_TO_NEXT_LEVEL
POWER POWER_ID CURRENT MAXIMUM
SPELL SPELL_ID ROOT_SPELL_ID REQUIRED_LEVEL SELECTED COST POWER_ID
END
```

`CLASS` and `SPELL` can repeat. `POWER` and `SPELL` are omitted without an active
subclass. `ACTIVE=0` means disabled; `SELECTED` is 0 or 1. Power IDs use native
WoW values: mana 0, rage 1, energy 3. Rage is normalized to a visible 0–100 scale.
The addon applies a snapshot only at `END`; it never predicts or pays resources.
An error is `ERROR TEXT`. Native cast failures include the numeric core result.

Spell casts carry a server-only `std::any` marker created by the adapter.
The bound SpellScript requires that marker for off-class spells, validates the
active class/loadout/level/resource again and charges once in `OnCast`.
Only the native resource-payment flag is bypassed. Ordinary primary-class and
NPC casts skip this adapter. Allowed secondary casts preserve native checks.

The catalogue is built from the pinned core's actual rank chains and requires
validated `spell_script_names` bindings. Numeric IDs from the client cannot add
new abilities, classes, resources or spell bindings to that catalogue.
