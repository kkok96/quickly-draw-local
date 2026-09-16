[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8787,
    [ValidateRange(1, 8)]
    [int]$Workers = 1
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "local_vector_api.py"
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Missing local API implementation: $scriptPath"
}

& py -3 $scriptPath --host $BindHost --port $Port --workers $Workers
