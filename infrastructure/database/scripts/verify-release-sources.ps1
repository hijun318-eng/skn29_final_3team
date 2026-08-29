# 책임: 불변 release manifest에서 source 검증 SQL을 발견해 실제 DB 엔진에서 읽기
# 전용으로 실행하고, checksum·실행시간·출력 hash가 결속된 receipt를 생성한다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$EnvFilePath,
    [Parameter(Mandatory)] [string]$ReleaseId,
    [Parameter(Mandatory)] [string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $databaseRoot '..\..')).Path
$composeFile = Join-Path $databaseRoot 'compose.yml'
$readOnlyVerifier = Join-Path $PSScriptRoot 'verify_readonly_sql.py'
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$values = Read-DeploymentEnvironment $resolvedEnvFile
Assert-DeploymentEnvironmentValues -Values $values -RequiredKeys @('CRM_DB_NAME')

if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$') {
    throw 'ReleaseId format is invalid.'
}
$releaseMatches = @()
foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $databaseRoot 'releases') -Directory) {
    $candidate = Join-Path $directory.FullName 'manifest.json'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    $document = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
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
$release = $releaseMatches[0]
$sourceSchema = [string]$release.Document.namespaces.source
if ($sourceSchema -notmatch '^[a-z][a-z0-9_]{1,62}$') {
    throw 'Release source namespace is invalid.'
}

# 일부 validation 파일만 맞고 나머지 release 파일이 변조된 상태를 PASS로 결속하지
# 않도록 manifest 전체 파일의 경로 경계와 checksum을 먼저 검증한다.
$releaseRoot = [IO.Path]::GetFullPath($release.Directory)
$releasePrefix = $releaseRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + `
    [IO.Path]::DirectorySeparatorChar
foreach ($entry in @($release.Document.files)) {
    $relativePath = [string]$entry.relative_path
    $expectedHash = [string]$entry.sha256
    if ([string]::IsNullOrWhiteSpace($relativePath) -or
        $expectedHash -notmatch '^[a-fA-F0-9]{64}$') {
        throw 'Release manifest contains an invalid file receipt.'
    }
    $releaseFile = [IO.Path]::GetFullPath((Join-Path $releaseRoot $relativePath))
    if (-not $releaseFile.StartsWith($releasePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $releaseFile -PathType Leaf)) {
        throw "Release file escaped its directory or is missing: $relativePath"
    }
    $actualHash = (Get-FileHash -LiteralPath $releaseFile -Algorithm SHA256).Hash
    if ($actualHash -cne $expectedHash.ToUpperInvariant()) {
        throw "Release checksum mismatch: $relativePath"
    }
}

$evidenceRoot = [IO.Path]::GetFullPath($EvidenceDirectory)
$repositoryPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + `
    [IO.Path]::DirectorySeparatorChar
if (-not $evidenceRoot.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'EvidenceDirectory must remain inside the repository.'
}
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null
$logRoot = Join-Path $evidenceRoot 'source-validation-logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        # Windows PowerShell 5.1은 compose가 전달한 container stdout도 상황에 따라
        # ErrorRecord로 감싼다. type으로 버리면 validation의 PASS/FAIL 행까지 사라지므로
        # 모든 native 출력을 즉시 문자열로 보존하고 성공 여부는 exit code로 판정한다.
        $output = & docker compose @composeEnvArguments -f $composeFile @Arguments 2>&1 |
            ForEach-Object { "$_" }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw 'docker compose command failed; inspect the selected service without printing credentials.'
    }
    return @($output | ForEach-Object { [string]$_ })
}

function Get-OutputHash {
    param([Parameter(Mandatory)] [AllowEmptyString()] [string]$Text)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ($algorithm.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join ''
    } finally {
        $algorithm.Dispose()
    }
}

