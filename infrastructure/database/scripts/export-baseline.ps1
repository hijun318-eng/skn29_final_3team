[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$OutputPath,
    [Parameter(Mandatory)] [string]$ReleaseId
)

$ErrorActionPreference = 'Stop'
# 이 script는 live service inventory와 Git-tracked runtime input의 checksum만
# 내보낸다. 질문·dataset 전용 manifest 또는 local secret snapshot은 만들지 않는다.
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Resolve-Path (Join-Path $databaseRoot '..\..')
$compose = Join-Path $repoRoot 'compose.yml'
$semanticCompose = Join-Path $databaseRoot 'datahub\compose.semantic-search.yml'
$exampleEnv = Join-Path $databaseRoot '.env.example'
Set-Location $repoRoot

if (git status --short) {
    throw 'Baseline export requires a clean Git worktree so checksums bind to one commit.'
}
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$') {
    throw 'ReleaseId must be an operator-assigned stable identifier.'
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
    'infrastructure/database/trino/etc',
    'infrastructure/database/datahub/compose.consumer.yml',
    'infrastructure/database/datahub/compose.ingestion.yml',
    'infrastructure/database/datahub/compose.semantic-search.yml',
    'infrastructure/database/datahub/Dockerfile.semantic-content',
    'infrastructure/database/datahub/recipes'
)
# Only tracked runtime inputs belong in release evidence. This deliberately
# excludes ignored .env and principal secrets even when they exist beside the
# provisioning scripts on the operator's machine.
$trackedRuntimePaths = @(& git ls-files -- @runtimeRoots)
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
