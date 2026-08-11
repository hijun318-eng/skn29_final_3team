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
    Assert-RuntimeIdentity `
        -Inventory @(ConvertFrom-Json -InputObject $RuntimeInventoryJson) `
        -ExpectedProject 'answervice' `
        -ExpectedRoot $root `
        -ExpectedCompose (Join-Path $root 'compose.yml') `
        -ExpectedEnv (Resolve-Path -LiteralPath $EnvFilePath -ErrorAction Stop).Path
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

$envFile = (Resolve-Path -LiteralPath $EnvFilePath -ErrorAction Stop).Path
$composeFile = (Resolve-Path -LiteralPath 'compose.yml' -ErrorAction Stop).Path
$projectName = (& docker compose -f $composeFile --env-file $envFile --profile dev config --format json | ConvertFrom-Json).name
if ($LASTEXITCODE -ne 0 -or -not $projectName) { throw 'Compose project identity를 확인하지 못했습니다.' }
$inventory = @()
foreach ($service in @('app-postgres', 'backend', 'frontend')) {
    $containerIds = @(& docker compose -f $composeFile --env-file $envFile --profile dev ps -q $service)
    if ($LASTEXITCODE -ne 0 -or $containerIds.Count -ne 1) { throw "runtime identity service count mismatch: $service" }
    $labels = & docker inspect --format '{{json .Config.Labels}}' $containerIds[0] | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $labels) { throw "runtime identity label을 확인하지 못했습니다: $service" }
    $inventory += [pscustomobject]@{ service = $service; labels = $labels }
}
Assert-RuntimeIdentity $inventory $projectName $root $composeFile $envFile
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
