$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
Get-Content .env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { Set-Item "Env:$($matches[1])" $matches[2] } }
docker compose --env-file .env -f compose.yml config --quiet
$services = 'app-postgres','pms-postgres','banquet-postgres','pos-mysql','crm-mssql','facility-clickhouse'
$json = docker compose --env-file .env -f compose.yml ps --format json | ForEach-Object { $_ | ConvertFrom-Json }
foreach ($service in $services) { if (($json | Where-Object Service -eq $service).Health -ne 'healthy') { throw "$service is not healthy" } }
docker compose --env-file .env -f compose.yml exec -T -e PGPASSWORD=$env:PMS_READONLY_PASSWORD pms-postgres psql -U $env:PMS_READONLY_USER -d $env:PMS_DB_NAME -tAc 'SELECT count(*) FROM pms_guests' | Out-Null
docker compose --env-file .env -f compose.yml exec -T -e PGPASSWORD=$env:APP_DB_PASSWORD app-postgres psql -U $env:APP_DB_USER -d $env:APP_DB_NAME -tAc "INSERT INTO app.application_health VALUES (2, 'verified') ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status" | Out-Null
Write-Output 'All verification checks passed.'
