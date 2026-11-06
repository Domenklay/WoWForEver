# Точная копия установленного клиента

6 ноября пользователь сообщил, что после восстановления в Multi снова появилась
ошибка целостности установки, и попросил обычное копирование без редактирования.
Точная причина повреждения по журналу запуска Multi не установлена. Операция
восстановления в app/src-tauri/src/client.rs заменяет файлы по манифесту и
перемещает некоторые лишние индексы/метаданные в карантин; это не простой clone.
Для следующей проверки этот механизм не используется.

Источник: весь `E:\WoW_Forever`, вместе с общими `Data`, `.build.info`,
`.forever` и `_forever_`. Папка `_forever_` сама по себе не содержит весь клиент.
Новая копия: `E:\WoWForEver-work\experiments\Forever-client-v4`.
Выбранная папка игры после копирования — её вложенная `_forever_`.

Закрыть обе игры и лаунчеры перед копированием. Использовать Windows PowerShell.
Назначение должно отсутствовать; существующая v3 сохраняется отдельно.

```powershell
$source = 'E:\WoW_Forever'
$target = 'E:\WoWForEver-work\experiments\Forever-client-v4'
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $target) { throw 'Папка назначения уже существует. Выберите новую пустую папку.' }
$links = @(Get-ChildItem -LiteralPath $source -Force -Recurse | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
if ($links.Count) { throw 'В оригинале есть ссылки/junction. Сначала нужно проверить их расположение.' }
robocopy $source $target /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /MT:8 /XJ
if ($LASTEXITCODE -ge 8) { throw "Копирование завершилось с ошибкой $LASTEXITCODE" }

$files = @(Get-ChildItem -LiteralPath $source -Force -Recurse -File)
$copies = @(Get-ChildItem -LiteralPath $target -Force -Recurse -File)
if ($files.Count -ne $copies.Count) { throw 'Число файлов не совпало.' }
$checked = 0
foreach ($file in $files) {
    $relative = $file.FullName.Substring($source.Length + 1)
    Write-Progress -Activity 'Сверка SHA-256 всех файлов' -Status $relative -PercentComplete (100 * $checked / $files.Count)
    $copy = Join-Path $target $relative
    if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash) {
        throw "Файлы различаются: $relative"
    }
    $checked++
}
Write-Progress -Activity 'Сверка SHA-256 всех файлов' -Completed
Write-Host "КОПИЯ СОВПАДАЕТ С ОРИГИНАЛОМ: $checked файлов"
```

Это штатное копирование файлов: без манифеста восстановления, перепаковки,
редактирования архивов/индексов или добавления наших marker/report-файлов в
назначение. Перед копированием проверяется отсутствие ссылок/junction;
`/XJ` дополнительно исключает их обход при появлении во время операции.

До первого запуска проверить набор относительных имён, размеры и SHA-256
**всех файлов**, включая архивы `data.NNN`. Не запускать игру или загрузчик во
время копирования и проверки. Сверка только шапок архивов или размеров не
доказывает идентичность. При ошибке проверки не применять поверх неё наше
«восстановление»; сохранить вывод и установить причину расхождения.

После совпадения копия ещё не проверена в игре: первоначальная проблема
зависания на выборе персонажа остаётся отдельным тестом. Для подключения к
локальному серверу Multi создаёт свой WTF с адресом/языком и заменяет публичный
ключ в памяти запущенного процесса. Эти действия не являются перепаковкой
CASC. Не запускать Download/Restore files и не переносить дополнения на новую
контрольную копию в рамках этого этапа. После первого запуска игра штатно
изменяет Logs, Cache, WTF и может менять собственное локальное состояние CASC;
исходная сверка относится к состоянию до запуска.

Чистый сервер уже прошёл проверку TCP/TLS для realm 70 и клиента 70658.
Для этого копирования сервер заново не устанавливается и базы не сбрасываются.
