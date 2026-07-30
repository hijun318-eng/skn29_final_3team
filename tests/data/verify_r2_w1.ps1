[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$databaseRoot = Join-Path $root 'infrastructure\database'
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'
$values = @{}

if (-not (Test-Path -LiteralPath $localEnv)) {
    throw '.env is missing.'
}
Get-Content -LiteralPath $localEnv -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*([^#=\s]+)=(.*)$') {
        $values[$matches[1]] = $matches[2].Trim()
    }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    $result = & docker compose --env-file $localEnv -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose command failed; arguments and secrets are intentionally omitted.'
    }
    return $result
}

function Assert-Denied {
    param(
        [string]$Name,
        [string]$ExpectedPattern,
        [string[]]$Arguments
    )
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & docker compose --env-file $localEnv -f $composeFile @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($exitCode -eq 0) {
        throw "$Name was unexpectedly allowed."
    }
    if ((@($result) -join "`n") -notmatch $ExpectedPattern) {
        throw "$Name failed for an unexpected reason."
    }
}

& powershell -NoProfile -ExecutionPolicy Bypass -File (
    Join-Path $databaseRoot 'scripts\verify.ps1'
)
if ($LASTEXITCODE -ne 0) {
    throw 'Base database verification failed.'
}

$contract = Get-Content -Raw -Encoding UTF8 (
    Join-Path $root 'src\data\r2_w1_contract.v1.json'
) | ConvertFrom-Json
$state = @()
$state += Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.PMS_READONLY_PASSWORD)",
    'pms-postgres', 'psql', '-U', $values.PMS_READONLY_USER, '-d', $values.PMS_DB_NAME,
    '-At', '-F', '|', '-c',
    "SELECT 'pms.pms_guests',count(*),md5(string_agg(guest_id,',' ORDER BY guest_id)) FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'pms.pms_room_inventory_daily',count(*),md5(sum(inventory_id)::text) FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'pms.pms_reservations',count(*),md5(sum(hashtext(reservation_id))::text) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'pms.pms_stays',count(*),md5(sum(hashtext(stay_id))::text) FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001'"
)
$state += Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "MYSQL_PWD=$($values.POS_READONLY_PASSWORD)",
    'pos-mysql', 'mysql', "-u$($values.POS_READONLY_USER)", "-D$($values.POS_DB_NAME)",
    '-N', '-B', '-e',
    "SELECT 'pos.pos_stores',COUNT(*),SHA2(GROUP_CONCAT(store_id ORDER BY store_id),256) FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'pos.pos_service_periods',COUNT(*),SHA2(SUM(service_period_id),256) FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'pos.pos_orders',COUNT(*),SHA2(SUM(CRC32(order_id)),256) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'pos.pos_order_items',COUNT(*),SHA2(SUM(CRC32(order_item_id)),256) FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001'"
)
$state += Invoke-Compose -Arguments @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', $values.CRM_READONLY_USER, '-P', $values.CRM_READONLY_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-h', '-1', '-W', '-s', '|', '-Q',
    "SET NOCOUNT ON; SELECT 'crm.crm_members',COUNT_BIG(*),CHECKSUM_AGG(BINARY_CHECKSUM(member_no,membership_grade,points_balance)) FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'crm.crm_member_grade_history',COUNT_BIG(*),CHECKSUM_AGG(BINARY_CHECKSUM(grade_history_id,grade_code)) FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'crm.crm_point_transactions',COUNT_BIG(*),CHECKSUM_AGG(BINARY_CHECKSUM(point_txn_id,points_delta)) FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'crm.crm_customer_map',COUNT_BIG(*),CHECKSUM_AGG(BINARY_CHECKSUM(customer_map_id,member_no)) FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001'"
)
$state += Invoke-Compose -Arguments @(
    'exec', '-T', 'facility-clickhouse', 'clickhouse-client',
    '--user', $values.FACILITY_READONLY_USER, '--password', $values.FACILITY_READONLY_PASSWORD,
    '--query',
    "SELECT 'facility.facility_master',count(),hex(groupBitXor(cityHash64(facility_id))) FROM facility.facility_master WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'facility.facility_events',count(),hex(groupBitXor(cityHash64(event_id))) FROM facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'facility.hotel_staffing_daily',count(),hex(groupBitXor(cityHash64(staffing_id))) FROM facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'facility.facility_resource_daily',count(),hex(groupBitXor(cityHash64(resource_id))) FROM facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' FORMAT TSVRaw"
)
$state += Invoke-Compose -Arguments @(
    'exec', '-T', '--env', "PGPASSWORD=$($values.BANQUET_READONLY_PASSWORD)",
    'banquet-postgres', 'psql', '-U', $values.BANQUET_READONLY_USER, '-d', $values.BANQUET_DB_NAME,
    '-At', '-F', '|', '-c',
    "SELECT 'banquet.banquet_bookings',count(*),md5(sum(hashtext(banquet_event_id))::text) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' UNION ALL SELECT 'banquet.banquet_revenue',count(*),md5(sum(hashtext(revenue_id))::text) FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001'"
)
$actualState = @($state) | ForEach-Object {
    $_.Trim().Replace("`t", '|') -replace '\s*\|\s*', '|'
} | Where-Object { $_ } | Sort-Object
$expectedState = $contract.data_state_manifest | ForEach-Object {
    "$($_.entity)|$($_.row_count)|$($_.checksum)"
} | Sort-Object
if (Compare-Object $expectedState $actualState) {
    throw 'Deterministic data state manifest mismatch.'
}

