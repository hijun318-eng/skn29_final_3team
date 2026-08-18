# 책임: 현재 Compose project의 지정 DataHub container만 중지·제거하고 volume을
# 복구 증거로 보존한다. project/service 경계가 불명확하면 rollback을 실행하지 않는다.
[CmdletBinding(SupportsShouldProcess)]
param([string]$EnvFilePath)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $repoRoot 'compose.yml'
$semanticComposeFile = Join-Path $databaseRoot 'datahub/compose.semantic-search.yml'
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$services = @(
    'frontend-quickstart', 'datahub-actions-quickstart', 'datahub-gms-quickstart',
    'dataset-semantic-content-bootstrap', 'datahub-ingestion',
    'system-update-quickstart', 'opensearch', 'semantic-elasticsearch',
    'ollama-model-bootstrap', 'ollama', 'mysql', 'kafka-broker'
)

$resolved = & docker compose @composeEnvArguments -f $composeFile `
    -f $semanticComposeFile --profile full --profile semantic-search `
    --profile legacy-search config --format json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $resolved.name) {
    throw 'Compose project identity could not be resolved.'
}

# Rollback removes only named DataHub containers. Volumes are preserved so a
# separately approved restore can validate and reuse them.
if ($PSCmdlet.ShouldProcess("$($resolved.name) exact DataHub services", 'Stop and remove containers while preserving volumes')) {
    $baseArgs = @(
        'compose'
    ) + $composeEnvArguments + @(
        '-f', $composeFile,
        '-f', $semanticComposeFile, '--profile', 'full',
        '--profile', 'semantic-search', '--profile', 'legacy-search'
    )
    & docker @baseArgs stop @services
    if ($LASTEXITCODE -ne 0) { throw 'Stopping exact DataHub services failed.' }
    & docker @baseArgs rm -f @services
    if ($LASTEXITCODE -ne 0) { throw 'Removing exact DataHub containers failed.' }
}
Write-Output 'DATAHUB_RUNTIME_ROLLED_BACK_VOLUMES_PRESERVED'
