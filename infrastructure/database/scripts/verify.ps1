# 책임: live DB/Trino health, runtime relation discovery, source 계정의 write 거절을
# 함께 검증한다. 빈 catalog나 privilege regression은 즉시 실패한다.
[CmdletBinding()]
param([string]$EnvFilePath)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $databaseRoot 'compose.yml'
$probeTable = "verify_readonly_create_$PID"
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)
$values = Read-DeploymentEnvironment $resolvedEnvFile
Assert-DeploymentEnvironmentValues -Values $values -RequiredKeys @(
    'PMS_READONLY_USER', 'PMS_READONLY_PASSWORD', 'PMS_ADMIN_USER',
    'PMS_ADMIN_PASSWORD', 'PMS_DB_NAME', 'BANQUET_READONLY_USER',
    'BANQUET_READONLY_PASSWORD', 'BANQUET_ADMIN_USER',
    'BANQUET_ADMIN_PASSWORD', 'BANQUET_DB_NAME', 'POS_READONLY_USER',
    'POS_READONLY_PASSWORD', 'POS_ROOT_PASSWORD', 'POS_DB_NAME',
    'CRM_READONLY_USER', 'CRM_READONLY_PASSWORD', 'CRM_SA_PASSWORD',
    'CRM_DB_NAME', 'FACILITY_READONLY_USER', 'FACILITY_READONLY_PASSWORD',
    'FACILITY_ADMIN_USER', 'FACILITY_ADMIN_PASSWORD', 'TRINO_ADMIN_USER',
    'TRINO_ADMIN_PASSWORD', 'TRINO_TLS_CA_HOST_FILE'
)
Assert-ExternalDeploymentFile -Values $values -Key 'TRINO_TLS_CA_HOST_FILE' `
    -RepositoryRoot $repoRoot | Out-Null
if ([string]$values['TRINO_ADMIN_USER'] -cne 'answervice_platform_admin') {
    throw "Deployment environment key 'TRINO_ADMIN_USER' does not match the Trino ACL identity."
}

# Keep Compose invocation and exit-code handling in one boundary. The argument
# list is intentionally omitted from errors because it can contain passwords.
function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)

    $result = & docker compose @composeEnvArguments -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose command failed; inspect the service logs.'
    }
    return $result
}

# Statement protocol 호출은 container에 mount된 CA로 server identity를 확인하고
# Basic principal과 X-Trino-User를 동일하게 보낸다. nextUri도 coordinator origin을
# 벗어나면 credential 전달 전에 거절한다.
function Invoke-TrinoStatementRequest {
    param(
        [Parameter(Mandatory)] [ValidateSet('GET', 'POST')] [string]$Method,
        [Parameter(Mandatory)] [string]$Uri,
        [string]$Sql = ''
    )

    if (-not $Uri.StartsWith('https://trino:8443/', [StringComparison]::Ordinal)) {
        throw 'Trino nextUri escaped the authenticated coordinator origin.'
    }
    $previousProbeUser = $env:TRINO_PROBE_USER
    $previousProbePassword = $env:TRINO_PROBE_PASSWORD
    $env:TRINO_PROBE_USER = [string]$values['TRINO_ADMIN_USER']
    $env:TRINO_PROBE_PASSWORD = [string]$values['TRINO_ADMIN_PASSWORD']
    try {
        # `--env NAME`은 값 대신 환경 변수 이름만 argv에 넣는다. URI/SQL은 공개
        # readiness probe이고 credential 두 개만 process environment로 전달한다.
        $arguments = @(
            'exec', '-T', '--env', 'TRINO_PROBE_USER',
            '--env', 'TRINO_PROBE_PASSWORD', '--env', "TRINO_PROBE_URI=$Uri"
        )
        $command = if ($Method -eq 'POST') {
            $arguments += @('--env', "TRINO_PROBE_SQL=$Sql")
            'auth=$(printf "%s:%s" "$TRINO_PROBE_USER" "$TRINO_PROBE_PASSWORD" | base64 | tr -d "\r\n"); printf "header = \"Authorization: Basic %s\"\n" "$auth" | curl --config - --fail --silent --show-error --cacert /run/secrets/trino-ca.pem --header "X-Trino-User: $TRINO_PROBE_USER" --header "Content-Type: text/plain" --data-binary "$TRINO_PROBE_SQL" "$TRINO_PROBE_URI"'
        } else {
            'auth=$(printf "%s:%s" "$TRINO_PROBE_USER" "$TRINO_PROBE_PASSWORD" | base64 | tr -d "\r\n"); printf "header = \"Authorization: Basic %s\"\n" "$auth" | curl --config - --fail --silent --show-error --cacert /run/secrets/trino-ca.pem --header "X-Trino-User: $TRINO_PROBE_USER" "$TRINO_PROBE_URI"'
        }
        $response = Invoke-Compose -Arguments ($arguments + @('trino', 'sh', '-ec', $command))
        return (($response -join "`n") | ConvertFrom-Json)
    } finally {
        $env:TRINO_PROBE_USER = $previousProbeUser
        $env:TRINO_PROBE_PASSWORD = $previousProbePassword
    }
}

