# 책임: 기존 DB credential을 보존해 외부 deployment env로 이관하고, 승인된 로컬
# Core용 TLS·Trino·DataHub·serving secret을 repository 밖에 원자적으로 준비한다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$EnvPath,
    [Parameter(Mandatory)] [string]$SecretsDirectory,
    [Parameter(Mandatory)] [string]$LegacyEnvPath,
    [Parameter(Mandatory)] [string]$ModelEnvPath,
    [Parameter(Mandatory)] [string]$HostIp,
    [string]$ComposeProjectName = 'hotel-synthetic-db'
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$databaseRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $databaseRoot 'scripts/deployment-environment.ps1')

foreach ($path in @($EnvPath, $SecretsDirectory, $LegacyEnvPath, $ModelEnvPath)) {
    if (-not (Test-FullyQualifiedFileSystemPath $path)) {
        throw 'All deployment and secret paths must be absolute.'
    }
}
foreach ($path in @($LegacyEnvPath, $ModelEnvPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Legacy and model environment files must already exist.'
    }
}
if ($HostIp -notmatch '^(?:\d{1,3}\.){3}\d{1,3}$') {
    throw 'HostIp must be an IPv4 address used in the local TLS SAN.'
}

$resolvedEnvPath = [IO.Path]::GetFullPath($EnvPath)
$resolvedSecrets = [IO.Path]::GetFullPath($SecretsDirectory)
$repoPrefix = $repoRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
foreach ($path in @($resolvedEnvPath, $resolvedSecrets)) {
    if ($path.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Deployment env and secrets must remain outside the repository.'
    }
}
New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedEnvPath) -Force | Out-Null
New-Item -ItemType Directory -Path $resolvedSecrets -Force | Out-Null

$examplePath = Join-Path $databaseRoot '.env.example'
$lines = [Collections.Generic.List[string]]::new()
$index = [Collections.Generic.Dictionary[string, int]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($line in Get-Content -LiteralPath $examplePath -Encoding UTF8) {
    $lines.Add($line)
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=') { $index[$Matches[1]] = $lines.Count - 1 }
}

function Read-EnvMap([string]$Path) {
    $map = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $map[$Matches[1]] = $Matches[2] }
    }
    return $map
}
function Set-Value([string]$Name, [string]$Value) {
    if ($Value.Contains("`r") -or $Value.Contains("`n")) { throw "Deployment value '$Name' is multiline." }
    $entry = "$Name=$Value"
    if ($index.ContainsKey($Name)) { $lines[$index[$Name]] = $entry }
    else { $index[$Name] = $lines.Count; $lines.Add($entry) }
}
function New-RandomValue([int]$ByteCount = 32) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
function Get-Value([string]$Name) {
    if (-not $index.ContainsKey($Name)) { return '' }
    return ($lines[$index[$Name]] -split '=', 2)[1]
}
function Set-RandomDefault([string]$Name) {
    $current = Get-Value $Name
    if ([string]::IsNullOrWhiteSpace($current) -or
        $current.StartsWith('CHANGE_ME_', [StringComparison]::OrdinalIgnoreCase) -or
        $current.StartsWith('REQUIRED_', [StringComparison]::OrdinalIgnoreCase)) {
        Set-Value $Name (New-RandomValue)
    }
}

$legacy = Read-EnvMap $LegacyEnvPath
foreach ($name in $legacy.Keys) {
    if ($index.ContainsKey($name)) { Set-Value $name $legacy[$name] }
}
if (Test-Path -LiteralPath $resolvedEnvPath -PathType Leaf) {
    $existing = Read-EnvMap $resolvedEnvPath
    foreach ($name in $existing.Keys) { Set-Value $name $existing[$name] }
}
$model = Read-EnvMap $ModelEnvPath
foreach ($name in @('OPENAI_ENDPOINT', 'OPENAI_API_KEY', 'OPENAI_MODEL')) {
    if (-not $model.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($model[$name])) {
        throw "Model environment key '$name' is missing."
    }
    Set-Value $name $model[$name]
}

