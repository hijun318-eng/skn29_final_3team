param([switch]$Force)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!$Force) { $answer = Read-Host 'Delete only hotel-synthetic-db volumes? Type YES'; if ($answer -ne 'YES') { exit } }
docker compose --env-file .env -f compose.yml down -v
& "$PSScriptRoot\start.ps1"
