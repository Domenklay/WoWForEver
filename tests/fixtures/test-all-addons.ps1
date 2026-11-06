#Requires -Version 5.1
[CmdletBinding()]
param([string]$Repository='.')
$ErrorActionPreference='Stop'
$repo=(Resolve-Path -LiteralPath $Repository).Path
$scriptPath=Join-Path $repo 'scripts\update-test-addons.ps1'
$root=Join-Path $env:TEMP ('forever-all-addons-' + [guid]::NewGuid().ToString('N'))
$game=Join-Path $root '_forever_'
$addons=Join-Path $game 'Interface\AddOns'
try {
 New-Item -ItemType Directory -Path (Join-Path $addons 'ForeverAscension') -Force | Out-Null
 New-Item -ItemType Directory -Path (Join-Path $addons 'ForeverEncyclopedia') -Force | Out-Null
 New-Item -ItemType Directory -Path (Join-Path $addons 'OtherAddon') -Force | Out-Null
 Set-Content -LiteralPath (Join-Path $game 'Wow.exe') -Value 'fixture'
 Set-Content -LiteralPath (Join-Path $addons 'ForeverAscension\original-ascension.txt') -Value 'before'
 Set-Content -LiteralPath (Join-Path $addons 'ForeverEncyclopedia\original-book.txt') -Value 'before'
 Set-Content -LiteralPath (Join-Path $addons 'OtherAddon\untouched.txt') -Value 'keep'
 & $scriptPath -GameDirectory $game -SkipLauncherSettings
 $book=(Get-Content -LiteralPath (Join-Path $addons 'ForeverEncyclopedia\ForeverEncyclopedia.toc') -Raw -Encoding UTF8)
 $asc=(Get-Content -LiteralPath (Join-Path $addons 'ForeverAscension\ForeverAscension.toc') -Raw -Encoding UTF8)
 if (-not $book.Contains('0.9.9-v2.1-talent-mana') -or -not $asc.Contains('1.11.0')) {throw 'Incomplete all-AddOn installation'}
 $saved=@(Get-ChildItem -LiteralPath (Join-Path $game '.forever-multi\addon-backups') -Recurse -File)
 if (-not @($saved|Where-Object Name -EQ 'original-book.txt').Count -or -not @($saved|Where-Object Name -EQ 'original-ascension.txt').Count) {
  throw 'Original AddOn backups are missing'
 }
 if (-not (Test-Path -LiteralPath (Join-Path $addons 'OtherAddon\untouched.txt'))) {throw 'Unrelated AddOn was changed'}
 & $scriptPath -GameDirectory $game -Stable -SkipLauncherSettings
 $book=(Get-Content -LiteralPath (Join-Path $addons 'ForeverEncyclopedia\ForeverEncyclopedia.toc') -Raw -Encoding UTF8)
 if (-not $book.Contains('0.9.8-v2.1-smartai-abilities')){throw 'Failed to restore stable Encyclopedia'}
 Write-Host 'ALL TEST ADDONS / STABLE ROLLBACK VERIFIED' -ForegroundColor Green
} finally {
 if (Test-Path -LiteralPath $root){Remove-Item -LiteralPath $root -Recurse -Force}
}
