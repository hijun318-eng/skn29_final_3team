# 책임: 외부 deployment environment로 DB·Trino·DataHub를 두 단계로 기동한다.
# Core 단계는 인증/TLS와 운영자 UI를 준비하고, Catalog 단계는 DataHub가 발급한
# publish service token으로 source/serving의 물리 metadata만 수집한다. 이 단계는
# semantic check/publish/read-back 전이므로 catalog ready를 선언하지 않는다. embedding과
# semantic index는 검색 전략 승인 전 이 기동 경로에 포함하지 않는다.
[CmdletBinding()]
param(
    [string]$EnvFilePath,
    [ValidateSet('Core', 'Catalog')]
    [string]$Stage = 'Core',
    [switch]$AllowRepositoryLocalDevelopment
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $databaseRoot 'compose.yml'
$dataHubComposeFile = Join-Path $databaseRoot 'datahub/compose.consumer.yml'
$dataHubIngestionFile = Join-Path $databaseRoot 'datahub/compose.ingestion.yml'
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-ExplicitDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot `
    -AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$deploymentEnvironment = Read-DeploymentEnvironment $resolvedEnvFile

# Core는 아직 존재할 수 없는 PAT를 요구하지 않는다. Catalog 단계에서만 운영자가
# DataHub UI/OIDC를 통해 발급하고 외부 secret store에 주입한 두 token을 요구한다.
$requiredKeys = @(
    'APP_ADMIN_USER', 'APP_ADMIN_PASSWORD', 'APP_MIGRATION_USER',
    'APP_MIGRATION_PASSWORD', 'APP_CATALOG_PUBLISHER_USER',
    'APP_CATALOG_PUBLISHER_PASSWORD', 'APP_DB_USER', 'APP_DB_PASSWORD',
    'PMS_ADMIN_USER', 'PMS_ADMIN_PASSWORD', 'PMS_READONLY_USER',
    'PMS_READONLY_PASSWORD', 'BANQUET_ADMIN_USER', 'BANQUET_ADMIN_PASSWORD',
    'BANQUET_READONLY_USER', 'BANQUET_READONLY_PASSWORD', 'POS_ROOT_PASSWORD',
    'POS_READONLY_USER', 'POS_READONLY_PASSWORD', 'CRM_SA_PASSWORD',
    'CRM_READONLY_USER', 'CRM_READONLY_PASSWORD', 'FACILITY_ADMIN_USER',
    'FACILITY_ADMIN_PASSWORD', 'FACILITY_READONLY_USER',
    'FACILITY_READONLY_PASSWORD', 'DATAHUB_TOKEN_SERVICE_SALT',
    'DATAHUB_TOKEN_SERVICE_SIGNING_KEY', 'DATAHUB_SECRET',
    'DATAHUB_MYSQL_PASSWORD', 'DATAHUB_MYSQL_ROOT_PASSWORD',
    'DATAHUB_SECRET_SERVICE_ENCRYPTION_KEY', 'DATAHUB_SYSTEM_CLIENT_SECRET',
    'DATAHUB_TLS_KEYSTORE_PASSWORD', 'DATAHUB_TLS_TRUSTSTORE_PASSWORD',
    'TRINO_ADMIN_USER', 'TRINO_ADMIN_PASSWORD', 'TRINO_RUNTIME_USER',
    'TRINO_RUNTIME_PASSWORD', 'TRINO_DATAHUB_USER', 'TRINO_DATAHUB_PASSWORD',
    'TRINO_INTERNAL_SHARED_SECRET', 'TRINO_TLS_KEYSTORE_PASSWORD',
    'SERVING_CATALOG_DB_USER', 'SERVING_CATALOG_DB_PASSWORD',
    'SERVING_CATALOG_ADMIN_CLIENT_ID', 'SERVING_CATALOG_ADMIN_CLIENT_SECRET',
    'SERVING_CATALOG_TRINO_PRINCIPAL', 'SERVING_OBJECT_STORE_ACCESS_KEY',
    'SERVING_OBJECT_STORE_SECRET_KEY', 'SERVING_OBJECT_STORE_BUCKET',
    'SERVING_OBJECT_STORE_REGION'
)
if ($Stage -eq 'Catalog') {
    $requiredKeys += @(
        'DATAHUB_READ_ACTOR_URN', 'DATAHUB_READ_API_TOKEN',
        'DATAHUB_PUBLISH_ACTOR_URN', 'DATAHUB_PUBLISH_API_TOKEN',
        'PMS_DATAHUB_SCHEMA', 'BANQUET_DATAHUB_SCHEMA',
        'POS_DATAHUB_DATABASE', 'CRM_DATAHUB_SCHEMA',
        'FACILITY_DATAHUB_DATABASE'
    )
}
Assert-DeploymentEnvironmentValues `
    -Values $deploymentEnvironment -RequiredKeys $requiredKeys

$appDatabaseRoles = @(
    [string]$deploymentEnvironment['APP_DB_USER'],
    [string]$deploymentEnvironment['APP_MIGRATION_USER'],
    [string]$deploymentEnvironment['APP_CATALOG_PUBLISHER_USER']
)
if (@($appDatabaseRoles | Sort-Object -Unique).Count -ne $appDatabaseRoles.Count) {
    throw 'App PostgreSQL runtime, migration, and catalog publisher roles must differ.'
}

foreach ($fileKey in @(
    'TRINO_PASSWORD_DB_HOST_FILE', 'TRINO_TLS_KEYSTORE_HOST_FILE',
    'TRINO_TLS_CA_HOST_FILE', 'DATAHUB_TLS_KEYSTORE_HOST_FILE',
    'DATAHUB_TLS_TRUSTSTORE_HOST_FILE', 'DATAHUB_TLS_CA_HOST_FILE',
    'SERVING_CATALOG_BOOTSTRAP_CREDENTIALS_HOST_FILE',
    'SERVING_CATALOG_TOKEN_PUBLIC_KEY_HOST_FILE',
    'SERVING_CATALOG_TOKEN_PRIVATE_KEY_HOST_FILE'
)) {
    Assert-ExplicitDeploymentFile -Values $deploymentEnvironment `
        -Key $fileKey -RepositoryRoot $repoRoot `
        -AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment | Out-Null
}

$trinoIdentities = [ordered]@{
    TRINO_ADMIN_USER = 'answervice_platform_admin'
    TRINO_RUNTIME_USER = 'answervice_runtime'
    TRINO_DATAHUB_USER = 'datahub_ingestion'
}
foreach ($entry in $trinoIdentities.GetEnumerator()) {
    if ([string]$deploymentEnvironment[$entry.Key] -cne $entry.Value) {
        throw "Deployment environment key '$($entry.Key)' does not match the Trino ACL identity."
    }
}

$boundedSecrets = @(
    'APP_CATALOG_PUBLISHER_PASSWORD',
    'TRINO_ADMIN_PASSWORD', 'TRINO_RUNTIME_PASSWORD', 'TRINO_DATAHUB_PASSWORD',
    'TRINO_TLS_KEYSTORE_PASSWORD', 'DATAHUB_SYSTEM_CLIENT_SECRET',
    'DATAHUB_TLS_KEYSTORE_PASSWORD', 'DATAHUB_TLS_TRUSTSTORE_PASSWORD',
    'SERVING_CATALOG_DB_PASSWORD', 'SERVING_CATALOG_ADMIN_CLIENT_SECRET',
    'SERVING_OBJECT_STORE_SECRET_KEY'
)
if ($Stage -eq 'Catalog') {
    $boundedSecrets += @('DATAHUB_READ_API_TOKEN', 'DATAHUB_PUBLISH_API_TOKEN')
}
foreach ($secretKey in $boundedSecrets) {
    if (([string]$deploymentEnvironment[$secretKey]).Length -lt 12) {
        throw "Deployment environment key '$secretKey' must contain at least 12 characters."
    }
}
if (([string]$deploymentEnvironment['TRINO_INTERNAL_SHARED_SECRET']).Length -lt 32) {
    throw 'TRINO_INTERNAL_SHARED_SECRET must contain at least 32 characters.'
}
if (([string]$deploymentEnvironment['SERVING_CATALOG_DB_PASSWORD']).Length -lt 16 -or
    ([string]$deploymentEnvironment['SERVING_CATALOG_ADMIN_CLIENT_SECRET']).Length -lt 24 -or
    ([string]$deploymentEnvironment['SERVING_OBJECT_STORE_SECRET_KEY']).Length -lt 24) {
    throw 'Serving persistence secrets do not meet the minimum length contract.'
}
if ($Stage -eq 'Catalog') {
    $readActor = [string]$deploymentEnvironment['DATAHUB_READ_ACTOR_URN']
    $publishActor = [string]$deploymentEnvironment['DATAHUB_PUBLISH_ACTOR_URN']
    if (-not $readActor.StartsWith('urn:li:corpuser:service_') -or
        -not $publishActor.StartsWith('urn:li:corpuser:service_')) {
        throw 'DataHub actor URNs must identify provisioned service accounts.'
    }
    if ($readActor -ceq $publishActor) {
        throw 'DataHub read and publish actors must differ.'
    }
    if ([string]$deploymentEnvironment['DATAHUB_READ_API_TOKEN'] -ceq
        [string]$deploymentEnvironment['DATAHUB_PUBLISH_API_TOKEN']) {
        throw 'DataHub read and publish tokens must differ.'
    }
}

# Core compose에는 PAT consumer를 포함하지 않아 clean MySQL에서 bootstrap 순환 의존이
# 생기지 않는다. Catalog는 metadata ingestion profile만 결합하며 semantic overlay를
# 자동으로 활성화하지 않는다.
$activeComposeFiles = @($composeFile, $dataHubComposeFile)
$activeProfiles = @('full')
if ($Stage -eq 'Catalog') {
    $activeComposeFiles += $dataHubIngestionFile
    $activeProfiles += 'metadata-ingestion'
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    $fixedArguments = @()
    foreach ($file in $activeComposeFiles) {
        $fixedArguments += @('-f', $file)
    }
    foreach ($profile in $activeProfiles) {
        $fixedArguments += @('--profile', $profile)
    }
    $previousBuildContext = $env:SEMANTIC_PRODUCER_BUILD_CONTEXT
    $env:SEMANTIC_PRODUCER_BUILD_CONTEXT = $repoRoot
    try {
        & docker compose @composeEnvArguments @fixedArguments @Arguments
    } finally {
        $env:SEMANTIC_PRODUCER_BUILD_CONTEXT = $previousBuildContext
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose command failed; inspect service logs without printing credentials.'
    }
}

Invoke-Compose config --quiet
$coreServices = @(
    'app-postgres', 'pms-postgres', 'banquet-postgres', 'pos-mysql',
    'crm-mssql', 'facility-clickhouse', 'serving-catalog', 'trino',
    'datahub-gms-quickstart'
)
$coreStartupServices = @($coreServices + 'system-update-quickstart')

if ($Stage -eq 'Catalog') {
    # Catalog는 Core 완료 후에만 실행한다. 누락된 Core를 암묵적으로 다시 만들면
    # operator가 token provisioning 단계를 건너뛴 사실을 READY로 오인할 수 있다.
    $runningServices = @(Invoke-Compose ps --status running --services)
    $missingCore = @($coreServices | Where-Object { $_ -notin $runningServices })
    if ($missingCore.Count) {
        throw 'Core stage is not running; run start.ps1 -Stage Core first.'
    }

    # Catalog refresh는 현재 기본 search backend를 유지한다. metadata 발행을 위해
    # GMS를 준비하되 embedding service나 vector index를 암묵적으로 기동하지 않는다.
    Invoke-Compose up --detach --wait --wait-timeout 1800 datahub-gms-quickstart

    # runtime recipe는 directory에서 동적으로 발견된다. 어느 source든 실패하면
    # one-shot이 non-zero로 끝나며 metadata 완료 marker를 출력하지 않는다.
    Invoke-Compose up --detach --force-recreate datahub-ingestion
    # `compose up --wait`는 one-shot이 아직 실행 중인 상태도 준비 완료로 본다.
    # 실제 process exit code를 기다려 부분 발행이나 403을 READY로 오인하지 않는다.
    $ingestionContainer = @(Invoke-Compose ps --all --quiet datahub-ingestion)
    if ($ingestionContainer.Count -ne 1) {
        throw 'DataHub metadata ingestion container was not created uniquely.'
    }
    $ingestionExit = & docker wait $ingestionContainer[0]
    if ($LASTEXITCODE -ne 0 -or [string]$ingestionExit -cne '0') {
        throw 'DataHub metadata ingestion failed; inspect its masked logs.'
    }
    $completionLogs = @(& docker logs --tail 20 $ingestionContainer[0] 2>&1)
    if ($LASTEXITCODE -ne 0 -or
        'ANSWERVICE_RUNTIME_CATALOG_INGESTION_COMPLETE' -notin $completionLogs) {
        throw 'DataHub metadata ingestion exited without its completion marker.'
    }
    Invoke-Compose up --detach --wait --wait-timeout 1800 `
        datahub-actions-quickstart frontend-quickstart
    # Base ingestion 성공은 semantic release 활성화가 아니다. 운영자는 동일 stdin policy로
    # author_semantic_catalog.py --check를 수행하고, exact predecessor/target checksum 승인 뒤
    # --publish의 PUBLISHED_AND_VERIFIED receipt를 받아야 backend readiness를 열 수 있다.
    Write-Output 'DATABASE_BASE_METADATA_INGESTED|catalog_ready=false|next=SEMANTIC_CHECK'
    return
}

# Polaris와 object store를 먼저 준비한 뒤 management API에서 Trino 전용 principal을
# 멱등 구성한다. 발급 credential을 동일 env file에 원자적으로 결속한 다음에야 Trino
# container를 생성하므로, bootstrap admin identity가 query runtime으로 새지 않는다.
Invoke-Compose up --detach --wait --wait-timeout 300 serving-catalog
if ($resolvedEnvFile) {
    $initializerArguments = @(
        (Join-Path $PSScriptRoot 'initialize_serving_catalog.py'),
        '--env-file', $resolvedEnvFile
    )
    if ($AllowRepositoryLocalDevelopment) {
        $initializerArguments += '--allow-repository-local-development'
    }
    & python @initializerArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Polaris serving catalog initialization failed.'
    }
    $deploymentEnvironment = Read-DeploymentEnvironment $resolvedEnvFile
}
Assert-DeploymentEnvironmentValues -Values $deploymentEnvironment -RequiredKeys @(
    'SERVING_CATALOG_TRINO_CLIENT_ID', 'SERVING_CATALOG_TRINO_CLIENT_SECRET'
)
if (([string]$deploymentEnvironment['SERVING_CATALOG_TRINO_CLIENT_SECRET']).Length -lt 16) {
    throw 'SERVING_CATALOG_TRINO_CLIENT_SECRET must contain at least 16 characters.'
}
Invoke-Compose config --quiet

# GMS가 healthy가 된 뒤에만 SystemUpdate가 policy/schema registry를 초기화한다.
# one-shot 성공까지 기다려야 이후 Catalog 단계가 반쯤 초기화된 control plane을 쓰지 않는다.
Invoke-Compose up --detach --wait --wait-timeout 1800 @coreStartupServices
Invoke-Compose exec -T app-postgres sh /security/provision-app-postgres.sh
Invoke-Compose exec -T pms-postgres sh /security/provision-source-postgres.sh
Invoke-Compose exec -T banquet-postgres sh /security/provision-source-postgres.sh
Invoke-Compose exec -T pos-mysql sh /security/provision-pos-mysql.sh
Invoke-Compose exec -T crm-mssql sh /security/provision-crm-mssql.sh
Invoke-Compose exec -T facility-clickhouse sh /security/provision-facility-clickhouse.sh

# Docker의 `--env NAME`은 secret을 argv에 넣지 않는다. probe 후 기존 process 값을
# 복원하여 호출자 세션에도 credential을 남기지 않는다.
$trinoReady = $false
$previousProbeUser = $env:TRINO_PROBE_USER
$previousProbePassword = $env:TRINO_PROBE_PASSWORD
$env:TRINO_PROBE_USER = [string]$deploymentEnvironment['TRINO_ADMIN_USER']
$env:TRINO_PROBE_PASSWORD = [string]$deploymentEnvironment['TRINO_ADMIN_PASSWORD']
try {
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-Compose exec -T `
                --env TRINO_PROBE_USER --env TRINO_PROBE_PASSWORD `
                trino sh -ec 'auth=$(printf "%s:%s" "$TRINO_PROBE_USER" "$TRINO_PROBE_PASSWORD" | base64 | tr -d "\r\n"); printf "header = \"Authorization: Basic %s\"\n" "$auth" | curl --config - --fail --silent --show-error --cacert /run/secrets/trino-ca.pem --header "X-Trino-User: $TRINO_PROBE_USER" --header "Content-Type: text/plain" --data-binary "SELECT 1" https://trino:8443/v1/statement'
            $probe = ($response -join "`n") | ConvertFrom-Json
            if ($probe.error -or -not $probe.id) {
                throw 'Authenticated Trino statement probe did not return a query id.'
            }
            $trinoReady = $true
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }
} finally {
    $env:TRINO_PROBE_USER = $previousProbeUser
    $env:TRINO_PROBE_PASSWORD = $previousProbePassword
}
if (-not $trinoReady) {
    throw 'Trino did not become query-ready within 120 seconds.'
}

# UI와 Actions는 system client 계약으로 GMS에 연결되므로 PAT 발급 전에도 시작할 수
# 있다. Core는 전체 readiness가 아니며 아래 marker로 다음 operator 단계를 명시한다.
Invoke-Compose up --detach --wait --wait-timeout 1800 `
    datahub-actions-quickstart frontend-quickstart
Write-Output 'DATABASE_CORE_READY|next=PROVISION_DATAHUB_SERVICE_TOKENS'
