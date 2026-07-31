[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'
$expectedContract = '1.0.0|20260729|synthetic'
$probeTable = "verify_readonly_create_$PID"

if (-not (Test-Path -LiteralPath $localEnv)) {
    throw '.env is missing. Run scripts/start.ps1 after creating an environment file.'
}
if (Select-String -LiteralPath $localEnv -Pattern '(^|=)CHANGE_ME_' -Quiet) {
    throw '.env contains CHANGE_ME_ values.'
}

$values = @{}
Get-Content -LiteralPath $localEnv -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*([^#=\s]+)=(.*)$') { $values[$matches[1]] = $matches[2].Trim() }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    $result = & docker compose --env-file $localEnv -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'docker compose command failed. Inspect Compose logs; command arguments are intentionally omitted.' }
    return $result
}

function Assert-Contract {
    param(
        [string]$Name,
        [string[]]$Result
    )

    $actual = (@($Result) -join "`n").Trim()
    if ($actual -ne $expectedContract) {
        throw "$Name contract mismatch. Expected $expectedContract, got $actual"
    }
}

function Assert-RowCount {
    param(
        [string]$Name,
        [string]$Expected,
        [string[]]$Result
    )

    $actual = (@($Result) -join "`n").Trim()
    if ($actual -ne $Expected) {
        throw "$Name row count mismatch. Expected $Expected, got $actual"
    }
    Write-Output "ROW_COUNT|$Name|$actual"
}

function Invoke-TrinoQuery {
    param([Parameter(Mandatory)] [string[]]$Arguments)

    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $result = & docker compose --env-file $localEnv -f $composeFile @Arguments 2>$null
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($exitCode -eq 0) { return $result }
        Start-Sleep -Seconds 2
    }
    throw 'Trino is healthy but did not become query-ready within 120 seconds.'
}

function Assert-ComposeDenied {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [scriptblock]$Cleanup
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker compose --env-file $localEnv -f $composeFile @Arguments *> $null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -eq 0) {
        & $Cleanup
        throw "$Name readonly account unexpectedly created a table."
    }
}

Invoke-Compose -Arguments @('config', '--quiet') | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File (
    Join-Path $PSScriptRoot 'verify-service-fragment.ps1'
)
if ($LASTEXITCODE -ne 0) {
    throw 'R2 service fragment verification failed.'
}
$services = 'app-postgres','pms-postgres','banquet-postgres','pos-mysql','crm-mssql','facility-clickhouse','trino'
$status = Invoke-Compose -Arguments @('ps', '-a', '--format', 'json') | ForEach-Object { $_ | ConvertFrom-Json }
foreach ($service in $services) {
    if (($status | Where-Object Service -eq $service).Health -ne 'healthy') {
        throw "$service is not healthy."
    }
}

Assert-Contract 'app-postgres' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.APP_DB_PASSWORD)",
    'app-postgres', 'psql', '-U', $values.APP_DB_USER, '-d', $values.APP_DB_NAME, '-tAc',
    "SELECT concat_ws('|', v.version, s.seed, s.data_class) FROM governance.schema_version v CROSS JOIN governance.seed_metadata s"
))
Assert-Contract 'pms-postgres' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.PMS_READONLY_PASSWORD)",
    'pms-postgres', 'psql', '-U', $values.PMS_READONLY_USER, '-d', $values.PMS_DB_NAME, '-tAc',
    "SELECT concat_ws('|', v.version, s.seed, s.data_class) FROM schema_version v CROSS JOIN seed_metadata s"
))
Assert-Contract 'banquet-postgres' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.BANQUET_READONLY_PASSWORD)",
    'banquet-postgres', 'psql', '-U', $values.BANQUET_READONLY_USER, '-d', $values.BANQUET_DB_NAME, '-tAc',
    "SELECT concat_ws('|', v.version, s.seed, s.data_class) FROM schema_version v CROSS JOIN seed_metadata s"
))
Assert-Contract 'pos-mysql' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "MYSQL_PWD=$($values.POS_READONLY_PASSWORD)",
    'pos-mysql', 'mysql', "-u$($values.POS_READONLY_USER)", "-D$($values.POS_DB_NAME)", '-N', '-B', '-e',
    "SELECT CONCAT_WS('|', v.version, s.seed, s.data_class) FROM schema_version v CROSS JOIN seed_metadata s"
))
Assert-Contract 'crm-mssql' (Invoke-Compose -Arguments @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', $values.CRM_READONLY_USER, '-P', $values.CRM_READONLY_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-h', '-1', '-W', '-Q',
    "SET NOCOUNT ON; SELECT CONCAT(v.version,'|',s.seed,'|',s.data_class) FROM dbo.schema_version v CROSS JOIN dbo.seed_metadata s"
))
Assert-Contract 'facility-clickhouse' (Invoke-Compose -Arguments @(
    'exec', '-T', 'facility-clickhouse', 'clickhouse-client',
    '--user', $values.FACILITY_READONLY_USER, '--password', $values.FACILITY_READONLY_PASSWORD,
    '--query', "SELECT concat(v.version,'|',toString(s.seed),'|',s.data_class) FROM facility.schema_version v CROSS JOIN facility.seed_metadata s FORMAT TSVRaw"
))

