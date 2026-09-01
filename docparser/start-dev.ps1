<#
.SYNOPSIS
    Bring the whole development stack up in the right order.

.DESCRIPTION
    Docker Desktop shuts down more often than people expect -- on reboot, on
    sign-out, or when someone closes the window -- and it takes the Redis
    container with it, because a container restart policy only applies while the
    Docker daemon itself is running.

    Losing Redis is not fatal (rate limiting passes through, live updates fall
    back to polling), which is exactly why it goes unnoticed for hours. This
    checks each dependency, fixes what it can, and refuses to pretend a broken
    one is fine.

.EXAMPLE
    .\start-dev.ps1
    .\start-dev.ps1 -NoApi        # dependencies only
    .\start-dev.ps1 -Reload       # uvicorn --reload (see the warning below)
#>
[CmdletBinding()]
param(
    [switch]$NoApi,
    [switch]$NoWeb,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
$root      = $PSScriptRoot
$apiDir    = Join-Path $root 'apps\api'
$webDir    = Join-Path $root 'apps\web'
$redisName = 'docparser-redis7'
$apiPort   = 8000

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "   OK   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   WARN $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "   FAIL $text" -ForegroundColor Red }

# -- Docker -------------------------------------------------------------------
Step 'Docker'
$dockerUp = $false
try { docker info *> $null; $dockerUp = $LASTEXITCODE -eq 0 } catch { $dockerUp = $false }

if (-not $dockerUp) {
    $exe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $exe)) {
        Fail 'Docker Desktop is not installed -- Redis cannot start.'
    } else {
        Write-Host '   starting Docker Desktop (this takes ~30s)...'
        Start-Process $exe -WindowStyle Hidden
        foreach ($i in 1..30) {
            Start-Sleep -Seconds 5
            try { docker info *> $null; if ($LASTEXITCODE -eq 0) { $dockerUp = $true; break } } catch { }
        }
        if ($dockerUp) { Ok "Docker started after ~$($i * 5)s" } else { Fail 'Docker did not start in time.' }
    }
} else { Ok 'Docker already running' }

# -- Redis --------------------------------------------------------------------
Step 'Redis'
if ($dockerUp) {
    $state = (docker inspect -f '{{.State.Running}}' $redisName 2>$null)
    if ($LASTEXITCODE -ne 0) {
        # Container has never been created on this machine.
        Write-Host '   creating the Redis 7.2 container...'
        docker run -d --name $redisName --restart unless-stopped -p 6380:6379 `
            redis:7.2-alpine redis-server --appendonly yes | Out-Null
        Start-Sleep -Seconds 4
        Ok 'Redis created on port 6380'
    } elseif ($state -eq 'false') {
        docker start $redisName | Out-Null
        Start-Sleep -Seconds 3
        Ok 'Redis started'
    } else {
        Ok 'Redis already running'
    }

    # Prove it actually answers, and that this is 7.x rather than the old
    # Windows Redis 3.2 on 6379 -- stream commands do not exist before 5.0, so
    # the wrong one connects happily and then silently disables live updates.
    $ver = (docker exec $redisName redis-cli INFO server 2>$null |
            Select-String '^redis_version:').ToString()
    if ($ver) { Ok $ver.Trim() } else { Warn 'Redis is up but did not answer INFO' }
} else {
    Warn 'Skipping Redis -- Docker is unavailable. The app will run, but live updates and rate limiting are off.'
}

# -- PostgreSQL ---------------------------------------------------------------
Step 'PostgreSQL'
if (Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue) {
    Ok 'listening on 5432'
} else {
    Fail 'Nothing on port 5432 -- start the PostgreSQL service.'
}

# -- Port 8000 ----------------------------------------------------------------
Step "API port $apiPort"
$holder = Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue |
          Select-Object -First 1
if ($holder) {
    $proc = Get-Process -Id $holder.OwningProcess -ErrorAction SilentlyContinue
    Warn "Port $apiPort is held by $($proc.ProcessName) (PID $($holder.OwningProcess))."
    Write-Host "        Free it with:  taskkill /F /PID $($holder.OwningProcess)"
    Write-Host '        Until then the API cannot bind -- the startup log looks healthy'
    Write-Host '        right up to the bind error, so it is easy to misread.'
} else {
    Ok 'free'
}

# -- Launch -------------------------------------------------------------------
if (-not $NoWeb) {
    Step 'Frontend'
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command', "Set-Location '$webDir'; npm run dev"
    )
    Ok 'starting in a new window -- http://localhost:3000  (localhost, not 127.0.0.1: Vite binds IPv6)'
}

if (-not $NoApi -and -not $holder) {
    Step 'API'
    if ($Reload) {
        Warn 'Running with --reload. Saving a file kills in-flight requests, and a'
        Write-Host '        Gemini OCR call takes 14-27s. With auto-posting enabled that can'
        Write-Host '        interrupt a real posting -- avoid it while testing postings.'
    }
    Set-Location $apiDir
    $args = @('-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', $apiPort)
    if ($Reload) { $args += '--reload' }
    Write-Host "`n   python $($args -join ' ')`n" -ForegroundColor DarkGray
    Write-Host '   Watch for: "Consumer group created" and "mail ingestion worker started"' -ForegroundColor DarkGray
    Write-Host ''
    & python @args
}
