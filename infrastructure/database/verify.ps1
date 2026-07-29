[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$databaseRoot = $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'
$expectedContract = '1.0.0|20260729|synthetic'
$probeTable = "verify_readonly_create_$PID"

if (-not (Test-Path -LiteralPath $localEnv)) {
    throw '.env is missing. Run start.ps1 after creating an environment file.'
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
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $($Arguments -join ' ')" }
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

$catalogs = Invoke-Compose -Arguments @(
    'exec', '-T', 'trino', 'trino',
    '--server', 'http://localhost:8080', '--user', 'hotel_synthetic_verify',
    '--output-format', 'CSV_UNQUOTED', '--execute', 'SHOW CATALOGS'
)
$requiredCatalogs = 'serving','pms','banquet','pos','crm','facility'
foreach ($catalog in $requiredCatalogs) {
    if ($catalogs -notcontains $catalog) { throw "Trino catalog is missing: $catalog" }
}

$viewCountResult = Invoke-Compose -Arguments @(
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

Write-Output 'DATABASE_CONTRACT_VERIFIED'
