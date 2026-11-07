# Forever Scaling 0.4.0 — XP, нейтралы и подготовка подземелий

Это **не активная версия**. На текущем сервере согласно последнему
подтверждённому снимку всё ещё используется Scaling 0.2.0. В ветке
feature/scaling-xp-neutral-lfg-70658 готовится кандидат 0.4.0.

- Для красных врагов минимальный виртуальный уровень теперь
  max(исходный, min(70, уровень игрока − 3)), вместо минус 9.
  Это рассчитано на ненулевой опыт там, где стандартная система
  выдаёт опыт за такого NPC. Формулы начисления XP не подменяются.
- Нейтральные жёлтые NPC также масштабируются, если исходный уровень
  не ниже 10, существо доступно для атаки, не является гражданским
  NPC, торговцем, тренером, квестодателем или NPC с диалогом.
- Нейтральные существа исходного уровня ниже 10, союзные и мирные NPC
  не затрагиваются. BG/арены и питомцы игроков исключены.
- Подземелья: отдельный opt-in FOREVER_DUNGEON_SCALING_ENABLED=1
  (по умолчанию 0). Телепорт: FOREVER_DUNGEON_FINDER_ENABLED=1
  (по умолчанию 0). Базовая политика коэффициентов из v0.3 сохранена.
- Дополнительный аддон ForeverDungeonFinder открывается в стандартном
  окне «Поиск группы» или через /fd. Подробности в
  mods/forever-dungeon-finder/README.ru.md.

Ограничения: на уровнях игрока выше 73 ограничение подъёма NPC до 70
может оставить врагов серыми; на пользовательском сервере XP и
нестандартные NPC требуют фактической игровой проверки. Не является
установленным обновлением; Docker/БД пользователя не менялись.

---

# Forever Scaling v0.3.0 — подготовка подземелий

**Версия 0.3.0 — кандидат, на рабочем сервере НЕ установлена.**
Действующий образ продолжает использовать персональный Scaling 0.2.0.

## Новое в 0.3.0

- Включение только через FOREVER_DUNGEON_SCALING_ENABLED=1 при FOREVER_SCALING_ENABLED=1.
- Применяется только к обычным подземельям на пять игроков; рейды, PvP,
  открытый мир и управляемые игроками существа не затрагиваются.
- При первом входе NPC в бой фиксируется число живых участников группы
  инициатора в том же инстансе (1–5). Во время боя число не меняется.
- Здоровье и максимальное здоровье NPC изменяются одновременно с сохранением
  процента здоровья. При сбросе боя или возрождении оригинальные параметры
  восстанавливаются. Урон по игрокам и их питомцам меняется по составу группы.
- Персональный виртуальный уровень врага не изменён; для игроков разных уровней
  по-прежнему действует индивидуальный расчёт.
- Для 1 игрока: обычные HP 40% / урон 60%; элита 50% / 65%;
  боссы 55% / 75%. Для 5 игроков — 100%, между ними линейный переход.

**Ограничения:** не масштабируются награды/предметы, сложные скриптовые
механики боссов и призываемые волны, меняющие состав сражения. Изменения
максимального HP некоторыми эффектами во время боя и сброса требуют отдельной
игровой проверки. CI проверяет интеграцию исходников и компиляцию, но не
доказывает игровой баланс.

Выполнить тест расчётов из отдельного checkout:
bash mod-forever-scaling/tests/run.sh

Не запускать старый установщик и не применять install поверх готового
профиля forever-clean. Прежде нужен изолированный образ с новой сборкой,
копия БД для теста и план переключения с возможностью отката.

---

# Справка о работающем Scaling v0.2.0

The current ready 70658 server uses `scripts/enable-clean-gameplay.py` and the
pinned b4e7b940593f core: see [combined installation](../docs/GAMEPLAY-70658.ru.md).
The legacy installer below manages a different Compose project.

Status: personal virtual-scaling integration candidate for the pinned TrinityCore Forever revision `91d49b230f89c3ab4719f5b2b2d1e70ed36613c4`. Policy tests pass; the server Docker build is the authoritative compile test for the pinned fork.

## Scope

