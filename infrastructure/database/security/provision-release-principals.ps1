# 책임: 외부 env/secret 경로에 release principal의 PBKDF2 verifier를 생성·회전한다.
# repository 내부 경로나 약한 credential은 파일을 쓰기 전에 거절한다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EnvPath,
    [Parameter(Mandatory)]
    [string]$PrincipalPath
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $scriptRoot '../scripts/deployment-environment.ps1')
$resolvedEnvPath = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvPath -RepositoryRoot $repoRoot
$resolvedPrincipalPath = [IO.Path]::GetFullPath($PrincipalPath)
$principalParent = Split-Path -Parent $resolvedPrincipalPath
if (-not (Test-FullyQualifiedFileSystemPath $PrincipalPath) -or
    -not (Test-Path -LiteralPath $principalParent -PathType Container)) {
    throw 'PrincipalPath must be an absolute path whose parent directory already exists.'
}
if ($resolvedPrincipalPath.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'PrincipalPath must remain outside the repository so authentication data cannot be committed.'
}
$envText = [IO.File]::ReadAllText($resolvedEnvPath)

# Reads one exact dotenv key. Regex is limited to configuration syntax and is
# never used for natural-language routing or SQL validation.
function Read-EnvValue([string]$Name) {
    $match = [regex]::Match($envText, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ''
}

# 동일 key의 모든 기존 entry를 같은 opaque value로 정규화한다. MatchEvaluator를
# 사용하므로 password 안의 '$'도 정규식 replacement group으로 재해석되지 않는다.
function Set-EnvValue([string]$Name, [string]$Value) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    if ([regex]::IsMatch($script:envText, $pattern)) {
        $replacement = "$Name=$Value"
        $script:envText = [regex]::Replace(
            $script:envText,
            $pattern,
            { param($match) $replacement }
        )
    } else {
        $script:envText = $script:envText.TrimEnd("`r", "`n") + "`r`n$Name=$Value`r`n"
    }
}

# Cryptographically secure random bytes are encoded without padding so the
# resulting value is safe in both dotenv files and JSON secrets.
function New-RandomValue([int]$ByteCount = 32) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($bytes)
    $generator.Dispose()
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# PBKDF2 parameters are persisted with the digest so iteration upgrades can be
# performed account-by-account without accepting a plaintext fallback.
function Get-PasswordHash([string]$Password, [byte[]]$Salt, [int]$Iterations) {
    $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
        $Password,
        $Salt,
        $Iterations,
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try { return ([BitConverter]::ToString($derive.GetBytes(32))).Replace('-', '').ToLowerInvariant() }
    finally { $derive.Dispose() }
}

# Login ID와 raw password는 command parameter로 받지 않는다. operator가 보호된
# 외부 env를 먼저 갱신해야 하며 이 script는 해당 file의 verifier만 파생한다.
$sessionSecret = Read-EnvValue 'AUTH_SESSION_SECRET'
if (-not $sessionSecret -or $sessionSecret.StartsWith('CHANGE_ME_')) {
    $sessionSecret = New-RandomValue
    Set-EnvValue 'AUTH_SESSION_SECRET' $sessionSecret
}
Set-EnvValue 'AUTH_PRINCIPALS_HOST_FILE' $resolvedPrincipalPath

$definitions = @(
    [ordered]@{ username_env = 'ANALYST_LOGIN_ID'; password_env = 'ANALYST_LOGIN_PASSWORD'; role = 'hotel_analyst' },
    [ordered]@{ username_env = 'REPORT_ADMIN_LOGIN_ID'; password_env = 'REPORT_ADMIN_LOGIN_PASSWORD'; role = 'report_admin' }
)
$existing = @()
if (Test-Path -LiteralPath $resolvedPrincipalPath) {
    try { $existing = @((Get-Content -Raw -LiteralPath $resolvedPrincipalPath | ConvertFrom-Json)) }
    catch { $existing = @() }
}
$iterations = 210000
$principals = foreach ($definition in $definitions) {
    $username = (Read-EnvValue $definition.username_env).ToLowerInvariant()
    $password = Read-EnvValue $definition.password_env
    if (-not $username -or $username.StartsWith('change_me_') -or -not $password -or $password.StartsWith('CHANGE_ME_')) {
        throw "$($definition.username_env) and $($definition.password_env) must be set in the external deployment env file"
    }
    if ($username -notmatch '^[a-z0-9._-]{3,64}$' -or $password.Length -lt 12) {
        throw "$($definition.role) login must use a valid username and a password of at least 12 characters"
    }
    $matching = @($existing | Where-Object { $_.username -eq $username -and $_.role -eq $definition.role }) | Select-Object -First 1
    $salt = [byte[]]::new(16)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($salt)
    $generator.Dispose()
    [ordered]@{
        username = $username
        password_salt = [Convert]::ToBase64String($salt).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        password_hash = Get-PasswordHash $password $salt $iterations
        password_iterations = $iterations
        subject = if ($matching) { $matching.subject } else { [guid]::NewGuid().ToString() }
        role = $definition.role
        active = $true
    }
}

[IO.File]::WriteAllText($resolvedEnvPath, $envText, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText(
    $resolvedPrincipalPath,
    (ConvertTo-Json @($principals) -Depth 5) + "`r`n",
    [Text.UTF8Encoding]::new($false)
)

[ordered]@{
    status = 'PROVISIONED'
    principal_count = @($principals).Count
    roles = @($principals.role)
    password_storage = 'PBKDF2-SHA256'
} | ConvertTo-Json -Compress