# Trino health와 connector query readiness는 다르다. bounded retry는 실제 인증된
# statement page를 끝까지 읽으며 startup window만 흡수하고 빈 data를 합성하지 않는다.
function Invoke-TrinoQuery {
    param([Parameter(Mandatory)] [string]$Sql)

    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $page = Invoke-TrinoStatementRequest -Method POST `
                -Uri 'https://trino:8443/v1/statement' -Sql $Sql
            $result = @()
            for ($pageNumber = 0; $pageNumber -lt 120; $pageNumber++) {
                if ($page.error) { throw [string]$page.error.message }
                foreach ($row in @($page.data)) {
                    if (@($row).Count) { $result += [string]$row[0] }
                }
                if (-not $page.nextUri) { return $result }
                $page = Invoke-TrinoStatementRequest -Method GET -Uri ([string]$page.nextUri)
            }
            throw 'Trino statement exceeded the page limit.'
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw 'Authenticated Trino connectors did not become query-ready within 120 seconds.'
}

# A source contract is considered present only when live metadata exposes at
# least one relation. Exact names and counts are discovered, never baked here.
function Assert-CatalogHasRelations {
    param([Parameter(Mandatory)] [string]$Catalog)

    $result = Invoke-TrinoQuery -Sql (
        "SELECT count(*) FROM $Catalog.information_schema.tables " +
        "WHERE table_schema <> 'information_schema'"
    )
    $count = [int64]((@($result) | Select-Object -Last 1).Trim())
    if ($count -lt 1) {
        throw "Catalog '$Catalog' has no discoverable runtime relations."
    }
    Write-Output "CATALOG_RELATIONS|$Catalog|$count"
}

# A successful CREATE proves a privilege regression. Cleanup runs before the
# failure is raised so a broken policy cannot leave a misleading probe table.
function Assert-ComposeDenied {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [scriptblock]$Cleanup
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker compose @composeEnvArguments -f $composeFile @Arguments *> $null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -eq 0) {
        & $Cleanup
        throw "$Name readonly account unexpectedly created a table."
    }
}

Invoke-Compose -Arguments @('config', '--quiet') | Out-Null

$services = @(
    'app-postgres', 'pms-postgres', 'banquet-postgres', 'pos-mysql',
    'crm-mssql', 'facility-clickhouse', 'trino'
)
$status = Invoke-Compose -Arguments @('ps', '-a', '--format', 'json') |
    ForEach-Object { $_ | ConvertFrom-Json }
foreach ($service in $services) {
    if (($status | Where-Object Service -eq $service).Health -ne 'healthy') {
        throw "$service is not healthy."
    }
}

$catalogs = Invoke-TrinoQuery -Sql 'SHOW CATALOGS'
$requiredCatalogs = @('serving', 'pms', 'banquet', 'pos', 'crm', 'facility')
foreach ($catalog in $requiredCatalogs) {
    if ($catalogs -notcontains $catalog) {
        throw "Trino catalog is missing: $catalog"
    }
    Assert-CatalogHasRelations -Catalog $catalog
}

Assert-ComposeDenied -Name 'pms-postgres' -Arguments @(
    'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'pms-postgres',
    'sh', '-ec', 'export PGPASSWORD="$SOURCE_READONLY_PASSWORD"; exec psql -U "$SOURCE_READONLY_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "CREATE TABLE public.$PROBE_TABLE (id integer)"'
) -Cleanup {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'pms-postgres',
        'sh', '-ec', 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "DROP TABLE IF EXISTS public.$PROBE_TABLE"'
    ) | Out-Null
}

Assert-ComposeDenied -Name 'banquet-postgres' -Arguments @(
    'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'banquet-postgres',
    'sh', '-ec', 'export PGPASSWORD="$SOURCE_READONLY_PASSWORD"; exec psql -U "$SOURCE_READONLY_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "CREATE TABLE public.$PROBE_TABLE (id integer)"'
) -Cleanup {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'banquet-postgres',
        'sh', '-ec', 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "DROP TABLE IF EXISTS public.$PROBE_TABLE"'
    ) | Out-Null
}

Assert-ComposeDenied -Name 'pos-mysql' -Arguments @(
    'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'pos-mysql',
    'sh', '-ec', 'export MYSQL_PWD="$POS_READONLY_PASSWORD"; exec mysql -u "$POS_READONLY_USER" -D "$MYSQL_DATABASE" -e "CREATE TABLE $PROBE_TABLE (id int)"'
) -Cleanup {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'pos-mysql',
        'sh', '-ec', 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -u root -D "$MYSQL_DATABASE" -e "DROP TABLE IF EXISTS $PROBE_TABLE"'
    ) | Out-Null
}

Assert-ComposeDenied -Name 'crm-mssql' -Arguments @(
    'exec', '-T', '--env', "PROBE_DATABASE=$($values.CRM_DB_NAME)",
    '--env', "PROBE_TABLE=$probeTable", 'crm-mssql', 'sh', '-ec',
    'export SQLCMDPASSWORD="$CRM_READONLY_PASSWORD"; exec /opt/mssql-tools18/bin/sqlcmd -S localhost -U "$CRM_READONLY_USER" -C -d "$PROBE_DATABASE" -b -Q "CREATE TABLE dbo.$PROBE_TABLE (id int)"'
) -Cleanup {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PROBE_DATABASE=$($values.CRM_DB_NAME)",
        '--env', "PROBE_TABLE=$probeTable", 'crm-mssql', 'sh', '-ec',
        'export SQLCMDPASSWORD="$MSSQL_SA_PASSWORD"; exec /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -d "$PROBE_DATABASE" -b -Q "DROP TABLE IF EXISTS dbo.$PROBE_TABLE"'
    ) | Out-Null
}

Assert-ComposeDenied -Name 'facility-clickhouse' -Arguments @(
    'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'facility-clickhouse',
    'sh', '-ec', 'export CLICKHOUSE_PASSWORD="$FACILITY_READONLY_PASSWORD"; exec clickhouse-client --user "$FACILITY_READONLY_USER" --query "CREATE TABLE $CLICKHOUSE_DB.$PROBE_TABLE (id UInt8) ENGINE=Memory"'
) -Cleanup {
    Invoke-Compose -Arguments @(
        'exec', '-T', '--env', "PROBE_TABLE=$probeTable", 'facility-clickhouse',
        'sh', '-ec', 'exec clickhouse-client --user "$CLICKHOUSE_USER" --query "DROP TABLE IF EXISTS $CLICKHOUSE_DB.$PROBE_TABLE"'
    ) | Out-Null
}

Write-Output 'DATABASE_RUNTIME_CONTRACT_VERIFIED'
