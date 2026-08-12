[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Approval
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$environmentFile = Join-Path $databaseRoot '.env'
$policyFile = Join-Path $databaseRoot 'sql\app\20-retention.sql'

if ($Apply -and $Approval -ne 'APPLY_RETENTION') {
    throw 'Deletion requires -Apply -Approval APPLY_RETENTION.'
}
if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw 'infrastructure/database/.env is required.'
}

$applyValue = if ($Apply) { 'true' } else { 'false' }
Get-Content -Raw -LiteralPath $policyFile | docker compose --env-file $environmentFile -f $composeFile exec -T app-postgres `
    sh -c 'exec psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set "apply=$1"' -- $applyValue
if ($LASTEXITCODE -ne 0) { throw 'Retention policy execution failed.' }

if ($Apply) { 'APP_POSTGRES_RETENTION_APPLIED' } else { 'APP_POSTGRES_RETENTION_DRY_RUN' }
