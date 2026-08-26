# 책임: release manifest의 분석 View를 선택한 serving namespace에 멱등 발행한다.
# namespace 변경과 connector별 출력 타입 호환은 문자열 치환이 아닌 SQLGlot AST
# 경계에서만 수행하고, target catalog 설정에서 connector 종류를 직접 읽는다.
#
# 아카이브의 `run-v43.ps1`을 쓰지 않는 이유는 두 가지다. 첫째, 그 스크립트는 release
# manifest에 sha256으로 고정된 불변 기록이라 수정 대상이 아니다. 둘째, 그 안의 실행
# 경로는 컨테이너 이름 `hotel-synthetic-db-trino-1`과 무인증 HTTP(`--server
# http://localhost:8080`)를 가정하는데 현재 런타임은 둘 다 다르다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ReleaseId,
    [string]$EnvFilePath,
    [string]$TargetSchema,
    # 검증 SQL까지 함께 실행해 cross-source 무결성을 확인한다.
    [switch]$IncludeValidation
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $databaseRoot 'compose.yml'
$viewInspector = Join-Path $PSScriptRoot 'inspect_release_views.py'
$sqlRenderer = Join-Path $PSScriptRoot 'render_release_serving_sql.py'
$icebergViewCoercions = Join-Path $databaseRoot 'trino/etc/iceberg-view-coercions.json'
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$') {
    throw 'ReleaseId format is invalid.'
}
$releaseMatches = @()
foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $databaseRoot 'releases') -Directory) {
    $candidate = Join-Path $directory.FullName 'manifest.json'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $document = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Release manifest is not valid JSON: $candidate"
    }
    if ([string]$document.release_id -ceq $ReleaseId) {
        $releaseMatches += [pscustomobject]@{
            Directory = $directory.FullName
            Manifest = $candidate
            Document = $document
        }
    }
}
if ($releaseMatches.Count -ne 1) {
    throw "ReleaseId must resolve to exactly one manifest: $ReleaseId"
}
$releaseRoot = $releaseMatches[0].Directory
$manifestPath = $releaseMatches[0].Manifest
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseId = [string]$manifest.release_id
$manifestViewCount = [int]$manifest.expected.serving_views
$servingSchema = [string]$manifest.namespaces.serving
if ([string]::IsNullOrWhiteSpace($releaseId) -or $manifestViewCount -lt 1 -or
    $servingSchema -notmatch '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$') {
    throw 'release manifest does not declare a valid release id and serving view count.'
}
if ([string]::IsNullOrWhiteSpace($TargetSchema)) { $TargetSchema = $servingSchema }
if ($TargetSchema -notmatch '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$') {
    throw 'TargetSchema must use lowercase catalog.schema form.'
}
$targetParts = $TargetSchema.Split('.')
$servingCatalog = $targetParts[0]
$servingDatabase = $targetParts[1]
$targetCatalogPath = Join-Path $databaseRoot "trino/etc/catalog/$servingCatalog.properties"
if (-not (Test-Path -LiteralPath $targetCatalogPath -PathType Leaf)) {
    throw "Target catalog configuration is missing: $servingCatalog"
}
$connectorValues = @(Get-Content -LiteralPath $targetCatalogPath -Encoding UTF8 |
    ForEach-Object {
        if ($_ -match '^\s*connector\.name\s*=\s*([a-z][a-z0-9_-]*)\s*$') {
            $Matches[1]
        }
    })
if ($connectorValues.Count -ne 1) {
    throw "Target catalog must declare exactly one connector.name: $servingCatalog"
}
$targetConnector = [string]$connectorValues[0]
$requiresIcebergCompatibility = $targetConnector -ceq 'iceberg'

# 실행 파일·순서·필수/검증 구분·정확한 View 목록은 파일명 배열이 아니라 manifest와
# SQL metadata/AST에서 결정한다. planner가 manifest 전체 checksum도 함께 검증한다.
$previousBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE = '1'
try {
    $planOutput = & python $viewInspector --manifest $manifestPath --schema $servingSchema
    if ($LASTEXITCODE -ne 0) {
        throw 'Trino serving recovery plan could not be derived from the release.'
    }
} finally {
    $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
}
try {
    $recoveryPlan = ($planOutput -join "`n") | ConvertFrom-Json
} catch {
    throw 'Trino serving recovery planner returned invalid JSON.'
}
if ([string]$recoveryPlan.release_id -cne $releaseId -or
    [int]$recoveryPlan.view_count -ne $manifestViewCount) {
    throw 'Trino recovery plan differs from the selected release manifest.'
}
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-RepositoryDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$values = Read-DeploymentEnvironment $resolvedEnvFile
Assert-DeploymentEnvironmentValues -Values $values -RequiredKeys @(
    'TRINO_ADMIN_USER', 'TRINO_ADMIN_PASSWORD'
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
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        # Trino CLI의 실제 parser/connector 오류는 진단에 필수다. 다만 compose argv나
        # process environment는 포함하지 않고, 도구가 반환한 마지막 출력만 제한한다.
        $diagnostic = @($output | ForEach-Object { [string]$_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Last 25) -join "`n"
        if ([string]::IsNullOrWhiteSpace($diagnostic)) {
            $diagnostic = 'native command returned no diagnostic output.'
        }
        throw "docker compose command failed (exit=$exitCode):`n$diagnostic"
    }
    return $output
}

