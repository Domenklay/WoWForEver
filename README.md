# WoWForEver — рабочий сервер и инструменты

**Актуальная документация на 7 ноября 2026:**

- **[Текущее состояние: версии, пути, команды, ограничения](https://github.com/Domenklay/WoWForEver/blob/main/docs/CURRENT-SERVER.ru.md)** — начать отсюда, в том числе новому чату.
- [Машиночитаемый снимок](https://github.com/Domenklay/WoWForEver/blob/main/docs/current-server.json).
- [Инструкции для AI-ассистентов](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/AGENTS.md).

Рабочий код находится в ветке
[`codex/native-cdn-70658-20261106`](https://github.com/Domenklay/WoWForEver/tree/codex/native-cdn-70658-20261106).
В main опубликована точка входа в документацию; старый код main не заменяет код
действующей установки. Для изменений используйте рабочую ветку в отдельном checkout.

## Действующая установка

| Компонент | Версия / расположение |
|---|---|
| Клиент | wowf, **1.60.1.70658** |
| TrinityCore Forever | `b4e7b940593f6402a822d4fbcdf31331d16f73b6` |
| Мультикласс | Ascension 1.11.0, протокол 3 |
| Энциклопедия / спутник | 0.9.8-v2.1-smartai-abilities |
| Forever Scaling | 0.2.0 |
| Multi | рабочий эталон 1.7.0; проверенный выпуск 1.7.1 с разработкой аддонов |
| Сервер WSL | `/home/Kayter/WoWForEver-clean`, проект forever-clean |
| Управление | `~/WoWForEver-clean/server.sh status\|start\|stop\|restart` |

Пользователь подтвердил работу игры/модулей и целостность свежего бэкапа.
Подробная игровая приёмка и полное пробное восстановление ещё не завершены.
Точные bind mounts и зависимости каталогов приведены в текущем состоянии.

## Лаунчер

[Полный Multi 1.7.1 для Windows](https://github.com/Domenklay/WoWForEver/actions/runs/42291254078/artifacts/13540302260)
(нужен вход в GitHub; у Actions-артефактов ограничен срок хранения).

Распакуйте отдельно и используйте работающий клиент. Настройки → Игровые аддоны →
Разработка аддонов: существующие папки сохраняются, отсутствующие устанавливаются.
По умолчанию действуют обычная проверка версий и резервирование заменяемых папок.

## Документация по задачам

- [Игровые модули на 70658](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/GAMEPLAY-70658.ru.md).
- [Рабочий эталон](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-70658.ru.md).
- [Резервная копия](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-BACKUP.ru.md).
- [Изолированный тест восстановления баз](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BASELINE-RESTORE.ru.md).
- [Загрузка ресурсов клиента](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/NATIVE-CDN.ru.md).
- [Аудит служебных манифестов](https://github.com/Domenklay/WoWForEver/blob/codex/native-cdn-70658-20261106/docs/BOOTSTRAP-AUDIT.ru.md).

Старые инструкции Docker/70450/70532 сохранены в
[историческом README](https://github.com/Domenklay/WoWForEver/blob/a7e7747778042b537d062f019bbf2465d67a2863/README.md).
Они не являются инструкцией переустановки действующего ready-сервера.

## Проект и лицензия

Основа — [TrinityCore Forever](https://github.com/advocaite/TrinityCore/tree/forever),
первоначальная Docker-основа — [jibay442/forever_docker](https://github.com/jibay442/forever_docker).
История исходного проекта и лицензия сохранены. GNU GPL v2.0 или более поздняя
версия, как у TrinityCore: [LICENSE](LICENSE). Проект не связан с Blizzard и не
одобрен ею. World of Warcraft — товарный знак Blizzard Entertainment; для игровых
данных нужен собственный доступ к игре. Клиент, игровые ресурсы, приватные ключи,
пароли и дампы баз в Git не входят.
