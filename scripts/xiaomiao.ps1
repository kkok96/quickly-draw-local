#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("health", "verify", "upload", "status", "download")]
    [string]$Action = "health",

    [string]$ImagePath,
    [string]$ImageId,
    [string]$OutputPath,
    [uri]$BaseUrl = "http://127.0.0.1:8787"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

function Test-LocalVectorBackend([uri]$Endpoint) {
    return $Endpoint.IsAbsoluteUri -and $Endpoint.Scheme -in @('http', 'https') -and $Endpoint.Host -in @('127.0.0.1', 'localhost', '::1', '[::1]') -and -not $Endpoint.UserInfo
}

function New-XiaomiaoClient([uri]$Endpoint) {
    if (-not (Test-LocalVectorBackend $Endpoint)) {
        throw "Only the local vector backend is supported; remote API endpoints are disabled."
    }
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(90)
    return $client
}

function Read-ResponseBody([Net.Http.HttpResponseMessage]$Response) {
    return $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
}

function Convert-ResponseJson([string]$Body) {
    try {
        return $Body | ConvertFrom-Json
    }
    catch {
        return [pscustomobject]@{ raw = $Body }
    }
}

function Get-ServerError([string]$Body) {
    try {
        $payload = $Body | ConvertFrom-Json
        if ($payload.error) { return [string]$payload.error }
    }
    catch { }
    return "The server rejected the request."
}

$root = $BaseUrl.AbsoluteUri.TrimEnd('/')

