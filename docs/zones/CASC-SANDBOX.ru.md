# Синтетическое CASC-хранилище: проверка полного чтения

Этот стенд создаёт собственные текстовые ресурсы и новое маленькое хранилище.
Он не открывает и не изменяет клиент Forever, серверные данные или базу MySQL.
Это проверка форматов и загрузчика, а не установщик Даларана.

## Что реализовано

`scripts/build-casc-sandbox.py` создаёт две независимые установки лаборатории:

- baseline: один собственный текстовый ресурс, FileDataID 16777200;
- candidate: тот же ресурс плюс второй текст, FileDataID 16777201.

Для каждой создаются ROOT TSFM version=2 с 17-байтовыми заголовками групп,
TVFS v1 flags=7, ENCODING v1 с CKey/EKey-страницами и их MD5, пустой DOWNLOAD,
локальный data.000, 16 IDX версии 7 и согласованные конфигурации с .build.info.
BLTE содержит настоящую таблицу одного кадра и его MD5. Заголовок записи в
сегменте также содержит Jenkins hash и checksum по алгоритму CascLib.
Здесь нет отключения контроля целостности или замены данных нулями.

CascLib прекращает чтение IDX при первом отсутствующем bucket-файле, поэтому
создаются все 16. Для пустых bucket используется поддерживаемая пустая страничная
форма; непустые используют блок записей с контрольной суммой.

Генератор **отказывается работать с существующим каталогом назначения**.
Это также относится к повторному запуску в папку предыдущего эксперимента.
Временные бинарные файлы и манифесты не добавляются в Git.

## Сквозная проверка

`tools/legion-casc-probe/check-storage.cpp` связан с CascLib из ядра
91d49b230f89c3ab4719f5b2b2d1e70ed36613c4. Хранилище открывается локально,
bOnlineStorage=false; файлы читаются по FileDataID с CASC_STRICT_DATA_CHECK.
После полного чтения вычисляется SHA-256 и сверяется с исходным текстом.
Колбэк подтверждает загрузку ENCODING, DOWNLOAD, TVFS и переход ROOT (reparsed)
к legacy ROOT. Специальный TVFS_PARSE_WOW_ROOT не включается.

| Случай | Исходный ресурс | Новый ресурс |
|---|---|---|
| baseline | READ_OK, исходный SHA-256 | OPEN_FAILED, ошибка 2 |
| candidate | READ_OK, тот же SHA-256 | READ_OK, ожидаемый SHA-256 |
| data-only: в baseline добавлены только байты нового BLTE | READ_OK | OPEN_FAILED, ошибка 2 |
| damaged-frame: в candidate испорчен байт нового текста | READ_OK | READ_FAILED, ошибка 1004 в Linux CascLib |

Таким образом, проверяется и успешное чтение, и два независимых отказа:
отсутствие регистрации и повреждение кадра. Baseline/candidate генерируются
целиком по отдельности; это ещё не обновление существующего хранилища.

В облаке дополнительно проверен контейнерный запуск с network=none,
read-only корнем и bind mount, UID/GID владельца лаборатории, cap-drop ALL
и no-new-privileges. Для него используется собранный здесь checker и системные
runtime-библиотеки в локальном scratch-образе. В CascLib применена только уже
существующая в Dockerfile поправка O_RDONLY при EROFS/EACCES.
Новый target casc-sandbox-check основного Dockerfile отдельно в облаке не собирался.

Результаты: [sandbox-storage-review.json](../../content/donors/legion-735/sandbox-storage-review.json).

## Как воспроизвести

Сначала можно создать лабораторию без запуска C++-проверки:

```bash
cd ~/WoWForEver
python3 scripts/build-casc-sandbox.py \
  --output /mnt/e/WoWForEver-work/experiments/casc-storage-v1
```

Для разработчика с собранным CascLib: связать check-storage.cpp с libcasc.a,
libz и libcrypto. Если проверка будет в read-only mount, нужна имеющаяся
в Dockerfile поправка FileStream.cpp. После сборки checker полный тест создаёт
новую папку и выполняет четыре сценария:

```bash
python3 scripts/build-casc-sandbox.py \
  --output /mnt/e/WoWForEver-work/experiments/casc-storage-v2 \
  --checker /path/to/check-storage
```

В выбранной папке появятся четыре синтетических хранилища, логи стадий
и verification.json. Команда завершается ошибкой при неожиданном результате;
ожидаемые OPEN_FAILED/READ_FAILED в отрицательных сценариях считаются проверками.

Основной Dockerfile также содержит необязательный target:

```bash
docker build --target casc-sandbox-check -t forever-casc-sandbox-check:local .
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --mount type=bind,src=/mnt/e/WoWForEver-work/experiments/casc-storage-v1/candidate,dst=/lab,readonly \
  forever-casc-sandbox-check:local /lab 16777200 16777201
```

Сборка target наследует build-стадию ядра; без подходящего кэша она может заново
собирать ядро. Прямой docker build не читает параметры .env для Compose:
при необходимости передайте TC_REF/BUILD_JOBS через --build-arg.
Рабочие контейнеры серверов эти команды не перезапускают.

Проверки Python с уже собранным native checker:

```bash
CASC_SANDBOX_CHECKER=/path/to/check-storage \
CASC_CONTENT_KEY_PROBE=/path/to/legionprobe \
python3 -m unittest discover -s tests -v
```

Без этих переменных два native-теста явно пропускаются; остальные не требуют
ядра или клиента. С обеими переменными в облаке проходят все 27 тестов:
первый native-тест включает четыре сквозных сценария, второй — поиск по CKey
и обработку неизвестного/некорректного ключа.

## Границы результата и следующий шаг

Стенд использует один сегмент, небольшие single-page CKey/EKey-таблицы,
незашифрованные собственные ресурсы и одну enUS-группу ROOT без name hashes.
Он не сохраняет все локали/группы реального ROOT и не обновляет существующие
141-МБ encoding или потоковую установку клиента.

Первый [инкрементальный updater](CASC-INCREMENTAL.ru.md) уже проверен на копиях
синтетического хранилища: добавлены 70 ресурсов, затем ещё один FileDataID,
с сохранением прежних данных. Для настоящего клиента ещё требуется профиль
его манифестов. После этого нужна отдельная проверка
WowB.exe 70532; успешного чтения CascLib для подтверждения работы игры недостаточно.
Map/Area, зависимости локации и серверные maps/vmaps пока не установлены.
