[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$fragmentPath = Join-Path $databaseRoot 'r1-service-fragment.v1.json'
$composePath = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'

$raw = Get-Content -LiteralPath $fragmentPath -Raw -Encoding UTF8
$fragment = $raw | ConvertFrom-Json
$expectedServices = @(
    'app-postgres', 'pms-postgres', 'banquet-postgres', 'pos-mysql',
    'crm-mssql', 'facility-clickhouse', 'trino', 'datahub-core'
)

if ($fragment.schema_version -ne '1.0.0' -or
    $fragment.seed_version -ne '20260729' -or
    $fragment.scenario_version -ne '1.0.0') {
    throw 'R2 service fragment data contract version mismatch.'
}
if ($raw -match 'CHANGE_ME_') {
    throw 'R2 service fragment contains a secret placeholder value.'
}
if (Compare-Object $expectedServices @($fragment.services.service_name)) {
    throw 'R2 service fragment service set mismatch.'
}

foreach ($service in $fragment.services) {
    foreach ($field in 'service_name', 'image_or_build', 'ports', 'env_keys', 'health', 'depends_on', 'profiles') {
        if ($null -eq $service.$field) {
            throw "$($service.service_name) is missing $field."
        }
    }
    foreach ($envKey in $service.env_keys) {
        if ($envKey -cnotmatch '^[A-Z][A-Z0-9_]+$') {
            throw "$($service.service_name) has an invalid env key."
        }
    }
}

$datahub = $fragment.services | Where-Object service_name -eq 'datahub-core'
if ($datahub.image_or_build -notmatch 'immutable v\* release or sha-\* tag' -or
    $datahub.health -notmatch '/health' -or
    $datahub.profiles -contains 'dev') {
    throw 'DataHub image, health, or profile requirement is unsafe.'
}

$compose = & docker compose --env-file $localEnv -f $composePath config --format json |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw 'Database Compose config failed while verifying the R2 service fragment.'
}
foreach ($service in $fragment.services | Where-Object kind -ne 'official-quickstart-compose-stack') {
    $configured = $compose.services.PSObject.Properties[$service.service_name].Value
    if ($null -eq $configured -or $configured.image -ne $service.image_or_build) {
        throw "$($service.service_name) image drifted from database Compose."
    }
}

Write-Output 'R2_SERVICE_FRAGMENT_VERIFIED'
