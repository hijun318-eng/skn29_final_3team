[CmdletBinding()]
param(
    [string]$EnvPath,
    [string]$PrincipalPath,
    [string]$AnalystLoginId,
    [string]$AnalystLoginPassword,
    [string]$ReportAdminLoginId,
    [string]$ReportAdminLoginPassword
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $EnvPath) { $EnvPath = Join-Path $scriptRoot '..\.env' }
if (-not $PrincipalPath) { $PrincipalPath = Join-Path $scriptRoot 'answervice_auth_principals.local.json' }
$resolvedEnvPath = Resolve-Path $EnvPath
$envText = [IO.File]::ReadAllText($resolvedEnvPath)

function Read-EnvValue([string]$Name) {
    $match = [regex]::Match($envText, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ''
}

function Set-EnvValue([string]$Name, [string]$Value) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    if ([regex]::IsMatch($script:envText, $pattern)) {
        $script:envText = [regex]::Replace($script:envText, $pattern, "$Name=$Value")
    } else {
        $script:envText = $script:envText.TrimEnd("`r", "`n") + "`r`n$Name=$Value`r`n"
    }
}

function New-RandomValue([int]$ByteCount = 32) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($bytes)
    $generator.Dispose()
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

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

if ($AnalystLoginId) { Set-EnvValue 'ANALYST_LOGIN_ID' $AnalystLoginId }
if ($AnalystLoginPassword) { Set-EnvValue 'ANALYST_LOGIN_PASSWORD' $AnalystLoginPassword }
if ($ReportAdminLoginId) { Set-EnvValue 'REPORT_ADMIN_LOGIN_ID' $ReportAdminLoginId }
if ($ReportAdminLoginPassword) { Set-EnvValue 'REPORT_ADMIN_LOGIN_PASSWORD' $ReportAdminLoginPassword }

$sessionSecret = Read-EnvValue 'AUTH_SESSION_SECRET'
if (-not $sessionSecret -or $sessionSecret.StartsWith('CHANGE_ME_')) {
    $sessionSecret = New-RandomValue
    Set-EnvValue 'AUTH_SESSION_SECRET' $sessionSecret
}

$definitions = @(
    [ordered]@{ username_env = 'ANALYST_LOGIN_ID'; password_env = 'ANALYST_LOGIN_PASSWORD'; role = 'hotel_analyst' },
    [ordered]@{ username_env = 'REPORT_ADMIN_LOGIN_ID'; password_env = 'REPORT_ADMIN_LOGIN_PASSWORD'; role = 'report_admin' }
)
$existing = @()
if (Test-Path -LiteralPath $PrincipalPath) {
    try { $existing = @((Get-Content -Raw -LiteralPath $PrincipalPath | ConvertFrom-Json)) }
    catch { $existing = @() }
}
$iterations = 210000
$principals = foreach ($definition in $definitions) {
    $username = (Read-EnvValue $definition.username_env).ToLowerInvariant()
    $password = Read-EnvValue $definition.password_env
    if (-not $username -or $username.StartsWith('change_me_') -or -not $password -or $password.StartsWith('CHANGE_ME_')) {
        throw "$($definition.username_env) and $($definition.password_env) must be set in .env"
    }
    if ($username -notmatch '^[a-z0-9._-]{3,64}$' -or $password.Length -lt 8) {
        throw "$($definition.role) login must use a valid username and a password of at least 8 characters"
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
    $PrincipalPath,
    (ConvertTo-Json @($principals) -Depth 5) + "`r`n",
    [Text.UTF8Encoding]::new($false)
)

[ordered]@{
    status = 'PROVISIONED'
    principal_count = @($principals).Count
    usernames = @($principals.username)
    roles = @($principals.role)
    password_storage = 'PBKDF2-SHA256'
} | ConvertTo-Json -Compress
