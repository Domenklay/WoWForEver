param(
    [string]$GameDir = 'E:\WoWForEver-work\experiments\Forever-client-v3\_forever_',
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string]$PublicKey = '02596F0D0C061A8B30745988FD72C59E29EC367FB0F341F28E0F08D037BAFC69'
)
$ErrorActionPreference = 'Stop'
$session = $null
try {
    if (-not [Environment]::Is64BitProcess) { throw 'Use 64-bit Windows PowerShell.' }
    $GameDir = (Resolve-Path -LiteralPath $GameDir).Path
    $exe = Join-Path $GameDir 'Wow.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'The selected test copy has no Wow.exe.' }
    $root = Split-Path -Parent $GameDir
    $marker = Join-Path $root 'forever-client-migration.json'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { throw 'Expected our independently verified client copy.' }
    $copy = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($copy.format -ne 'wowforever-migrated-client-copy-v1' -or
        $copy.layout.product -ne 'wowf' -or $copy.layout.executable -ne 'Wow.exe' -or
        $copy.layout.game_part -ne '_forever_') { throw 'Unexpected test-copy product/layout.' }
    if (-not (Test-Path -LiteralPath (Join-Path $root 'Data') -PathType Container)) { throw 'The copied shared Data folder is missing.' }
    $portal = 'trinity.actual.battle.net'
    $addresses = @([System.Net.Dns]::GetHostAddresses($portal))
    if ($addresses.Count -eq 0 -or @($addresses | Where-Object { -not [System.Net.IPAddress]::IsLoopback($_) }).Count -ne 0) {
        throw 'The portal must resolve only to localhost. Expected hosts: 127.0.0.1 trinity.actual.battle.net'
    }
    foreach ($running in @(Get-Process -Name Wow -ErrorAction SilentlyContinue)) {
        if ($running.Path -eq $exe) { throw 'This test copy is already running. Close it before using this launcher.' }
    }
    Add-Type -Path (Join-Path $PSScriptRoot 'LocalKey.cs')
    $wtf = Join-Path $GameDir 'WTF'
    New-Item -ItemType Directory -Path $wtf -Force | Out-Null
    $configName = 'LocalLauncher-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.wtf'
    $configPath = Join-Path $wtf $configName
    $base = Join-Path $wtf 'Config.wtf'
    $lines = @()
    if (Test-Path -LiteralPath $base) { $lines = [System.IO.File]::ReadAllLines($base) }
    $lines = @($lines | Where-Object { $_ -notmatch '^\s*SET\s+portal\s' })
    $lines += 'SET portal "trinity.actual.battle.net:1119"'
    [System.IO.File]::WriteAllLines($configPath, [string[]]$lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host ('Starting test copy with ' + $portal + ':1119')
    $startedAt = Get-Date
    $started = Start-Process -FilePath $exe -WorkingDirectory $GameDir -ArgumentList @('-config', $configName) -PassThru
    $game = $null
    $processDeadline = (Get-Date).AddSeconds(90)
    while ($null -eq $game) {
        # A small Wow.exe bootstrap may spawn the actual client with the same path.
        # Only this previously closed copy is eligible; multiple full clients are refused.
        $candidates = @(Get-Process -Name Wow -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -eq $exe -and $_.StartTime -ge $startedAt.AddSeconds(-2) -and $_.WorkingSet64 -gt 50MB
        })
        if ($candidates.Count -gt 1) { throw 'Multiple full clients from this test copy are running; close them before retrying.' }
        if ($candidates.Count -eq 1) { $game = $candidates[0]; break }
        if ((Get-Date) -gt $processDeadline) { throw ('No full client process found after launch PID=' + $started.Id) }
        Start-Sleep -Milliseconds 500
    }
    $session = New-Object ForeverLocalLogin.Session -ArgumentList @($game.Id, $exe, $PublicKey)
    $deadline = (Get-Date).AddMinutes(3)
    $ready = $false
    $notice = [DateTime]::MinValue
    while ($true) {
        $state = $session.Step()
        if ($state -eq -1) {
            if (-not $ready) { throw 'Started game process exited before the public key was ready.' }
            Write-Host 'Game process exited.'
            break
        }
        if ($state -eq 1) {
            if (-not $ready) {
                Write-Host ('LOCAL KEY READY: PID=' + $game.Id + '; regionGroup=8; public key verified.') -ForegroundColor Green
                Write-Host 'You can log in now. Keep this PowerShell window open while playing.'
            }
            $ready = $true
            $deadline = (Get-Date).AddMinutes(3)
        } else {
            if ($ready) { Write-Host 'Key store changed; waiting for its validated replacement.' }
            $ready = $false
            if ((Get-Date) -gt $deadline) { throw 'No unique validated key store found in 3 minutes. No unvalidated writes were made.' }
            if (((Get-Date) - $notice).TotalSeconds -gt 15) {
                Write-Host 'Waiting for the client public-key store; do not enter a realm yet...'
                $notice = Get-Date
            }
        }
        Start-Sleep -Seconds 1
    }
} catch {
    Write-Host ('Stopped: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'If the game is still open, close it before retrying. Please report this message.'
    exit 1
} finally {
    if ($null -ne $session) { $session.Dispose() }
}
