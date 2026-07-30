[CmdletBinding()]
param(
    [string]$ServiceFragmentPath,
    [string]$DataHubConsumerPath
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$fragmentPath = if ($ServiceFragmentPath) {
    $ServiceFragmentPath
} else {
    Join-Path $databaseRoot 'r1-service-fragment.v1.json'
}
$consumerPath = if ($DataHubConsumerPath) {
    $DataHubConsumerPath
} else {
    Join-Path $databaseRoot 'datahub/compose.consumer.yml'
}
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
if ($raw -match '(?i)CHANGE_ME_|placeholder|must be pinned|:latest|sha-\*|<[^>]+>') {
    throw 'R2 service fragment contains a placeholder or mutable version.'
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
if ($datahub.datahub_version -notmatch '^v\d+\.\d+\.\d+(?:\.\d+)?$|^sha-[0-9a-f]{7,}$' -or
    $datahub.compose_source_revision -notmatch '^[0-9a-f]{40}$' -or
    $datahub.compose_source -notmatch "^https://raw\.githubusercontent\.com/datahub-project/datahub/$($datahub.compose_source_revision)/docker/quickstart/docker-compose\.quickstart-profile\.yml$" -or
    $datahub.compose_source_blob -notmatch '^[0-9a-f]{40}$' -or
    $datahub.consumer_fragment -ne 'datahub/compose.consumer.yml' -or
    $datahub.health -notmatch '/health' -or
    $datahub.health -notmatch '4319/actuator/health' -or
    $datahub.profiles -contains 'dev') {
    throw 'DataHub version, source, health, consumer, or profile requirement is unsafe.'
}

$consumerRaw = Get-Content -LiteralPath $consumerPath -Raw -Encoding UTF8
if ($consumerRaw -match '(?i)CHANGE_ME_|placeholder|must be pinned|:latest|sha-\*|<[^>]+>|\$\{DATAHUB_VERSION') {
    throw 'DataHub consumer fragment contains a placeholder or mutable version.'
}
if ($consumerRaw -notmatch [regex]::Escape($datahub.datahub_version) -or
    $consumerRaw -notmatch [regex]::Escape($datahub.compose_source_revision) -or
    $consumerRaw -notmatch [regex]::Escape($datahub.compose_source_blob) -or
    $consumerRaw -notmatch [regex]::Escape($datahub.compose_source)) {
    throw 'DataHub consumer source provenance drifted from the service fragment.'
}
$consumerOutput = & docker compose --env-file $localEnv -f $consumerPath --profile full config --format json
if ($LASTEXITCODE -ne 0) {
    throw 'DataHub consumer Compose config failed.'
}
$consumer = $consumerOutput | ConvertFrom-Json
$expectedDataHubServices = @(
    'kafka-broker', 'mysql', 'opensearch', 'system-update-quickstart',
    'datahub-gms-quickstart', 'datahub-actions-quickstart', 'frontend-quickstart'
)
if (Compare-Object $expectedDataHubServices @($consumer.services.PSObject.Properties.Name)) {
    throw 'DataHub consumer service set mismatch.'
}
foreach ($service in $consumer.services.PSObject.Properties.Value) {
    if ($service.profiles -contains 'dev' -or
        $service.profiles -notcontains 'full' -or
        $service.profiles -notcontains 'split-host') {
        throw 'DataHub consumer profile requirement is unsafe.'
    }
}
$gms = $consumer.services.'datahub-gms-quickstart'
$gmsHealth = @($gms.healthcheck.test) -join ' '
if ($gms.image -ne 'acryldata/datahub-gms:v1.6.0' -or
    $gms.environment.DATAHUB_VERSION -ne $datahub.datahub_version -or
    $gmsHealth -notmatch '8080/health' -or
    $gmsHealth -notmatch '4319/actuator/health') {
    throw 'DataHub GMS image or health contract mismatch.'
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
