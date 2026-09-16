param(
    [Parameter(Mandatory = $true)]
    [string]$InputSvg,

    [string]$OutputAi,
    [string]$OutputPng,

    [ValidateSet('center', 'bottom-right', 'top-right', 'bottom-left', 'top-left')]
    [string]$Placement = 'center',

    [ValidateRange(0.01, 1.0)]
    [double]$MaxWidthFraction = 0.72,

    [ValidateRange(0.01, 1.0)]
    [double]$MaxHeightFraction = 0.78,

    [ValidateRange(0, 5000)]
    [int]$DelayMs = 90,

    [switch]$NewDocument,

    [ValidateRange(10, 16348)]
    [double]$DocumentWidth = 1254,

    [ValidateRange(10, 16348)]
    [double]$DocumentHeight = 1254,

    [bool]$ReplaceExistingGroup = $true,

    [ValidateRange(-1, 1000000)]
    [int]$AtomicIndex = -1,

    [bool]$SaveOutputs = $true,

    [string]$AtomicBatchJson,

    [string]$GroupName = 'VECTOR_DIRECT_Runtime_SVG',
    [string]$IllustratorProgId = ''
)

$ErrorActionPreference = 'Stop'

$resolvedInput = (Resolve-Path -LiteralPath $InputSvg).Path
if ([IO.Path]::GetExtension($resolvedInput) -ne '.svg') {
    throw "Input must be an SVG file: $resolvedInput"
}

$inputDirectory = [IO.Path]::GetDirectoryName($resolvedInput)
$inputStem = [IO.Path]::GetFileNameWithoutExtension($resolvedInput)
if ([string]::IsNullOrWhiteSpace($OutputAi)) {
    $OutputAi = [IO.Path]::Combine($inputDirectory, "${inputStem}_vector.ai")
}
if ([string]::IsNullOrWhiteSpace($OutputPng)) {
    $OutputPng = [IO.Path]::Combine($inputDirectory, "${inputStem}_vector.png")
}

$OutputAi = [IO.Path]::GetFullPath($OutputAi)
$OutputPng = [IO.Path]::GetFullPath($OutputPng)
foreach ($outputPath in @($OutputAi, $OutputPng)) {
    $outputDirectory = [IO.Path]::GetDirectoryName($outputPath)
    if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
        New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    }
}

$runtimePath = Join-Path $PSScriptRoot 'direct_vector_runtime.jsx'
if (-not (Test-Path -LiteralPath $runtimePath)) {
    throw "Runtime JSX is missing: $runtimePath"
}

$atomicBatch = $null
if (-not [string]::IsNullOrWhiteSpace($AtomicBatchJson)) {
    $atomicBatch = @($AtomicBatchJson | ConvertFrom-Json)
}

$configuration = [ordered]@{
    inputSvg = ($resolvedInput -replace '\\', '/')
    outputAi = ($OutputAi -replace '\\', '/')
    outputPng = ($OutputPng -replace '\\', '/')
    placement = $Placement
    maxWidthFraction = $MaxWidthFraction
    maxHeightFraction = $MaxHeightFraction
    delayMs = $DelayMs
    createNewDocument = [bool]$NewDocument
    documentWidth = $DocumentWidth
    documentHeight = $DocumentHeight
    groupName = $GroupName
    replaceExistingGroup = $ReplaceExistingGroup
    atomicIndex = $AtomicIndex
    saveOutputs = $SaveOutputs
    atomicBatch = $atomicBatch
}

$configJson = $configuration | ConvertTo-Json -Compress -Depth 8
$runtimeJson = (($runtimePath -replace '\\', '/') | ConvertTo-Json -Compress)
$bootstrap = "var VECTOR_DIRECT_CONFIG = $configJson; $.evalFile(new File($runtimeJson));"

$illustrator = $null
try {
    if ([string]::IsNullOrWhiteSpace($IllustratorProgId)) {
        $registered = @(Get-ChildItem -Path Registry::HKEY_CLASSES_ROOT -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -match '^Illustrator\.Application(?:\.\d+)?$' } |
            Select-Object -ExpandProperty PSChildName)
        $progIds = @('Illustrator.Application') + @($registered | Sort-Object -Descending -Unique)
    } else {
        $progIds = @($IllustratorProgId)
    }
    foreach ($progId in $progIds) {
        try {
            $illustrator = New-Object -ComObject $progId
            if ($illustrator.Documents.Count -ge 1 -or $NewDocument) { break }
            [Runtime.InteropServices.Marshal]::ReleaseComObject($illustrator) | Out-Null
            $illustrator = $null
        } catch {
            if ($null -ne $illustrator) { [Runtime.InteropServices.Marshal]::ReleaseComObject($illustrator) | Out-Null }
            $illustrator = $null
        }
    }
    if ($null -eq $illustrator) { throw 'AI_COM_UNAVAILABLE|No working Illustrator COM interface was found.' }
    $result = [string]$illustrator.DoJavaScript($bootstrap)
    if (-not $result.StartsWith('OK|')) {
        throw "Illustrator runtime failed: $result"
    }
    $result
} finally {
    if ($null -ne $illustrator) {
        [Runtime.InteropServices.Marshal]::ReleaseComObject($illustrator) | Out-Null
    }
}