Assert-RowCount 'app-postgres.reference.calendar_daily' '1826' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.APP_DB_PASSWORD)",
    'app-postgres', 'psql', '-U', $values.APP_DB_USER, '-d', $values.APP_DB_NAME, '-tAc',
    'SELECT count(*) FROM reference.calendar_daily'
))
Assert-RowCount 'pms-postgres.pms_guests' '100000' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.PMS_READONLY_PASSWORD)",
    'pms-postgres', 'psql', '-U', $values.PMS_READONLY_USER, '-d', $values.PMS_DB_NAME, '-tAc',
    'SELECT count(*) FROM pms_guests'
))
Assert-RowCount 'banquet-postgres.banquet_bookings' '6000' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.BANQUET_READONLY_PASSWORD)",
    'banquet-postgres', 'psql', '-U', $values.BANQUET_READONLY_USER, '-d', $values.BANQUET_DB_NAME, '-tAc',
    'SELECT count(*) FROM banquet_bookings'
))
Assert-RowCount 'pos-mysql.pos_orders' '320000' (Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "MYSQL_PWD=$($values.POS_READONLY_PASSWORD)",
    'pos-mysql', 'mysql', "-u$($values.POS_READONLY_USER)", "-D$($values.POS_DB_NAME)", '-N', '-B', '-e',
    'SELECT count(*) FROM pos_orders'
))
Assert-RowCount 'crm-mssql.crm_members' '80000' (Invoke-Compose -Arguments @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', $values.CRM_READONLY_USER, '-P', $values.CRM_READONLY_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-h', '-1', '-W', '-Q', 'SET NOCOUNT ON; SELECT count(*) FROM dbo.crm_members'
))
Assert-RowCount 'facility-clickhouse.facility_events' '700000' (Invoke-Compose -Arguments @(
    'exec', '-T', 'facility-clickhouse', 'clickhouse-client',
    '--user', $values.FACILITY_READONLY_USER, '--password', $values.FACILITY_READONLY_PASSWORD,
    '--query', 'SELECT count(*) FROM facility.facility_events FORMAT TSVRaw'
))

$catalogs = Invoke-TrinoQuery -Arguments @(
    'exec', '-T', 'trino', 'trino',
    '--server', 'http://localhost:8080', '--user', 'hotel_synthetic_verify',
    '--output-format', 'CSV_UNQUOTED', '--execute', 'SHOW CATALOGS'
)
$requiredCatalogs = 'serving','pms','banquet','pos','crm','facility'
foreach ($catalog in $requiredCatalogs) {
    if ($catalogs -notcontains $catalog) { throw "Trino catalog is missing: $catalog" }
}

$viewCountResult = Invoke-TrinoQuery -Arguments @(
    'exec', '-T', 'trino', 'trino',
    '--server', 'http://localhost:8080', '--user', 'hotel_synthetic_verify',
    '--output-format', 'CSV_UNQUOTED',
    '--execute', "SELECT count(*) FROM serving.information_schema.views WHERE table_schema='analytics'"
)
$viewCount = (@($viewCountResult) | Select-Object -Last 1).Trim()
if ($viewCount -ne '8') {
    throw "Expected 8 analytics views, got $viewCount."
}

