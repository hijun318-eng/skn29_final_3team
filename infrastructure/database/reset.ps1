[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$databaseDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $databaseDirectory

try {
    if (-not $Force) {
        $answer = Read-Host 'This deletes every hotel-synthetic-db volume and recreates fixed seed data. Type RESET to continue'
        if ($answer -cne 'RESET') {
            Write-Host 'Cancelled.'
            return
        }
    }

    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose config validation failed.'
    }

    & docker compose down --volumes --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to delete existing project volumes.'
    }

    & docker compose up -d --wait --wait-timeout 420
    if ($LASTEXITCODE -ne 0) {
        throw 'Fixed-seed recreation or healthcheck wait failed.'
    }

    & docker compose ps
}
finally {
    Pop-Location
}
