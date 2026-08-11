[CmdletBinding(SupportsShouldProcess)]
param([string]$EnvFilePath)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $repoRoot 'compose.yml'
$envFile = if ($EnvFilePath) { $EnvFilePath } else { Join-Path $databaseRoot '.env' }
$services = @(
    'frontend-quickstart', 'datahub-actions-quickstart', 'datahub-gms-quickstart',
    'system-update-quickstart', 'opensearch', 'mysql', 'kafka-broker'
)

if (-not (Test-Path -LiteralPath $envFile)) { throw 'Local database env file is missing.' }
if ($PSCmdlet.ShouldProcess('hotel-synthetic-db exact DataHub services', 'Stop and remove containers while preserving volumes')) {
    & docker compose --env-file $envFile -f $composeFile --profile full stop @services
    if ($LASTEXITCODE -ne 0) { throw 'Stopping exact DataHub services failed.' }
    & docker compose --env-file $envFile -f $composeFile --profile full rm -f @services
    if ($LASTEXITCODE -ne 0) { throw 'Removing exact DataHub containers failed.' }
}
Write-Output 'DATAHUB_RUNTIME_ROLLED_BACK_VOLUMES_PRESERVED'
