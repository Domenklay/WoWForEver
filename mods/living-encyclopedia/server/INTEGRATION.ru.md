# Серверная интеграция: состояние
На этой стадии реализованы самостоятельные C++ правила маны, лечения, щита, локальных открытий и подсчёта каталога зоны, плюс тесты.
**Нет регистрации ScriptMgr, нет SQL-транзакций в worldserver, нет обработчиков убийств, предметов или достижений, нет сетевого протокола.**
Нельзя подключать код к production только на основании успешного standalone-теста.

## Фактическая инфраструктура репозитория
- Dockerfile собирает TrinityCore forever на зафиксированном коммите 91d49b230f89c3ab4719f5b2b2d1e70ed36613c4.
- Перед CMake работает scripts/inject-subclass.py, который внедряет отдельный subclass-адаптер.
- Не менять subclass adapter без проверки совместимости и регрессионных тестов.
- Ветка feature/living-encyclopedia-v0 не развёрнута и не входит в Dockerfile.

## Очередность безопасного подключения
1. Проверить точные сигнатуры PlayerScript/CreatureScript/WorldScript и AddonMessage в pinned core.
2. Реализовать отдельный inject-encyclopedia.py с однократными anchors и fail-closed, подключить после subclass.
3. Добавить SQL в правильные базы (auth vs characters) и обновления с backup и rollback.
4. Реализовать atomic first-discovery: уникальная запись + начисление очков в одной DB транзакции; защита от повторного входа.
5. Создать каталог по map/zone/area на основе server spawns, проверка accessibility и pagination.
6. Связать серверные эффекты с Player и auras; запрет PvP/рейда, корректное снятие щитов.
7. Проверить на staging, потом включить feature flag на игровом сервере.

## Локальный тест независимых правил
bash mods/living-encyclopedia/tests/run-rules.sh

## Примечание
Текущие SQL-файлы — черновики, не запускать на production без привязки к конкретной DB и тестирования.
