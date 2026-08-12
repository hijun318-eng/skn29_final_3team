[CmdletBinding()]
param(
    [string]$ServiceFragmentPath,
    [string]$DataHubConsumerPath,
    [string]$EnvFilePath
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
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
$rootComposePath = Join-Path $repoRoot 'compose.yml'
$accessProfilePath = Join-Path $repoRoot 'config/server-access-profiles.v1.json'
$privateEnv = Join-Path $databaseRoot '.env'
$localEnv = if ($EnvFilePath) {
    $EnvFilePath
} elseif (Test-Path -LiteralPath $privateEnv) {
    $privateEnv
} else {
    Join-Path $repoRoot '.env.example'
}

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
if ($gms.image -ne 'acryldata/datahub-gms:v1.7.0' -or
    $gms.environment.DATAHUB_VERSION -ne $datahub.datahub_version -or
    $gms.environment.DATAHUB_OBJECT_STORAGE_URI -ne 'file:///tmp/datahub-object-storage' -or
    $gms.environment.METADATA_SERVICE_AUTH_ENABLED -ne 'true' -or
    $gms.environment.AUTH_POLICIES_ENABLED -ne 'true' -or
    $gms.environment.VIEW_AUTHORIZATION_ENABLED -ne 'true' -or
    $gms.environment.REST_API_AUTHORIZATION_ENABLED -ne 'true' -or
    $gmsHealth -notmatch '8080/health') {
    throw 'DataHub GMS image or health contract mismatch.'
}
$frontend = $consumer.services.'frontend-quickstart'
if ($frontend.environment.METADATA_SERVICE_AUTH_ENABLED -ne 'true' -or
    $frontend.environment.DATAHUB_SYSTEM_CLIENT_SECRET -eq 'JohnSnowKnowsNothing' -or
    $gms.environment.DATAHUB_SYSTEM_CLIENT_SECRET -ne $frontend.environment.DATAHUB_SYSTEM_CLIENT_SECRET) {
    throw 'DataHub metadata authentication is not consistently configured.'
}
$accessProfiles = Get-Content -LiteralPath $accessProfilePath -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedAccessProfiles = @('pms_only', 'crm_only', 'pms_crm', 'integrated_revenue')
if ($accessProfiles.contract_version -ne 'SERVER-ACCESS-PROFILES-v1.0.0' -or
    $accessProfiles.default_effect -ne 'deny' -or
    $accessProfiles.all_users_policy_dependency -ne $false -or
    (Compare-Object $expectedAccessProfiles @($accessProfiles.profiles.PSObject.Properties.Name))) {
    throw 'DataHub server access profile contract is unsafe.'
}
foreach ($profile in $accessProfiles.profiles.PSObject.Properties.Value) {
    if ($profile.datahub_actor -notmatch '^urn:li:corpuser:answervice_[a-z_]+$' -or
        $profile.datahub_token_env -notmatch '^DATAHUB_[A-Z_]+_TOKEN$' -or
        $profile.trino_principal -notmatch '^answervice_[a-z_]+$' -or
        @($profile.domains).Count -eq 0) {
        throw 'DataHub server access profile mapping is invalid.'
    }
}
$expectedDataHubImages = @{
    'system-update-quickstart' = 'acryldata/datahub-upgrade:v1.7.0'
    'datahub-gms-quickstart' = 'acryldata/datahub-gms:v1.7.0'
    'datahub-actions-quickstart' = 'acryldata/datahub-actions:v1.7.0-slim'
    'frontend-quickstart' = 'acryldata/datahub-frontend-react:v1.7.0'
    'kafka-broker' = 'confluentinc/cp-kafka:8.2.2'
}
foreach ($entry in $expectedDataHubImages.GetEnumerator()) {
    if ($consumer.services.PSObject.Properties[$entry.Key].Value.image -ne $entry.Value) {
        throw "DataHub consumer image drifted: $($entry.Key)"
    }
}

$compose = & docker compose --env-file $localEnv -f $composePath --profile full config --format json |
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

$rootOutput = & docker compose --env-file $localEnv -f $rootComposePath --profile full config --format json
if ($LASTEXITCODE -ne 0) {
    throw 'Root full Compose config failed while verifying the R2 service fragment.'
}
$rootCompose = $rootOutput | ConvertFrom-Json
if (Compare-Object $expectedDataHubServices @(
        $rootCompose.services.PSObject.Properties.Name |
            Where-Object { $_ -in $expectedDataHubServices }
    )) {
    throw 'Root full Compose does not include the complete DataHub consumer service set.'
}

$devOutput = & docker compose --env-file $localEnv -f $rootComposePath --profile dev config --format json
if ($LASTEXITCODE -ne 0) {
    throw 'Root dev Compose config failed while verifying the R2 service fragment.'
}
$devCompose = $devOutput | ConvertFrom-Json
if (@($devCompose.services.PSObject.Properties.Name |
        Where-Object { $_ -in $expectedDataHubServices }).Count -ne 0) {
    throw 'Root dev Compose unexpectedly includes a DataHub consumer service.'
}

Write-Output 'R2_SERVICE_FRAGMENT_VERIFIED'
