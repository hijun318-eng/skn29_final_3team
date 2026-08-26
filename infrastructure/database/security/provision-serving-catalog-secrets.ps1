# 책임: Polaris 영속 catalog와 object storage의 local/deployment secret을 생성하고,
# plaintext가 argv나 출력에 노출되지 않는 bootstrap credential file을 원자적으로 쓴다.
[CmdletBinding()]
param(
    [string]$EnvPath,
    [Parameter(Mandatory)] [string]$CredentialsPath,
    [Parameter(Mandatory)] [string]$TokenPublicKeyPath,
    [Parameter(Mandatory)] [string]$TokenPrivateKeyPath
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $scriptRoot '../scripts/deployment-environment.ps1')
$resolvedEnvPath = Resolve-RepositoryDeploymentEnvFile `
    -Path $EnvPath -RepositoryRoot $repoRoot

if (-not (Test-FullyQualifiedFileSystemPath $CredentialsPath)) {
    throw 'CredentialsPath must be an absolute path.'
}
$resolvedCredentialsPath = [IO.Path]::GetFullPath($CredentialsPath)
$credentialsParent = Split-Path -Parent $resolvedCredentialsPath
if (-not (Test-Path -LiteralPath $credentialsParent -PathType Container)) {
    throw 'CredentialsPath parent directory must already exist.'
}
$repositoryPrefix = $repoRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
$credentialsAreLocal = $resolvedCredentialsPath.StartsWith(
    $repositoryPrefix,
    [StringComparison]::OrdinalIgnoreCase
)
if ($credentialsAreLocal) {
    & git -C $repoRoot check-ignore -q -- $resolvedCredentialsPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Repository-local bootstrap credentials must be covered by .gitignore.'
    }
}

$resolvedTokenPublicKeyPath = [IO.Path]::GetFullPath($TokenPublicKeyPath)
$resolvedTokenPrivateKeyPath = [IO.Path]::GetFullPath($TokenPrivateKeyPath)
foreach ($tokenPath in @($resolvedTokenPublicKeyPath, $resolvedTokenPrivateKeyPath)) {
    $tokenParent = Split-Path -Parent $tokenPath
    if (-not (Test-FullyQualifiedFileSystemPath $tokenPath) -or
        -not (Test-Path -LiteralPath $tokenParent -PathType Container)) {
        throw 'Token key paths must be absolute and their parent directories must exist.'
    }
    if ($tokenPath.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        & git -C $repoRoot check-ignore -q -- $tokenPath
        if ($LASTEXITCODE -ne 0) {
            throw 'Repository-local token keys must be covered by .gitignore.'
        }
    }
}
if ((Test-Path -LiteralPath $resolvedTokenPublicKeyPath -PathType Leaf) -xor
    (Test-Path -LiteralPath $resolvedTokenPrivateKeyPath -PathType Leaf)) {
    throw 'Polaris token public/private keys must both exist or both be absent.'
}

$envText = [IO.File]::ReadAllText($resolvedEnvPath)

function Read-EnvValue([string]$Name) {
    $match = [regex]::Match($script:envText, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($match.Success) { return $match.Groups[1].Value.Trim().Trim('"', "'") }
    return ''
}

function Set-EnvValue([string]$Name, [string]$Value) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    $replacement = "$Name=$Value"
    if ([regex]::IsMatch($script:envText, $pattern)) {
        $script:envText = [regex]::Replace(
            $script:envText,
            $pattern,
            { param($match) $replacement }
        )
    } else {
        $script:envText = $script:envText.TrimEnd("`r", "`n") + "`r`n$replacement`r`n"
    }
}

function New-RandomValue([int]$ByteCount = 32) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function New-HexValue([int]$ByteCount) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

function Set-DefaultValue([string]$Name, [string]$Value) {
    $current = Read-EnvValue $Name
    if ([string]::IsNullOrWhiteSpace($current) -or
        $current.StartsWith('CHANGE_ME_', [StringComparison]::OrdinalIgnoreCase) -or
        $current.StartsWith('REQUIRED_', [StringComparison]::OrdinalIgnoreCase)) {
        Set-EnvValue $Name $Value
        return $true
    }
    return $false
}

$generated = [Collections.Generic.List[string]]::new()
foreach ($entry in @(
    @('SERVING_CATALOG_DB_PASSWORD', (New-RandomValue)),
    @('SERVING_OBJECT_STORE_ACCESS_KEY', (New-HexValue 10)),
    @('SERVING_OBJECT_STORE_SECRET_KEY', (New-RandomValue))
)) {
    if (Set-DefaultValue -Name $entry[0] -Value $entry[1]) {
        $generated.Add([string]$entry[0])
    }
}
if (Set-DefaultValue 'SERVING_CATALOG_ADMIN_CLIENT_SECRET' (New-RandomValue)) {
    $generated.Add('SERVING_CATALOG_ADMIN_CLIENT_SECRET')
}
Set-DefaultValue 'SERVING_CATALOG_DB_NAME' 'serving_catalog' | Out-Null
Set-DefaultValue 'SERVING_CATALOG_DB_USER' 'serving_catalog' | Out-Null
Set-DefaultValue 'SERVING_CATALOG_ADMIN_CLIENT_ID' 'answervice_catalog_admin' | Out-Null
Set-DefaultValue 'SERVING_CATALOG_TRINO_PRINCIPAL' 'answervice_trino' | Out-Null
Set-DefaultValue 'SERVING_CATALOG_TRINO_CLIENT_ID' 'REQUIRED_PROVISION_BY_POLARIS' | Out-Null
Set-DefaultValue 'SERVING_CATALOG_TRINO_CLIENT_SECRET' 'REQUIRED_PROVISION_BY_POLARIS' | Out-Null
Set-DefaultValue 'SERVING_OBJECT_STORE_BUCKET' 'answervice-serving' | Out-Null
Set-DefaultValue 'SERVING_OBJECT_STORE_REGION' 'ap-northeast-2' | Out-Null
Set-DefaultValue 'SERVING_CATALOG_API_PORT' '18181' | Out-Null
Set-EnvValue 'SERVING_CATALOG_BOOTSTRAP_CREDENTIALS_HOST_FILE' $resolvedCredentialsPath
Set-EnvValue 'SERVING_CATALOG_TOKEN_PUBLIC_KEY_HOST_FILE' $resolvedTokenPublicKeyPath
Set-EnvValue 'SERVING_CATALOG_TOKEN_PRIVATE_KEY_HOST_FILE' $resolvedTokenPrivateKeyPath

$required = @(
    'SERVING_CATALOG_DB_NAME', 'SERVING_CATALOG_DB_USER',
    'SERVING_CATALOG_DB_PASSWORD', 'SERVING_CATALOG_ADMIN_CLIENT_ID',
    'SERVING_CATALOG_ADMIN_CLIENT_SECRET', 'SERVING_CATALOG_TRINO_PRINCIPAL',
    'SERVING_OBJECT_STORE_ACCESS_KEY',
    'SERVING_OBJECT_STORE_SECRET_KEY', 'SERVING_OBJECT_STORE_BUCKET',
    'SERVING_OBJECT_STORE_REGION'
)
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace((Read-EnvValue $name))) {
        throw "Serving persistence key '$name' is missing."
    }
}
if ((Read-EnvValue 'SERVING_CATALOG_DB_PASSWORD').Length -lt 16 -or
    (Read-EnvValue 'SERVING_CATALOG_ADMIN_CLIENT_SECRET').Length -lt 24 -or
    (Read-EnvValue 'SERVING_OBJECT_STORE_SECRET_KEY').Length -lt 24) {
    throw 'Serving persistence secrets do not meet the minimum length contract.'
}

$credentialDocument = [ordered]@{
    ANSWERVICE = [ordered]@{
        'client-id' = Read-EnvValue 'SERVING_CATALOG_ADMIN_CLIENT_ID'
        'client-secret' = Read-EnvValue 'SERVING_CATALOG_ADMIN_CLIENT_SECRET'
    }
} | ConvertTo-Json -Depth 3
$envTemporary = Join-Path (Split-Path -Parent $resolvedEnvPath) (
    ".serving-env-$([guid]::NewGuid().ToString('N')).tmp"
)
$credentialTemporary = Join-Path $credentialsParent (
    ".serving-credential-$([guid]::NewGuid().ToString('N')).tmp"
)
$privateKeyTemporary = Join-Path (Split-Path -Parent $resolvedTokenPrivateKeyPath) (
    ".serving-token-private-$([guid]::NewGuid().ToString('N')).tmp"
)
$publicKeyTemporary = Join-Path (Split-Path -Parent $resolvedTokenPublicKeyPath) (
    ".serving-token-public-$([guid]::NewGuid().ToString('N')).tmp"
)
try {
    if (-not (Test-Path -LiteralPath $resolvedTokenPrivateKeyPath -PathType Leaf)) {
        $openssl = Get-Command openssl -ErrorAction Stop
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $openssl.Source genpkey -algorithm RSA -out $privateKeyTemporary `
                -pkeyopt rsa_keygen_bits:2048 2>$null
            $privateExitCode = $LASTEXITCODE
            & $openssl.Source rsa -in $privateKeyTemporary -pubout `
                -out $publicKeyTemporary 2>$null
            $publicExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($privateExitCode -ne 0) { throw 'OpenSSL failed to generate Polaris private key.' }
        if ($publicExitCode -ne 0) { throw 'OpenSSL failed to derive Polaris public key.' }
        Move-Item -LiteralPath $privateKeyTemporary `
            -Destination $resolvedTokenPrivateKeyPath -Force
        Move-Item -LiteralPath $publicKeyTemporary `
            -Destination $resolvedTokenPublicKeyPath -Force
    }
    [IO.File]::WriteAllText($envTemporary, $envText, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText(
        $credentialTemporary,
        $credentialDocument + "`r`n",
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $envTemporary -Destination $resolvedEnvPath -Force
    Move-Item -LiteralPath $credentialTemporary -Destination $resolvedCredentialsPath -Force
} finally {
    foreach ($temporary in @(
        $envTemporary, $credentialTemporary, $privateKeyTemporary, $publicKeyTemporary
    )) {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

[ordered]@{
    status = 'PROVISIONED'
    generated_keys = @($generated)
    bootstrap_file = 'WRITTEN'
    token_key_pair = 'PRESENT'
    secret_values_logged = $false
} | ConvertTo-Json -Compress
