[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$EncryptionKeyFile,
    [string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$environmentFile = Join-Path $databaseRoot '.env'
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$keyPath = [System.IO.Path]::GetFullPath($EncryptionKeyFile)
if (-not (Test-Path -LiteralPath $environmentFile)) { throw 'infrastructure/database/.env is required.' }
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'External encryption key file is required.' }
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$plainPath = Join-Path $outputRoot "app-postgres-$stamp.dump"
$encryptedPath = "$plainPath.gpg"
try {
    docker compose --env-file $environmentFile -f $composeFile exec -T app-postgres `
        sh -c 'exec pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format custom --no-owner --no-privileges' `
        | Set-Content -LiteralPath $plainPath -AsByteStream
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
    & gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file $keyPath --output $encryptedPath $plainPath
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