# 서비스 이름과 native CLI는 배포 topology의 adapter 계약이다. 검증 대상 파일 목록과
# 기대 row는 이 map에 넣지 않고 release manifest와 SQL 자체에서만 발견한다.
$adapters = [ordered]@{
    '01_postgresql_pms' = [pscustomobject]@{
        Service = 'pms-postgres'
        Command = 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/answervice_release_validation.sql'
        Inventory = 'printf "%s" "$INVENTORY_SQL_BASE64" | base64 -d > /tmp/answervice_inventory.sql; export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/answervice_inventory.sql'
        InventorySql = "SELECT count(*) FROM pg_indexes WHERE schemaname='$sourceSchema'"
        Shell = 'sh'
        Dialect = 'postgres'
        DatabaseArgument = @()
    }
    '02_postgresql_banquet' = [pscustomobject]@{
        Service = 'banquet-postgres'
        Command = 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/answervice_release_validation.sql'
        Inventory = 'printf "%s" "$INVENTORY_SQL_BASE64" | base64 -d > /tmp/answervice_inventory.sql; export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/answervice_inventory.sql'
        InventorySql = "SELECT count(*) FROM pg_indexes WHERE schemaname='$sourceSchema'"
        Shell = 'sh'
        Dialect = 'postgres'
        DatabaseArgument = @()
    }
    '03_mysql_pos' = [pscustomobject]@{
        Service = 'pos-mysql'
        Command = 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql --default-character-set=utf8mb4 --batch --raw --show-warnings -uroot "$MYSQL_DATABASE" < /tmp/answervice_release_validation.sql'
        Inventory = 'printf "%s" "$INVENTORY_SQL_BASE64" | base64 -d > /tmp/answervice_inventory.sql; export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql --default-character-set=utf8mb4 --batch --skip-column-names -uroot "$MYSQL_DATABASE" < /tmp/answervice_inventory.sql'
        InventorySql = 'SELECT count(*) FROM information_schema.statistics WHERE table_schema=DATABASE()'
        Shell = 'sh'
        Dialect = 'mysql'
        DatabaseArgument = @()
    }
    '04_sqlserver_crm' = [pscustomobject]@{
        Service = 'crm-mssql'
        Command = 'export SQLCMDPASSWORD="$MSSQL_SA_PASSWORD"; exec /opt/mssql-tools18/bin/sqlcmd -C -b -S localhost -U sa -d "$PROBE_DATABASE" -i /tmp/answervice_release_validation.sql'
        Inventory = 'printf "%s" "$INVENTORY_SQL_BASE64" | base64 -d > /tmp/answervice_inventory.sql; export SQLCMDPASSWORD="$MSSQL_SA_PASSWORD"; exec /opt/mssql-tools18/bin/sqlcmd -C -b -W -h -1 -S localhost -U sa -d "$PROBE_DATABASE" -i /tmp/answervice_inventory.sql'
        InventorySql = "SET NOCOUNT ON; SELECT count(*) FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=N'$sourceSchema' AND i.index_id>0 AND i.is_hypothetical=0"
        Shell = 'sh'
        Dialect = 'tsql'
        DatabaseArgument = @('--env', "PROBE_DATABASE=$([string]$values['CRM_DB_NAME'])")
    }
    '05_clickhouse_facility' = [pscustomobject]@{
        Service = 'facility-clickhouse'
        Command = 'exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery --queries-file /tmp/answervice_release_validation.sql'
        Inventory = 'printf "%s" "$INVENTORY_SQL_BASE64" | base64 -d > /tmp/answervice_inventory.sql; exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --queries-file /tmp/answervice_inventory.sql'
        InventorySql = "SELECT count() FROM system.tables WHERE database='$sourceSchema' AND (sorting_key!='' OR primary_key!='')"
        Shell = 'sh'
        Dialect = 'clickhouse'
        DatabaseArgument = @()
    }
}

function Get-LiveIndexInventory {
    $result = @()
    foreach ($key in $adapters.Keys) {
        $adapter = $adapters[$key]
        $inventoryArguments = @()
        if (-not [string]::IsNullOrWhiteSpace([string]$adapter.InventorySql)) {
            $encodedSql = [Convert]::ToBase64String(
                [Text.Encoding]::UTF8.GetBytes([string]$adapter.InventorySql)
            )
            $inventoryArguments = @('--env', "INVENTORY_SQL_BASE64=$encodedSql")
        }
        $arguments = @('exec', '-T', '--env', "RELEASE_SCHEMA=$sourceSchema") + `
            @($adapter.DatabaseArgument) + $inventoryArguments + @(
                $adapter.Service, $adapter.Shell, '-ec', $adapter.Inventory
            )
        $composeItems = @(Invoke-Compose -Arguments $arguments)
        $output = $composeItems -join "`n"
        $numericValues = @()
        foreach ($line in $output -split "`r?`n") {
            $candidate = $line.Trim().Trim('"')
            $parsed = 0L
            if ([int64]::TryParse($candidate, [ref]$parsed)) {
                $numericValues += $parsed
            }
        }
        if (-not $numericValues.Count) {
            $outputHash = Get-OutputHash -Text $output
            throw "Index inventory did not return a count: $($adapter.Service), output_sha256=$outputHash"
        }
        $count = [int64]$numericValues[$numericValues.Count - 1]
        if ($count -lt 1) {
            throw "Index inventory is empty: $($adapter.Service)"
        }
        $result += [pscustomobject]@{
            service = [string]$adapter.Service
            index_count = $count
        }
    }
    return $result
}

