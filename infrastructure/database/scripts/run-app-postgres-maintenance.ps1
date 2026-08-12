[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupDirectory,
    [Parameter(Mandatory)][string]$EncryptionKeyFile,
    [Parameter(Mandatory)][string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
$mutex = [System.Threading.Mutex]::new($false, 'Local\AnswerviceAppPostgresMaintenance')
if (-not $mutex.WaitOne(0)) { throw 'APP_POSTGRES_MAINTENANCE_ALREADY_RUNNING' }

try {
    & (Join-Path $PSScriptRoot 'backup-app-postgres.ps1') `
        -OutputDirectory $BackupDirectory `
        -EncryptionKeyFile $EncryptionKeyFile `
        -EvidenceDirectory $EvidenceDirectory
    & (Join-Path $PSScriptRoot 'retention-app-postgres.ps1') `
        -EvidenceDirectory $EvidenceDirectory
    'APP_POSTGRES_DAILY_MAINTENANCE_COMPLETED'
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
