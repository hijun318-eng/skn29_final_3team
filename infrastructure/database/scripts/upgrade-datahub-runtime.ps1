[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$EnvFilePath,
    [switch]$InitializeSecrets,
    [switch]$Start
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $repoRoot 'compose.yml'
$envFile = if ($EnvFilePath) { $EnvFilePath } else { Join-Path $databaseRoot '.env' }
$project = 'hotel-synthetic-db'
$services = @(
    'kafka-broker', 'mysql', 'opensearch', 'system-update-quickstart',
    'datahub-gms-quickstart', 'datahub-actions-quickstart', 'frontend-quickstart'
)
$secretKeys = @(
    'DATAHUB_SECRET', 'DATAHUB_MYSQL_PASSWORD', 'DATAHUB_MYSQL_ROOT_PASSWORD',
    'DATAHUB_TOKEN_SERVICE_SALT', 'DATAHUB_TOKEN_SERVICE_SIGNING_KEY'
)

function Read-Env([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

function New-Secret {
    $bytes = [byte[]]::new(48)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes)
}

if (-not (Test-Path -LiteralPath $envFile)) { throw 'Local database env file is missing.' }
$env = Read-Env $envFile
if ($InitializeSecrets) {
    foreach ($key in $secretKeys) {
        if (-not $env.ContainsKey($key) -or $env[$key].Length -lt 32) {
            [IO.File]::AppendAllText($envFile, "`n$key=$(New-Secret)", [Text.UTF8Encoding]::new($false))
        }
    }
    $env = Read-Env $envFile
}
if (@($secretKeys | Where-Object { -not $env.ContainsKey($_) -or $env[$_].Length -lt 32 }).Count) {
    throw 'DataHub local secrets are missing or shorter than 32 characters.'
}

& docker compose --env-file $envFile -f $composeFile --profile full config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose config validation failed.' }

$targetContainers = @(docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}}') |
    Where-Object { $_ -match 'datahub|kafka-broker|opensearch' -or $_ -eq "$project-mysql-1" }
$allowedContainers = @($services | ForEach-Object { "$project-$_-1" })
if (@($targetContainers | Where-Object { $_ -notin $allowedContainers }).Count) {
    throw 'Unexpected container exists in the target DataHub service set.'
}

$volumeNames = @(
    "${project}_datahub-kafka-data", "${project}_datahub-mysql-data",
    "${project}_datahub-opensearch-data"
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

foreach ($name in @('kafka-broker', 'mysql', 'opensearch')) {
    if ($PSCmdlet.ShouldProcess($name, 'Start DataHub dependency')) {
        & docker compose --env-file $envFile -f $composeFile --profile full up -d --wait $name
        if ($LASTEXITCODE -ne 0) { throw "DataHub dependency failed: $name" }
    }
}
if ($PSCmdlet.ShouldProcess('system-update-quickstart', 'Run DataHub system update')) {
    & docker compose --env-file $envFile -f $composeFile --profile full run --rm system-update-quickstart
    if ($LASTEXITCODE -ne 0) { throw 'DataHub system update failed.' }
}
foreach ($name in @('datahub-gms-quickstart', 'datahub-actions-quickstart', 'frontend-quickstart')) {
    if ($PSCmdlet.ShouldProcess($name, 'Start DataHub service')) {
        & docker compose --env-file $envFile -f $composeFile --profile full up -d --wait $name
        if ($LASTEXITCODE -ne 0) { throw "DataHub service failed: $name" }
    }
}
Write-Output 'DATAHUB_RUNTIME_HEALTHY'
