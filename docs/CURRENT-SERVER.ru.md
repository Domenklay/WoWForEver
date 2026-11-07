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
| Новая проверенная сборка | Multi `1.9.0`; вкладка аддонов, журнал и автовход проверены в CI, тест на ПК пользователя ещё не подтверждён |

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
и SHA-256. Тестовый комплект теперь содержит Ascension 1.13.0 и Encyclopedia 0.9.19-v2.1-archive-filters; stable остаётся 1.11.0/0.9.8. Публикация нового
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

## Подготовлено: мультикласс 1.13 и Multi 1.9

Multi 1.9.0 добавляет отдельную вкладку «Игровые аддоны» с фактически установленными
версиями, проверкой наших файлов по квитанции и переключателем полного stable/testing.
Журнал стал отдельной страницей с прокруткой и явным пустым состоянием.
Windows CI: 81 тест лаунчера, 224 загрузчика; Chromium проверил навигацию и сохранение.
Сервер на ПК пользователя этим не изменён.

[Мультикласс 1.13: поведение, ограничения, подготовка и переход](MULTICLASS-1.13.ru.md):
90% XP подклассу / 10% персонажу с отдельным отключением; штатный каталог
70658 без кастомной вкладки и старого дерева 3.3.5. Убраны добавленные классы
«Охотник на демонов» и «Пробудитель». Способности прокручиваются единым списком.
В `PlayerSpellsFrame` добавляется штатная вкладка «Мультикласс» через `AddNamedTab`,
без закрытия основного окна. Нативные деревья сохраняют ветки, сетку, связи и ранги;
выдача/возврат поддерживаемых узлов проходят штатный `TraitMgr::ValidateConfig`.
Неподдерживаемые эффекты и ресурсы остаются заблокированы. Базовые умения охотника
и временное владение оружием/бронёй берутся из нативных данных выбранного класса.

Аддон 1.13 совместим с сервером 1.11 по протоколу 3, но новые деревья, каталог,
владение и XP требуют нового backend. На пользовательском скриншоте есть сообщение
«Распределение опыта: обновите сервер»: сервер не обновился от установки аддона.
Читающие UI-пробы подтвердили `PlayerSpellsFrame`, его `TabSystem`, `TalentsFrame`,
`SpecFrame` и `SpellBookFrame`. Новая вкладка пока проверена фикстурами, не в игре.

Переход — `upgrade-clean-gameplay.py prepare/apply/rollback`: полная сборка,
изолированный старт на копии baseline, свежий дамп перед переключением, добавочная
таблица preferences. Откат меняет runtime, не загружает старые БД поверх прогресса.
Источник кандидата: `ae6a3f8ed5aa2fd43b65cc704ae88377ee25a8f2`.
CI [Ascension](https://github.com/Domenklay/WoWForEver/actions/runs/42380875759),
[совместные 14 единиц C++](https://github.com/Domenklay/WoWForEver/actions/runs/42380875788)
и [Windows/Linux worker](https://github.com/Domenklay/WoWForEver/actions/runs/42380875760)
прошли; локально 488 тестов, 30 пропусков. Проверка компиляции использует точные
команды CMake и `-fsyntax-only`; полная линковка новой версии и пользовательский
кандидат выполняются в `prepare`. Рабочий сервер всё ещё подтверждён на 1.11.0.
Игровая приёмка 1.13 и все механики питомцев/проков пока не подтверждены.
