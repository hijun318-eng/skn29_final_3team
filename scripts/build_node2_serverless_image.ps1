[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ImageRef,

    [string]$ModelPath = "",

    [switch]$Push
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $ModelPath) {
    $ModelPath = Join-Path (Split-Path $repositoryRoot -Parent) `
        "Node2_artifacts\qwen35-2b-full3000-static-corrected"
}
$resolvedModelPath = (Resolve-Path -LiteralPath $ModelPath).Path
$dockerfile = Join-Path $repositoryRoot "infrastructure\ai\node2_serverless\Dockerfile"

if ($ImageRef -match "(?i)(^|:)latest$") {
    throw "Use an immutable canary tag; latest is not allowed."
}

$weights = Join-Path $resolvedModelPath "model.safetensors"
$mergeManifestPath = Join-Path $resolvedModelPath "merge_manifest.json"
foreach ($requiredPath in @($weights, $mergeManifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Corrected checkpoint file is missing: $requiredPath"
    }
}

$expectedMergeManifestSha256 = "db8c3c52c5566711ad0b5c8dca17cbc7f7f3508ff94b0084248efa2282d33d74"
$actualMergeManifestSha256 = (
    Get-FileHash -LiteralPath $mergeManifestPath -Algorithm SHA256
).Hash.ToLowerInvariant()
if ($actualMergeManifestSha256 -ne $expectedMergeManifestSha256) {
    throw "Corrected checkpoint merge manifest SHA-256 mismatch."
}

$expectedWeightSha256 = "3e2ff059714318ba0b355e35247704e1a7accfc4a03b8c2ad0122d96982a1dda"
$actualWeightSha256 = (Get-FileHash -LiteralPath $weights -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualWeightSha256 -ne $expectedWeightSha256) {
    throw "Corrected checkpoint weight SHA-256 mismatch."
}

$mergeManifest = Get-Content -Raw -LiteralPath $mergeManifestPath | ConvertFrom-Json
if (
    $mergeManifest.expected_keys -ne 632 -or
    $mergeManifest.saved_keys -ne 632 -or
    $mergeManifest.replaced_language_keys -ne 96 -or
    $mergeManifest.preserved_base_keys -ne 536
) {
    throw "Corrected checkpoint merge counts do not match 632/96/536."
}

$dockerArguments = @(
    "buildx", "build",
    "--platform", "linux/amd64",
    "--file", $dockerfile,
    "--tag", $ImageRef,
    "--provenance=false",
    "--sbom=false"
)
if ($Push) {
    $dockerArguments += "--push"
} else {
    $dockerArguments += "--load"
}
$dockerArguments += $repositoryRoot

& docker @dockerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker buildx failed with exit code $LASTEXITCODE."
}

Write-Host "PASS_NODE2_SERVERLESS_IMAGE_BUILD"
Write-Host "image_ref=$ImageRef"
Write-Host "model_weight_sha256=$actualWeightSha256"
Write-Host "model_delivery=RUNPOD_HUGGINGFACE_CACHE"
Write-Host "pushed=$($Push.IsPresent)"
