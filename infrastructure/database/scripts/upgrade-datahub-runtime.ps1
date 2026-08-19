# 책임: DataHub v1.7 dependency를 backup·resource·secret 사전조건 이후 순서대로
# 전환한다. 기존 volume이나 부족한 memory가 확인되면 mutation 전에 차단한다.
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$EnvFilePath,
    [switch]$Start
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $repoRoot 'compose.yml'
$semanticComposeFile = Join-Path $databaseRoot 'datahub/compose.semantic-search.yml'
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$envFile = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $envFile)
$services = @(
    'kafka-broker', 'mysql', 'semantic-elasticsearch', 'ollama',
    'ollama-model-bootstrap', 'system-update-quickstart',
    'datahub-gms-quickstart', 'datahub-ingestion',
    'dataset-semantic-content-bootstrap',
    'datahub-actions-quickstart', 'frontend-quickstart'
)
$secretKeys = @(
    'DATAHUB_SECRET', 'DATAHUB_MYSQL_PASSWORD', 'DATAHUB_MYSQL_ROOT_PASSWORD',
    'DATAHUB_TOKEN_SERVICE_SALT', 'DATAHUB_TOKEN_SERVICE_SIGNING_KEY',
    'DATAHUB_SECRET_SERVICE_ENCRYPTION_KEY', 'DATAHUB_SYSTEM_CLIENT_SECRET',
    'DATAHUB_READ_API_TOKEN', 'DATAHUB_READ_ACTOR_URN',
    'DATAHUB_PUBLISH_API_TOKEN', 'DATAHUB_PUBLISH_ACTOR_URN',
    'DATAHUB_TLS_KEYSTORE_PASSWORD',
    'DATAHUB_TLS_TRUSTSTORE_PASSWORD'
)

# semantic overlay를 항상 root Compose와 결합하고 실패 exit code를 즉시 전파한다.
function Invoke-DataHubCompose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    & docker compose @composeEnvArguments `
        -f $composeFile -f $semanticComposeFile `
        --profile full --profile semantic-search @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Semantic DataHub Compose failed; inspect logs without printing arguments.'
    }
}

$env = Read-DeploymentEnvironment $envFile
$project = [string]$env['COMPOSE_PROJECT_NAME']
if (-not $project -or $project -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]+$') {
    throw 'COMPOSE_PROJECT_NAME must be an explicit valid project identifier.'
}
Assert-DeploymentEnvironmentValues -Values $env -RequiredKeys $secretKeys
foreach ($fileKey in @(
    'DATAHUB_TLS_KEYSTORE_HOST_FILE', 'DATAHUB_TLS_TRUSTSTORE_HOST_FILE',
    'DATAHUB_TLS_CA_HOST_FILE'
)) {
    Assert-ExternalDeploymentFile -Values $env -Key $fileKey `
        -RepositoryRoot $repoRoot | Out-Null
}

Invoke-DataHubCompose config --quiet

$targetContainers = @(docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}}') |
    Where-Object {
        $_ -match 'datahub|kafka-broker|semantic-elasticsearch|ollama' -or
        $_ -eq "$project-mysql-1"
    }
$allowedContainers = @($services | ForEach-Object { "$project-$_-1" })
if (@($targetContainers | Where-Object { $_ -notin $allowedContainers }).Count) {
    throw 'Unexpected container exists in the target DataHub service set.'
}

$volumeNames = @(
    "${project}_datahub-kafka-data", "${project}_datahub-mysql-data",
    "${project}_datahub-semantic-elasticsearch-data", "${project}_datahub-ollama-data"
)
$existingVolumes = @(docker volume ls --filter "label=com.docker.compose.project=$project" --format '{{.Name}}') |
    Where-Object { $_ -in $volumeNames }
$backupStatus = if ($existingVolumes.Count) { 'REQUIRED_BEFORE_MUTATION' } else { 'BACKUP_NOT_APPLICABLE_NEW_RUNTIME' }
$freeGb = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)
$resourceStatus = if ($freeGb -ge 8) { 'READY' } else { 'BLOCKED_INSUFFICIENT_MEMORY' }

[ordered]@{
    project = $project
    datahub_version = 'v1.7.0'
    target_container_count = $targetContainers.Count
    target_volume_count = $existingVolumes.Count
    backup_status = $backupStatus
    free_memory_gb = $freeGb
    resource_status = $resourceStatus
    secret_readiness = 'READY'
} | ConvertTo-Json -Compress

if (-not $Start) { exit 0 }
if ($resourceStatus -ne 'READY') { throw 'At least 8 GB free host memory is required before DataHub start.' }
if ($existingVolumes.Count) { throw 'Existing target volumes require a verified backup before start.' }

foreach ($name in @('kafka-broker', 'mysql', 'semantic-elasticsearch', 'ollama')) {
    if ($PSCmdlet.ShouldProcess($name, 'Start DataHub dependency')) {
        Invoke-DataHubCompose up -d --wait $name
    }
}
if ($PSCmdlet.ShouldProcess('ollama-model-bootstrap', 'Pull pinned DataHub embedding model tag')) {
    Invoke-DataHubCompose run --rm ollama-model-bootstrap
}
if ($PSCmdlet.ShouldProcess('system-update-quickstart', 'Run DataHub system update')) {
    Invoke-DataHubCompose run --rm system-update-quickstart
}
foreach ($name in @('datahub-gms-quickstart', 'datahub-actions-quickstart', 'frontend-quickstart')) {
    if ($PSCmdlet.ShouldProcess($name, 'Start DataHub service')) {
        Invoke-DataHubCompose up -d --wait $name
    }
}
Write-Output 'DATAHUB_RUNTIME_HEALTHY'
