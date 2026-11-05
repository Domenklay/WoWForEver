#requires -Version 5.1
<# Moves test-client settings, cache and AddOns into a reversible local backup.
   The original installation and CASC Data/.build.info are never changed. #>
[CmdletBinding()]
param(
    [string]$GameDirectory,
    [string]$OriginalDirectory = 'E:\WoW_Forever'
)
$ErrorActionPreference = 'Stop'
function Assert-PlainPath([string]$Value) {
    $path = $Value
    while ($path) {
        if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Linked installation or backup path is not supported.'
        }
        $parent = [IO.Directory]::GetParent($path)
        if ($null -eq $parent) { break }
        $path = $parent.FullName
    }
}
if (!$GameDirectory) {
    $settingsPath = Join-Path $env:APPDATA 'forever-launcher-app\settings.json'
    $settings = [IO.File]::ReadAllText($settingsPath) | ConvertFrom-Json
    $GameDirectory = [string]$settings.gameDir
    if (!$GameDirectory) { throw 'Choose the independent test client in Multi first.' }
}
$game = [IO.Path]::GetFullPath($GameDirectory).TrimEnd('\')
if (!(Test-Path -LiteralPath (Join-Path $game 'Wow.exe') -PathType Leaf)) {
    $game = Join-Path $game '_forever_'
}
if (!(Test-Path -LiteralPath (Join-Path $game 'Wow.exe') -PathType Leaf)) { throw 'Selected test folder has no Wow.exe.' }
$root = Split-Path -Parent $game
$original = [IO.Path]::GetFullPath($OriginalDirectory).TrimEnd('\')
if ((Split-Path -Leaf $original) -eq '_forever_') { $original = Split-Path -Parent $original }
Assert-PlainPath $root
Assert-PlainPath $original
if ($root -eq $original -or $root.StartsWith($original + '\', [StringComparison]::OrdinalIgnoreCase) -or $original.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Select an independent test copy, separate from the original.'
}
foreach ($required in @('.build.info', 'Data')) {
    if (!(Test-Path -LiteralPath (Join-Path $root $required))) { throw 'Invalid test installation root.' }
}
foreach ($relative in @('', 'WTF', 'Cache', 'Interface', 'Interface\AddOns')) {
    $path = if ($relative) { Join-Path $game $relative } else { $game }
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Linked test folders are not supported.'
    }
}
foreach ($process in Get-CimInstance Win32_Process -Filter "Name='Wow.exe' OR Name='WowB.exe'") {
    if ($process.ExecutablePath -and $process.ExecutablePath.Equals((Join-Path $game 'Wow.exe'), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Close the test game before preparing the clean client.'
    }
}
$backupRoot = Join-Path $root '.forever-multi'
if ((Test-Path -LiteralPath $backupRoot) -and ((Get-Item -LiteralPath $backupRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Linked backup folder is not supported.'
}
$backup = Join-Path $backupRoot ('clean-client-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($backup) | Out-Null
$moved = @()
$reportPath = Join-Path $backup 'result.json'
$report = [ordered]@{ format = 'forever-clean-client-v1'; game = $game; backup = $backup; phase = 'prepared'; planned = @('WTF', 'Cache', 'Interface\AddOns'); moved = @(); cascModified = $false }
[IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
try {
    foreach ($relative in @('WTF', 'Cache', 'Interface\AddOns')) {
        $source = Join-Path $game $relative
        if (Test-Path -LiteralPath $source) {
            $destination = Join-Path $backup $relative
            [IO.Directory]::CreateDirectory((Split-Path -Parent $destination)) | Out-Null
            Move-Item -LiteralPath $source -Destination $destination
            $moved += $relative
        }
    }
    $report.phase = 'complete'; $report.moved = @($moved)
    [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
} catch {
    for ($i = $moved.Count - 1; $i -ge 0; $i--) {
        $destination = Join-Path $game $moved[$i]
        if (Test-Path -LiteralPath $destination) { throw "Preparation interrupted; retained backup: $backup" }
        Move-Item -LiteralPath (Join-Path $backup $moved[$i]) -Destination $destination
    }
    throw
}
Write-Host "Clean test client: $game"
Write-Host "Settings/cache/AddOns backup: $backup"
Write-Host 'CASC was not changed. Start the game through Multi after the clean server is ready.'
