# 책임: 모든 deployment script가 repository의 고정 `.env` 하나만 읽도록 강제하고,
# 외부 env file이나 process environment fallback이 credential source가 되지 않게 한다.

function Disable-ImplicitComposeEnvironment {
    <#
    Docker Compose의 현재 작업 directory 기반 `.env` 자동 탐색을 끈다.
    Compose의 묵시적 `.env` 탐색을 끄고 검증된 repository env를 `--env-file`로만
    전달해 실행 directory에 따라 credential source가 달라지지 않게 한다.
    #>
    $env:COMPOSE_DISABLE_ENV_FILE = '1'
}

function Test-FullyQualifiedFileSystemPath {
    <#
    Windows PowerShell 5.1과 PowerShell 7에서 동일하게 drive-rooted/UNC 또는 Unix
    root path만 허용한다. ``C:relative``처럼 현재 drive directory에 의존하는 값은
    .NET version과 무관하게 거절해 secret source가 실행 위치에 따라 바뀌지 않는다.
    #>
    param([AllowEmptyString()] [string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    if ([IO.Path]::DirectorySeparatorChar -eq '\') {
        return [bool]($Path -match '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)')
    }
    return $Path.StartsWith('/', [StringComparison]::Ordinal)
}

function Resolve-RepositoryDeploymentEnvFile {
    <#
    빈 입력은 `infrastructure/database/.env`로 해석한다. 명시된 path도 이 canonical
    file과 정확히 같아야 하며, 외부·대체 env file과 commit 가능한 file은 거절한다.
    #>
    param(
        [AllowEmptyString()] [string]$Path,
        [Parameter(Mandatory)] [string]$RepositoryRoot
    )

    $resolvedRepository = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RepositoryRoot).Path
    ).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $canonicalPath = [IO.Path]::GetFullPath(
        (Join-Path $resolvedRepository 'infrastructure/database/.env')
    )
    $selectedPath = if ([string]::IsNullOrWhiteSpace($Path)) { $canonicalPath } else { $Path }
    if (-not (Test-FullyQualifiedFileSystemPath $selectedPath) -or
        -not (Test-Path -LiteralPath $selectedPath -PathType Leaf)) {
        throw 'Deployment env must be the existing repository file infrastructure/database/.env.'
    }
    $resolvedPath = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $selectedPath).Path)
    if (-not $resolvedPath.Equals($canonicalPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'External or alternate deployment env files are not allowed.'
    }
    $envFile = Get-Item -LiteralPath $resolvedPath -Force
    if (($envFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'The repository deployment env must not be a symbolic link or reparse point.'
    }
    & git -C $resolvedRepository check-ignore -q -- $resolvedPath
    if ($LASTEXITCODE -ne 0) {
        throw 'The repository deployment env must be covered by .gitignore.'
    }
    return $resolvedPath
}

function Get-ComposeEnvironmentArguments {
    <#
    검증된 repository env path를 Docker Compose CLI argument로 변환한다.
    #>
    param([Parameter(Mandatory)] [string]$ResolvedEnvFile)

    return @('--env-file', $ResolvedEnvFile)
}

function Read-DeploymentEnvironment {
    <#
    검증된 repository dotenv를 key/value map으로 읽는다. 중복 key와 해석할 수 없는
    행은 Compose와 검증 code의 값 불일치를 막기 위해 거절하며, 값 자체는 출력하거나
    expression으로 재평가하지 않는다.
    #>
    param([Parameter(Mandatory)] [string]$ResolvedEnvFile)

    $values = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $ResolvedEnvFile -Encoding UTF8) {
        $lineNumber++
        if ($line -match '^\s*(?:#.*)?$') { continue }
        if ($line -notmatch '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            throw "EnvFilePath contains unsupported dotenv syntax at line $lineNumber."
        }
        $key = $Matches[1]
        if ($values.ContainsKey($key)) {
            throw "EnvFilePath contains duplicate key '$key'."
        }
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Assert-DeploymentEnvironmentValues {
    <#
    caller가 실제로 소비할 key가 존재하고 placeholder가 아닌지 확인한다. secret 값은
    오류에 포함하지 않으며, 누락/placeholder를 Compose 실행 전에 차단한다.
    #>
    param(
        [Parameter(Mandatory)] $Values,
        [Parameter(Mandatory)] [string[]]$RequiredKeys
    )

    foreach ($key in $RequiredKeys) {
        $value = if ($Values.ContainsKey($key)) { [string]$Values[$key] } else { '' }
        if ([string]::IsNullOrWhiteSpace($value) -or
            $value.StartsWith('CHANGE_ME_', [StringComparison]::OrdinalIgnoreCase) -or
            $value.StartsWith('REQUIRED_', [StringComparison]::OrdinalIgnoreCase) -or
            $value -match '(?i)(^|[\\/])REQUIRED_') {
            throw "Deployment environment key '$key' is missing or still a placeholder."
        }
    }
}

function Assert-ExternalDeploymentFile {
    <#
    deployment map의 path key가 존재하는 외부 regular file을 가리키는지 확인한다.
    인증 DB·CA·keystore 같은 secret material이 repository 내부에 들어오거나 missing
    bind mount가 directory로 생성되는 상황을 Compose 호출 전에 차단한다.
    #>
    param(
        [Parameter(Mandatory)] $Values,
        [Parameter(Mandatory)] [string]$Key,
        [Parameter(Mandatory)] [string]$RepositoryRoot
    )

    Assert-DeploymentEnvironmentValues -Values $Values -RequiredKeys @($Key)
    $path = [string]$Values[$Key]
    if (-not (Test-FullyQualifiedFileSystemPath $path) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Deployment environment key '$Key' must reference an existing absolute file."
    }
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $path).Path)
    $repository = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RepositoryRoot).Path
    ).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    if ($resolved.StartsWith(
        $repository + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Deployment environment key '$Key' must reference a file outside the repository."
    }
    return $resolved
}

function Assert-ExplicitDeploymentFile {
    <#
    외부 regular file 또는 repository 내부의 gitignored regular file만 허용한다.
    개발 secret이 commit 가능한 설정 파일이나 missing bind-mount directory로 바뀌지
    않도록 실행 전에 검증한다.
    #>
    param(
        [Parameter(Mandatory)] $Values,
        [Parameter(Mandatory)] [string]$Key,
        [Parameter(Mandatory)] [string]$RepositoryRoot
    )

    Assert-DeploymentEnvironmentValues -Values $Values -RequiredKeys @($Key)
    $path = [string]$Values[$Key]
    if (-not (Test-FullyQualifiedFileSystemPath $path) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Deployment environment key '$Key' must reference an existing absolute file."
    }
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $path).Path)
    $repository = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RepositoryRoot).Path
    ).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $repositoryPrefix = $repository + [IO.Path]::DirectorySeparatorChar
    $isRepositoryLocal = $resolved.StartsWith(
        $repositoryPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )
    if (-not $isRepositoryLocal) { return $resolved }
    & git -C $repository check-ignore -q -- $resolved
    if ($LASTEXITCODE -ne 0) {
        throw "Repository-local deployment file '$Key' must be covered by .gitignore."
    }
    return $resolved
}
