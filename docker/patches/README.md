# Patches applied to TrinityCore (forever branch)

Applied in name order right after the `git clone` (see the Dockerfile). The build stops if a patch no longer
applies: either it was merged into the branch (delete it) or it needs updating.

| File | What it fixes (found with packet logs of client 1.60.1.70450) |
|---|---|
| `0002-classic-surname-invite-and-names.patch` | The 1.60 client shows and sends "Name Surname". `normalizePlayerName` keeps the first word only (add friend, ignore, guild, mail by name: no more "player not found"); `CMSG_PARTY_INVITE` is read in the 70425+ layout (shifted bits, surname, trailing byte) instead of failing. |
| `0003-classic-contact-list-request.patch` | The 1.60 client's `CMSG_SEND_CONTACT_LIST` is 5 bytes: one byte (0) before the flags. Read as a uint32 it gave wrong flags (0x1500) and the server sent an empty friend list every time it was opened, although the friends were stored. |
| `0004-classic-360-action-buttons.patch` | The 1.60 client has 360 action bar slots; the server kept 180 (one-byte index). Spells placed beyond, notably on the gamepad bars (slots 184+), were ignored and lost at the next login. `MAX_ACTION_BUTTONS` becomes 360, the index 16 bits, and `character_action.button` a `smallint` (`sql/custom/characters/2026_10_17_00_…`, applied by the updater). |
