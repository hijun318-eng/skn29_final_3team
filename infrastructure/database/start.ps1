$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env -f compose.yml up -d --wait --wait-timeout 420
docker compose --env-file .env -f compose.yml run --rm crm-mssql-init
docker compose --env-file .env -f compose.yml ps
