#Requires -Version 5.1
<#
.SYNOPSIS
 Safely installs a pinned test (or stable) Forever Encyclopedia for the selected WoW Forever client.
 Run with the game and Multi closed. Never edits worldserver, databases or other AddOns.
.EXAMPLE
 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-encyclopedia-addon.ps1 -GameDirectory 'E:\WoWForEver-work\clients\70658\_forever_'
#>
[CmdletBinding()]
param(
    [string]$GameDirectory = 'E:\WoWForEver-work\clients\70658\_forever_',
    [switch]$Stable,
    [switch]$SkipLauncherSettings
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Assert-NotLink([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -ne $item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "Refusing linked path: $Path"
    }
}

$game = [IO.Path]::GetFullPath($GameDirectory.TrimEnd([char[]]@('\','/')))
if (-not (Test-Path -LiteralPath (Join-Path $game 'Wow.exe') -PathType Leaf) -and
    -not (Test-Path -LiteralPath (Join-Path $game 'WowB.exe') -PathType Leaf)) {
    throw "Wow.exe/WowB.exe not found: $game"
}
foreach ($name in @('Wow','WowB','forever-launcher','WoWForeverMulti')) {
    if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
        throw "Close WoW and WoW Forever Multi before updating AddOns (running: $name)."
    }
}

$addons = Join-Path $game 'Interface\AddOns'
$target = Join-Path $addons 'ForeverEncyclopedia'
# Reject junctions/symlinks anywhere in the destination ancestry.
$current = $game
while (-not [string]::IsNullOrWhiteSpace($current)) {
    Assert-NotLink $current
    $parent = Split-Path -Parent $current
    if ($parent -eq $current -or [string]::IsNullOrEmpty($parent)) { break }
    $current = $parent
}
foreach ($item in @((Join-Path $game 'Interface'), $addons, $target, (Join-Path $game '.forever-multi'), (Join-Path $game '.forever-multi\addon-backups'))) {
    Assert-NotLink $item
}
if ((Test-Path -LiteralPath $target) -and -not (Test-Path -LiteralPath $target -PathType Container)) {
    throw "AddOn target is not a folder: $target"
}

$settingsPath = Join-Path $env:APPDATA 'forever-launcher-app\settings.json'
$settings = $null
if (-not $SkipLauncherSettings) {
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw "Launcher settings not found: $settingsPath. Open and configure Multi first."
    }
    Assert-NotLink $settingsPath
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $selected = [IO.Path]::GetFullPath(([string]$settings.gameDir).TrimEnd([char[]]@('\','/')))
    if ($selected -ine $game) {
        throw "Multi selected another game folder: $selected. Save the intended game folder in Multi first."
    }
}

$ref = 'testing/addons-70658'
$filename = if ($Stable) { 'forever-encyclopedia.json' } else { 'forever-encyclopedia-test.json' }
$manifestUrl = "https://raw.githubusercontent.com/Domenklay/WoWForEver/$ref/app/src-tauri/addons/$filename"
$manifest = Invoke-RestMethod -Uri $manifestUrl -UseBasicParsing
$expectedVersion = if ($Stable) { '0.9.8-v2.1-smartai-abilities' } else { '0.9.9-v2.1-talent-mana' }
if ($manifest.format -ne 'forever-addon-v1' -or $manifest.name -ne 'ForeverEncyclopedia' -or
    $manifest.version -ne $expectedVersion -or [int]$manifest.protocol -ne 1 -or
    $manifest.sourceCommit -notmatch '^[0-9a-f]{40}$' -or $manifest.files.Count -ne 8) {
    throw 'Unexpected or invalid Encyclopedia manifest.'
}
New-Item -ItemType Directory -Path $addons -Force | Out-Null
$id = [guid]::NewGuid().ToString('N')
$stage = Join-Path $addons ".ForeverEncyclopedia-install-$id"
$backup = Join-Path $game (".forever-multi\addon-backups\$id\ForeverEncyclopedia")
$settingsBackup = "$settingsPath.test-addon-$id.bak"
$previousMoved = $false
$stageCommitted = $false
$settingsBackedUp = $false

try {
    New-Item -ItemType Directory -Path $stage -ErrorAction Stop | Out-Null
    $seen = @{}
    foreach ($file in $manifest.files) {
        $name = [string]$file.name
        $size = [long]$file.size
        $hash = [string]$file.sha256
        if ($name -notmatch '^[a-zA-Z0-9._-]+$' -or $name.StartsWith('.') -or
            $seen.ContainsKey($name) -or $hash -notmatch '^[0-9a-f]{64}$' -or
            $size -lt 1 -or $size -gt 33554432) {
            throw "Invalid file entry in manifest: $name"
        }
        $seen[$name] = $true
        $url = "https://raw.githubusercontent.com/Domenklay/WoWForEver/$($manifest.sourceCommit)/mods/living-encyclopedia/addon/ForeverEncyclopedia/$name"
        $filePath = Join-Path $stage $name
        Write-Host "Downloading and verifying $name"
        Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $filePath
        $realSize = (Get-Item -LiteralPath $filePath).Length
        $realHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($realSize -ne $size -or $realHash -ne $hash) {
            throw "Hash/size check failed: $name"
        }
    }
    Write-Host "All $($seen.Count) files verified (SHA-256)."
    if (Test-Path -LiteralPath $target) {
        $backupParent = Split-Path -Parent $backup
        New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
        Assert-NotLink $backupParent
        Move-Item -LiteralPath $target -Destination $backup -ErrorAction Stop
        $previousMoved = $true
    }
    Move-Item -LiteralPath $stage -Destination $target -ErrorAction Stop
    $stageCommitted = $true
    if (-not $SkipLauncherSettings) {
        Copy-Item -LiteralPath $settingsPath -Destination $settingsBackup -ErrorAction Stop
        $settingsBackedUp = $true
        # Old Multi 1.7.1 preserves test AddOns only when development mode is enabled.
        # New Multi also remembers its separate test channel.
        $testMode = -not [bool]$Stable
        $settings | Add-Member -MemberType NoteProperty -Name 'addonDevelopmentMode' -Value $testMode -Force
        $settings | Add-Member -MemberType NoteProperty -Name 'addonTestMode' -Value $testMode -Force
        $newJson = $settings | ConvertTo-Json -Depth 64
        [IO.File]::WriteAllText($settingsPath, $newJson, (New-Object Text.UTF8Encoding($false)))
    }
    Write-Host "INSTALLED: ForeverEncyclopedia $($manifest.version)" -ForegroundColor Green
    Write-Host "CLIENT: $game"
    if ($previousMoved) { Write-Host "PREVIOUS ADDON BACKUP: $backup" }
    if ($settingsBackedUp) { Write-Host "LAUNCHER SETTINGS BACKUP: $settingsBackup" }
} catch {
    $failure = $_
    if ($settingsBackedUp) {
        try { Copy-Item -LiteralPath $settingsBackup -Destination $settingsPath -Force } catch { }
    }
    if ($stageCommitted -and (Test-Path -LiteralPath $target)) {
        try { Remove-Item -LiteralPath $target -Recurse -Force } catch { }
    }
    if ($previousMoved -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $target)) {
        try { Move-Item -LiteralPath $backup -Destination $target } catch { }
    }
    throw $failure
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
