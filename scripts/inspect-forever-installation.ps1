#requires -Version 5.1
<#
Read-only inspection of an owned installation after source-launcher preloading.
No CASC archives are opened or changed. EXE version resources are read, never executed.
Only a new report outside the
installation is written. Metadata mentions do not prove an active EXE upgrade
or a complete download. Compatible protocol and server data need separate checks.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$GameDirectory,
    [ValidateRange(1, 999999)][int]$ExpectedBuild = 70707,
    [ValidateRange(1, 999999)][int]$ServerBuild = 70658,
    [switch]$FindStagedExecutables,
    [string]$OutputPath = (Join-Path ([IO.Path]::GetTempPath()) ('Forever-installation-' + [guid]::NewGuid().ToString('N') + '.json'))
)
$ErrorActionPreference = 'Stop'

function Assert-Unlinked([string]$Path) {
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if (((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Choose a direct installation and report path without links.'
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) { break }
        $current = $parent.FullName
    }
}

$selected = [IO.Path]::GetFullPath($GameDirectory)
if ($selected.Length -gt [IO.Path]::GetPathRoot($selected).Length) { $selected = $selected.TrimEnd('\', '/') }
Assert-Unlinked $selected
$item = Get-Item -LiteralPath $selected -Force
if (!$item.PSIsContainer) { $selected = $item.DirectoryName }
$root = $selected
if ((Split-Path -Leaf $root) -in @('_forever_', '_classic_beta_', '_retail_', '_classic_', '_classic_era_')) {
    $root = Split-Path -Parent $root
}
$output = [IO.Path]::GetFullPath($OutputPath)
if ($output.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
    $output.StartsWith($root.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The report must be outside the game installation.'
}
Assert-Unlinked $output
if (Test-Path -LiteralPath $output) { throw 'Choose a new report filename; existing files are not overwritten.' }

$metadata = @()
$info = Join-Path $root '.build.info'
if (Test-Path -LiteralPath $info -PathType Leaf) {
    Assert-Unlinked $info
    if ((Get-Item -LiteralPath $info).Length -gt 1MB) { throw 'Unexpectedly large .build.info.' }
    $lines = @(Get-Content -LiteralPath $info -Encoding UTF8)
    if ($lines.Count -gt 1) {
        $headers = @($lines[0].Split('|') | ForEach-Object { ($_ -split '!')[0] })
        $metadata = @($lines[1..($lines.Count - 1)] | ConvertFrom-Csv -Delimiter '|' -Header $headers | ForEach-Object {
            [ordered]@{ product = $_.Product; active = $_.Active; version = $_.Version }
        })
    }
}

$binaries = @()
$folders = @($selected, (Join-Path $root '_forever_'), (Join-Path $root '_classic_beta_')) | Select-Object -Unique
foreach ($folder in $folders) {
    foreach ($name in @('Wow.exe', 'WowB.exe')) {
        $path = Join-Path $folder $name
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        Assert-Unlinked $path
        $binary = Get-Item -LiteralPath $path
        $version = $binary.VersionInfo.FileVersion
        $build = $null
        if ($version -match '^\s*(?:Version\s+)?1[.,]60[.,]1[.,](\d+)\b') { $build = [int]$Matches[1] }
        $binaries += [ordered]@{
            path = $binary.FullName; fileVersion = $version; productVersion = $binary.VersionInfo.ProductVersion
            actualForeverBuild = $build; matchesExpectedBuild = ($build -eq $ExpectedBuild)
            matchesServerBuild = ($build -eq $ServerBuild)
        }
    }
}
$staged = @()
$visited = 0
$scanErrors = @()
$scanLimited = $false
if ($FindStagedExecutables) {
    # Bounded walk of installer/staging directories only. Never walk Data or
    # game caches, and never follow junctions. A directory name is not a version.
    $pending = New-Object 'System.Collections.Generic.Stack[object]'
    foreach ($folder in Get-ChildItem -LiteralPath $root -Directory -Force) {
        if ($folder.Name -match '^(\.forever([._-].*)?|preload([._-].*)?|staging([._-].*)?|builds)$' -and
            ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
            $pending.Push(@{ path = $folder.FullName; depth = 0 })
        }
    }
    while ($pending.Count -gt 0 -and $visited -lt 512) {
        $current = $pending.Pop()
        $visited++
        foreach ($exe in Get-ChildItem -LiteralPath $current.path -File -Force -Filter 'Wow*.exe' -ErrorAction SilentlyContinue -ErrorVariable +scanErrors) {
            if ($exe.Name -notin @('Wow.exe', 'WowB.exe') -or ($exe.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
            Assert-Unlinked $exe.FullName
            $version = $exe.VersionInfo.FileVersion
            $build = $null
            if ($version -match '^\s*(?:Version\s+)?1[.,]60[.,]1[.,](\d+)\b') { $build = [int]$Matches[1] }
            $staged += [ordered]@{
                path = $exe.FullName; fileVersion = $version; actualForeverBuild = $build
                matchesExpectedBuild = ($build -eq $ExpectedBuild); activated = $false
            }
        }
        $children = @(Get-ChildItem -LiteralPath $current.path -Directory -Force -ErrorAction SilentlyContinue -ErrorVariable +scanErrors |
            Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0 -and $_.Name -ne 'Data' })
        if ($current.depth -ge 7) { if ($children.Count -gt 0) { $scanLimited = $true }; continue }
        foreach ($child in $children) { $pending.Push(@{ path = $child.FullName; depth = $current.depth + 1 }) }
    }
    if ($pending.Count -gt 0 -or $scanErrors.Count -gt 0) { $scanLimited = $true }
}
$report = [ordered]@{
    format = 'wowforever-owned-installation-v1'; root = $root
    expectedBuild = $ExpectedBuild; serverBuild = $ServerBuild
    executables = @($binaries); metadata = @($metadata)
    stagedExecutables = @($staged)
    stagedScan = [ordered]@{ requested = [bool]$FindStagedExecutables; directories = $visited; limited = $scanLimited }
    known70707BuildConfigPresent = (Test-Path -LiteralPath (Join-Path $root 'Data\config\7f\eb\7feb61f3c994bcb168526b8db521514a') -PathType Leaf)
    storageDirectoryPresent = (Test-Path -LiteralPath (Join-Path $root 'Data\data') -PathType Container)
    downloadCompletenessVerified = $false
    note = 'Preloading is not activation. Finish installation in the source launcher, then inspect the actual EXE. Cached configs and staged files do not establish a complete installation. Server protocol and extracted data must match separately. No game files were changed.'
}
$bytes = [Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Depth 8))
$stream = [IO.File]::Open($output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Write-Host ('Report saved: ' + $output)
Write-Host ('Expected client: ' + $ExpectedBuild + '; current server profile: ' + $ServerBuild)
$binaries | ForEach-Object { [pscustomobject]$_ } | Format-Table path, fileVersion, matchesExpectedBuild, matchesServerBuild -AutoSize
if ($FindStagedExecutables) {
    Write-Host 'Staged EXEs (not activated; cached archives are not searched):'
    $staged | ForEach-Object { [pscustomobject]$_ } | Format-List path, fileVersion, actualForeverBuild, matchesExpectedBuild
    if ($staged.Count -eq 0) { Write-Host 'No unpacked staged Wow.exe/WowB.exe found in the bounded installer-folder scan.' }
    if ($scanLimited) { Write-Host 'Scan was limited or some directories were unreadable; see the JSON report.' }
}
Write-Host 'Game files unchanged. Full download and server compatibility are not certified by this report.'
