[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$databaseRoot = $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'

if (-not (Test-Path -LiteralPath $localEnv)) {
    throw '.env is missing. Run start.ps1 after creating an environment file.'
}

$values = @{}
Get-Content -LiteralPath $localEnv | ForEach-Object {
    if ($_ -match '^\s*([^#=\s]+)=(.*)$') { $values[$matches[1]] = $matches[2].Trim() }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    $result = & docker compose --env-file $localEnv -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $($Arguments -join ' ')" }
    return $result
}

Invoke-Compose config --quiet | Out-Null
$services = 'app-postgres','pms-postgres','banquet-postgres','pos-mysql','crm-mssql','facility-clickhouse'
$status = Invoke-Compose ps --format json | ForEach-Object { $_ | ConvertFrom-Json }
foreach ($service in $services) {
    if (($status | Where-Object Service -eq $service).Health -ne 'healthy') {
        throw "$service is not healthy."
    }
}

Invoke-Compose -Arguments @('exec', '-T', '--env', "PGPASSWORD=$($values.APP_DB_PASSWORD)", 'app-postgres', 'psql', '-U', $values.APP_DB_USER, '-d', $values.APP_DB_NAME, '-tAc', 'SELECT count(*) FROM reference.calendar_daily') | Out-Null
Invoke-Compose -Arguments @('exec', '-T', '--env', "PGPASSWORD=$($values.PMS_READONLY_PASSWORD)", 'pms-postgres', 'psql', '-U', $values.PMS_READONLY_USER, '-d', $values.PMS_DB_NAME, '-tAc', 'SELECT count(*) FROM pms_guests') | Out-Null
Invoke-Compose -Arguments @('exec', '-T', '--env', "PGPASSWORD=$($values.BANQUET_READONLY_PASSWORD)", 'banquet-postgres', 'psql', '-U', $values.BANQUET_READONLY_USER, '-d', $values.BANQUET_DB_NAME, '-tAc', 'SELECT count(*) FROM banquet_bookings') | Out-Null
Invoke-Compose -Arguments @('exec', '-T', '--env', "MYSQL_PWD=$($values.POS_READONLY_PASSWORD)", 'pos-mysql', 'mysql', "-u$($values.POS_READONLY_USER)", "-D$($values.POS_DB_NAME)", '-N', '-B', '-e', 'SELECT count(*) FROM pos_orders') | Out-Null
Invoke-Compose -Arguments @('exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd', '-S', 'localhost', '-U', $values.CRM_READONLY_USER, '-P', $values.CRM_READONLY_PASSWORD, '-C', '-d', $values.CRM_DB_NAME, '-b', '-Q', 'SELECT count(*) FROM dbo.crm_members') | Out-Null
Invoke-Compose -Arguments @('exec', '-T', 'facility-clickhouse', 'clickhouse-client', '--user', $values.FACILITY_READONLY_USER, '--password', $values.FACILITY_READONLY_PASSWORD, '--query', 'SELECT count() FROM facility.facility_events') | Out-Null

$catalogs = Invoke-Compose exec -T trino trino --server http://localhost:8080 --user hotel_synthetic_verify --output-format CSV_UNQUOTED --execute 'SHOW CATALOGS'
$requiredCatalogs = 'app','pms','banquet','pos','crm','facility'
foreach ($catalog in $requiredCatalogs) {
    if ($catalogs -notcontains $catalog) { throw "Trino catalog is missing: $catalog" }
}
Invoke-Compose exec -T trino trino --server http://localhost:8080 --user hotel_synthetic_verify --execute 'SELECT count(*) FROM app.analytics.hotel_daily_metrics' | Out-Null

Write-Output 'All read-only compatibility checks passed.'
