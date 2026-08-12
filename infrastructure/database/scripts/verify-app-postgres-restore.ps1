[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupFile,
    [Parameter(Mandatory)][string]$EncryptionKeyFile,
    [string]$TargetDatabase,
    [string]$Approval,
    [string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
$backupPath = [System.IO.Path]::GetFullPath($BackupFile)
$keyPath = [System.IO.Path]::GetFullPath($EncryptionKeyFile)
$evidencePath = "$backupPath.restore-evidence.json"
$gpgPath = (Get-Command gpg -ErrorAction SilentlyContinue).Source
if (-not $gpgPath -and (Test-Path -LiteralPath 'C:\Program Files\Git\usr\bin\gpg.exe')) {
    $gpgPath = 'C:\Program Files\Git\usr\bin\gpg.exe'
}
if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) { throw 'Encrypted backup file is required.' }
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'External encryption key file is required.' }
if (-not $gpgPath) { throw 'gpg is required. Install GnuPG or Git for Windows.' }
if ($TargetDatabase -and ($Approval -ne 'RESTORE_TO_ISOLATED_DB' -or $TargetDatabase -eq 'app_db')) {
    throw 'Restore requires an isolated target and -Approval RESTORE_TO_ISOLATED_DB.'
}

$started = Get-Date
$temporaryDump = Join-Path ([System.IO.Path]::GetTempPath()) ("answervice-restore-" + [guid]::NewGuid() + '.dump')
$containerDump = "/tmp/answervice-restore-$([guid]::NewGuid().ToString('N')).dump"
$containerId = $null
try {
    & $gpgPath --batch --yes --decrypt --passphrase-file $keyPath --output $temporaryDump $backupPath
    if ($LASTEXITCODE -ne 0) { throw 'Backup decryption failed.' }
    $containers = @(docker ps --quiet --filter 'label=com.docker.compose.service=app-postgres' --filter 'status=running')
    if ($LASTEXITCODE -ne 0 -or $containers.Count -ne 1) { throw 'Exactly one running app-postgres container is required.' }
    $containerId = $containers[0]
    docker cp $temporaryDump "${containerId}:$containerDump" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Copying backup into app-postgres failed.' }
    docker exec $containerId pg_restore --list $containerDump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore archive verification failed.' }

    $mode = 'archive-list-only'
    if ($TargetDatabase) {
        docker exec $containerId `
            pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges --dbname $TargetDatabase $containerDump
        if ($LASTEXITCODE -ne 0) { throw 'Isolated restore failed.' }
        $mode = 'isolated-restore'
    }
    $completed = Get-Date
    $ageHours = ($started.ToUniversalTime() - (Get-Item -LiteralPath $backupPath).LastWriteTimeUtc).TotalHours
    $durationHours = ($completed - $started).TotalHours
    $evidence = [ordered]@{
        verified_at_utc = $completed.ToUniversalTime().ToString('o')
        mode = $mode
        backup_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupPath).Hash.ToLowerInvariant()
        backup_age_hours = [math]::Round($ageHours, 3)
        restore_duration_hours = [math]::Round($durationHours, 3)
        rpo_target_hours = 24
        rpo_passed = $ageHours -le 24
        rto_target_hours = 4
        rto_passed = $durationHours -le 4
    } | ConvertTo-Json
    $evidence | Set-Content -Encoding utf8 -LiteralPath $evidencePath
    if ($EvidenceDirectory) {
        $evidenceRoot = [System.IO.Path]::GetFullPath($EvidenceDirectory)
        New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
        $evidence | Set-Content -Encoding utf8 -LiteralPath (Join-Path $evidenceRoot ([System.IO.Path]::GetFileName($evidencePath)))
    }
    "APP_POSTGRES_RESTORE_VERIFIED $evidencePath"
}
finally {
    if ($containerId) {
        docker exec $containerId rm -f -- $containerDump | Out-Null
    }
    if (Test-Path -LiteralPath $temporaryDump) { Remove-Item -Force -LiteralPath $temporaryDump }
}
