[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$RepoId,

    [string]$ModelPath = "",

    [switch]$Upload
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $ModelPath) {
    $ModelPath = Join-Path (Split-Path $repositoryRoot -Parent) `
        "Node2_artifacts\qwen35-2b-full3000-static-corrected"
}
$resolvedModelPath = (Resolve-Path -LiteralPath $ModelPath).Path
$mergeManifestPath = Join-Path $resolvedModelPath "merge_manifest.json"
if (-not (Test-Path -LiteralPath $mergeManifestPath -PathType Leaf)) {
    throw "Merge manifest is missing: $mergeManifestPath"
}

$expectedMergeManifestSha256 = "db8c3c52c5566711ad0b5c8dca17cbc7f7f3508ff94b0084248efa2282d33d74"
$actualMergeManifestSha256 = (
    Get-FileHash -LiteralPath $mergeManifestPath -Algorithm SHA256
).Hash.ToLowerInvariant()
if ($actualMergeManifestSha256 -ne $expectedMergeManifestSha256) {
    throw "Corrected checkpoint merge manifest SHA-256 mismatch."
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
$expectedWeightSha256 = "3e2ff059714318ba0b355e35247704e1a7accfc4a03b8c2ad0122d96982a1dda"
if ($mergeManifest.files.'model.safetensors' -ne $expectedWeightSha256) {
    throw "Corrected checkpoint model weight SHA-256 is not pinned."
}

$verifiedBytes = [int64]0
$verifiedFiles = 0
foreach ($fileEntry in $mergeManifest.files.PSObject.Properties) {
    $filePath = Join-Path $resolvedModelPath $fileEntry.Name
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        throw "Checkpoint file is missing: $filePath"
    }
    $expectedHash = [string]$fileEntry.Value
    $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Checkpoint file SHA-256 mismatch: $($fileEntry.Name)"
    }
    $verifiedBytes += (Get-Item -LiteralPath $filePath).Length
    $verifiedFiles += 1
}

Write-Host "PASS_NODE2_HF_MODEL_SOURCE"
Write-Host "repo_id=$RepoId"
Write-Host "model_path=$resolvedModelPath"
Write-Host "verified_files=$verifiedFiles"
Write-Host "verified_bytes=$verifiedBytes"
Write-Host "weight_sha256=$($mergeManifest.files.'model.safetensors')"
Write-Host "upload_requested=$($Upload.IsPresent)"

if (-not $Upload) {
    return
}

if ($null -eq (Get-Command hf -ErrorAction SilentlyContinue)) {
    throw "The hf CLI is not installed. Install huggingface_hub with hf_xet first."
}

& hf auth whoami --format quiet | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Hugging Face login is required. Run 'hf auth login' in your terminal."
}

& hf repos create $RepoId --repo-type model --private --exist-ok --format quiet
if ($LASTEXITCODE -ne 0) {
    throw "Could not create or access the Hugging Face model repository."
}

$beforeUploadJson = & hf models info $RepoId --expand private --format json
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the Hugging Face model repository."
}
$beforeUpload = $beforeUploadJson | ConvertFrom-Json
if ($beforeUpload.private -ne $true) {
    throw "Refusing to upload because the Hugging Face repository is not private."
}

$previousHighPerformance = $env:HF_XET_HIGH_PERFORMANCE
try {
    $env:HF_XET_HIGH_PERFORMANCE = "1"
    & hf upload $RepoId $resolvedModelPath "." `
        --repo-type model `
        --private `
        --commit-message "Node2 Qwen3.5-2B Full3000 corrected static checkpoint" `
        --commit-description "632 keys; 96 adapter targets replaced; weight SHA-256 $($mergeManifest.files.'model.safetensors')"
    if ($LASTEXITCODE -ne 0) {
        throw "Hugging Face model upload failed. Re-run the same command to resume."
    }
}
finally {
    if ($null -eq $previousHighPerformance) {
        Remove-Item Env:HF_XET_HIGH_PERFORMANCE -ErrorAction SilentlyContinue
    }
    else {
        $env:HF_XET_HIGH_PERFORMANCE = $previousHighPerformance
    }
}

$modelInfoJson = & hf models info $RepoId --expand sha,private,usedStorage --format json
if ($LASTEXITCODE -ne 0) {
    throw "Upload completed, but the final Hugging Face revision could not be resolved."
}
$modelInfo = $modelInfoJson | ConvertFrom-Json
if ($modelInfo.private -ne $true -or $modelInfo.sha -notmatch '^[0-9a-f]{40}$') {
    throw "The uploaded repository is not private or has no immutable commit SHA."
}

Write-Host "PASS_NODE2_HF_MODEL_UPLOAD"
Write-Host "model_name=$RepoId"
Write-Host "model_revision=$($modelInfo.sha)"
Write-Host "private=$($modelInfo.private)"
Write-Host "used_storage=$($modelInfo.usedStorage)"
