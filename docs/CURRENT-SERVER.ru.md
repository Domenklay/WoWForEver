# WoWForEver: текущее состояние сервера

Обновлено **8 ноября 2026, Europe/Moscow**. Это точка входа для нового чата и
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
| Образ мира | `forever-trinitycore:gameplay-70658-54f07b4ce9ca` |
| Версия миграции в state | `gameplay-1.13@pristine-b4e7b940593f` |
| Realm / content set / группа шифрования | `70` / `137` / `8` |
| Мультикласс | Forever Ascension `1.13.0`, протокол `3` |
| Энциклопедия / спутник | Forever Encyclopedia `0.9.8-v2.1-smartai-abilities` |
| Подстройка NPC | Forever Scaling `0.4.0`; Dungeon Finder `0.2.0`, solo/group включены |
| MySQL | образ `mysql:8.0`; точная patch-версия в текущем отчёте не читалась |
| Последний рабочий эталон лаунчера | Multi `1.7.0` |
| Новая проверенная сборка | Multi `1.9.0`; вкладка аддонов, журнал и автовход проверены в CI, тест на ПК пользователя ещё не подтверждён |

Модули полностью скомпилированы и слинкованы на ПК пользователя. Установка
завершилась `GAMEPLAY ACTIVE`; повторная попытка использовала готовый образ без
новой компиляции. Пользователь подтвердил общую работоспособность игры и модулей.
Это не полный тест каждого заклинания, группового боя или сохранения после всех
сценариев перезапуска.

Отпечатки исходников активного комплекта:

```text
gameplay:    54f07b4ce9cadef8561096e6074d400d2a80a9d983fc5e7815e74c18157a9f52
advancement: 53c704ac9d98823769614008101390981bc9260fa879de87e6f512b285870520
```

## Карта Windows и WSL

| Назначение | Путь |
|---|---|
| Основной checkout в Ubuntu | `/home/Kayter/WoWForEver` (`~/WoWForEver`) |
| Рабочая установка сервера | `/home/Kayter/WoWForEver-clean` |
| Приватное состояние / Compose | `~/WoWForEver-clean/state.json`, `compose.private.json` |
| Команда управления | `~/WoWForEver-clean/server.sh` |
| **Активный controller checkout** | `/home/Kayter/WoWForEver-dungeon-upgrade-70658` |
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
exec python3 /home/Kayter/WoWForEver-dungeon-upgrade-70658/scripts/clean-forever-server.py "$@" --root /home/Kayter/WoWForEver-clean
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
| worldserver | `forever-trinitycore:gameplay-70658-54f07b4ce9ca` | `127.0.0.1:8085 → 8085/tcp` |
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