# 비밀번호는 argv가 아니라 process environment로만 전달한다. Trino CLI는 TRINO_PASSWORD를
# 읽으므로 `--password`에 값을 붙이지 않는다.
function Invoke-TrinoSqlFile {
    param([Parameter(Mandatory)] [string]$RelativePath)

    $localPath = Join-Path $releaseRoot $RelativePath
    if (-not (Test-Path -LiteralPath $localPath)) {
        throw "serving SQL file is missing: $RelativePath"
    }
    $renderedPath = $null
    $executionPath = $localPath
    if ($TargetSchema -cne $servingSchema -or $requiresIcebergCompatibility) {
        if ($requiresIcebergCompatibility -and
            -not (Test-Path -LiteralPath $icebergViewCoercions -PathType Leaf)) {
            throw 'Iceberg View coercion contract is missing.'
        }
        $renderedPath = Join-Path ([IO.Path]::GetTempPath()) (
            "serving-rendered-$PID-$([guid]::NewGuid().ToString('N')).sql"
        )
        $rendererArguments = @(
            $sqlRenderer, '--input', $localPath, '--output', $renderedPath,
            '--source-schema', $servingSchema, '--target-schema', $TargetSchema
        )
        if ($requiresIcebergCompatibility) {
            $rendererArguments += @('--coercions', $icebergViewCoercions)
        }
        & python @rendererArguments
        if ($LASTEXITCODE -ne 0) {
            throw "serving SQL AST rendering failed: $RelativePath"
        }
        $executionPath = $renderedPath
    }
    try {
        Invoke-Compose -Arguments @('cp', $executionPath, 'trino:/tmp/serving_current.sql') | Out-Null
    } finally {
        if ($renderedPath -and (Test-Path -LiteralPath $renderedPath -PathType Leaf)) {
            Remove-Item -LiteralPath $renderedPath -Force
        }
    }

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
        throw "serving SQL reported FAIL: $RelativePath"
    }
    Write-Output "SERVING_SQL_APPLIED|$TargetSchema|$RelativePath"
}

# 최초 publish 전 collision=0을 요구하는 preflight는 이미 schema가 존재하는 멱등 recovery와
# 계약이 다르므로 자동 재실행하지 않는다. 필수 DDL과 사후 validation만 실행한다.
$executionPlan = @($recoveryPlan.files | Where-Object {
    [string]$_.mode -eq 'required' -or
    ($IncludeValidation -and [string]$_.mode -eq 'validation')
} | Sort-Object execution_order)
if (-not $executionPlan.Count) {
    throw 'Trino recovery plan selected no executable files.'
}
foreach ($entry in $executionPlan) {
    Invoke-TrinoSqlFile -RelativePath ([string]$entry.relative_path)
}

# 생성 직후 실제 relation 수를 인증 경로로 다시 읽어, 빈 catalog나 일부 누락을 성공으로
# 보고하지 않는다. SQL 선언 수와 manifest 기대 수부터 일치해야 하며, target catalog에
# 남은 extra View까지 허용하지 않도록 live read-back도 exact match한다.
$countSql = @"
SELECT table_name FROM $servingCatalog.information_schema.tables
WHERE table_schema = '$servingDatabase' AND table_type = 'VIEW'
ORDER BY table_name;
"@
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

$observedViews = @(($countOutput -join "`n") -split "`r?`n" | ForEach-Object {
    if ($_ -match '^\s*"?([a-z][a-z0-9_]*)"?\s*$') { $Matches[1] }
})
$declaredNames = @($recoveryPlan.views | ForEach-Object {
    ([string]$_).Split('.')[-1]
} | Sort-Object)
$observedViews = @($observedViews | Sort-Object)
if ($observedViews.Count -ne $manifestViewCount) {
    throw "serving catalog has $($observedViews.Count) views but manifest expects $manifestViewCount."
}
$difference = @(Compare-Object -ReferenceObject $declaredNames -DifferenceObject $observedViews)
if ($difference.Count) {
    throw 'serving live View identities differ from release SQL declarations.'
}
foreach ($name in $observedViews) { Write-Output "SERVING_VIEW_VERIFIED|$name" }
Write-Output "SERVING_VIEWS_RECREATED|$releaseId|$TargetSchema|$($observedViews.Count)"
