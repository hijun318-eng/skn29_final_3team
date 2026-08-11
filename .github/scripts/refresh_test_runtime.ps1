[CmdletBinding()]
param(
    [string]$BaseRef = 'ORIG_HEAD',
    [string]$HeadRef = 'HEAD',
    [string]$EnvFilePath = '.env',
    [string[]]$ChangedPaths = @(),
    [string]$ChangedPathsJson = '',
    [string]$RuntimeInventoryJson = '',
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'

function Resolve-ApprovedEnvFile {
    param([string]$Path)
    if (-not [System.IO.Path]::IsPathFullyQualified($Path)) {
        throw 'test env path must be absolute'
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer) { throw 'test env path must be a regular file' }
    return $item.FullName
}

function Assert-RequiredEnvNames {
    param([string]$Path)
    $required = @(
        'COMPOSE_PROJECT_NAME', 'APP_DB_NAME', 'APP_ADMIN_USER',
        'APP_ADMIN_PASSWORD', 'APP_MIGRATION_USER', 'APP_MIGRATION_PASSWORD',
        'APP_DB_USER', 'APP_DB_PASSWORD', 'APP_DATABASE_URL'
    )
    $present = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=.+$') { $present[$Matches[1]] = $true }
    }
    $missing = @($required | Where-Object { -not $present.ContainsKey($_) })
    if ($missing.Count) {
        throw "required env variable names are missing: $($missing -join ', ')"
    }
}

function Assert-NoRuntimeConflict {
    param([hashtable]$ExpectedContainers)
    foreach ($entry in $ExpectedContainers.GetEnumerator()) {
        $conflicts = @(& docker ps -aq --filter "name=^/$($entry.Key)$")
        if ($LASTEXITCODE -ne 0) { throw 'container conflict inventory failed' }
        if (@($conflicts | Where-Object { $_ -ne $entry.Value }).Count) {
            throw "fixed container name conflict: $($entry.Key)"
        }
    }
    foreach ($port in @(15432, 28000, 13000)) {
        $conflicts = @(& docker ps -q --filter "publish=$port")
        if ($LASTEXITCODE -ne 0) { throw 'port conflict inventory failed' }
        if (@($conflicts | Where-Object { $_ -notin $ExpectedContainers.Values }).Count) {
            throw "fixed port conflict: $port"
        }
    }
}

