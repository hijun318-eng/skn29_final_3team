[CmdletBinding()]
param(
    [string]$Remote = "origin",

    [switch]$Push
)

$ErrorActionPreference = "Stop"
$personalBranches = @("junhee", "minji", "seung", "daesung", "jaehong")

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "Run this script inside the new project Git repository."
}

Push-Location $repoRoot
try {
    $hasHead = $false
    try {
        & git rev-parse --verify HEAD 2>$null | Out-Null
        $hasHead = $LASTEXITCODE -eq 0
    }
    catch {
        $hasHead = $false
    }
    if (-not $hasHead) {
        throw "Create and review the initial commit before creating dev and personal branches."
    }

    $dirty = @(& git status --porcelain)
    if ($dirty.Count -gt 0) {
        throw "Working tree must be clean before branch initialization."
    }

    & git show-ref --verify --quiet refs/heads/main
    if ($LASTEXITCODE -ne 0) {
        throw "Local main branch is required."
    }

    & git show-ref --verify --quiet refs/heads/dev
    if ($LASTEXITCODE -ne 0) {
        & git branch dev main
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create dev from main."
        }
        Write-Output "Created branch: dev"
    }
    else {
        Write-Output "Branch already exists: dev"
    }

    foreach ($branch in $personalBranches) {
        & git show-ref --verify --quiet "refs/heads/$branch"
        if ($LASTEXITCODE -ne 0) {
            & git branch $branch dev
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create $branch from dev."
            }
            Write-Output "Created branch: $branch"
        }
        else {
            Write-Output "Branch already exists: $branch"
        }
    }

    if ($Push) {
        $hasRemote = $false
        try {
            & git remote get-url $Remote 2>$null | Out-Null
            $hasRemote = $LASTEXITCODE -eq 0
        }
        catch {
            $hasRemote = $false
        }
        if (-not $hasRemote) {
            throw "Remote '$Remote' is not configured."
        }

        & git push -u $Remote main
        if ($LASTEXITCODE -ne 0) { throw "Failed to push main." }
        & git push -u $Remote dev
        if ($LASTEXITCODE -ne 0) { throw "Failed to push dev." }
        foreach ($branch in $personalBranches) {
            & git push -u $Remote $branch
            if ($LASTEXITCODE -ne 0) { throw "Failed to push $branch." }
        }
    }

    & git switch dev
    if ($LASTEXITCODE -ne 0) {
        throw "Branches were created, but switching to dev failed."
    }

    Write-Output "Branch structure is ready: main, dev, junhee, minji, seung, daesung, jaehong"
    Write-Output "Current branch: dev"
}
finally {
    Pop-Location
}
