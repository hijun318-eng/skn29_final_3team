# 책임: Trino `serving` catalog의 분석 View를 현재 런타임 인증 계약으로 재생성한다.
# `serving`은 memory connector이므로 Trino를 재시작하면 View가 사라진다. 이 스크립트는
# release 아카이브의 SQL을 원본 그대로 사용하되, 실행 경로만 현재 운영 계약(HTTPS,
# password 인증, 현재 compose project)에 맞춘다.
#
# 아카이브의 `run-v43.ps1`을 쓰지 않는 이유는 두 가지다. 첫째, 그 스크립트는 release
# manifest에 sha256으로 고정된 불변 기록이라 수정 대상이 아니다. 둘째, 그 안의 실행
# 경로는 컨테이너 이름 `hotel-synthetic-db-trino-1`과 무인증 HTTP(`--server
# http://localhost:8080`)를 가정하는데 현재 런타임은 둘 다 다르다.
[CmdletBinding()]
param(
    [string]$EnvFilePath,
    # 검증 SQL까지 함께 실행해 cross-source 무결성을 확인한다.
    [switch]$IncludeValidation
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $databaseRoot 'compose.yml'
# 아카이브 경로에는 한글 디렉터리명이 있다. 스크립트 파일 인코딩에 따라 리터럴 비교가
# 깨질 수 있으므로 이름을 직접 적지 않고 릴리스 폴더에서 `06_trino_serving`을 찾아 쓴다.
$releaseRoot = Join-Path $databaseRoot 'releases/walkerhill_v4_3_20260815_derived_1'
$servingSqlRoot = (
    Get-ChildItem -LiteralPath $releaseRoot -Directory -Recurse -Filter '06_trino_serving' |
    Select-Object -First 1
).FullName
if (-not $servingSqlRoot) {
    throw "serving SQL directory was not found under $releaseRoot"
}
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$values = Read-DeploymentEnvironment $resolvedEnvFile
Assert-DeploymentEnvironmentValues -Values $values -RequiredKeys @(
    'TRINO_ADMIN_USER', 'TRINO_ADMIN_PASSWORD'
)

# View 생성은 순서에 의존한다. schema가 먼저 있어야 하고, 통합 View는 도메인 View를
# 참조하므로 파일 순서를 임의로 바꾸면 실패한다.
$viewFiles = @(
    '10_trino_serving_schema.sql',
    '20_trino_room_views.sql',
    '21_trino_fnb_views.sql',
    '22_trino_membership_views.sql',
    '23_trino_banquet_views.sql',
    '24_trino_facility_views.sql',
    '25_trino_integrated_hotel_views.sql',
    '26_trino_voc_views.sql'
)
$validationFiles = @(
    '30_trino_cross_source_validation.sql',
    '31_trino_event_counterfactual_validation.sql'
)

# docker compose는 진행 상황을 stderr로 출력한다. 최상위 $ErrorActionPreference='Stop'
# 아래에서는 그 줄 하나하나가 NativeCommandError로 승격되어 exit 0인 호출도 종료시키므로,
# 성공 여부는 $LASTEXITCODE로만 판단하고 stderr 승격은 이 경계에서만 끈다.
function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & docker compose @composeEnvArguments -f $composeFile @Arguments 2>&1 |
            Where-Object { $_ -isnot [Management.Automation.ErrorRecord] }
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose command failed; inspect the Trino service logs.'
    }
    return $output
}