function Get-RefreshPlan {
    param([string[]]$Paths)

    $normalized = @($Paths | ForEach-Object { $_.Replace('\', '/').TrimStart('./') } | Where-Object { $_ })
    $manual = @($normalized | Where-Object {
        $_ -in @('compose.yml', 'compose.app-postgres.override.yml', '.env.example') -or
        $_ -like 'infrastructure/*'
    })
    $frontend = @($normalized | Where-Object { $_ -like 'app/enterprise-react/*' })
    $backend = @($normalized | Where-Object {
        $_ -like 'app/backend/*' -or $_ -like 'src/*' -or $_ -like 'config/*'
    })

    if ($manual.Count) {
        return [ordered]@{ action = 'manual-review'; services = @(); paths = $normalized }
    }

    $services = @()
    if ($backend.Count) { $services += 'backend' }
    if ($frontend.Count) { $services += 'frontend' }
    return [ordered]@{
        action = $(if ($services.Count) { 'refresh' } else { 'no-op' })
        services = $services
        paths = $normalized
    }
}

function Assert-RuntimeIdentity {
    param(
        [object[]]$Inventory,
        [string]$ExpectedProject,
        [string]$ExpectedRoot,
        [string]$ExpectedCompose,
        [string]$ExpectedEnv
    )

    $expected = @{
        'com.docker.compose.project' = $ExpectedProject
        'com.docker.compose.project.working_dir' = $ExpectedRoot
        'com.docker.compose.project.config_files' = $ExpectedCompose
        'com.docker.compose.project.environment_file' = $ExpectedEnv
    }
    foreach ($service in @('app-postgres', 'backend', 'frontend')) {
        $matches = @($Inventory | Where-Object { $_.service -eq $service })
        if ($matches.Count -ne 1) { throw "runtime identity service count mismatch: $service" }
        foreach ($entry in $expected.GetEnumerator()) {
            $actual = $matches[0].labels.PSObject.Properties[$entry.Key].Value
            $matchesExpected = if ($entry.Key -eq 'com.docker.compose.project') {
                [System.StringComparer]::Ordinal.Equals($actual, $entry.Value)
            } else {
                $actual -and [System.StringComparer]::OrdinalIgnoreCase.Equals(
                    [System.IO.Path]::GetFullPath($actual).TrimEnd('\', '/'),
                    [System.IO.Path]::GetFullPath($entry.Value).TrimEnd('\', '/')
                )
            }
            if (-not $matchesExpected) {
                throw "runtime identity mismatch: service=$service label=$($entry.Key) expected=$($entry.Value) actual=$actual"
            }
        }
    }
}

$root = (& git rev-parse --show-toplevel 2>$null).Trim()
if (-not $root) { throw 'Repository root를 확인할 수 없습니다.' }
Set-Location -LiteralPath $root

if ($RuntimeInventoryJson) {
    $resolvedEnv = Resolve-ApprovedEnvFile $EnvFilePath
    Assert-RequiredEnvNames $resolvedEnv
    Assert-RuntimeIdentity `
        -Inventory @(ConvertFrom-Json -InputObject $RuntimeInventoryJson) `
        -ExpectedProject 'answervice' `
        -ExpectedRoot $root `
        -ExpectedCompose (Join-Path $root 'compose.yml') `
        -ExpectedEnv $resolvedEnv
    Write-Output 'RUNTIME_IDENTITY_OK'
    exit 0
}

if ($ChangedPathsJson) {
    $ChangedPaths = @(ConvertFrom-Json -InputObject $ChangedPathsJson)
}
if (-not $ChangedPaths.Count) {
    $ChangedPaths = @(& git diff --name-only --diff-filter=ACMR $BaseRef $HeadRef --)
    if ($LASTEXITCODE -ne 0) { throw '변경 경로를 확인하지 못했습니다.' }
}

$plan = Get-RefreshPlan -Paths $ChangedPaths
if ($PlanOnly) {
    $plan | ConvertTo-Json -Compress
    exit $(if ($plan.action -eq 'manual-review') { 2 } else { 0 })
}

if ((& git branch --show-current).Trim() -ne 'test') {
    throw 'test branch에서만 runtime을 갱신할 수 있습니다.'
}
if (& git status --short) {
    throw 'Dirty worktree에서는 runtime을 갱신하지 않습니다.'
}
if ($plan.action -eq 'manual-review') {
    throw 'Compose, env 또는 stateful infrastructure 변경은 수동 검토가 필요합니다.'
}
if ($plan.action -eq 'no-op') {
    Write-Output 'No runtime-owned paths changed; containers were not touched.'
    exit 0
}

$envFile = Resolve-ApprovedEnvFile $EnvFilePath
Assert-RequiredEnvNames $envFile
$composeFile = (Resolve-Path -LiteralPath 'compose.yml' -ErrorAction Stop).Path
$projectName = (& docker compose -f $composeFile --env-file $envFile --profile dev config --format json | ConvertFrom-Json).name
if ($LASTEXITCODE -ne 0 -or -not $projectName) { throw 'Compose project identity를 확인하지 못했습니다.' }
$inventory = @()
$expectedContainers = @{}
foreach ($service in @('app-postgres', 'backend', 'frontend')) {
    $containerIds = @(& docker compose -f $composeFile --env-file $envFile --profile dev ps -q $service)
    if ($LASTEXITCODE -ne 0 -or $containerIds.Count -ne 1) { throw "runtime identity service count mismatch: $service" }
    $labels = & docker inspect --format '{{json .Config.Labels}}' $containerIds[0] | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $labels) { throw "runtime identity label을 확인하지 못했습니다: $service" }
    $inventory += [pscustomobject]@{ service = $service; labels = $labels }
    $expectedName = @{ 'app-postgres' = 'app-postgres'; 'backend' = 'answervice-backend'; 'frontend' = 'answervice-frontend' }[$service]
    $expectedContainers[$expectedName] = $containerIds[0]
}
Assert-RuntimeIdentity $inventory $projectName $root $composeFile $envFile
Assert-NoRuntimeConflict $expectedContainers
$running = @(& docker compose -f compose.yml --env-file $envFile --profile dev ps --status running --services)
if ($LASTEXITCODE -ne 0) { throw 'Compose runtime inventory를 확인하지 못했습니다.' }
foreach ($service in $plan.services) {
    if ($service -notin $running) { throw "필수 service가 실행 중이 아닙니다: $service" }
}

& docker compose -f compose.yml --env-file $envFile --profile dev up -d --build --no-deps --wait @($plan.services)
if ($LASTEXITCODE -ne 0) { throw '선택 service 재기동 또는 health 검증에 실패했습니다.' }

if ('backend' -in $plan.services) {
    Invoke-RestMethod -Uri 'http://127.0.0.1:28000/health' -TimeoutSec 5 | Out-Null
}
if ('frontend' -in $plan.services) {
    Invoke-RestMethod -Uri 'http://127.0.0.1:13000/health' -TimeoutSec 5 | Out-Null
}

$plan | ConvertTo-Json -Compress
