[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$EncryptionKeyFile,
    [string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$keyPath = [System.IO.Path]::GetFullPath($EncryptionKeyFile)
$gpgPath = (Get-Command gpg -ErrorAction SilentlyContinue).Source
if (-not $gpgPath -and (Test-Path -LiteralPath 'C:\Program Files\Git\usr\bin\gpg.exe')) {
    $gpgPath = 'C:\Program Files\Git\usr\bin\gpg.exe'
}
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'External encryption key file is required.' }
if (-not $gpgPath) { throw 'gpg is required. Install GnuPG or Git for Windows.' }
$containers = @(docker ps --quiet --filter 'label=com.docker.compose.service=app-postgres' --filter 'status=running')
if ($LASTEXITCODE -ne 0 -or $containers.Count -ne 1) { throw 'Exactly one running app-postgres container is required.' }
$containerId = $containers[0]
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$plainPath = Join-Path $outputRoot "app-postgres-$stamp.dump"
$encryptedPath = "$plainPath.gpg"
try {
    docker exec $containerId `
        sh -c 'exec pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format custom --no-owner --no-privileges' `
        | Set-Content -LiteralPath $plainPath -AsByteStream
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
    & $gpgPath --batch --yes --symmetric --cipher-algo AES256 --passphrase-file $keyPath --output $encryptedPath $plainPath
    if ($LASTEXITCODE -ne 0) { throw 'Backup encryption failed.' }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $encryptedPath).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        backup_file = [System.IO.Path]::GetFileName($encryptedPath)
        sha256 = $hash
        encrypted = $true
        schedule = 'daily'
        rpo_target_hours = 24
    } | ConvertTo-Json
    $manifest | Set-Content -Encoding utf8 -LiteralPath "$encryptedPath.json"
    if ($EvidenceDirectory) {
        $evidenceRoot = [System.IO.Path]::GetFullPath($EvidenceDirectory)
        New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
        $manifest | Set-Content -Encoding utf8 -LiteralPath (Join-Path $evidenceRoot ([System.IO.Path]::GetFileName("$encryptedPath.json")))
    }
    "APP_POSTGRES_BACKUP_CREATED $encryptedPath"
}
finally {
    if (Test-Path -LiteralPath $plainPath) { Remove-Item -Force -LiteralPath $plainPath }
}