switch ($Action) {
    "health" {
        $client = New-XiaomiaoClient -Endpoint $BaseUrl
        try {
            $response = $client.GetAsync("$root/api/health").GetAwaiter().GetResult()
            $body = Read-ResponseBody $response
            if (-not $response.IsSuccessStatusCode) {
                throw "Xiaomiao health check failed (HTTP $([int]$response.StatusCode))."
            }
            Convert-ResponseJson $body
        }
        finally {
            if ($response) { $response.Dispose() }
            $client.Dispose()
        }
    }

    "verify" {
        $client = New-XiaomiaoClient -Endpoint $BaseUrl
        try {
            $probeId = "__codex_connection_probe__"
            $response = $client.GetAsync("$root/api/images/$probeId").GetAwaiter().GetResult()
            $statusCode = [int]$response.StatusCode
            $body = Read-ResponseBody $response

            if ($statusCode -eq 404) {
                [pscustomobject]@{
                    ok = $true
                    authenticated = $true
                    service = "local-vector-service"
                    credits_charged = 0
                }
                break
            }
            if ($statusCode -in 401, 403) {
                throw "Xiaomiao API-key authentication failed (HTTP $statusCode)."
            }
            throw "Xiaomiao authentication probe returned unexpected HTTP ${statusCode}: $(Get-ServerError $body)"
        }
        finally {
            if ($response) { $response.Dispose() }
            $client.Dispose()
        }
    }

    "upload" {
        if (-not $ImagePath) { throw "-ImagePath is required for upload." }
        $resolvedImage = (Resolve-Path -LiteralPath $ImagePath).Path
        $fileInfo = Get-Item -LiteralPath $resolvedImage
        if ($fileInfo.Length -gt 10MB) { throw "The image exceeds Xiaomiao's 10 MB limit." }

        $mimeTypes = @{
            ".png" = "image/png"
            ".jpg" = "image/jpeg"
            ".jpeg" = "image/jpeg"
            ".webp" = "image/webp"
        }
        $extension = [IO.Path]::GetExtension($resolvedImage).ToLowerInvariant()
        if (-not $mimeTypes.ContainsKey($extension)) {
            throw "Xiaomiao accepts PNG, JPEG, or WebP files."
        }

        $client = New-XiaomiaoClient -Endpoint $BaseUrl
        $bodyContent = $null
        $imageBytes = $null
        $bodyBytes = $null
        $response = $null
        try {
            $boundary = "local-vector-$([Guid]::NewGuid().ToString('N'))"
            $crlf = "`r`n"
            $prefix = "--$boundary$crlf" +
                "Content-Disposition: form-data; name=`"image`"; filename=`"$($fileInfo.Name)`"$crlf" +
                "Content-Type: $($mimeTypes[$extension])$crlf$crlf"
            $suffix = "$crlf--$boundary--$crlf"
            $prefixBytes = [Text.Encoding]::UTF8.GetBytes($prefix)
            $imageBytes = [IO.File]::ReadAllBytes($resolvedImage)
            $suffixBytes = [Text.Encoding]::UTF8.GetBytes($suffix)
            $bodyBytes = [byte[]]::new($prefixBytes.Length + $imageBytes.Length + $suffixBytes.Length)
            [Buffer]::BlockCopy($prefixBytes, 0, $bodyBytes, 0, $prefixBytes.Length)
            [Buffer]::BlockCopy($imageBytes, 0, $bodyBytes, $prefixBytes.Length, $imageBytes.Length)
            [Buffer]::BlockCopy($suffixBytes, 0, $bodyBytes, $prefixBytes.Length + $imageBytes.Length, $suffixBytes.Length)
            $bodyContent = [Net.Http.ByteArrayContent]::new($bodyBytes)
            $bodyContent.Headers.TryAddWithoutValidation("Content-Type", "multipart/form-data; boundary=$boundary") | Out-Null

            $response = $client.PostAsync("$root/api/images", $bodyContent).GetAwaiter().GetResult()
            $body = Read-ResponseBody $response
            if (-not $response.IsSuccessStatusCode) {
                throw "Xiaomiao upload failed (HTTP $([int]$response.StatusCode)): $(Get-ServerError $body)"
            }
            Convert-ResponseJson $body
        }
        finally {
            if ($response) { $response.Dispose() }
            if ($bodyContent) { $bodyContent.Dispose() }
            $bodyBytes = $null
            $imageBytes = $null
            $client.Dispose()
        }
    }

    "status" {
        if (-not $ImageId) { throw "-ImageId is required for status." }
        $escapedId = [Uri]::EscapeDataString($ImageId)
        $client = New-XiaomiaoClient -Endpoint $BaseUrl
        try {
            $response = $client.GetAsync("$root/api/images/$escapedId").GetAwaiter().GetResult()
            $body = Read-ResponseBody $response
            if (-not $response.IsSuccessStatusCode) {
                throw "Xiaomiao status request failed (HTTP $([int]$response.StatusCode)): $(Get-ServerError $body)"
            }
            Convert-ResponseJson $body
        }
        finally {
            if ($response) { $response.Dispose() }
            $client.Dispose()
        }
    }

    "download" {
        if (-not $ImageId) { throw "-ImageId is required for download." }
        if (-not $OutputPath) { throw "-OutputPath is required for download." }
        $escapedId = [Uri]::EscapeDataString($ImageId)
        $client = New-XiaomiaoClient -Endpoint $BaseUrl
        try {
            $response = $client.GetAsync("$root/api/images/$escapedId/file").GetAwaiter().GetResult()
            if (-not $response.IsSuccessStatusCode -and [int]$response.StatusCode -eq 410) {
                $response.Dispose()
                $response = $client.GetAsync("$root/api/images/$escapedId/result").GetAwaiter().GetResult()
            }
            if (-not $response.IsSuccessStatusCode) {
                $body = Read-ResponseBody $response
                throw "Xiaomiao download failed (HTTP $([int]$response.StatusCode)): $(Get-ServerError $body)"
            }
            $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
            $target = [IO.Path]::GetFullPath($OutputPath)
            $targetDirectory = Split-Path -Parent $target
            if ($targetDirectory) { New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null }
            [IO.File]::WriteAllBytes($target, $bytes)
            [pscustomobject]@{ ok = $true; output_path = $target; bytes = $bytes.Length }
        }
        finally {
            if ($response) { $response.Dispose() }
            $client.Dispose()
        }
    }
}
