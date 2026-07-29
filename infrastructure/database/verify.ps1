[CmdletBinding()]
param(
    [switch]$SkipRestartTest
)

$ErrorActionPreference = 'Stop'
$databaseDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$services = @(
    'app-postgres',
    'pms-postgres',
    'banquet-postgres',
    'pos-mysql',
    'crm-mssql',
    'facility-clickhouse'
)

function Invoke-DockerChecked {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [Parameter(Mandatory)]
        [string]$FailureMessage
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "$FailureMessage`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-ServiceCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Service,
        [Parameter(Mandatory)]
        [string]$Command,
        [Parameter(Mandatory)]
        [string]$Description,
        [switch]$ExpectFailure
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $commandForStdin = $Command.TrimEnd("`r", "`n") + ' # end-of-command'
        $output = $commandForStdin | & docker compose exec -T $Service sh 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($ExpectFailure) {
        if ($exitCode -eq 0) {
            throw "$Description unexpectedly succeeded; the operation should have been denied."
        }
        Write-Host "[PASS] $Description (denied as expected)"
        return
    }

    if ($exitCode -ne 0) {
        throw "$Description failed`n$($output -join [Environment]::NewLine)"
    }
    Write-Host "[PASS] $Description"
}

Push-Location $databaseDirectory
try {
    Invoke-DockerChecked -Arguments @('compose', 'config', '--quiet') `
        -FailureMessage 'docker compose config validation failed' | Out-Null
    Write-Host '[PASS] docker compose config'

    foreach ($service in $services) {
        $containerId = (
            Invoke-DockerChecked -Arguments @('compose', 'ps', '-q', $service) `
                -FailureMessage "$service container lookup failed"
        ).Trim()
        if ([string]::IsNullOrWhiteSpace($containerId)) {
            throw "$service container is not running."
        }

        $health = (
            Invoke-DockerChecked -Arguments @(
                'inspect',
                '--format',
                '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}',
                $containerId
            ) -FailureMessage "$service state lookup failed"
        ).Trim()
        if ($health -ne 'healthy') {
            throw "$service is not healthy: $health"
        }
        Write-Host "[PASS] $service healthy"
    }

    $postgresSeedChecks = @{
        'app-postgres' = @'
actual=$(PGPASSWORD="$APP_DB_PASSWORD" psql -h 127.0.0.1 -U "$APP_DB_USER" -d "$POSTGRES_DB" -Atc "SELECT version || ':' || seed FROM app.schema_version WHERE version = '1.0.0';"); test "$actual" = "1.0.0:20260729"
'@
        'pms-postgres' = @'
actual=$(PGPASSWORD="$PMS_READONLY_PASSWORD" psql -h 127.0.0.1 -U "$PMS_READONLY_USER" -d "$POSTGRES_DB" -Atc "SELECT version || ':' || seed FROM pms.schema_version WHERE version = '1.0.0';"); test "$actual" = "1.0.0:20260729"
'@
        'banquet-postgres' = @'
actual=$(PGPASSWORD="$BANQUET_READONLY_PASSWORD" psql -h 127.0.0.1 -U "$BANQUET_READONLY_USER" -d "$POSTGRES_DB" -Atc "SELECT version || ':' || seed FROM banquet.schema_version WHERE version = '1.0.0';"); test "$actual" = "1.0.0:20260729"
'@
    }
    foreach ($entry in $postgresSeedChecks.GetEnumerator()) {
        Invoke-ServiceCommand -Service $entry.Key -Command $entry.Value.Trim() `
            -Description "$($entry.Key) schema version and seed"
    }

    $posSeedCheck = @'
actual=$(mysql -h 127.0.0.1 -u"$POS_READONLY_USER" -p"$POS_READONLY_PASSWORD" "$MYSQL_DATABASE" --batch --skip-column-names -e "SELECT CONCAT(version, ':', seed) FROM schema_version WHERE version = '1.0.0';" 2>/dev/null); test "$actual" = "1.0.0:20260729"
'@
    Invoke-ServiceCommand -Service 'pos-mysql' -Command $posSeedCheck.Trim() `
        -Description 'pos-mysql schema version and seed'

    $crmSeedCheck = @'
SQLCMD=/opt/mssql-tools18/bin/sqlcmd; [ -x "$SQLCMD" ] || SQLCMD=/opt/mssql-tools/bin/sqlcmd; "$SQLCMD" -S 127.0.0.1 -U "$CRM_READONLY_USER" -P "$CRM_READONLY_PASSWORD" -C -d "$CRM_DB_NAME" -b -Q "IF NOT EXISTS (SELECT 1 FROM crm.schema_version WHERE version = N'1.0.0' AND seed = 20260729) THROW 50001, 'Unexpected schema version or seed', 1;"
'@
    Invoke-ServiceCommand -Service 'crm-mssql' -Command $crmSeedCheck.Trim() `
        -Description 'crm-mssql schema version and seed'

    $facilitySeedCheck = @'
actual=$(clickhouse-client --host 127.0.0.1 --user "$FACILITY_READONLY_USER" --password "$FACILITY_READONLY_PASSWORD" --query "SELECT concat(version, ':', toString(seed)) FROM facility.schema_version FINAL WHERE version = '1.0.0' LIMIT 1"); test "$actual" = "1.0.0:20260729"
'@
    Invoke-ServiceCommand -Service 'facility-clickhouse' -Command $facilitySeedCheck.Trim() `
        -Description 'facility-clickhouse schema version and seed'

    $appWrite = @'
PGPASSWORD="$APP_DB_PASSWORD" psql -h 127.0.0.1 -U "$APP_DB_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc "INSERT INTO app.health_probe(probe_key, note) VALUES ('codex-verify', 'persistence-check') ON CONFLICT (probe_key) DO UPDATE SET note = EXCLUDED.note, updated_at = now(); SELECT note FROM app.health_probe WHERE probe_key = 'codex-verify';"
'@
    Invoke-ServiceCommand -Service 'app-postgres' -Command $appWrite.Trim() `
        -Description 'app-postgres application account read/write'

    $pmsSelect = @'
actual=$(PGPASSWORD="$PMS_READONLY_PASSWORD" psql -h 127.0.0.1 -U "$PMS_READONLY_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc "SELECT (SELECT count(*) FROM pms.reservation) || ':' || (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'pms');"); test "$actual" = "4:4"
'@
    Invoke-ServiceCommand -Service 'pms-postgres' -Command $pmsSelect.Trim() `
        -Description 'PMS read-only account SELECT'

    $pmsWrite = @'
PGPASSWORD="$PMS_READONLY_PASSWORD" psql -h 127.0.0.1 -U "$PMS_READONLY_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "INSERT INTO pms.hotel(hotel_id, hotel_name, city, timezone) VALUES (999, 'forbidden', 'Seoul', 'Asia/Seoul');"
'@
    Invoke-ServiceCommand -Service 'pms-postgres' -Command $pmsWrite.Trim() `
        -Description 'PMS read-only account INSERT' -ExpectFailure

    $banquetSelect = @'
actual=$(PGPASSWORD="$BANQUET_READONLY_PASSWORD" psql -h 127.0.0.1 -U "$BANQUET_READONLY_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc "SELECT (SELECT count(*) FROM banquet.event) || ':' || (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'banquet');"); test "$actual" = "3:4"
'@
    Invoke-ServiceCommand -Service 'banquet-postgres' -Command $banquetSelect.Trim() `
        -Description 'Banquet read-only account SELECT'

    $banquetWrite = @'
PGPASSWORD="$BANQUET_READONLY_PASSWORD" psql -h 127.0.0.1 -U "$BANQUET_READONLY_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "DELETE FROM banquet.event WHERE event_id = 20001;"
'@
    Invoke-ServiceCommand -Service 'banquet-postgres' -Command $banquetWrite.Trim() `
        -Description 'Banquet read-only account DELETE' -ExpectFailure

    $posSelect = @'
actual=$(mysql -h 127.0.0.1 -u"$POS_READONLY_USER" -p"$POS_READONLY_PASSWORD" "$MYSQL_DATABASE" --batch --skip-column-names -e "SELECT CONCAT((SELECT COUNT(*) FROM pos_transaction), ':', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$MYSQL_DATABASE'));" 2>/dev/null); test "$actual" = "5:4"
'@
    Invoke-ServiceCommand -Service 'pos-mysql' -Command $posSelect.Trim() `
        -Description 'POS read-only account SELECT'

    $posWrite = @'
mysql -h 127.0.0.1 -u"$POS_READONLY_USER" -p"$POS_READONLY_PASSWORD" "$MYSQL_DATABASE" -e "UPDATE menu_item SET unit_price = 1 WHERE menu_item_id = 101;"
'@
    Invoke-ServiceCommand -Service 'pos-mysql' -Command $posWrite.Trim() `
        -Description 'POS read-only account UPDATE' -ExpectFailure

    $crmSelect = @'
SQLCMD=/opt/mssql-tools18/bin/sqlcmd; [ -x "$SQLCMD" ] || SQLCMD=/opt/mssql-tools/bin/sqlcmd; "$SQLCMD" -S 127.0.0.1 -U "$CRM_READONLY_USER" -P "$CRM_READONLY_PASSWORD" -C -d "$CRM_DB_NAME" -b -Q "IF (SELECT COUNT(*) FROM crm.member_profile) <> 3 THROW 50002, 'Unexpected synthetic row count', 1; IF (SELECT COUNT(*) FROM sys.tables WHERE schema_id = SCHEMA_ID(N'crm')) <> 4 THROW 50003, 'Metadata visibility failed', 1;"
'@
    Invoke-ServiceCommand -Service 'crm-mssql' -Command $crmSelect.Trim() `
        -Description 'CRM read-only account SELECT'

    $crmWrite = @'
SQLCMD=/opt/mssql-tools18/bin/sqlcmd; [ -x "$SQLCMD" ] || SQLCMD=/opt/mssql-tools/bin/sqlcmd; "$SQLCMD" -S 127.0.0.1 -U "$CRM_READONLY_USER" -P "$CRM_READONLY_PASSWORD" -C -d "$CRM_DB_NAME" -b -Q "DELETE FROM crm.member_profile WHERE member_id = 40001;"
'@
    Invoke-ServiceCommand -Service 'crm-mssql' -Command $crmWrite.Trim() `
        -Description 'CRM read-only account DELETE' -ExpectFailure

    $facilitySelect = @'
actual=$(clickhouse-client --host 127.0.0.1 --user "$FACILITY_READONLY_USER" --password "$FACILITY_READONLY_PASSWORD" --query "SELECT concat(toString((SELECT count(*) FROM facility.work_order)), ':', toString((SELECT count(*) FROM system.tables WHERE database = 'facility')))"); test "$actual" = "3:4"
'@
    Invoke-ServiceCommand -Service 'facility-clickhouse' -Command $facilitySelect.Trim() `
        -Description 'Facility read-only account SELECT'

    $facilityWrite = @'
clickhouse-client --host 127.0.0.1 --user "$FACILITY_READONLY_USER" --password "$FACILITY_READONLY_PASSWORD" --query "TRUNCATE TABLE facility.work_order"
'@
    Invoke-ServiceCommand -Service 'facility-clickhouse' -Command $facilityWrite.Trim() `
        -Description 'Facility read-only account DDL' -ExpectFailure

    $pmsId = (& docker compose ps -q pms-postgres).Trim()
    $banquetId = (& docker compose ps -q banquet-postgres).Trim()
    $pmsInspectJson = & docker inspect $pmsId
    if ($LASTEXITCODE -ne 0) {
        throw 'PMS container inspect failed.'
    }
    $banquetInspectJson = & docker inspect $banquetId
    if ($LASTEXITCODE -ne 0) {
        throw 'Banquet container inspect failed.'
    }
    $pmsInspect = ($pmsInspectJson -join [Environment]::NewLine) | ConvertFrom-Json
    $banquetInspect = ($banquetInspectJson -join [Environment]::NewLine) | ConvertFrom-Json
    $pmsVolume = (
        $pmsInspect[0].Mounts |
            Where-Object { $_.Destination -eq '/var/lib/postgresql/data' } |
            Select-Object -ExpandProperty Name
    )
    $banquetVolume = (
        $banquetInspect[0].Mounts |
            Where-Object { $_.Destination -eq '/var/lib/postgresql/data' } |
            Select-Object -ExpandProperty Name
    )
    if ([string]::IsNullOrWhiteSpace($pmsVolume) -or $pmsVolume -eq $banquetVolume) {
        throw 'PMS and Banquet PostgreSQL data volumes are not isolated.'
    }
    Write-Host '[PASS] PMS/Banquet PostgreSQL volume isolation'

    $crossLogin = @'
PGPASSWORD="$PMS_READONLY_PASSWORD" psql -h banquet-postgres -U "$PMS_READONLY_USER" -d banquet_db -v ON_ERROR_STOP=1 -Atc "SELECT 1;"
'@
    Invoke-ServiceCommand -Service 'pms-postgres' -Command $crossLogin.Trim() `
        -Description 'PMS account cross-login to Banquet DB' -ExpectFailure

    if (-not $SkipRestartTest) {
        Invoke-DockerChecked -Arguments @('compose', 'restart', 'app-postgres') `
            -FailureMessage 'app-postgres restart failed' | Out-Null
        Invoke-DockerChecked -Arguments @('compose', 'up', '-d', '--wait', '--wait-timeout', '180', 'app-postgres') `
            -FailureMessage 'app-postgres healthcheck failed after restart' | Out-Null

        $persistenceRead = @'
PGPASSWORD="$APP_DB_PASSWORD" psql -h 127.0.0.1 -U "$APP_DB_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc "SELECT note FROM app.health_probe WHERE probe_key = 'codex-verify';"
'@
        Invoke-ServiceCommand -Service 'app-postgres' -Command $persistenceRead.Trim() `
            -Description 'data persistence after container restart'
    }

    $cleanup = @'
PGPASSWORD="$APP_DB_PASSWORD" psql -h 127.0.0.1 -U "$APP_DB_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "DELETE FROM app.health_probe WHERE probe_key = 'codex-verify';"
'@
    Invoke-ServiceCommand -Service 'app-postgres' -Command $cleanup.Trim() `
        -Description 'verification probe cleanup'

    Write-Host ''
    Write-Host 'All verification checks passed.'
}
finally {
    Pop-Location
}
