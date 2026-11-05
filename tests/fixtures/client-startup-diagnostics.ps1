#requires -Version 5.1
param([string]$Repository = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$ErrorActionPreference = 'Stop'
$collector = Join-Path $Repository 'scripts\collect-client-startup.ps1'
$tokens = $null; $parseErrors = $null
[Management.Automation.Language.Parser]::ParseFile($collector, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
function Assert($Condition, [string]$Message) { if (!$Condition) { throw $Message } }
function Snapshot([string]$Root) {
    return ((Get-ChildItem -LiteralPath $Root -Recurse -File | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Root.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName).Hash
    }) -join "`n")
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ('fm-startup-tests-' + [guid]::NewGuid().ToString('N'))
try {
    $target = Join-Path $temp 'copy'; $source = Join-Path $temp 'original'
    foreach ($root in @($target, $source)) {
        [IO.Directory]::CreateDirectory((Join-Path $root 'Data\data')) | Out-Null
        [IO.Directory]::CreateDirectory((Join-Path $root '_forever_\Logs')) | Out-Null
        [IO.Directory]::CreateDirectory((Join-Path $root '_forever_\WTF')) | Out-Null
        [IO.File]::WriteAllText((Join-Path $root 'Data\data\data.000'), 'synthetic archive')
        [IO.File]::WriteAllText((Join-Path $root 'Data\data\shmem'), 'synthetic local state')
        for ($i = 0; $i -lt 16; $i++) {
            [IO.File]::WriteAllText((Join-Path $root ('Data\data\{0:x2}00000325.idx' -f $i)), 'synthetic index')
        }
    }
    [IO.File]::WriteAllText((Join-Path $target 'Data\data\0000000326.idx'), 'higher generation outside source')
    [IO.File]::WriteAllText((Join-Path $target 'Data\data\RepairMarker.psv'), 'synthetic repair marker')
    [IO.File]::WriteAllText((Join-Path $target '_forever_\Logs\Tact.log'), ((1..230 | ForEach-Object { "log line $_" }) -join "`n"))
    [IO.File]::WriteAllText((Join-Path $target '_forever_\WTF\Config.wtf'), "SET portal `"trinity.actual.battle.net:1119`"`nSET accountName `"private-config-value`"`n")
    Write-Host 'Synthetic installations prepared; taking snapshots.'
    $beforeTarget = Snapshot $target; $beforeSource = Snapshot $source
    $reportPath = Join-Path $temp 'report.json'
    Write-Host 'Collecting synthetic startup report.'
    & $collector -ClientRoot (Join-Path $target '_forever_') -ReferenceRoot $source -OutputPath $reportPath -Verbose
    $raw = [IO.File]::ReadAllText($reportPath); $report = $raw | ConvertFrom-Json
    Assert ($raw.Length -lt 64000 -and !$raw.Contains('PSProvider') -and !$raw.Contains('PSDrive')) 'PowerShell provider graphs must not be serialized'
    Assert ($report.comparisonAvailable) 'Both storage folders should be compared'
    Assert (!$report.clientModified -and !$report.referenceModified) 'Collector must declare read-only scope'
    Assert (($report.extraStorageFiles | Sort-Object) -join ',' -eq '0000000326.idx,RepairMarker.psv') 'Extra index/marker not identified'
    Assert (($report.client.highestIndexes | Where-Object bucket -eq '00').generation -eq 806) 'Wrong highest generation'
    Assert (($report.client.files | Where-Object name -eq 'data.000').sha256 -eq $null) 'Archive content must not be hashed/exported'
    Assert (($report.client.files | Where-Object name -eq 'shmem').sha256.Length -eq 64) 'Small metadata hash missing'
    $log = $report.logs | Where-Object { $_.path.EndsWith('Tact.log') }
    Assert ($log.tail.Count -eq 200 -and $log.tail[0] -eq 'log line 31' -and $log.tail[-1] -eq 'log line 230') 'Log tail must be bounded and fresh'
    Assert (!$raw.Contains('private-config-value')) 'Non-diagnostic config values must not be exported'
    Assert ($beforeTarget -eq (Snapshot $target)) 'Target installation changed'
    Assert ($beforeSource -eq (Snapshot $source)) 'Reference installation changed'
    Write-Host 'Snapshots unchanged; verifying report path protection.'
    $blockedPath = Join-Path $target 'must-not-create.json'; $rejected = $false
    try { & $collector -ClientRoot $target -ReferenceRoot $source -OutputPath $blockedPath } catch { $rejected = $true }
    Assert ($rejected -and !(Test-Path -LiteralPath $blockedPath)) 'Reports inside installations must be rejected'
    Write-Host 'Verifying missing source handling.'
    $missingPath = Join-Path $temp 'missing.json'
    & $collector -ClientRoot $target -ReferenceRoot (Join-Path $temp 'absent') -OutputPath $missingPath
    $missing = [IO.File]::ReadAllText($missingPath) | ConvertFrom-Json
    Assert (!$missing.comparisonAvailable -and $missing.extraStorageFiles.Count -eq 0) 'Missing source must not make every file extra'
    Write-Host 'Verifying junction protection.'
    $junction = Join-Path $temp 'linked-source'
    New-Item -ItemType Junction -Path $junction -Target $source | Out-Null
    $rejected = $false
    try { & $collector -ClientRoot $target -ReferenceRoot $junction -OutputPath (Join-Path $temp 'linked.json') } catch { $rejected = $true }
    Assert ($rejected) 'Linked installation must be rejected'
    # Remove the junction itself before recursive fixture cleanup.
    [IO.Directory]::Delete($junction)
    Write-Host 'Startup diagnostics: read-only snapshots, extra indices, log bounds, privacy, path guards and missing sources passed.'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