Set-Value 'COMPOSE_PROJECT_NAME' $ComposeProjectName
Set-Value 'TRINO_ADMIN_USER' 'answervice_platform_admin'
Set-Value 'TRINO_RUNTIME_USER' 'answervice_runtime'
Set-Value 'TRINO_DATAHUB_USER' 'datahub_ingestion'
Set-Value 'DATAHUB_GMS_URL' 'https://127.0.0.1:18081'
Set-Value 'ANALYST_LOGIN_ID' 'analyst'
Set-Value 'ANALYST_LOGIN_ROLE' 'analyst'
Set-Value 'REPORT_ADMIN_LOGIN_ID' 'admin'
Set-Value 'FRONTEND_BIND_ADDRESS' '0.0.0.0'
Set-Value 'BACKEND_BIND_ADDRESS' '0.0.0.0'
Set-Value 'CORS_ALLOW_ORIGINS' "http://127.0.0.1:13000,http://localhost:13000,http://$HostIp`:13000"

$trinoPasswordDb = Join-Path $resolvedSecrets 'trino-password.db'
$trinoKeystore = Join-Path $resolvedSecrets 'trino-keystore.p12'
$caPem = Join-Path $resolvedSecrets 'answervice-local-ca.pem'
$datahubKeystore = Join-Path $resolvedSecrets 'datahub-gms-keystore.p12'
$datahubTruststore = Join-Path $resolvedSecrets 'datahub-truststore.p12'
$principalFile = Join-Path $resolvedSecrets 'answervice-auth-principals.json'
$servingCredentials = Join-Path $resolvedSecrets 'serving-catalog-bootstrap.json'
$servingPublicKey = Join-Path $resolvedSecrets 'serving-catalog-token-public.pem'
$servingPrivateKey = Join-Path $resolvedSecrets 'serving-catalog-token-private.pem'

Set-Value 'TRINO_PASSWORD_DB_HOST_FILE' $trinoPasswordDb
Set-Value 'TRINO_TLS_KEYSTORE_HOST_FILE' $trinoKeystore
Set-Value 'TRINO_TLS_CA_HOST_FILE' $caPem
Set-Value 'DATAHUB_TLS_KEYSTORE_HOST_FILE' $datahubKeystore
Set-Value 'DATAHUB_TLS_TRUSTSTORE_HOST_FILE' $datahubTruststore
Set-Value 'DATAHUB_TLS_CA_HOST_FILE' $caPem
Set-Value 'AUTH_PRINCIPALS_HOST_FILE' $principalFile
Set-Value 'SERVING_CATALOG_BOOTSTRAP_CREDENTIALS_HOST_FILE' $servingCredentials
Set-Value 'SERVING_CATALOG_TOKEN_PUBLIC_KEY_HOST_FILE' $servingPublicKey
Set-Value 'SERVING_CATALOG_TOKEN_PRIVATE_KEY_HOST_FILE' $servingPrivateKey

foreach ($name in @(
    'TRINO_ADMIN_PASSWORD', 'TRINO_RUNTIME_PASSWORD', 'TRINO_DATAHUB_PASSWORD',
    'TRINO_INTERNAL_SHARED_SECRET', 'TRINO_TLS_KEYSTORE_PASSWORD',
    'DATAHUB_SYSTEM_CLIENT_SECRET', 'DATAHUB_TLS_KEYSTORE_PASSWORD',
    'DATAHUB_TLS_TRUSTSTORE_PASSWORD', 'DATAHUB_TOKEN_SERVICE_SALT',
    'DATAHUB_TOKEN_SERVICE_SIGNING_KEY', 'DATAHUB_SECRET_SERVICE_ENCRYPTION_KEY',
    'DATAHUB_SECRET', 'DATAHUB_MYSQL_PASSWORD', 'DATAHUB_MYSQL_ROOT_PASSWORD',
    'AUTH_SESSION_SECRET'
)) { Set-RandomDefault $name }