Assert-ComposeDenied 'pms-postgres' @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.PMS_READONLY_PASSWORD)",
    'pms-postgres', 'psql', '-U', $values.PMS_READONLY_USER, '-d', $values.PMS_DB_NAME,
    '-v', 'ON_ERROR_STOP=1', '-c', "CREATE TABLE public.$probeTable (id integer)"
) {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PGPASSWORD=$($values.PMS_ADMIN_PASSWORD)",
        'pms-postgres', 'psql', '-U', $values.PMS_ADMIN_USER, '-d', $values.PMS_DB_NAME,
        '-v', 'ON_ERROR_STOP=1', '-c', "DROP TABLE IF EXISTS public.$probeTable"
    ) | Out-Null
}
Assert-ComposeDenied 'banquet-postgres' @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.BANQUET_READONLY_PASSWORD)",
    'banquet-postgres', 'psql', '-U', $values.BANQUET_READONLY_USER, '-d', $values.BANQUET_DB_NAME,
    '-v', 'ON_ERROR_STOP=1', '-c', "CREATE TABLE public.$probeTable (id integer)"
) {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PGPASSWORD=$($values.BANQUET_ADMIN_PASSWORD)",
        'banquet-postgres', 'psql', '-U', $values.BANQUET_ADMIN_USER, '-d', $values.BANQUET_DB_NAME,
        '-v', 'ON_ERROR_STOP=1', '-c', "DROP TABLE IF EXISTS public.$probeTable"
    ) | Out-Null
}
Assert-ComposeDenied 'pos-mysql' @(
    'exec', '-T', '--env', "MYSQL_PWD=$($values.POS_READONLY_PASSWORD)",
    'pos-mysql', 'mysql', "-u$($values.POS_READONLY_USER)", "-D$($values.POS_DB_NAME)",
    '-e', "CREATE TABLE $probeTable (id int)"
) {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "MYSQL_PWD=$($values.POS_ROOT_PASSWORD)",
        'pos-mysql', 'mysql', '-uroot', "-D$($values.POS_DB_NAME)",
        '-e', "DROP TABLE IF EXISTS $probeTable"
    ) | Out-Null
}
Assert-ComposeDenied 'crm-mssql' @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', $values.CRM_READONLY_USER, '-P', $values.CRM_READONLY_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-Q', "CREATE TABLE dbo.$probeTable (id int)"
) {
    Invoke-Compose -Arguments @(
        'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
        '-S', 'localhost', '-U', 'sa', '-P', $values.CRM_SA_PASSWORD,
        '-C', '-d', $values.CRM_DB_NAME, '-b', '-Q', "DROP TABLE IF EXISTS dbo.$probeTable"
    ) | Out-Null
}
Assert-ComposeDenied 'facility-clickhouse' @(
    'exec', '-T', 'facility-clickhouse', 'clickhouse-client',
    '--user', $values.FACILITY_READONLY_USER, '--password', $values.FACILITY_READONLY_PASSWORD,
    '--query', "CREATE TABLE facility.$probeTable (id UInt8) ENGINE=Memory"
) {
    Invoke-Compose -Arguments @(
        'exec', '-T', 'facility-clickhouse', 'clickhouse-client',
        '--user', $values.FACILITY_ADMIN_USER, '--password', $values.FACILITY_ADMIN_PASSWORD,
        '--query', "DROP TABLE IF EXISTS facility.$probeTable"
    ) | Out-Null
}

$i2Contract = Get-Content -Raw -Encoding UTF8 (
    Join-Path $databaseRoot '..\..\src\data\i2_contract.v1.json'
) | ConvertFrom-Json
$i2Sql = Get-Content -Raw -Encoding UTF8 (
    Join-Path $databaseRoot 'sql\queries\i2_gold_recognized_room_revenue.sql'
)
$i2Rows = Invoke-TrinoQuery -Arguments @(
    'exec', '-T', 'trino', 'trino',
    '--server', 'http://localhost:8080', '--user', 'hotel_synthetic_verify',
    '--output-format', 'TSV', '--execute', $i2Sql
)
$i2Canonical = ((@($i2Rows) | ForEach-Object {
    $_.Trim().Replace("`t", '|')
}) -join "`n") + "`n"
$i2HashBytes = [System.Security.Cryptography.SHA256]::Create().ComputeHash(
    [System.Text.Encoding]::UTF8.GetBytes($i2Canonical)
)
$i2Hash = ([System.BitConverter]::ToString($i2HashBytes) -replace '-', '').ToLowerInvariant()
if ($i2Hash -ne $i2Contract.gold_fixture.sha256) {
    throw "I2 gold result hash mismatch. Expected $($i2Contract.gold_fixture.sha256), got $i2Hash."
}
Write-Output "I2_GOLD_HASH_VERIFIED|$i2Hash"

Write-Output 'DATABASE_CONTRACT_VERIFIED'
