[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$databaseDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $databaseDirectory

try {
    if (-not (Test-Path -LiteralPath '.env')) {
        throw '.env is missing. Copy .env.example and change every password.'
    }

    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose config validation failed.'
    }

    & docker compose up -d --wait --wait-timeout 420
    if ($LASTEXITCODE -ne 0) {
        throw 'Database startup or healthcheck wait failed.'
    }

    & docker compose ps
}
finally {
    Pop-Location
}
