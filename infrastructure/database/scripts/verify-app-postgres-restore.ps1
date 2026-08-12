[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupFile,
    [Parameter(Mandatory)][string]$EncryptionKeyFile,
    [string]$TargetDatabase,
    [string]$Approval
)

$ErrorActionPreference = 'Stop'
$backupPath = [System.IO.Path]::GetFullPath($BackupFile)
$keyPath = [System.IO.Path]::GetFullPath($EncryptionKeyFile)
$evidencePath = "$backupPath.restore-evidence.json"
if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) { throw 'Encrypted backup file is required.' }
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'External encryption key file is required.' }
if ($TargetDatabase -and ($Approval -ne 'RESTORE_TO_ISOLATED_DB' -or $TargetDatabase -eq 'app_db')) {
    throw 'Restore requires an isolated target and -Approval RESTORE_TO_ISOLATED_DB.'
}

$started = Get-Date
$temporaryDump = Join-Path ([System.IO.Path]::GetTempPath()) ("answervice-restore-" + [guid]::NewGuid() + '.dump')
try {
    & gpg --batch --yes --decrypt --passphrase-file $keyPath --output $temporaryDump $backupPath
    if ($LASTEXITCODE -ne 0) { throw 'Backup decryption failed.' }
    & pg_restore --list $temporaryDump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore archive verification failed.' }

    $mode = 'archive-list-only'
    if ($TargetDatabase) {
        & pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges --dbname $TargetDatabase $temporaryDump
        if ($LASTEXITCODE -ne 0) { throw 'Isolated restore failed.' }
        $mode = 'isolated-restore'
    }
    $completed = Get-Date
    $ageHours = ($started.ToUniversalTime() - (Get-Item -LiteralPath $backupPath).LastWriteTimeUtc).TotalHours
    $durationHours = ($completed - $started).TotalHours
    [ordered]@{
        verified_at_utc = $completed.ToUniversalTime().ToString('o')
        mode = $mode
        backup_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupPath).Hash.ToLowerInvariant()
        backup_age_hours = [math]::Round($ageHours, 3)
        restore_duration_hours = [math]::Round($durationHours, 3)
        rpo_target_hours = 24
        rpo_passed = $ageHours -le 24
        rto_target_hours = 4
        rto_passed = $durationHours -le 4
    } | ConvertTo-Json | Set-Content -Encoding utf8 -LiteralPath $evidencePath
    "APP_POSTGRES_RESTORE_VERIFIED $evidencePath"
}
finally {
    if (Test-Path -LiteralPath $temporaryDump) { Remove-Item -Force -LiteralPath $temporaryDump }
}
