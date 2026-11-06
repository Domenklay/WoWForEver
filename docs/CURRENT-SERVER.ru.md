# WoWForEver: текущее состояние сервера

Обновлено **7 ноября 2026, Europe/Moscow**. Это точка входа для нового чата и
разработчика. Сведения о путях и активных образах подтверждены читающим отчётом
пользователя из Ubuntu/WSL; работа игры — его сообщением «Супер все работает».
Это снимок состояния, а не онлайн-мониторинг.

[Машиночитаемый снимок JSON](https://github.com/Domenklay/WoWForEver/blob/main/docs/current-server.json).
[Рабочая ветка с кодом](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106).
Код текущего сервера находится в **`codex/native-cdn-70658-20261106`**.
В `main` продублирована документация; старый код `main` не является кодом
активного сервера. Исторические инструкции для 70450/70532 и старого Compose
не описывают действующую установку.

## Версии и подтверждённые результаты

| Компонент | Текущее значение |
|---|---|
| Клиент | `wowf`, `1.60.1.70658`, последний выбранный язык `ruRU` |
| Ядро | `advocaite/TrinityCore`, ветка `forever`, commit `b4e7b940593f6402a822d4fbcdf31331d16f73b6` |
| Compose-проект | `forever-clean` |
| Сохранённая фаза | `ready`; фактическое состояние контейнеров проверять отдельно |
| Образ мира | `forever-trinitycore:gameplay-70658-4530bd4e14a1` |
| Версия миграции в state | `gameplay-1@pristine-b4e7b940593f` |
| Realm / content set / группа шифрования | `70` / `137` / `8` |
| Мультикласс | Forever Ascension `1.11.0`, протокол `3` |
| Энциклопедия / спутник | Forever Encyclopedia `0.9.8-v2.1-smartai-abilities` |
| Подстройка NPC | Forever Scaling `0.2.0`; не повышает уровень персонажа |
| MySQL | образ `mysql:8.0`; точная patch-версия в текущем отчёте не читалась |
| Последний рабочий эталон лаунчера | Multi `1.7.0` |
| Новая проверенная сборка | Multi `1.7.1`; установка и тест нового режима на ПК пользователя ещё не подтверждены |

Модули полностью скомпилированы и слинкованы на ПК пользователя. Установка
завершилась `GAMEPLAY ACTIVE`; повторная попытка использовала готовый образ без
новой компиляции. Пользователь подтвердил общую работоспособность игры и модулей.
Это не полный тест каждого заклинания, группового боя или сохранения после всех
сценариев перезапуска.

Отпечатки исходников активного комплекта:

```text
gameplay:    4530bd4e14a1193236e18203ca3e8977680cbea01804afdcd77630647889b1e1
advancement: 5fca3dc2eb4de36967900718016add6fb0e6834f316edcdb2f1249e996632309
```

## Карта Windows и WSL

| Назначение | Путь |
|---|---|
| Основной checkout в Ubuntu | `/home/Kayter/WoWForEver` (`~/WoWForEver`) |
| Рабочая установка сервера | `/home/Kayter/WoWForEver-clean` |
| Приватное состояние / Compose | `~/WoWForEver-clean/state.json`, `compose.private.json` |
| Команда управления | `~/WoWForEver-clean/server.sh` |
| **Активный controller checkout** | `/home/Kayter/WoWForEver-gameplay-tools.hReuvj` |
| **Активный clean checkout для bind-файлов** | `/home/Kayter/WoWForEver-clean-tools.ZbyhNF` |
| Извлечённые серверные данные | `/home/Kayter/WoWForEver-clean/data` |
| TLS-файлы действующего сервера | `/home/Kayter/WoWForEver/certs` |
| Последняя известная папка игры Windows | `E:\WoWForEver-work\clients\70658\_forever_` |
| Та же папка в WSL | `/mnt/e/WoWForEver-work/clients/70658/_forever_` |
| CASC-ресурсы клиента | `E:\WoWForEver-work\clients\70658\Data` — рядом с `_forever_` |
| Отчёты и резервные копии Windows | `E:\WoWForEver-work\reports` |
| Те же отчёты в WSL | `/mnt/e/WoWForEver-work/reports` |
| Настройки Multi | `%APPDATA%\forever-launcher-app\settings.json` |
| Приватная сессия Multi | `%APPDATA%\forever-launcher-app\session.json` |
| Отчёты проверки клиента | `%APPDATA%\forever-launcher-app\workshop\reports` |

В читающем отчёте `data_directory` — `null` (не задан): используется путь по умолчанию
`~/WoWForEver-clean/data`, подтверждённый действующим bind mount.

`server.sh` реально выполняет:

```text
exec python3 /home/Kayter/WoWForEver-gameplay-tools.hReuvj/scripts/clean-forever-server.py "$@" --root /home/Kayter/WoWForEver-clean
```

Обе выделенные папки инструментов являются зависимостями установки. Одной копии
`server.sh` недостаточно. Новые `baseline-tools.*` / `backup-check.*` — отдельные
checkout инструментов, а не автоматическая замена активного controller.
Перед удалением любого worktree нужно проверить ссылки из controller, Compose
и записей восстановления. Не переносить и не переименовывать действующие папки.

Путь извлечения исходных ресурсов и фактический `gameDir` могут меняться
независимо: актуальный выбор лаунчера хранится в settings.json. Переключение
клиента в Multi само по себе не меняет источник данных уже собранного сервера.
Старые `E:\WoW_Forever`, `experiments/Forever-client-v4` и staging 70707 сохраняются
как отдельные копии; они не являются основанием переключать текущий сервер.

## Контейнеры, порты и реальные bind mounts

| Сервис | Образ | Публикация на Windows/WSL-хосте |
|---|---|---|
| worldserver | `forever-trinitycore:gameplay-70658-4530bd4e14a1` | `127.0.0.1:8085 → 8085/tcp` |
| bnetserver | `forever-trinitycore:clean-b4e7b940593f` | `127.0.0.1:1119 → 1119/tcp`, `127.0.0.1:8081 → 8081/tcp` |
| web | `forever-clean-web:local` | `127.0.0.1:8088 → 8000/tcp` |
| mysql | `mysql:8.0` | наружу не опубликован; `3306` внутри Docker |

Профиль подключения: адрес `127.0.0.1`, portal/certificate hostname
`trinity.actual.battle.net`, группа ключа `8`. Сайт: `http://127.0.0.1:8088`.
SOAP `worldserver:7878` используется внутри сети Docker; это не клиентский порт.
Публикация ограничена loopback. Доступ извне не настроен этим описанием.

Подключённые файлы и каталоги:

| Хост WSL | Контейнер / назначение |
|---|---|
| `~/WoWForEver-clean/data` | worldserver: `/opt/trinitycore/data` |
| `~/WoWForEver-clean-tools.ZbyhNF/docker/clean/mysql-init.sh` | mysql: `/docker-entrypoint-initdb.d/01-clean.sh` |
| `~/WoWForEver-clean-tools.ZbyhNF/docker/clean/entrypoint.py` | bnetserver: `/usr/local/bin/forever-clean-entrypoint.py` |
| `~/WoWForEver/certs` | bnetserver: `/opt/trinitycore/certs` |
| `~/WoWForEver/certs/ca/forever_root_ca.crt` | web: `/certs/ca/forever_root_ca.crt` |

У worldserver сейчас нет bind mount старого entrypoint: он находится в игровом
образе. Базы `auth`, `world`, `characters`, `hotfixes` размещены в именованном
Docker-томе MySQL; логи — в отдельном именованном томе. Ключи томов в Compose:
`mysql-data` и `logs`. Фактические выделенные имена томов следует читать через
Docker/Compose, а не угадывать путь внутри WSL или копировать живой MySQL-каталог.

Сгенерированные конфиги: `/opt/trinitycore/etc/worldserver.conf` и
`bnetserver.conf`; логи: `/opt/trinitycore/logs`. Конфиги создаются entrypoint из
`.dist` и настроек окружения при старте. Временная правка внутри контейнера
не является сохранённой настройкой. Старый `overrides/worldserver.conf` сейчас
не подключён к worldserver: инструкции legacy-профиля к нему неприменимы.
Автоимпорт/автомиграция баз в активном игровом профиле выключены.

## Повседневное управление

Из Ubuntu/WSL на **ПК пользователя**:

```bash
~/WoWForEver-clean/server.sh status
~/WoWForEver-clean/server.sh start
~/WoWForEver-clean/server.sh stop
~/WoWForEver-clean/server.sh restart
```

`stop` останавливает web/bnet/world; MySQL остаётся запущенным.
`restart` перезапускает игровые сервисы. Эти команды не предназначены для
смены ядра, повторного импорта базы или установки модулей.

Читающие проверки текущего состояния:

```bash
docker compose -p forever-clean -f "$HOME/WoWForEver-clean/compose.private.json" ps -a
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
git -C "$HOME/WoWForEver-gameplay-tools.hReuvj" rev-parse HEAD
git -C "$HOME/WoWForEver-clean-tools.ZbyhNF" rev-parse HEAD
```

Для нового чата достаточно отфильтрованных полей state, ссылок и сообщений
ошибок. Полный state/Compose содержит пароли; полный session.json — токен.

Ранее порт 8085 занимал отдельный Windows-процесс `mangosd`; конфликт устранён.
Если ошибка привязки повторится, проверяйте владельца порта во всех TCP-состояниях,
не только Listen: тогда порт удерживался Established/bound-сокетом. Смена ядра,
сброс базы или повторная загрузка клиента такую причину не исправляют.

## Где менять код

Все ссылки ниже ведут в рабочую ветку. Перед работой получите её в отдельный
checkout/worktree и проверьте состояние активной установки; `main` не содержит
автоматически весь код рабочей ветки.

| Задача | Исходники / инструменты |
|---|---|
| Лаунчер, настройки, запуск, автоустановка аддонов | [`app/src-tauri/src`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106/app/src-tauri/src), особенно `addon.rs`, `config.rs`, `lib.rs` |
| Интерфейс Multi | [`app/ui`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106/app/ui), пять языков |
| Отдельный загрузчик CASC | [`tools/forever-casc-worker`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106/tools/forever-casc-worker) |
| Мультикласс | [`mods/forever-advancement`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106/mods/forever-advancement): C++, SQL, Lua, каталог |
| Энциклопедия / спутник | [`mods/living-encyclopedia`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106/mods/living-encyclopedia), активный адаптер `ForeverEncyclopediaRuntimeV5.cpp` |
| Scaling | [`mod-forever-scaling`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106/mod-forever-scaling) |
| Инъекция всех модулей в pinned core | [`scripts/inject-gameplay.py`](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/scripts/inject-gameplay.py) и отдельные injectors |
| Сборка игрового образа | [`docker/gameplay/Dockerfile`](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docker/gameplay/Dockerfile), базовый `docker/clean/Dockerfile` |
| Установщик / readiness | `scripts/enable-clean-gameplay.py`, `enable-clean-advancement.py`, `module_readiness.py` |
| Бэкап / проверка восстановления SQL | `scripts/backup-clean-baseline.py`, `docker_archive_identity.py`, `test-baseline-restore.py` |

TrinityCore клонируется на точный SHA в Docker build (`/src/TrinityCore`),
модули инъецируются и компилируются вместе с изменёнными файлами ядра.
Бинарники устанавливаются в `/opt/trinitycore/bin`. Правки исходников в новом
checkout не меняют уже запущенный образ; правки бинарника контейнера не являются
переносимым обновлением.

`enable-clean-gameplay.py install` уже был выполнен. Он не является универсальной
командой обновления любого активного профиля: другой отпечаток исходников
требует подготовленного перехода. Не выполнять откат только ради обхода этой
проверки. Изменение ядра/схемы готовится с отдельной копией баз, проверкой данных
и конкретным планом переключения. Изменение `.build.info`, build в профиле или
`auth.realmlist` само по себе не переносит клиентский протокол на 70707.

## Лаунчер и работа с аддонами

[Проверенный Multi 1.7.1](https://github.com/Domenklay/WoWForEver/actions/runs/42291254078/artifacts/13540302260).
Полный ZIP: `9 149 166` байт, SHA-256:

```text
a9254f60a896d7e029dc78cc7a6e1b39d16875224ec9e446b233b5e86f5c8d29
```

Артефакты Actions требуют входа в GitHub и имеют срок хранения. Скачанную копию
стоит хранить рядом с эталоном. Публичный CA сохранён; его SHA-256:
`d2a887dfe8e07191b7cb1d6fa8801bc4c59f4b87668ef4f6973f39d287bb799c`.

Аддоны находятся в выбранной папке игры:

```text
_forever_/Interface/AddOns/ForeverAscension
_forever_/Interface/AddOns/ForeverEncyclopedia
```

Multi 1.7.1: **Настройки → Игровые аддоны → Разработка аддонов → Сохранить**.
Режим выключен по умолчанию. При включении сохраняются существующие папки,
включая неполные; отсутствующие скачиваются из закреплённой версии. При
выключении на следующем запуске возвращается проверка опубликованных версий,
а заменяемые папки копируются в `.forever-multi/addon-backups/<id>/<имя>`.
Ссылки и Windows junction не поддерживаются. Режим сохраняется в настройках
Multi, включая последующую смену выбранного клиента.

Команды игры: `/fa` или `/ascension`, `/ency`. Scaling отдельного аддона не требует.
Покупки/открытия хранятся на сервере; SavedVariables — у клиента в WTF.
Multi использует отдельный `WTF/ForeverLauncher.wtf`, сохраняя исходный Config.wtf.
Сессия лаунчера содержит токен и не публикуется.

## Резервная копия и восстановление

Свежая проверенная папка: `E:\WoWForEver-work\reports\baseline-70658-20261107-003902`.
7 ноября пользователь получил `BASELINE BACKUP VERIFIED` при создании на `877b877`.
Прежняя проверенная копия `baseline-70658-20261106-231543` остаётся предыдущей опорной точкой.
В ней свежий SQL четырёх баз, ресурсы/конфиги/сертификаты/исходники controller,
точные Docker-образы и manifest с контрольными суммами. Это приватная копия;
она не входит в Git. Клиент WoW в серверный архив не включён.

Запись отката установки модулей:
`~/WoWForEver-clean/advancement/4bae99119c86/install.json`.
Её `databases-before.sql.gz` — старый снимок **до** установки; текущий дамп
в проверенном эталоне называется `databases-current.sql.gz`.

[Порядок резервирования](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-BACKUP.ru.md).
[Тест восстановления SQL](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-RESTORE.ru.md).
Тест уже прошёл в CI на настоящем MySQL с созданными тестовыми базами,
строками модулей и представлением, включая отказ на ошибочном SQL и очистку.
7 ноября на свежей приватной копии пользователя также получен
`DATABASE RESTORE VERIFIED`: четыре базы импортированы в отдельный MySQL,
счётчики и структура совпали со снимком, проверены десять таблиц модулей.
Тестовые контейнер и том удалены. Отчёт:
`/mnt/e/WoWForEver-work/reports/restore-test-20261107-004340-520b852f5c8f/report.json`.
Рабочий сервер был возобновлён и прошёл readiness до копирования больших архивов.
Полный запуск worldserver/bnetserver/web из восстановленного архива и вход клиента
в восстановленный мир пока не проверены. Подготовлен
[изолированный тест запуска сервисов](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-SERVICES-RESTORE.ru.md):
восстановленные файлы, отдельный MySQL/внутренняя сеть, TLS и HTTP, затем очистка.
Рабочие сервисы и клиент не переключаются; вход клиента и импорт образов на
пустой Docker этим тестом не подтверждаются.

## Что ещё не завершено

- Экономика Ability Essence: пока лимит покупок, по умолчанию 8 способностей.
- Кастомный Mana-forged Barrier `701463`: эффекты не перенесены, покупка/каст блокируются.
- Полный каталог талантов, сложные проки, питомцы и все ресурсы не поддерживаются автоматически.
- Спутник использует диагностический шаблон `1933`; внешность летающей книги не подтверждена.
- Scaling: `max(исходный уровень NPC, min(70, max(1, эффективный уровень игрока − 9)))`.
  Ограничение 70 применяется к поднимаемой части; исходный уровень старшего NPC не снижается.
  Защита ограничивает одно событие урона, а не серию/временное окно. Нет полного
  слоя масштабирования наград и подземелий под размер группы.
- Mmap pathfinding выключен в текущем entrypoint.
- Ранее был ACCESS_VIOLATION клиента и ошибки CDN. Позднее пользователь подтвердил
  рабочий запуск; точная причина старого вылета не установлена.
- Подробная игровая приёмка, тест режима разработки 1.7.1 на ПК пользователя и
  полное аварийное восстановление остаются незавершёнными.

## Доказательства и правила для следующего чата

- [Сборка Multi 1.7.1](https://github.com/Domenklay/WoWForEver/actions/runs/42291254078): 61 тест лаунчера, 224 теста загрузчика, UI пяти языков, PowerShell 5.1, NSIS/portable; ZIP/EXE/CA/GPL source проверены.
- [Проверки игрового комплекта](https://github.com/Domenklay/WoWForEver/actions/runs/42291253941): 449 Python-тестов, 28 пропусков и компиляция 12 файлов на реальных заголовках 70658.
- [Проверки SQL-восстановления](https://github.com/Domenklay/WoWForEver/actions/runs/42295336273): 461 тест, 29 условных пропусков; отдельный реальный MySQL integration test прошёл.
- [Код сборки Multi](https://github.com/Domenklay/WoWForEver/commit/87edd5aa6bdf0168dd25714c17b5815df82f6c68), [код restore-теста](https://github.com/Domenklay/WoWForEver/commit/08c75faa6e99a24c72b8034d242f1fa037701b3b).

Сначала прочитайте эту страницу, JSON и AGENTS.md рабочей ветки. Среда нового
чата может быть облачной: доступ к Git не означает доступ к Windows/WSL пользователя.
Не объявляйте локальное развёртывание выполненным по одним облачным тестам.

Сохраняйте существующие базы, персонажей, сертификаты, клиент и активные
worktree-зависимости. Не запускайте старые root Compose/install-dev/cleanup/reset
команды для этой ready-установки. Не меняйте сборку клиента ради совпадения числа
в профиле. Делайте изменения в отдельном checkout, проверяйте на точном ядре,
обновляйте этот документ и JSON только по подтверждённым фактам.

В Git и сообщения не включаются пароли, закрытые ключи, session.json, полные
state/Compose, SQL-дампы, приватные бэкапы и игровые ресурсы. Публичный сертификат,
исходники и отфильтрованные сведения о версиях/путях допустимы.
