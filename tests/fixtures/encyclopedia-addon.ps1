#Requires -Version 5.1
[CmdletBinding()]
param([string]$Repository = '.')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath $Repository).Path
$installer = Join-Path $repo 'scripts\update-encyclopedia-addon.ps1'
$root = Join-Path $env:TEMP ('encyclopedia-addon-test-' + [guid]::NewGuid().ToString('N'))
$game = Join-Path $root '_forever_'
$addons = Join-Path $game 'Interface\AddOns'
$book = Join-Path $addons 'ForeverEncyclopedia'
try {
    New-Item -ItemType Directory -Path $book -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $game 'Wow.exe') -Value 'fixture'
    Set-Content -LiteralPath (Join-Path $book 'old-marker.txt') -Value 'previous AddOn'

    & $installer -GameDirectory $game -SkipLauncherSettings
    $toc = Get-Content -LiteralPath (Join-Path $book 'ForeverEncyclopedia.toc') -Raw -Encoding UTF8
    if (-not $toc.Contains('0.9.9-v2.1-talent-mana')) { throw 'Test AddOn is not installed' }
    $backups = @(Get-ChildItem -LiteralPath (Join-Path $game '.forever-multi\addon-backups') -Recurse -Filter 'old-marker.txt')
    if ($backups.Count -ne 1) { throw 'The original AddOn backup is missing' }
    & $installer -GameDirectory $game -Stable -SkipLauncherSettings
    $toc = Get-Content -LiteralPath (Join-Path $book 'ForeverEncyclopedia.toc') -Raw -Encoding UTF8
    if (-not $toc.Contains('0.9.8-v2.1-smartai-abilities')) { throw 'Stable AddOn was not restored' }
    $testBackups = @(Get-ChildItem -LiteralPath (Join-Path $game '.forever-multi\addon-backups') -Recurse -Filter 'ForeverEncyclopedia.toc')
    if ($testBackups.Count -lt 1) { throw 'The test AddOn backup is missing' }
    Write-Host 'ENCYCLOPEDIA CHANNEL INSTALL VERIFIED' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
