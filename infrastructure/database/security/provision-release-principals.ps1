[CmdletBinding()]
param(
    [string]$EnvPath,
    [string]$PrincipalPath
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $EnvPath) {
    $EnvPath = Join-Path $scriptRoot '..\.env'
}
if (-not $PrincipalPath) {
    $PrincipalPath = Join-Path $scriptRoot 'answervice_auth_principals.local.json'
}
$envText = [IO.File]::ReadAllText((Resolve-Path $EnvPath))

function Read-EnvValue([string]$Name) {
    $match = [regex]::Match($envText, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ''
}

function New-Token {
    $bytes = [byte[]]::new(32)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($bytes)
    $generator.Dispose()
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$tokenDefinitions = @(
    [ordered]@{ env_name = 'VITE_AUTH_TOKEN'; role = 'hotel_analyst' },
    [ordered]@{ env_name = 'REPORT_ADMIN_AUTH_TOKEN'; role = 'report_admin' }
)
$tokens = @{}
foreach ($definition in $tokenDefinitions) {
    $token = Read-EnvValue $definition.env_name
    if (-not $token -or $token.StartsWith('CHANGE_ME_')) {
        $token = New-Token
        $pattern = "(?m)^$([regex]::Escape($definition.env_name))=.*$"
        if ([regex]::IsMatch($envText, $pattern)) {
            $envText = [regex]::Replace(
                $envText,
                $pattern,
                "$($definition.env_name)=$token"
            )
        } else {
            $envText = $envText.TrimEnd("`r", "`n") + "`r`n$($definition.env_name)=$token`r`n"
        }
    }
    $tokens[$definition.role] = $token
}
[IO.File]::WriteAllText(
    (Resolve-Path $EnvPath),
    $envText,
    [Text.UTF8Encoding]::new($false)
)

$existing = @()
if (Test-Path -LiteralPath $PrincipalPath) {
    $existing = @((Get-Content -Raw -LiteralPath $PrincipalPath | ConvertFrom-Json))
}
$sha = [Security.Cryptography.SHA256]::Create()
$managedRoles = @($tokenDefinitions.role)
$principals = @($existing | Where-Object { $_.role -notin $managedRoles })
$now = [DateTimeOffset]::UtcNow
foreach ($definition in $tokenDefinitions) {
    $token = $tokens[$definition.role]
    $digest = ([BitConverter]::ToString(
        $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($token))
    )).Replace('-', '').ToLowerInvariant()
    $matching = @($existing | Where-Object {
        $_.role -eq $definition.role -and $_.token_sha256 -eq $digest
    }) | Select-Object -First 1
    if ($matching) {
        $principals += $matching
    } else {
        $principals += [ordered]@{
            token_sha256 = $digest
            subject = [guid]::NewGuid().ToString()
            role = $definition.role
            not_before = $now.AddMinutes(-5).ToString('o')
            expires_at = $now.AddYears(1).ToString('o')
        }
    }
}
$sha.Dispose()
$json = ConvertTo-Json @($principals) -Depth 5
[IO.File]::WriteAllText($PrincipalPath, $json + "`r`n", [Text.UTF8Encoding]::new($false))

[ordered]@{
    status = 'PROVISIONED'
    principal_count = $principals.Count
    roles = @($principals.role)
    tokens_stored_in_env = $true
} | ConvertTo-Json -Compress
