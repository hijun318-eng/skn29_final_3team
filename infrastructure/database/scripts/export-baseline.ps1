[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$OutputPath,
    [Parameter(Mandatory)] [string]$ReleaseId
)

$ErrorActionPreference = 'Stop'
# 이 script는 live service inventory와 Git-tracked runtime input의 checksum만
# 내보낸다. 질문·dataset 전용 manifest 또는 local secret snapshot은 만들지 않는다.
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $databaseRoot '..\..')).Path
$compose = Join-Path $repoRoot 'compose.yml'
$semanticCompose = Join-Path $databaseRoot 'datahub\compose.semantic-search.yml'
$exampleEnv = Join-Path $databaseRoot '.env.example'
Set-Location $repoRoot

if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$') {
    throw 'ReleaseId must be an operator-assigned stable identifier.'
}

# ReleaseId를 임의 label로만 기록하면 실제 SQL과 receipt가 다른 release에 결속될 수
# 있다. tracked manifest를 읽어 정확히 하나의 release directory를 선택하고, manifest가
# 선언한 모든 파일 checksum을 먼저 검증한다.
$releaseMatches = @()
foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $databaseRoot 'releases') -Directory) {
    $candidate = Join-Path $directory.FullName 'manifest.json'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $document = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Release manifest is not valid JSON: $candidate"
    }
    if ([string]$document.release_id -ceq $ReleaseId) {
        $releaseMatches += [pscustomobject]@{
            Directory = $directory.FullName
            Manifest = $candidate
            Document = $document
        }
    }
}
if ($releaseMatches.Count -ne 1) {
    throw "ReleaseId must resolve to exactly one tracked manifest: $ReleaseId"
}
$release = $releaseMatches[0]
$releaseRelative = $release.Directory.Substring($repoRoot.Length + 1).Replace('\', '/')
$manifestRelative = $release.Manifest.Substring($repoRoot.Length + 1).Replace('\', '/')
foreach ($entry in @($release.Document.files)) {
    $relativePath = [string]$entry.relative_path
    $expectedHash = [string]$entry.sha256
    if ([string]::IsNullOrWhiteSpace($relativePath) -or
        $expectedHash -notmatch '^[a-fA-F0-9]{64}$') {
        throw 'Release manifest contains an invalid file receipt.'
    }
    $releaseFile = Join-Path $release.Directory $relativePath
    if (-not (Test-Path -LiteralPath $releaseFile -PathType Leaf)) {
        throw "Release file is missing: $relativePath"
    }
    $actualHash = (Get-FileHash -LiteralPath $releaseFile -Algorithm SHA256).Hash
    if ($actualHash -cne $expectedHash.ToUpperInvariant()) {
        throw "Release checksum mismatch: $relativePath"
    }
}

# Compose is the service/image source of truth. Deriving this inventory avoids
# duplicating engine versions and service names in a manually maintained table.
$composeJson = & docker compose --env-file $exampleEnv -f $compose `
    -f $semanticCompose `
    --profile full --profile semantic-search config --format json
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration could not be resolved.' }
$resolvedCompose = $composeJson | ConvertFrom-Json

$runtimeRoots = @(
    'compose.yml',
    'compose.app-postgres.override.yml',
    'app/backend/compose.fragment.yml',
    'app/backend/Dockerfile',
    'app/backend/entrypoint.sh',
    'app/frontend/compose.fragment.yml',
    'infrastructure/database/compose.yml',
    'infrastructure/database/sql/ddl',
    'infrastructure/database/sql/app',
    'infrastructure/database/security',
    'infrastructure/database/scripts',
    'infrastructure/database/trino/etc',
    'infrastructure/database/datahub/compose.consumer.yml',
    'infrastructure/database/datahub/compose.ingestion.yml',
    'infrastructure/database/datahub/compose.semantic-search.yml',
    'infrastructure/database/datahub/Dockerfile.semantic-content',
    'infrastructure/database/datahub/recipes'
)
# 다른 작업자가 수정 중인 문서나 presentation 산출물은 runtime baseline의 입력이 아니다.
# 반대로 선택된 runtime/release scope 안의 tracked 수정·삭제 또는 untracked 파일은 모두
# 거절해 working file checksum이 BASE_SHA와 다른 상태로 발행되지 않게 한다.
$baselineScope = @($runtimeRoots + $releaseRelative)
$scopeChanges = @(& git status --porcelain=v1 --untracked-files=all -- @baselineScope)
if ($LASTEXITCODE -ne 0) {
    throw 'Runtime/release worktree state could not be inspected.'
}
if ($scopeChanges.Count) {
    throw 'Baseline export requires the selected runtime and release scope to match HEAD.'
}
# Only tracked runtime inputs belong in release evidence. This deliberately
# excludes ignored .env and principal secrets even when they exist beside the
# provisioning scripts on the operator's machine.
$trackedRuntimePaths = @(& git ls-files -- @baselineScope)
if ($LASTEXITCODE -ne 0 -or -not $trackedRuntimePaths.Count) {
    throw 'Tracked runtime inputs could not be resolved from Git.'
}
$runtimeFiles = $trackedRuntimePaths | ForEach-Object {
    Get-Item -LiteralPath (Join-Path $repoRoot $_)
}

$lines = @(
    '# Answervice runtime baseline',
    '',
    "- RELEASE_ID: $ReleaseId",
    "- BASE_BRANCH: $(git branch --show-current)",
    "- BASE_SHA: $(git rev-parse HEAD)",
    "- RELEASE_MANIFEST: $manifestRelative",
    "- RELEASE_MANIFEST_SHA256: $((Get-FileHash -LiteralPath $release.Manifest -Algorithm SHA256).Hash.ToLowerInvariant())",
    '- WORKTREE_SCOPE: runtime_and_release_match_head',
    "- EXPORTED_AT_UTC: $([DateTimeOffset]::UtcNow.ToString('O'))",
    '',
    '## Resolved services',
    '',
    '| Service | Immutable image/build source | Profiles |',
    '|---|---|---|'
)
foreach ($property in $resolvedCompose.services.PSObject.Properties | Sort-Object Name) {
    $service = $property.Value
    $source = if ($service.image) { $service.image } elseif ($service.build) {
        "build:$($service.build.context):$($service.build.dockerfile)"
    } else { 'compose-defined' }
    $profiles = @($service.profiles) -join ','
    $lines += "| $($property.Name) | $source | $profiles |"
}

$lines += @('', '## Runtime checksums', '', '| Path | SHA256 |', '|---|---|')
foreach ($file in $runtimeFiles | Sort-Object FullName -Unique) {
    $relative = $file.FullName.Substring($repoRoot.Path.Length + 1).Replace('\', '/')
    $hash = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $lines += "| $relative | $hash |"
}

$outputParent = Split-Path -Parent $OutputPath
if ($outputParent) { New-Item -ItemType Directory -Force -Path $outputParent | Out-Null }
Set-Content -LiteralPath $OutputPath -Value $lines -Encoding utf8
Write-Output "BASELINE_EXPORTED=$OutputPath"