$temporaryEnv = Join-Path (Split-Path -Parent $resolvedEnvPath) ".answervice-env-$([guid]::NewGuid().ToString('N')).tmp"
try {
    [IO.File]::WriteAllLines($temporaryEnv, $lines, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryEnv -Destination $resolvedEnvPath -Force
} finally {
    if (Test-Path -LiteralPath $temporaryEnv -PathType Leaf) { Remove-Item -LiteralPath $temporaryEnv -Force }
}

& (Join-Path $scriptRoot 'provision-serving-catalog-secrets.ps1') `
    -EnvPath $resolvedEnvPath -CredentialsPath $servingCredentials `
    -TokenPublicKeyPath $servingPublicKey -TokenPrivateKeyPath $servingPrivateKey

$values = Read-DeploymentEnvironment $resolvedEnvPath
$caKey = Join-Path $resolvedSecrets 'answervice-local-ca.key'
if ((Test-Path -LiteralPath $caPem -PathType Leaf) -xor
    (Test-Path -LiteralPath $caKey -PathType Leaf)) {
    throw 'Local CA certificate and private key must both exist or both be absent.'
}
function Invoke-OpenSsl([string[]]$Arguments, [hashtable]$Environment = @{}) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = (Get-Command openssl -ErrorAction Stop).Source
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$info.ArgumentList.Add($argument) }
    foreach ($entry in $Environment.GetEnumerator()) { $info.Environment[$entry.Key] = $entry.Value }
    $process = [Diagnostics.Process]::Start($info)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw 'OpenSSL provisioning failed; secret output was suppressed.' }
}
if (-not (Test-Path -LiteralPath $caPem -PathType Leaf)) {
    Invoke-OpenSsl @('req', '-config', 'NUL', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '3650', '-subj', '/CN=Answervice Local CA', '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', $caKey, '-out', $caPem)
}
function New-ServerKeystore([string]$Name, [string]$DnsName, [string]$OutputPath, [string]$PasswordKey) {
    if (Test-Path -LiteralPath $OutputPath -PathType Leaf) { return }
    $key = Join-Path $resolvedSecrets "$Name.key.tmp"
    $csr = Join-Path $resolvedSecrets "$Name.csr.tmp"
    $certificate = Join-Path $resolvedSecrets "$Name.pem.tmp"
    $extension = Join-Path $resolvedSecrets "$Name.ext.tmp"
    try {
        [IO.File]::WriteAllText($extension, "basicConstraints=critical,CA:FALSE`r`nkeyUsage=critical,digitalSignature,keyEncipherment`r`nsubjectAltName=DNS:$DnsName,DNS:localhost,IP:127.0.0.1,IP:$HostIp`r`nextendedKeyUsage=serverAuth`r`n", [Text.UTF8Encoding]::new($false))
        Invoke-OpenSsl @('req', '-config', 'NUL', '-new', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-subj', "/CN=$DnsName", '-keyout', $key, '-out', $csr)
        Invoke-OpenSsl @('x509', '-req', '-sha256', '-days', '825', '-in', $csr, '-CA', $caPem, '-CAkey', $caKey, '-CAcreateserial', '-extfile', $extension, '-out', $certificate)
        Invoke-OpenSsl @('pkcs12', '-export', '-name', $DnsName, '-inkey', $key, '-in', $certificate, '-certfile', $caPem, '-out', $OutputPath, '-passout', 'env:ANSWERVICE_P12_PASSWORD') @{ ANSWERVICE_P12_PASSWORD = [string]$values[$PasswordKey] }
    } finally {
        foreach ($path in @($key, $csr, $certificate, $extension)) { if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force } }
    }
}
New-ServerKeystore 'trino-server' 'trino' $trinoKeystore 'TRINO_TLS_KEYSTORE_PASSWORD'
New-ServerKeystore 'datahub-server' 'datahub-gms' $datahubKeystore 'DATAHUB_TLS_KEYSTORE_PASSWORD'
if (-not (Test-Path -LiteralPath $datahubTruststore -PathType Leaf)) {
    $previousPassword = $env:ANSWERVICE_TRUSTSTORE_PASSWORD
    $env:ANSWERVICE_TRUSTSTORE_PASSWORD = [string]$values['DATAHUB_TLS_TRUSTSTORE_PASSWORD']
    try {
        & keytool -importcert -noprompt -alias answervice-local-ca -file $caPem `
            -keystore $datahubTruststore -storetype PKCS12 `
            -storepass:env ANSWERVICE_TRUSTSTORE_PASSWORD 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'DataHub truststore provisioning failed.' }
    } finally { $env:ANSWERVICE_TRUSTSTORE_PASSWORD = $previousPassword }
}
& (Join-Path $scriptRoot 'provision-trino-password-database.ps1') `
    -EnvPath $resolvedEnvPath -PasswordDatabasePath $trinoPasswordDb -Confirm:$false

[ordered]@{
    status = 'PROVISIONED'
    deployment_env = 'WRITTEN'
    legacy_credentials = 'PRESERVED'
    model_configuration = 'PRESERVED'
    tls_files = 'PRESENT'
    trino_password_database = 'PRESENT'
    secret_values_logged = $false
} | ConvertTo-Json -Compress