# 비밀번호는 argv가 아니라 process environment로만 전달한다. Trino CLI는 TRINO_PASSWORD를
# 읽으므로 `--password`에 값을 붙이지 않는다.
function Invoke-TrinoSqlFile {
    param([Parameter(Mandatory)] [string]$FileName)

    $localPath = Join-Path $servingSqlRoot $FileName
    if (-not (Test-Path -LiteralPath $localPath)) {
        throw "serving SQL file is missing: $FileName"
    }
    Invoke-Compose -Arguments @('cp', $localPath, 'trino:/tmp/serving_current.sql') | Out-Null

    $previousPassword = $env:TRINO_PASSWORD
    $env:TRINO_PASSWORD = [string]$values['TRINO_ADMIN_PASSWORD']
    try {
        $output = Invoke-Compose -Arguments @(
            'exec', '-T', '--env', 'TRINO_PASSWORD', 'trino',
            'trino', '--server', 'https://localhost:8443',
            '--user', [string]$values['TRINO_ADMIN_USER'], '--password',
            '--truststore-path', '/run/secrets/trino-ca.pem',
            '--output-format', 'CSV', '--file', '/tmp/serving_current.sql'
        )
    } finally {
        $env:TRINO_PASSWORD = $previousPassword
    }

    $text = ($output -join "`n")
    # 검증 SQL은 실패를 exit code가 아니라 결과 행의 FAIL 문자열로 알린다.
    if ($text -match '(?m)"FAIL"') {
        throw "serving SQL reported FAIL: $FileName"
    }
    Write-Output "SERVING_SQL_APPLIED|$FileName"
}

# 기대 View 수는 상수로 적지 않고 이번에 실제 실행한 SQL에서 센다. 파일이 늘거나 줄면
# 기대치도 함께 따라가므로 검증이 낡지 않는다.
function Get-DeclaredViewCount {
    param([Parameter(Mandatory)] [string[]]$FileNames)

    $total = 0
    foreach ($name in $FileNames) {
        $text = Get-Content -LiteralPath (Join-Path $servingSqlRoot $name) -Raw
        $total += ([regex]::Matches($text, '(?im)^\s*CREATE\s+(OR\s+REPLACE\s+)?VIEW\s')).Count
    }
    return $total
}

$appliedFiles = @($viewFiles)
foreach ($file in $viewFiles) {
    Invoke-TrinoSqlFile -FileName $file
}
if ($IncludeValidation) {
    foreach ($file in $validationFiles) {
        Invoke-TrinoSqlFile -FileName $file
    }
    $appliedFiles += $validationFiles
}

# 생성 직후 실제 relation 수를 인증 경로로 다시 읽어, 빈 catalog나 일부 누락을 성공으로
# 보고하지 않는다. memory connector는 재시작으로 조용히 비므로 read-back이 유일한 증거다.
$expectedViews = Get-DeclaredViewCount -FileNames $appliedFiles
$countSql = @'
SELECT count(*) FROM serving.information_schema.tables
WHERE table_schema <> 'information_schema';
'@
$countPath = Join-Path ([IO.Path]::GetTempPath()) "serving-view-count-$PID.sql"
[IO.File]::WriteAllText($countPath, ($countSql -replace "`r`n", "`n"), [Text.UTF8Encoding]::new($false))
try {
    Invoke-Compose -Arguments @('cp', $countPath, 'trino:/tmp/serving_count.sql') | Out-Null
} finally {
    Remove-Item -LiteralPath $countPath -Force -ErrorAction SilentlyContinue
}

$previousPassword = $env:TRINO_PASSWORD
$env:TRINO_PASSWORD = [string]$values['TRINO_ADMIN_PASSWORD']
try {
    $countOutput = Invoke-Compose -Arguments @(
        'exec', '-T', '--env', 'TRINO_PASSWORD', 'trino',
        'trino', '--server', 'https://localhost:8443',
        '--user', [string]$values['TRINO_ADMIN_USER'], '--password',
        '--truststore-path', '/run/secrets/trino-ca.pem',
        '--output-format', 'CSV', '--file', '/tmp/serving_count.sql'
    )
} finally {
    $env:TRINO_PASSWORD = $previousPassword
}

$observed = [int](($countOutput -join "`n") -replace '[^0-9]', '')
if ($observed -lt $expectedViews) {
    throw "serving catalog has $observed relations but $expectedViews views were declared."
}
Write-Output "SERVING_VIEWS_RECREATED|$observed"
