#requires -Version 5.1
param([Parameter(Mandatory = $true)][string]$Repository)
$ErrorActionPreference = 'Stop'
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('multi-preload-test-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $temporary 'game'
$game = Join-Path $root '_forever_'
$script = Join-Path $Repository 'scripts\inspect-forever-installation.ps1'
try {
    New-Item -ItemType Directory -Path $game, (Join-Path $root 'Data\data') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $env:WINDIR 'System32\kernel32.dll') -Destination (Join-Path $game 'Wow.exe')
    [IO.File]::WriteAllText((Join-Path $root '.build.info'), "Product!STRING:0|Active!DEC:1|Version!STRING:0`nwowf|1|1.60.1.70707`n")
    [IO.File]::WriteAllText((Join-Path $root 'Data\data\shmem'), 'owned storage fixture')
    $staging = Join-Path $root '.forever\preload-70707\_forever_'
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $env:WINDIR 'System32\kernel32.dll') -Destination (Join-Path $staging 'Wow.exe')
    Copy-Item -LiteralPath (Join-Path $env:WINDIR 'System32\kernel32.dll') -Destination (Join-Path $root 'Data\data\Wow.exe')
    $before = @(Get-ChildItem -LiteralPath $root -File -Recurse | Get-FileHash -Algorithm SHA256)
    $number = 0
    foreach ($selection in @($root, $game, (Join-Path $game 'Wow.exe'))) {
        $reportPath = Join-Path $temporary ('report-' + $number++ + '.json')
        & $script -GameDirectory $selection -OutputPath $reportPath | Out-Null
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        if ($report.executables.Count -ne 1) { throw 'Expected one installed executable.' }
        if ($report.executables[0].matchesExpectedBuild) { throw 'Metadata was mistaken for the native EXE version.' }
        if ($report.metadata[0].version -ne '1.60.1.70707') { throw 'Metadata inspection failed.' }
        if ($report.downloadCompletenessVerified) { throw 'Preloading must not be reported as a complete download.' }
    }
    $stagedReportPath = Join-Path $temporary 'staged.json'
    & $script -GameDirectory $root -FindStagedExecutables -OutputPath $stagedReportPath | Out-Null
    $stagedReport = Get-Content -LiteralPath $stagedReportPath -Raw | ConvertFrom-Json
    if ($stagedReport.stagedExecutables.Count -ne 1) { throw 'Expected one staged executable in the bounded scan.' }
    if ($stagedReport.stagedExecutables[0].matchesExpectedBuild) { throw 'A folder called 70707 was mistaken for an EXE version.' }
    if ($stagedReport.stagedExecutables[0].activated) { throw 'Discovering a staged EXE must not activate it.' }
    if ($stagedReport.stagedScan.directories -ge 512) { throw 'Small fixture unexpectedly hit the scan limit.' }
    $denied = $false
    try { & $script -GameDirectory $root -OutputPath (Join-Path $game 'report.json') | Out-Null } catch { $denied = $true }
    if (!$denied -or (Test-Path -LiteralPath (Join-Path $game 'report.json'))) { throw 'Report inside installation was not rejected.' }
    $after = @(Get-ChildItem -LiteralPath $root -File -Recurse | Get-FileHash -Algorithm SHA256)
    if (Compare-Object $before $after -Property Path, Hash) { throw 'Installation bytes or paths changed.' }
    Write-Host 'Preload inspection: native version, metadata separation, root/folder/EXE paths and unchanged installation passed.'
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
