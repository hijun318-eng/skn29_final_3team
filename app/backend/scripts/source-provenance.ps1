# 책임: backend image가 어떤 Git revision과 working tree에서 만들어졌는지
# 재현 가능한 build argument로 제공한다. ignored secret은 fingerprint에 포함하지 않는다.
function Get-AnswerviceTextSha256 {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Value
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        $hash = $algorithm.ComputeHash($bytes)
        return ([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
    }
}

function Resolve-AnswerviceSourceProvenance {
    param(
        [Parameter(Mandatory)]
        [string]$RepositoryRoot
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
    $previousGitConfigGlobal = $env:GIT_CONFIG_GLOBAL
    try {
        # 사용자 global excludes가 source identity를 host별로 바꾸거나 접근 경고를
        # 만들지 않게 하고, repository의 tracked 파일과 .gitignore만 기준으로 삼는다.
        $env:GIT_CONFIG_GLOBAL = 'NUL'
        $gitConfigArguments = @(
            '-c', 'core.excludesFile=',
            '-c', 'core.safecrlf=false',
            '-C', $resolvedRoot
        )

        $revision = (@(
            & git @gitConfigArguments rev-parse --verify HEAD
        ) -join '').Trim()
        if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
            throw 'Backend image provenance requires a valid Git HEAD revision.'
        }

        $statusLines = @(
            & git @gitConfigArguments status --porcelain=v1 --untracked-files=all
        )
        if ($LASTEXITCODE -ne 0) {
            throw 'Backend image provenance could not inspect the Git working tree.'
        }

        $trackedDiffLines = @(
            & git @gitConfigArguments diff --binary --no-ext-diff HEAD --
        )
        if ($LASTEXITCODE -ne 0) {
            throw 'Backend image provenance could not read the tracked source patch.'
        }
        $trackedPatchHash = Get-AnswerviceTextSha256 `
            -Value (($trackedDiffLines -join "`n") + "`n")

        $untrackedPaths = @(
            & git @gitConfigArguments ls-files --others --exclude-standard
        ) | Sort-Object
        if ($LASTEXITCODE -ne 0) {
            throw 'Backend image provenance could not enumerate untracked source files.'
        }

        $untrackedManifest = @(
            foreach ($path in $untrackedPaths) {
                $blobHash = (@(
                    & git @gitConfigArguments hash-object -- $path
                ) -join '').Trim()
                if ($LASTEXITCODE -ne 0 -or $blobHash -notmatch '^[0-9a-f]{40}$') {
                    throw "Backend image provenance could not hash source file '$path'."
                }
                "$path`t$blobHash"
            }
        )

        $fingerprintInput = @(
            "revision=$revision"
            "tracked_patch_sha256=$trackedPatchHash"
            "untracked_count=$($untrackedManifest.Count)"
        ) + $untrackedManifest
        $fingerprint = Get-AnswerviceTextSha256 `
            -Value (($fingerprintInput -join "`n") + "`n")

        return [pscustomobject]@{
            Revision = $revision
            Dirty = if ($statusLines.Count -gt 0) { 'true' } else { 'false' }
            Fingerprint = $fingerprint
        }
    }
    finally {
        $env:GIT_CONFIG_GLOBAL = $previousGitConfigGlobal
    }
}

function Set-AnswerviceSourceProvenanceEnvironment {
    param(
        [Parameter(Mandatory)]
        [string]$RepositoryRoot
    )

    $provenance = Resolve-AnswerviceSourceProvenance -RepositoryRoot $RepositoryRoot
    $env:ANSWERVICE_SOURCE_REVISION = $provenance.Revision
    $env:ANSWERVICE_SOURCE_DIRTY = $provenance.Dirty
    $env:ANSWERVICE_SOURCE_FINGERPRINT = $provenance.Fingerprint
    return $provenance
}
