# 책임: runtime recipe를 directory에서 발견해 DataHub의 source/serving 물리 metadata를
# 갱신한다. embedding과 semanticContent는 별도 검색 전략 승인 전 수행하지 않는다.
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Apply,
    [string]$EnvFilePath
)

$ErrorActionPreference = 'Stop'
# runtime recipe 목록은 directory에서 매번 발견한다. 특정 source 개수나 dataset
# 이름을 별도 manifest로 복제하지 않아 recipe 추가가 자동으로 ingestion에 포함된다.
$databaseRoot = Split-Path -Parent $PSScriptRoot
$composeFiles = @(
    Join-Path $databaseRoot 'compose.yml'
    Join-Path $PSScriptRoot 'compose.consumer.yml'
    Join-Path $PSScriptRoot 'compose.ingestion.yml'
)
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
. (Join-Path $databaseRoot 'scripts/deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-RepositoryDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$recipes = Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'recipes') `
    -Filter '*.runtime.yml' -File | Sort-Object Name

if (-not $Apply) {
    throw 'Metadata ingestion mutates DataHub. Re-run with -Apply after reviewing the runtime recipes.'
}
if (-not $recipes) {
    throw 'No runtime discovery recipes were found.'
}

$composeArguments = @($composeEnvArguments)
foreach ($file in $composeFiles) {
    $composeArguments += @('-f', $file)
}
$composeArguments += @('--profile', 'full', '--profile', 'metadata-ingestion')

& docker compose @composeArguments config --quiet
if ($LASTEXITCODE -ne 0) {
    throw 'DataHub ingestion compose configuration is invalid.'
}

if ($PSCmdlet.ShouldProcess(
    "$($recipes.Count) runtime recipes",
    'Ingest live source metadata into DataHub'
)) {
    & docker compose @composeArguments up --detach --force-recreate datahub-ingestion
    if ($LASTEXITCODE -ne 0) {
        throw 'DataHub metadata ingestion did not start.'
    }
    $ingestionContainer = @(
        & docker compose @composeArguments ps --all --quiet datahub-ingestion
    )
    if ($LASTEXITCODE -ne 0 -or $ingestionContainer.Count -ne 1) {
        throw 'DataHub metadata ingestion container was not created uniquely.'
    }
    $ingestionExit = & docker wait $ingestionContainer[0]
    if ($LASTEXITCODE -ne 0 -or [string]$ingestionExit -cne '0') {
        throw 'DataHub metadata ingestion failed.'
    }
    $completionLogs = @(& docker logs --tail 20 $ingestionContainer[0] 2>&1)
    if ($LASTEXITCODE -ne 0 -or
        'ANSWERVICE_RUNTIME_CATALOG_INGESTION_COMPLETE' -notin $completionLogs) {
        throw 'DataHub metadata ingestion exited without its completion marker.'
    }
}

Write-Output "BASE_METADATA_INGESTED|recipes=$($recipes.Count)|catalog_ready=false|next=SEMANTIC_CHECK"
