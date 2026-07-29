[CmdletBinding()]
param(
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'
$exampleEnv = Join-Path $databaseRoot '.env.example'

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    & docker compose --env-file $localEnv -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $localEnv)) {
    Copy-Item -LiteralPath $exampleEnv -Destination $localEnv
    throw '.env was created from .env.example. Replace every CHANGE_ME_ value, then run this script again.'
}

if (Select-String -LiteralPath $localEnv -Pattern '(^|=)CHANGE_ME_' -Quiet) {
    throw '.env contains CHANGE_ME_ values. Set environment-specific passwords before starting the database stack.'
}

Invoke-Compose config --quiet

if ($Reset) {
    Invoke-Compose down --volumes --remove-orphans
}

Invoke-Compose up -d --wait --wait-timeout 1800

Invoke-Compose exec -T app-postgres sh /security/provision-app-postgres.sh
Invoke-Compose exec -T pms-postgres sh /security/provision-source-postgres.sh
Invoke-Compose exec -T banquet-postgres sh /security/provision-source-postgres.sh
Invoke-Compose exec -T pos-mysql sh /security/provision-pos-mysql.sh
Invoke-Compose exec -T crm-mssql sh /security/provision-crm-mssql.sh
Invoke-Compose exec -T facility-clickhouse sh /security/provision-facility-clickhouse.sh

$trinoReady = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    & docker compose --env-file $localEnv -f $composeFile exec -T trino trino --server http://localhost:8080 --user hotel_synthetic_setup --execute 'SELECT 1' | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $trinoReady = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $trinoReady) {
    throw 'Trino did not become query-ready within 120 seconds.'
}
Invoke-Compose exec -T trino trino --server http://localhost:8080 --user hotel_synthetic_setup --file /sql/ddl/06_trino_analytics_views.sql

Write-Output 'DATABASE_STACK_READY'
