#requires -Version 5.1
param([string]$Repository = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$ErrorActionPreference = 'Stop'
$script = Join-Path $Repository 'tools\clean-server\Prepare-CleanClient.ps1'
function Assert($Value, [string]$Message) { if (!$Value) { throw $Message } }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('clean-client-' + [guid]::NewGuid().ToString('N'))
try {
    $root = Join-Path $temp 'copy'; $original = Join-Path $temp 'original'
    foreach ($base in @($root, $original)) {
        foreach ($folder in @('Data\data', '_forever_\WTF', '_forever_\Cache', '_forever_\Interface\AddOns\OwnedAddon')) {
            [IO.Directory]::CreateDirectory((Join-Path $base $folder)) | Out-Null
        }
        [IO.File]::WriteAllText((Join-Path $base '.build.info'), 'synthetic build metadata')
        [IO.File]::WriteAllText((Join-Path $base 'Data\data\data.000'), 'synthetic CASC payload')
        [IO.File]::WriteAllText((Join-Path $base '_forever_\Wow.exe'), 'synthetic EXE')
        [IO.File]::WriteAllText((Join-Path $base '_forever_\WTF\Config.wtf'), 'owned settings')
        [IO.File]::WriteAllText((Join-Path $base '_forever_\Cache\owned.cache'), 'owned cache')
        [IO.File]::WriteAllText((Join-Path $base '_forever_\Interface\AddOns\OwnedAddon\main.lua'), 'owned addon')
    }
    $game = Join-Path $root '_forever_'
    & $script -GameDirectory $game -OriginalDirectory $original
    $backup = @(Get-ChildItem -LiteralPath (Join-Path $root '.forever-multi') -Directory)[0].FullName
    Assert (!(Test-Path -LiteralPath (Join-Path $game 'WTF'))) 'Test settings were not moved'
    Assert (!(Test-Path -LiteralPath (Join-Path $game 'Cache'))) 'Test cache was not moved'
    Assert (!(Test-Path -LiteralPath (Join-Path $game 'Interface\AddOns'))) 'Test AddOns were not moved'
    Assert ([IO.File]::ReadAllText((Join-Path $backup 'WTF\Config.wtf')) -eq 'owned settings') 'Settings backup missing'
    Assert ([IO.File]::ReadAllText((Join-Path $backup 'Interface\AddOns\OwnedAddon\main.lua')) -eq 'owned addon') 'AddOn backup missing'
    Assert ([IO.File]::ReadAllText((Join-Path $root 'Data\data\data.000')) -eq 'synthetic CASC payload') 'CASC changed'
    Assert ([IO.File]::ReadAllText((Join-Path $root '.build.info')) -eq 'synthetic build metadata') 'Build metadata changed'
    Assert ([IO.File]::ReadAllText((Join-Path $original '_forever_\WTF\Config.wtf')) -eq 'owned settings') 'Original changed'
    $report = [IO.File]::ReadAllText((Join-Path $backup 'result.json')) | ConvertFrom-Json
    Assert ($report.phase -eq 'complete' -and $report.moved.Count -eq 3 -and !$report.cascModified) 'Incomplete backup report'
    $rejected = $false
    try { & $script -GameDirectory (Join-Path $original '_forever_') -OriginalDirectory $original } catch { $rejected = $true }
    Assert $rejected 'Original must not be reset'
    $alias = Join-Path $temp 'alias'
    New-Item -ItemType Junction -Path $alias -Target $original | Out-Null
    $rejected = $false
    try { & $script -GameDirectory (Join-Path $alias '_forever_') -OriginalDirectory $original } catch { $rejected = $true }
    Assert $rejected 'Junction alias must not reset original'
    [IO.Directory]::Delete($alias)
    Write-Host 'Clean client: settings/AddOns backup, source isolation, CASC preservation and junction guards passed.'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
