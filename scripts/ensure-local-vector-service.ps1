#requires -Version 5.1

[CmdletBinding()]
param(
    [uri]$BaseUrl = "http://127.0.0.1:8787",
    [ValidateRange(5, 120)]
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$root = $BaseUrl.AbsoluteUri.TrimEnd('/')
if ($BaseUrl.Host -notin @('127.0.0.1', 'localhost', '::1')) {
    throw "Automatic startup is only supported for the local backend at http://127.0.0.1:8787."
}

$skillRoot = Split-Path -Parent $PSScriptRoot
$apiScript = Join-Path $skillRoot 'local-api\local_vector_api.py'
if (-not (Test-Path -LiteralPath $apiScript -PathType Leaf)) {
    throw "Missing local API implementation: $apiScript"
}

function Get-LocalHealth {
    try {
        $payload = Invoke-RestMethod -Uri "$root/api/health" -Method Get -TimeoutSec 2 -MaximumRedirection 0
        if ($payload.ok -eq $true) {
            return $payload
        }
    }
    catch {
        return $null
    }
    return $null
}

function Write-SetupResult([object]$Health, [bool]$Started) {
    [pscustomobject]@{
        ok = $true
        started = $Started
        service = [string]$Health.service
        backend = [string]$Health.backend
        url = $root
    } | ConvertTo-Json -Compress
}

$health = Get-LocalHealth
if ($null -ne $health) {
    Write-SetupResult -Health $health -Started $false
    return
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $pythonLauncher) {
    throw "Python launcher 'py' is required for the local vector service."
}

& $pythonLauncher.Source -3 -c "import vtracer" 2>$null
if ($LASTEXITCODE -ne 0) {
    $installOutput = @(& $pythonLauncher.Source -3 -m pip install --user vtracer 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "The local vtracer dependency could not be installed automatically: $($installOutput -join ' ')"
    }
}

$pythonPath = ((& $pythonLauncher.Source -3 -c "import sys; print(sys.executable)") | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pythonPath) -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python 3 could not be resolved for the local vector service."
}

$port = $BaseUrl.Port
if ($port -lt 1 -or $port -gt 65535) {
    throw "The local backend URL must include a valid TCP port."
}

$logRoot = Join-Path ([IO.Path]::GetTempPath()) 'quickly-draw-local-api'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$runId = [guid]::NewGuid().ToString('N')
$stdoutLog = Join-Path $logRoot "$runId.stdout.log"
$stderrLog = Join-Path $logRoot "$runId.stderr.log"
$arguments = @($apiScript, '--host', $BaseUrl.Host, '--port', [string]$port, '--workers', '1')
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $skillRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Milliseconds 500
    $health = Get-LocalHealth
    if ($null -ne $health) {
        Write-SetupResult -Health $health -Started $true
        return
    }
}
while ((Get-Date) -lt $deadline)

$errorDetail = ''
if (Test-Path -LiteralPath $stderrLog -PathType Leaf) {
    $errorDetail = (Get-Content -Raw -Encoding UTF8 -LiteralPath $stderrLog).Trim()
}
if ([string]::IsNullOrWhiteSpace($errorDetail)) {
    $errorDetail = "startup process PID=$($process.Id) did not expose an error"
}
throw "The local vector service did not become healthy at $root. $errorDetail"