$validationEntries = @($release.Document.files | Where-Object {
    $name = [IO.Path]::GetFileName([string]$_.relative_path)
    $name -match '^50_[A-Za-z0-9_]+_validation\.sql$' -and
    [string]$_.relative_path -notmatch '[\\/]06_trino_serving[\\/]'
})
if (-not $validationEntries.Count) {
    throw 'Release manifest contains no source validation files.'
}

$startedAt = [DateTimeOffset]::UtcNow
$inventory = @(Get-LiveIndexInventory)
foreach ($item in $inventory) {
    Write-Output "SOURCE_INDEX_INVENTORY|$($item.service)|$($item.index_count)"
}
$receipts = @()
foreach ($entry in $validationEntries) {
    $relativePath = [string]$entry.relative_path
    $expectedHash = [string]$entry.sha256
    $filePath = Join-Path $release.Directory $relativePath
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        throw "Validation file is missing: $relativePath"
    }
    $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -cne $expectedHash.ToLowerInvariant()) {
        throw "Validation file checksum mismatch: $relativePath"
    }
    $header = (Get-Content -LiteralPath $filePath -TotalCount 12 -Encoding UTF8) -join "`n"
    if ($header -notmatch 'script_type=VALIDATION_READONLY') {
        throw "Validation file is not explicitly read-only: $relativePath"
    }
    $adapterKey = @($adapters.Keys | Where-Object {
        $relativePath -match ('[\\/]' + [regex]::Escape($_) + '[\\/]')
    })
    if ($adapterKey.Count -ne 1) {
        throw "Validation adapter could not be resolved: $relativePath"
    }
    $adapter = $adapters[$adapterKey[0]]
    $previousBytecode = $env:PYTHONDONTWRITEBYTECODE
    $env:PYTHONDONTWRITEBYTECODE = '1'
    try {
        & python $readOnlyVerifier --dialect $adapter.Dialect $filePath | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Validation SQL is not read-only: $relativePath"
        }
    } finally {
        $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
    }
    Invoke-Compose -Arguments @('cp', $filePath, "$($adapter.Service):/tmp/answervice_release_validation.sql") | Out-Null
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $arguments = @('exec', '-T', '--env', "RELEASE_SCHEMA=$sourceSchema") + `
        @($adapter.DatabaseArgument) + @(
            $adapter.Service, $adapter.Shell, '-ec', $adapter.Command
        )
    $output = Invoke-Compose -Arguments $arguments
    $timer.Stop()
    $text = $output -join "`n"
    if ($text -match '(?im)(?:^|[|\s])FAIL(?:[|\s]|$)') {
        throw "Source validation reported FAIL: $relativePath"
    }
    $safeName = ($relativePath -replace '[^A-Za-z0-9._-]', '_')
    $logPath = Join-Path $logRoot "$safeName.log"
    [IO.File]::WriteAllText($logPath, $text, [Text.UTF8Encoding]::new($false))
    $receipts += [ordered]@{
        relative_path = $relativePath.Replace('\', '/')
        sha256 = $actualHash
        service = [string]$adapter.Service
        duration_seconds = [math]::Round($timer.Elapsed.TotalSeconds, 3)
        status = 'PASS'
        output_sha256 = Get-OutputHash -Text $text
        log_path = $logPath.Substring($repoRoot.Length + 1).Replace('\', '/')
    }
    Write-Output "SOURCE_VALIDATION_PASS|$relativePath|$([math]::Round($timer.Elapsed.TotalSeconds, 3))s"
}

$receipt = [ordered]@{
    schema_version = 'answervice.d0-source-validation-receipt.v1'
    release_id = $ReleaseId
    base_sha = (& git -C $repoRoot rev-parse HEAD).Trim()
    manifest_sha256 = (Get-FileHash -LiteralPath $release.Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    verifier_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    readonly_sql_verifier_sha256 = (Get-FileHash -LiteralPath $readOnlyVerifier -Algorithm SHA256).Hash.ToLowerInvariant()
    started_at_utc = $startedAt.ToString('O')
    ended_at_utc = [DateTimeOffset]::UtcNow.ToString('O')
    validation_file_count = $receipts.Count
    validations = $receipts
    live_index_inventory = $inventory
    status = 'PASS'
}
$receiptPath = Join-Path $evidenceRoot 'source-validation-receipt.json'
[IO.File]::WriteAllText(
    $receiptPath,
    ($receipt | ConvertTo-Json -Depth 8),
    [Text.UTF8Encoding]::new($false)
)
Write-Output "SOURCE_RELEASE_VALIDATED|$ReleaseId|$($receipts.Count)|$receiptPath"