$crmQuality = Invoke-Compose -Arguments @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', $values.CRM_READONLY_USER, '-P', $values.CRM_READONLY_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-h', '-1', '-W', '-Q', @'
SET NOCOUNT ON;
SELECT CONCAT(
  (SELECT COUNT_BIG(*) FROM dbo.crm_customer_map WHERE is_synthetic=0), '|',
  (SELECT COUNT_BIG(*) FROM dbo.crm_member_grade_history WHERE is_synthetic=0), '|',
  (SELECT COUNT_BIG(*) FROM dbo.crm_customer_map a JOIN dbo.crm_customer_map b
     ON a.customer_map_id < b.customer_map_id AND a.property_id=b.property_id
    AND a.member_no=b.member_no
    AND a.valid_from < COALESCE(b.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999'))
    AND b.valid_from < COALESCE(a.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999'))), '|',
  (SELECT COUNT_BIG(*) FROM dbo.crm_member_grade_history a JOIN dbo.crm_member_grade_history b
     ON a.grade_history_id < b.grade_history_id AND a.property_id=b.property_id
    AND a.member_no=b.member_no
    AND a.valid_from < COALESCE(b.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999'))
    AND b.valid_from < COALESCE(a.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999')))
);
'@
)
if ((@($crmQuality) -join '').Trim() -ne '0|0|0|0') {
    throw 'CRM quality contract failed.'
}

Assert-Denied 'CRM identity overlap' 'CRM_IDENTITY_PERIOD_OVERLAP' @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', 'sa', '-P', $values.CRM_SA_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-Q',
    "SET XACT_ABORT ON; SET QUOTED_IDENTIFIER ON; SET ANSI_NULLS ON; SET ANSI_WARNINGS ON; SET ANSI_PADDING ON; SET CONCAT_NULL_YIELDS_NULL ON; SET ARITHABORT ON; SET NUMERIC_ROUNDABORT OFF; BEGIN TRANSACTION; INSERT dbo.crm_customer_map VALUES ('SYNTHETIC_HOTEL_001','MAP-REJECT-OVERLAP','MEM-00000001','GST-00000001',NULL,NULL,NULL,'2023-01-01','2023-02-01','REVOKED',0.9000,1,'2026-07-28T05:00:00'); ROLLBACK"
)
Assert-Denied 'CRM grade overlap' 'CRM_GRADE_PERIOD_OVERLAP' @(
    'exec', '-T', 'crm-mssql', '/opt/mssql-tools18/bin/sqlcmd',
    '-S', 'localhost', '-U', 'sa', '-P', $values.CRM_SA_PASSWORD,
    '-C', '-d', $values.CRM_DB_NAME, '-b', '-Q',
    "SET XACT_ABORT ON; SET QUOTED_IDENTIFIER ON; SET ANSI_NULLS ON; SET ANSI_WARNINGS ON; SET ANSI_PADDING ON; SET CONCAT_NULL_YIELDS_NULL ON; SET ARITHABORT ON; SET NUMERIC_ROUNDABORT OFF; BEGIN TRANSACTION; INSERT dbo.crm_member_grade_history VALUES ('SYNTHETIC_HOTEL_001','GRD-REJECT-OVERLAP','MEM-00000001','BASIC','2022-06-01','2022-07-01','REVIEW',1,'2026-07-28T05:00:00'); ROLLBACK"
)
Assert-Denied 'Trino write' 'Access Denied|Cannot create table' @(
    'exec', '-T', 'trino', 'trino', '--server', 'http://localhost:8080',
    '--user', 'hotel_synthetic_verify', '--execute',
    'CREATE TABLE serving.analytics.rejected_write (id integer)'
)
Assert-Denied 'Trino system catalog' 'Access Denied|Cannot access catalog system' @(
    'exec', '-T', 'trino', 'trino', '--server', 'http://localhost:8080',
    '--user', 'hotel_synthetic_verify', '--execute',
    'SELECT node_id FROM system.runtime.nodes'
)
Assert-Denied 'Trino passthrough query' 'Access Denied|Cannot execute function|Cannot select from columns' @(
    'exec', '-T', 'trino', 'trino', '--server', 'http://localhost:8080',
    '--user', 'hotel_synthetic_verify', '--execute',
    "SELECT * FROM TABLE(crm.system.query(query => 'SELECT 1'))"
)

Write-Output 'R2_W1_CONTRACT_VERIFIED'