[Проверенный Multi 1.9.0](https://github.com/Domenklay/WoWForEver/actions/runs/42361020986/artifacts/13570041961).
SHA-256 полного ZIP: `189fd565a0d2eb743ede0b4924f71c634574814a03fb8d63ad2602523824d748`.
Actions-артефакты требуют входа в GitHub и имеют срок хранения. Публичный CA
сохранён: `d2a887dfe8e07191b7cb1d6fa8801bc4c59f4b87668ef4f6973f39d287bb799c`.
Последняя точно подтверждённая версия эталона — 1.7.0. На новом скриншоте
пользователя уже видна отдельная страница аддонов; точный номер установленного
EXE, исправление журнала и автовход отдельно пока не подтверждены.

[Каналы аддонов и инструкция разработчику](https://github.com/Domenklay/WoWForEver/blob/main/docs/ADDON-CHANNELS.ru.md).
Главный список — [main/addons/channels.json](https://github.com/Domenklay/WoWForEver/blob/main/addons/channels.json).
В нём оба комплекта с точными исходными коммитами, версиями, протоколами, размерами
и SHA-256. Тестовый комплект теперь содержит аддон Ascension 1.14.0 и Encyclopedia 0.9.23-v2.1-fdf-diagnostics; stable остаётся 1.11.0/0.9.8. Публикация нового
совместимого комплекта не требует пересборки Multi; формат рассчитан на действующие
ForeverAscension и ForeverEncyclopedia, клиент 70658. Scaling отдельного аддона не требует.

В настройках отдельно управляются операции загрузки/исправления WoW,
обновления аддонов, stable/testing и локальная разработка. Отключение обновлений
аддонов пропускает даже установку отсутствующих папок. Для тестового комплекта
включить обновления, выключить разработку, выбрать «Тестовые» и сохранить.
Все изменённые аддоны скачиваются и проверяются до замены первого; резервные копии
в `.forever-multi/addon-backups/<id>/<имя>`, восстановление прерванной операции
ведётся журналом. Другие аддоны, SavedVariables и CASC не заменяются этим механизмом.
При недоступном GitHub используются проверенный кеш или список сборки с сообщением
в журнале; тестовый канал не подменяется утверждённым. Battle.net управляется отдельно.

Автовход включён по умолчанию и для Wow.exe: свежий серверный билет запрашивается
после подготовки аддонов, проверяется аккаунт ответа, затем билет передаётся клиенту
через его профиль запуска. На Windows используется DPAPI, подходящая ветка реестра
выбирается по EXE. Пароль не записывается в WTF, билет не передаётся в CLI.
Пустой список игровых аккаунтов не заменяется произвольным WoW1. Ручной вход
доступен отдельным переключателем; выбор персонажа остаётся в игре.

Проверены 80 Rust-тестов лаунчера, 224 теста загрузчика, UI на пяти языках,
реальный Chromium и PowerShell 5.1. Catalogue CI 42359312577 проверил байты из точных
исходных коммитов. Игровые проверки каналов и автовхода на ПК пользователя ещё ожидаются.
Команды игры: `/fa`, `/ascension`, `/ency`. Сессия лаунчера приватная и не публикуется.

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
Затем пользователь успешно выполнил
[изолированный тест запуска сервисов](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-SERVICES-RESTORE.ru.md)
на исходниках `b282fb2` и получил `RESTORED SERVICES VERIFIED`. Проверены
восстановленные worldserver, три модуля, online realm 70/build 70658, вход
TCP/TLS с исходным CA, HTTP health/status и выдаваемый CA. Тестовые контейнеры,
тома, сеть, распакованные файлы и временные пароли очищены. Отчёт:
`/home/Kayter/WoWForEver-restore-trials/forever-services-check-885b9c3e9bc2/report.json`.
Рабочие сервисы и клиент не переключались. Вход игрового клиента в восстановленный
мир и импорт сохранённых образов на пустой Docker ещё не проверены.
[CI 42301993948](https://github.com/Domenklay/WoWForEver/actions/runs/42301993948)
успешно проверил 473 теста (30 условных пропусков), настоящий MySQL и сервисные
фикстуры с TLS/HTTP, отказом мира и очисткой. Это отдельные проверки инструмента;
запуск реального восстановленного TrinityCore подтверждён выводом пользователя выше.

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
- Подробная игровая приёмка, тест вкладки аддонов/автовхода 1.9.0 на ПК пользователя и
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

## Подготовлено: сервер мультикласса 1.14.2

Пользователь подтвердил уже установленный сервер Ascension 1.13, Scaling 0.4,
DungeonFinder 0.2 и controller checkout `WoWForEver-dungeon-upgrade-70658`,
коммит `a1bc54e3aed2aa2d08e4c0c41213b295cf01d987`.
Текущая запись перехода: `advancement/347c815174f8/transition.json`.
Состав источников действующего образа воспроизведён по обоим SHA-256 выше.

[Мультикласс 1.14.2: исправления, ограничения и безопасный переход](MULTICLASS-1.14.ru.md).
Причина ездовых животных в меню — слишком широкий отбор категории CLASS,
куда входят также Mounts/Companions и pet-skills. Причина пустых деревьев —
присланные GridX 50–53, выводившиеся за пределами панели; отдельные источники
талантов также порождали повторы веток. Исправлены школа/классовая принадлежность,
относительные координаты, три ветки и родные фоны из клиента.

Вкладка нативного окна подтверждена пользователем; её привязку сохраняем.
Исправление каталога требует серверной версии 1.14.1. Подготовка включает полный
новый образ и изолированный старт на копии baseline; Scaling 0.4, Finder 0.2,
существующие environment мира, службы, TLS и прогресс сохраняются.
CI 42398310341/42398310377/42398310367 прошли; локально 499 тестов, 30 пропусков,
UI 31. Исходник `c13cdbff6cc0623e24a8667d42f343b80f8005a8`.
Установка и игровая приёмка 1.14.1 на ПК ещё не подтверждены.

Испытание 1.14 на ПК завершилось `failed-cleaned`: у воина определилась одна
школа вместо трёх, отчёт `forever-services-check-ce722b2f8d81/report.json`.
Рабочий сервер остаётся 1.13. Исправленный источник 1.14.1:
`80abf81afa1eecd977f4b172894db4c63d49411c` — школа определяется по заклинанию,
а не по единственному корню классового дерева. Явные ошибки инициализации
сразу останавливают испытание с подробной причиной. Аддон остаётся 1.14.0.
Старый образ `gameplay-70658-ca79ccc1c1eb` не является проверенным кандидатом.
Команда подготовки обновлена в [инструкции](MULTICLASS-1.14.ru.md).

Испытание 1.14.1 также завершилось `failed-cleaned` (отчёт
`forever-services-check-34d3a8de1d72/report.json`): три школы воина найдены,
семь узлов не имеют прямой/связной привязки. Кандидат `gameplay-70658-dd9ed66dd339`
не применяется. Исправление 1.14.2, исходник
`335c9192e6ddb576095c0323499bcb39ee3499c6`, дополняет метаданные aliases/ranks,
вариантами узлов, однозначными группами и точным совпадением столбцов в трёх
непересекающихся нативных ветках. Нет удаления узлов или подбора ближайшей ветки.
Пользовательское испытание 1.14.2 и визуальная приёмка ожидаются; рабочий сервер
остаётся 1.13 / Scaling 0.4 / Finder 0.2, аддон 1.14.0 менять не требуется.
