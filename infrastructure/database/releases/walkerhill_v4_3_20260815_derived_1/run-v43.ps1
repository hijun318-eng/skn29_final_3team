param(
    [ValidateSet("Source", "Trino", "Realism", "All")]
    [string]$Phase = "Source",
    [ValidateSet("All", "PMS", "Banquet", "POS", "CRM", "Facility")]
    [string]$SourceDomain = "All",
    [string]$ReceiptRoot = (Join-Path $env:TEMP "walkerhill-v4.3-sql-20260815-derived.1")
)

$ErrorActionPreference = "Stop"
$releaseId = "walkerhill-v4.3-sql-20260815-derived.1"
$releaseRoot = $PSScriptRoot
$sqlRoot = Join-Path $releaseRoot "01_V4.3_생성_및_서빙_SQL"
$realismRoot = Join-Path $releaseRoot "02_V4.3_현실성_검증_SQL"
$logRoot = Join-Path $ReceiptRoot "logs"
$receiptPath = Join-Path $ReceiptRoot "receipts.jsonl"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Get-KstTimestamp {
    [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Korea Standard Time").ToString("o")
}

function Get-OutputHash([string]$text) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        ($algorithm.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
    }
    finally {
        $algorithm.Dispose()
    }
}

function Invoke-V43Sql {
    param(
        [Parameter(Mandatory)][string]$Container,
        [Parameter(Mandatory)][ValidateSet("postgres", "mysql", "mssql", "clickhouse", "trino")][string]$Engine,
        [Parameter(Mandatory)][string]$File
    )

    $resolved = (Resolve-Path -LiteralPath $File).Path
    $relative = $resolved.Substring($script:releaseRoot.Length).TrimStart("\").Replace("\", "/")
    $sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    $safeName = ($relative -replace '[^A-Za-z0-9._-]', '_')
    $logPath = Join-Path $logRoot "$safeName.log"
    $startedAt = Get-KstTimestamp
    $timer = [Diagnostics.Stopwatch]::StartNew()

    & docker cp $resolved "${Container}:/tmp/v43_current.sql" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "docker cp failed: $relative"
    }

    $command = switch ($Engine) {
        "postgres" { 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/v43_current.sql' }
        "mysql" { 'mysql --default-character-set=utf8mb4 --batch --show-warnings --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" < /tmp/v43_current.sql' }
        "mssql" { '/opt/mssql-tools18/bin/sqlcmd -C -b -S localhost -d crm_db -U sa -P "$MSSQL_SA_PASSWORD" -i /tmp/v43_current.sql' }
        "clickhouse" { 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery --queries-file /tmp/v43_current.sql' }
        "trino" { 'trino --server http://localhost:8080 --user hotel_synthetic_setup --file /tmp/v43_current.sql' }
    }

    $shell = if ($Engine -eq "mssql") { "bash" } else { "sh" }
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& docker exec $Container $shell -lc $command 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    $timer.Stop()
    [IO.File]::WriteAllText($logPath, $output, [Text.UTF8Encoding]::new($false))

    $status = if ($exitCode -ne 0 -or $output -match '(?im)\bFAIL\b') { "FAIL" } else { "PASS" }
    $receipt = [ordered]@{
        release_id = $releaseId
        relative_path = $relative
        sha256 = $sha256
        container = $Container
        engine = $Engine
        started_at_kst = $startedAt
        ended_at_kst = Get-KstTimestamp
        duration_seconds = [math]::Round($timer.Elapsed.TotalSeconds, 3)
        exit_code = $exitCode
        status = $status
        output_sha256 = Get-OutputHash $output
        log_path = $logPath
    }
    Add-Content -LiteralPath $receiptPath -Value ($receipt | ConvertTo-Json -Compress) -Encoding UTF8
    Write-Host ("{0} {1} ({2:n1}s)" -f $status, $relative, $timer.Elapsed.TotalSeconds)

    if ($status -eq "FAIL") {
        throw "V4.3 SQL gate failed: $relative (see $logPath)"
    }
}

$sourceDomains = @(
    @{ Container = "pms-postgres"; Engine = "postgres"; Directory = "01_postgresql_pms"; Files = @("00_postgresql_pms_preflight_readonly.sql", "10_postgresql_pms_reference_ddl.sql", "11_postgresql_pms_operation_ddl.sql", "20_postgresql_pms_reference_seed.sql", "21_postgresql_pms_event_seed.sql", "30_postgresql_pms_inventory_seed.sql", "31_postgresql_pms_guest_reservation_seed.sql", "32_postgresql_pms_status_stay_seed.sql", "33_postgresql_pms_folio_seed.sql", "40_postgresql_pms_constraints_indexes.sql", "50_postgresql_pms_validation.sql") },
    @{ Container = "banquet-postgres"; Engine = "postgres"; Directory = "02_postgresql_banquet"; Files = @("00_postgresql_banquet_preflight_readonly.sql", "10_postgresql_banquet_ddl.sql", "20_postgresql_banquet_venue_seed.sql", "30_postgresql_banquet_booking_seed.sql", "31_postgresql_banquet_status_history_seed.sql", "32_postgresql_banquet_revenue_block_seed.sql", "40_postgresql_banquet_constraints_indexes.sql", "50_postgresql_banquet_validation.sql") },
    @{ Container = "pos-mysql"; Engine = "mysql"; Directory = "03_mysql_pos"; Files = @("00_mysql_pos_preflight_readonly.sql", "10_mysql_pos_ddl.sql", "20_mysql_pos_outlet_menu_seed.sql", "21_mysql_pos_menu_price_history_seed.sql", "30_mysql_pos_order_seed.sql", "31_mysql_pos_order_item_seed.sql", "32_mysql_pos_payment_refund_seed.sql", "40_mysql_pos_constraints_indexes.sql", "41_mysql_pos_readonly_grant.sql", "50_mysql_pos_validation.sql") },
    @{ Container = "crm-mssql"; Engine = "mssql"; Directory = "04_sqlserver_crm"; Files = @("00_sqlserver_crm_preflight_readonly.sql", "10_sqlserver_crm_ddl.sql", "20_sqlserver_crm_tier_member_seed.sql", "30_sqlserver_crm_grade_history_seed.sql", "31_sqlserver_crm_point_transaction_seed.sql", "32_sqlserver_crm_customer_map_seed.sql", "33_sqlserver_crm_voc_review_seed.sql", "40_sqlserver_crm_constraints_indexes.sql", "50_sqlserver_crm_validation.sql") },
    @{ Container = "facility-clickhouse"; Engine = "clickhouse"; Directory = "05_clickhouse_facility"; Files = @("00_clickhouse_facility_preflight_readonly.sql", "10_clickhouse_facility_ddl.sql", "20_clickhouse_facility_master_seed.sql", "30_clickhouse_facility_usage_seed.sql", "31_clickhouse_facility_incident_seed.sql", "32_clickhouse_facility_staffing_seed.sql", "33_clickhouse_facility_resource_seed.sql", "40_clickhouse_facility_indexes_settings.sql", "41_clickhouse_facility_readonly_grant.sql", "50_clickhouse_facility_validation.sql") }
)

if ($Phase -in @("Source", "All")) {
    $sourceContainer = @{
        PMS = "pms-postgres"
        Banquet = "banquet-postgres"
        POS = "pos-mysql"
        CRM = "crm-mssql"
        Facility = "facility-clickhouse"
    }
    foreach ($domain in $sourceDomains) {
        if ($SourceDomain -ne "All" -and $domain.Container -ne $sourceContainer[$SourceDomain]) {
            continue
        }
        foreach ($name in $domain.Files) {
            Invoke-V43Sql -Container $domain.Container -Engine $domain.Engine -File (Join-Path $sqlRoot "$($domain.Directory)/$name")
        }
    }
}

if ($Phase -in @("Trino", "All")) {
    foreach ($name in @("00_trino_source_preflight_readonly.sql", "10_trino_serving_schema.sql", "20_trino_room_views.sql", "21_trino_fnb_views.sql", "22_trino_membership_views.sql", "23_trino_banquet_views.sql", "24_trino_facility_views.sql", "25_trino_integrated_hotel_views.sql", "26_trino_voc_views.sql", "30_trino_cross_source_validation.sql", "31_trino_event_counterfactual_validation.sql")) {
        Invoke-V43Sql -Container "hotel-synthetic-db-trino-1" -Engine "trino" -File (Join-Path $sqlRoot "06_trino_serving/$name")
    }
}

if ($Phase -in @("Realism", "All")) {
    $realism = @(
        @{ Container = "pms-postgres"; Engine = "postgres"; File = "01_postgresql_pms/51_postgresql_pms_realism_validation.sql" },
        @{ Container = "banquet-postgres"; Engine = "postgres"; File = "02_postgresql_banquet/51_postgresql_banquet_realism_validation.sql" },
        @{ Container = "pos-mysql"; Engine = "mysql"; File = "03_mysql_pos/51_mysql_pos_realism_validation.sql" },
        @{ Container = "crm-mssql"; Engine = "mssql"; File = "04_sqlserver_crm/51_sqlserver_crm_realism_validation.sql" },
        @{ Container = "facility-clickhouse"; Engine = "clickhouse"; File = "05_clickhouse_facility/51_clickhouse_facility_realism_validation.sql" },
        @{ Container = "hotel-synthetic-db-trino-1"; Engine = "trino"; File = "06_trino_serving/32_trino_realism_validation.sql" }
    )
    foreach ($item in $realism) {
        Invoke-V43Sql -Container $item.Container -Engine $item.Engine -File (Join-Path $realismRoot $item.File)
    }
}
