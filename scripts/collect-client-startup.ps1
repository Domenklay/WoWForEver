#requires -Version 5.1
<#
Read-only installation diagnostics. Only the requested JSON report is written.
No game files, hosts, certificates, processes or registry settings are changed.
Log excerpts may contain account names; review the report before sharing it.
#>
[CmdletBinding()]
param(
    [string]$ClientRoot = 'E:\WoWForEver-work\experiments\Forever-client-v3',
    [string]$ReferenceRoot = 'E:\WoW_Forever',
    [string]$OutputPath = (Join-Path ([IO.Path]::GetTempPath()) ('Forever-client-startup-' + [guid]::NewGuid().ToString('N') + '.json'))
)
$ErrorActionPreference = 'Stop'

function Get-RootPath([string]$Value) {
    $path = [IO.Path]::GetFullPath($Value).TrimEnd('\', '/')
    if ((Split-Path -Leaf $path) -in @('_forever_', '_classic_beta_')) {
        $path = Split-Path -Parent $path
    }
    return $path
}
function Test-LinkedPath([string]$Value) {
    $path = $Value
    $seen = @{}
    while ($path) {
        if ($seen.ContainsKey($path)) { throw "Repeated ancestor while checking path: $path" }
        $seen[$path] = $true
        Write-Verbose "Inspecting ancestor: $path"
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $true }
        }
        $parent = [IO.Directory]::GetParent($path)
        if ($null -eq $parent) { break }
        $path = $parent.FullName
    }
    return $false
}
function Get-StorageSnapshot([string]$RootPath) {
    $folder = Join-Path $RootPath 'Data\data'
    if (!(Test-Path -LiteralPath $folder -PathType Container)) {
        return [ordered]@{ root = $RootPath; status = 'missing-storage'; files = @(); highestIndexes = @() }
    }
    if (Test-LinkedPath $folder) { throw "Linked storage is not inspected: $folder" }
    $rows = @()
    $highest = @{}
    foreach ($item in Get-ChildItem -LiteralPath $folder -Force | Sort-Object Name) {
        $linked = ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        $hash = $null
        $kind = 'other'
        if ($item.Name -match '^[0-9a-f]{10}\.idx$') { $kind = 'index' }
        elseif ($item.Name -match '^data\.\d{3}$') { $kind = 'archive' }
        elseif ($item.Name -eq 'RepairMarker.psv') { $kind = 'repair-marker' }
        elseif ($item.Name -eq 'shmem' -or $item.Name -match '\.lru$') { $kind = 'local-state' }
        if (!$item.PSIsContainer -and !$linked -and $kind -in @('index', 'local-state', 'repair-marker') -and $item.Length -le 64MB) {
            $hash = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $rows += [ordered]@{
            name = $item.Name; kind = $kind; bytes = $(if ($item.PSIsContainer) { $null } else { $item.Length })
            modifiedUtc = $item.LastWriteTimeUtc.ToString('o'); sha256 = $hash; linked = $linked
        }
        if ($kind -eq 'index' -and !$linked -and !$item.PSIsContainer) {
            $bucket = $item.Name.Substring(0, 2).ToLowerInvariant()
            $generation = [Convert]::ToUInt32($item.Name.Substring(2, 8), 16)
            if (!$highest.ContainsKey($bucket) -or $generation -gt $highest[$bucket].generation) {
                $highest[$bucket] = [ordered]@{ bucket = $bucket; generation = $generation; name = $item.Name }
            }
        }
    }
    return [ordered]@{ root = $RootPath; status = 'read'; files = @($rows); highestIndexes = @($highest.Keys | Sort-Object | ForEach-Object { $highest[$_] }) }
}
function Get-LogExcerpt([string]$Path) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return [ordered]@{ path = $Path; status = 'missing' } }
    if (Test-LinkedPath $Path) { return [ordered]@{ path = $Path; status = 'linked-skipped' } }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $Path; status = 'read'; modifiedUtc = $item.LastWriteTimeUtc.ToString('o')
        bytes = $item.Length; head = @(Get-Content -LiteralPath $Path -Encoding UTF8 -TotalCount 40)
        tail = @(Get-Content -LiteralPath $Path -Encoding UTF8 -Tail 200)
    }
}

$target = Get-RootPath $ClientRoot
$reference = Get-RootPath $ReferenceRoot
$output = [IO.Path]::GetFullPath($OutputPath)
foreach ($root in @($target, $reference)) {
    if ($output.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or $output.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The report must be outside both installations.'
    }
    if (Test-LinkedPath $root) { throw "Linked installation is not inspected: $root" }
}
if (Test-LinkedPath $output) { throw 'Linked report path is not supported.' }
if (Test-Path -LiteralPath $output) { throw 'Choose a new report filename; existing files are not overwritten.' }
$copied = Get-StorageSnapshot $target
$original = Get-StorageSnapshot $reference
$originalNames = @{}
foreach ($row in $original.files) { $originalNames[$row.name] = $true }
$comparisonAvailable = ($copied.status -eq 'read' -and $original.status -eq 'read')
$extras = @()
if ($comparisonAvailable) {
    $extras = @($copied.files | Where-Object { !$originalNames.ContainsKey($_.name) } | ForEach-Object { $_.name })
}
$logs = @()
foreach ($name in @('Tact.log', 'General.log', 'Connection.log', 'Client.log', 'DeveloperLog.log')) {
    $logs += Get-LogExcerpt (Join-Path $target ('_forever_\Logs\' + $name))
}
$configs = @()
foreach ($name in @('Config.wtf', 'ForeverLauncher.wtf')) {
    $path = Join-Path $target ('_forever_\WTF\' + $name)
    if ((Test-Path -LiteralPath $path -PathType Leaf) -and !(Test-LinkedPath $path)) {
        $configs += [ordered]@{ name = $name; lines = @(Get-Content -LiteralPath $path -Encoding UTF8 | Where-Object { $_ -match '^\s*SET\s+(portal|textLocale|audioLocale|gxApi|dataPath|lastClientBuild|lastClientVersion)\s' }) }
    }
}
$report = [ordered]@{
    format = 'forever-multi-startup-diagnostics-v1'; createdUtc = [DateTime]::UtcNow.ToString('o')
    clientModified = $false; referenceModified = $false
    scope = 'Storage filenames, sizes and small metadata hashes; bounded client log excerpts. No archive/object integrity validation.'
    client = $copied; reference = $original; extraStorageFiles = $extras
    comparisonAvailable = $comparisonAvailable
    configs = @($configs); logs = @($logs)
}
$parent = Split-Path -Parent $output
[IO.Directory]::CreateDirectory($parent) | Out-Null
$json = $report | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($output, $json, [Text.UTF8Encoding]::new($false))
Write-Host "Report saved: $output"
Write-Host "Storage comparison available: $($report.comparisonAvailable); extra storage files: $($extras.Count)"
Write-Host 'Installation files were not changed. Review the report before sharing it.'