The module is compiled into `worldserver` but is disabled until `FOREVER_SCALING_ENABLED=1`. It changes no creature database rows and never persists a scaled level to `creature_template` or spawn data.

It applies to hostile NPCs in the outdoor world, dungeons and raids. Battlegrounds/arenas and player-controlled creatures are excluded.

## Personal virtual scaling

v0.2 no longer calls `Creature::SetLevel()` to scale an encounter. The creature keeps one physical/original server level while TrinityCore's target-dependent APIs calculate a different virtual level and stat profile for every player.

Example for one original level-6 creature:

- player level 11 sees/fights level 6;
- player level 20 sees/fights level 11;
- player level 60 sees/fights level 51.

Those players may be in the same group and attack the same creature simultaneously. One player's virtual level does not overwrite another player's view.

The progression rule is intentionally only a lower floor:

`virtualLevel = max(originalCreatureLevel, playerLevel - 9)`

with the result capped by `FOREVER_SCALING_CREATURE_MAX_LEVEL` (default 70). Existing higher-level enemies are not downscaled.

## How shared combat works

The integration extends the pinned core's existing per-target hooks:

- `Creature::GetLevelForTarget(player)` - personal virtual level;
- `Creature::GetDamageMultiplierForTarget(player)` - creature outgoing damage against that player;
- `Creature::GetArmorMultiplierForTarget(player)` - effective armor against that attacker;
- `Creature::GetHealthMultiplierForTarget(player)` - normalizes incoming damage against the shared physical health pool.

The Classic update-field serializer is also patched for fixed-level ForeverScaling creatures. Each client receives viewer-specific `Level`, `EffectiveLevel`, `Health` and `MaxHealth`. The absolute HP numbers can therefore differ between two players while both clients still see the same health percentage and one shared creature/death state.

XP already follows TrinityCore's `GetLevelForTarget(player)` path, so XP/gray-level decisions are evaluated against each member's virtual creature level rather than whichever group member attacked first.

## Damage guard

`UnitScript::OnDamage` caps NPC-to-player damage events to a percentage of the victim's maximum HP:

- normal: 20%;
- elite: 30%;
- rare elite: 40%;
- boss: 45%.

Player-controlled attackers and battleground/arena combat are excluded. The guard is still per damage event; a rolling window for deliberate rapid multi-hit/DoT mechanics and explicit scripted lethal-mechanic exceptions remain follow-up work.

## Foundation for scalable dungeons

v0.2 deliberately separates personal scaling from encounter-wide scaling. The next dungeon layer can therefore add an instance/encounter profile without replacing this work:

- party-size health multiplier shared by the encounter;
- party-size damage/mechanic tuning;
- dungeon minimum/maximum virtual level rules;
- scalable item level/loot context per eligible player;
- boss/elite-specific coefficients and difficulty tiers;
- encounter snapshot/lock so group-size changes cannot be exploited mid-fight.

Personal player level remains target/viewer-dependent; party-size/difficulty values belong to the shared encounter profile.

## Install

Run from the initialized `~/WoWForEver` server checkout:

```bash
bash scripts/forever-scaling-mod.sh install
```

The installer:

1. runs policy/static checks;
2. preserves the currently running `worldserver` image and `.env`;
3. builds the new image inside Docker while the old server keeps running;
4. verifies image label `org.wowforever.scaling=0.2.0`;
5. enables scaling and recreates only `worldserver` after a successful build;
6. prints the exact rollback command and backup directory.

Useful commands:

```bash
bash scripts/forever-scaling-mod.sh status
bash scripts/forever-scaling-mod.sh disable
bash scripts/forever-scaling-mod.sh rollback backups/scaling-YYYYMMDD-HHMMSS
```

## v0.2 live acceptance test

Use two characters with a large level difference against the same low-level hostile creature. For example, with an original level-6 creature:

- level-20 player should receive level 11;
- level-60 player should receive level 51;
- both should see the same health percentage but different absolute max HP;
- damage dealt by each player should be normalized against their personal virtual-health multiplier;
- creature damage/armor checks should use the relevant player's virtual level;
- killing the creature should award XP according to each player's personal `GetLevelForTarget` result.

Also verify that friendly NPCs, PvP and player-controlled creatures remain unchanged.
