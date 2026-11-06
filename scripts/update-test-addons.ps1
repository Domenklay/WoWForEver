#Requires -Version 5.1
<#
.SYNOPSIS
 Installs every verified client AddOn in WoWForEver's live testing catalog.
 Separate server-only modules (Forever Scaling, worldserver abilities) are not installed here.
.EXAMPLE
 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-test-addons.ps1 -GameDirectory 'E:\WoWForEver-work\clients\70658\_forever_'
#>
[CmdletBinding()]
param(
    [string]$GameDirectory = 'E:\WoWForEver-work\clients\70658\_forever_',
    [switch]$Stable,
    [switch]$SkipLauncherSettings
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = 'Domenklay/WoWForEver'
$branch = 'testing/addons-70658'
$rootUrl = "https://raw.githubusercontent.com/$repo/$branch"
$game = [IO.Path]::GetFullPath($GameDirectory.TrimEnd([char[]]@('\','/')))
$addons = Join-Path $game 'Interface\AddOns'
$id = [guid]::NewGuid().ToString('N')

function Assert-RealPath([string]$Path) {
    $p = $Path
    while ($p) {
        $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
        if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "Linked path is not supported: $p"
        }
        $parent = Split-Path -Path $p -Parent
        if (-not $parent -or $parent -eq $p) { break }
        $p = $parent
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $game 'Wow.exe') -PathType Leaf) -and
    -not (Test-Path -LiteralPath (Join-Path $game 'WowB.exe') -PathType Leaf)) {
    throw "Wow.exe/WowB.exe was not found: $game"
}
foreach ($name in @('Wow','WowB','forever-launcher','WoWForeverMulti')) {
    if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
        throw "Close the game and Multi first: $name"
    }
}
Assert-RealPath $addons
New-Item -ItemType Directory -Path $addons -Force | Out-Null
$settingsPath = Join-Path $env:APPDATA 'forever-launcher-app\settings.json'
$settings = $null
if (-not $SkipLauncherSettings) {
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw "Multi settings not found: $settingsPath"
    }
    Assert-RealPath $settingsPath
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $selected = [IO.Path]::GetFullPath(([string]$settings.gameDir).TrimEnd([char[]]@('\','/')))
    if ($selected -ine $game) {
        throw "Multi selected a different game folder: $selected"
    }
}

if ($Stable) {
    $catalog = @(
        @{ sourcePath='mods/forever-advancement/addon/ForeverAscension'; manifest=(Invoke-RestMethod -UseBasicParsing -Uri "$rootUrl/app/src-tauri/addons/forever-ascension.json") },
        @{ sourcePath='mods/living-encyclopedia/addon/ForeverEncyclopedia'; manifest=(Invoke-RestMethod -UseBasicParsing -Uri "$rootUrl/app/src-tauri/addons/forever-encyclopedia.json") }
    )
} else {
    $live = Invoke-RestMethod -UseBasicParsing -Uri "$rootUrl/app/src-tauri/addons/testing-catalog.json"
    if ($live.format -ne 'forever-addon-testing-v1' -or $live.channel -ne 'testing' -or
        $live.project -ne $repo -or [int]$live.clientBuild -ne 70658 -or
        $live.addons.Count -lt 1 -or $live.addons.Count -gt 20) {
        throw 'Unrecognized testing catalog.'
    }
    $catalog = @($live.addons)
    Write-Host 'Server-only modules in the catalog:'
    foreach ($m in $live.serverModules) {
        Write-Host (" - {0}: {1} (requires separate worldserver deployment)" -f $m.name,$m.testVersion)
    }
}

$prepared = New-Object Collections.Generic.List[object]
$moved = New-Object Collections.Generic.List[object]
$seen = @{}
$settingsBackup = "$settingsPath.test-addons-$id.bak"
$settingsBackedUp = $false
try {
    # Download and verify ALL AddOns before replacing ANY existing folder.
    foreach ($entry in $catalog) {
        $m = $entry.manifest
        $name = [string]$m.name
        $source = [string]$entry.sourcePath
        if ($name -notmatch '^Forever[A-Za-z0-9]+$' -or
            $source -cnotmatch '^mods/[a-z0-9_-]+/addon/Forever[A-Za-z0-9]+$' -or
            $source.Split('/')[-1] -cne $name -or $seen.ContainsKey($name) -or
            $m.format -ne 'forever-addon-v1' -or [int]$m.protocol -lt 1 -or
            $m.version -notmatch '^[a-zA-Z0-9._-]{1,96}$' -or
            $m.sourceCommit -notmatch '^[a-f0-9]{40}$' -or
            $m.files.Count -lt 1 -or $m.files.Count -gt 100) {
            throw "Invalid AddOn descriptor: $name"
        }
        $seen[$name] = $true
        $stage = Join-Path $addons (".$name-install-$id")
        $target = Join-Path $addons $name
        $backup = Join-Path $game (".forever-multi\addon-backups\$id\$name")
        Assert-RealPath $target
        New-Item -ItemType Directory -Path $stage -ErrorAction Stop | Out-Null
        $prepared.Add([pscustomobject]@{ name=$name; manifest=$m; stage=$stage; target=$target; backup=$backup; changed=$true })
        $fileNames = @{}
        foreach ($file in $m.files) {
            $fn = [string]$file.name
            $hash = [string]$file.sha256
            $size = [long]$file.size
            if ($fn -notmatch '^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$' -or
                $fileNames.ContainsKey($fn) -or $hash -notmatch '^[a-f0-9]{64}$' -or
                $size -gt 33554432 -or $size -lt 1) {
                throw "Invalid file descriptor: $name/$fn"
            }
            $fileNames[$fn] = $true
            $url = "https://raw.githubusercontent.com/$repo/$($m.sourceCommit)/$source/$fn"
            $dest = Join-Path $stage $fn
            Write-Host "Verifying $name/$fn"
            Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $dest
            if ((Get-Item -LiteralPath $dest).Length -ne $size -or
                (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) {
                throw "SHA-256/size mismatch: $name/$fn"
            }
        }
        if (-not $fileNames.ContainsKey("$name.toc")) { throw "Missing $name.toc" }
        if (Test-Path -LiteralPath $target -PathType Container) {
            $same = $true
            foreach ($file in $m.files) {
                $localFile = Join-Path $target $file.name
                if (-not (Test-Path -LiteralPath $localFile -PathType Leaf) -or
                    (Get-Item -LiteralPath $localFile).Length -ne [long]$file.size -or
                    (Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$file.sha256) {
                    $same = $false; break
                }
            }
            if ($same) { $prepared[$prepared.Count-1].changed = $false }
        }
    }
    foreach ($p in $prepared) {
        if (-not $p.changed) {
            Write-Host "ALREADY CURRENT: $($p.name) $($p.manifest.version)"
            continue
        }
        $record = [pscustomobject]@{ item=$p; hadPrevious=$false; stageCommitted=$false }
        $moved.Add($record)
        if (Test-Path -LiteralPath $p.target) {
            $backupParent = Split-Path -Parent $p.backup
            Assert-RealPath $backupParent
            New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
            Move-Item -LiteralPath $p.target -Destination $p.backup -ErrorAction Stop
            $record.hadPrevious = $true
        }
        Move-Item -LiteralPath $p.stage -Destination $p.target -ErrorAction Stop
        $record.stageCommitted = $true
        Write-Host "INSTALLED: $($p.name) $($p.manifest.version)" -ForegroundColor Green
        if ($record.hadPrevious) { Write-Host "BACKUP: $($p.backup)" }
    }
    if (-not $SkipLauncherSettings) {
        Copy-Item -LiteralPath $settingsPath -Destination $settingsBackup -ErrorAction Stop
        $settingsBackedUp = $true
        $test = -not [bool]$Stable
        $settings | Add-Member -MemberType NoteProperty -Name addonTestMode -Value $test -Force
        # Compatibility with current Multi 1.7.1: prevents automatic rollback on Play.
        $settings | Add-Member -MemberType NoteProperty -Name addonDevelopmentMode -Value $test -Force
        [IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json -Depth 64), (New-Object Text.UTF8Encoding($false)))
        Write-Host "LAUNCHER SETTINGS BACKUP: $settingsBackup"
    }
    Write-Host ("CLIENT ADDONS VERIFIED: {0} | CHANNEL: {1}" -f $prepared.Count, $(if ($Stable) {'stable'} else {'testing'}))
} catch {
    $failure = $_
    if ($settingsBackedUp) {
        try { Copy-Item -LiteralPath $settingsBackup -Destination $settingsPath -Force } catch {}
    }
    # Restore every changed AddOn in reverse order if any installation fails.
    for ($i = $moved.Count - 1; $i -ge 0; $i--) {
        $record = $moved[$i]
        if ($record.stageCommitted -and (Test-Path -LiteralPath $record.item.target)) {
            try { Remove-Item -LiteralPath $record.item.target -Recurse -Force } catch {}
        }
        if ($record.hadPrevious -and (Test-Path -LiteralPath $record.item.backup) -and
            -not (Test-Path -LiteralPath $record.item.target)) {
            try { Move-Item -LiteralPath $record.item.backup -Destination $record.item.target } catch {}
        }
    }
    throw $failure
} finally {
    foreach ($p in $prepared) {
        if (Test-Path -LiteralPath $p.stage) {
            Remove-Item -LiteralPath $p.stage -Recurse -Force
        }
    }
}
