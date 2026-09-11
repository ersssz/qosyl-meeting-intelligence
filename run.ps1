[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ProjectRoot

$ApiProcess = $null
$UiProcess = $null

function Get-AvailablePort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$PreferredPort
    )

    foreach ($Candidate in $PreferredPort..($PreferredPort + 50)) {
        $Listener = $null
        try {
            $Listener = [System.Net.Sockets.TcpListener]::new(
                [System.Net.IPAddress]::Loopback,
                $Candidate
            )
            $Listener.Start()
            return $Candidate
        }
        catch [System.Net.Sockets.SocketException] {
            continue
        }
        finally {
            if ($null -ne $Listener) {
                $Listener.Stop()
            }
        }
    }
    throw "No free TCP port found from $PreferredPort through $($PreferredPort + 50)."
}

try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is not installed or is not available on PATH."
    }

    if (-not $env:UV_CACHE_DIR) {
        $env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"
    }
    $env:PYTHONIOENCODING = "utf-8"

    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Host "Created .env from safe offline defaults." -ForegroundColor Yellow
    }

    Write-Host "Syncing dependencies..." -ForegroundColor Cyan
    $SyncArguments = @("sync")
    if (Select-String -LiteralPath ".env" -Pattern '^TRANSCRIPTION_PROVIDER=faster-whisper$' -Quiet) {
        $SyncArguments += @("--extra", "local")
        Write-Host "Local ASR profile detected; installing faster-whisper." -ForegroundColor Cyan
    }
    & uv @SyncArguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE."
    }

    $ConfiguredApiPort = 8000
    $ConfiguredUiPort = 8501
    foreach ($Line in Get-Content -LiteralPath ".env") {
        if ($Line -match '^API_PORT=(\d+)$') { $ConfiguredApiPort = [int]$Matches[1] }
        if ($Line -match '^UI_PORT=(\d+)$') { $ConfiguredUiPort = [int]$Matches[1] }
    }

    $ApiPort = Get-AvailablePort -PreferredPort $ConfiguredApiPort
    $UiPort = Get-AvailablePort -PreferredPort $ConfiguredUiPort
    $env:API_PORT = "$ApiPort"
    $env:UI_PORT = "$UiPort"
    $env:API_URL = "http://127.0.0.1:$ApiPort"

    if ($ApiPort -ne $ConfiguredApiPort) {
        Write-Host "API port $ConfiguredApiPort is busy; using $ApiPort." -ForegroundColor Yellow
    }
    if ($UiPort -ne $ConfiguredUiPort) {
        Write-Host "UI port $ConfiguredUiPort is busy; using $UiPort." -ForegroundColor Yellow
    }

    Write-Host "Starting FastAPI:   http://127.0.0.1:$ApiPort" -ForegroundColor Green
    Write-Host "Starting Streamlit: http://127.0.0.1:$UiPort" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop both services." -ForegroundColor DarkGray

    $ApiProcess = Start-Process -FilePath "uv" -ArgumentList @(
        "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort"
    ) -PassThru -NoNewWindow

    Start-Sleep -Milliseconds 800

    $UiProcess = Start-Process -FilePath "uv" -ArgumentList @(
        "run", "streamlit", "run", "streamlit_app.py", "--server.port", "$UiPort",
        "--server.headless", "true"
    ) -PassThru -NoNewWindow

    while (-not $ApiProcess.HasExited -and -not $UiProcess.HasExited) {
        Start-Sleep -Milliseconds 500
    }

    if ($ApiProcess.HasExited) {
        throw "FastAPI exited with code $($ApiProcess.ExitCode)."
    }
    throw "Streamlit exited with code $($UiProcess.ExitCode)."
}
finally {
    foreach ($Process in @($UiProcess, $ApiProcess)) {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Pop-Location
}
