[CmdletBinding()]
param(
    [ValidateRange(50, 2000)]
    [int]$MaxPatchLines = 500
)

$ErrorActionPreference = "Stop"

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "Run this script inside a Git repository."
}

Push-Location $repoRoot
try {
    $nameStatus = @(& git diff --cached --name-status --no-renames)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to read the staged diff."
    }
    if ($nameStatus.Count -eq 0) {
        [Console]::Error.WriteLine("No staged changes. Stage only the intended paths, review them, and run again.")
        exit 2
    }

    $stat = @(& git diff --cached --stat --no-renames)
    $patch = @(& git diff --cached --no-ext-diff --no-color --no-renames --unified=1 -- .)
    $recent = @()
    & git rev-parse --verify HEAD *> $null
    if ($LASTEXITCODE -eq 0) {
        $recent = @(& git log -5 --format="%h %s")
    }

    $visiblePatch = $patch | Select-Object -First $MaxPatchLines
    $truncated = $patch.Count -gt $visiblePatch.Count

    Write-Output "# Staged diff context"
    Write-Output ""
    Write-Output "Repository: $repoRoot"
    Write-Output "Patch lines: $($patch.Count)"
    Write-Output "Patch truncated: $($truncated.ToString().ToLowerInvariant())"
    Write-Output ""
    Write-Output "## Staged paths"
    Write-Output '```text'
    Write-Output ($nameStatus -join "`n")
    Write-Output '```'
    Write-Output ""
    Write-Output "## Diff stat"
    Write-Output '```text'
    Write-Output ($stat -join "`n")
    Write-Output '```'

    if ($recent.Count -gt 0) {
        Write-Output ""
        Write-Output "## Recent subjects"
        Write-Output '```text'
        Write-Output ($recent -join "`n")
        Write-Output '```'
    }

    Write-Output ""
    Write-Output "## Patch"
    Write-Output '```diff'
    Write-Output ($visiblePatch -join "`n")
    if ($truncated) {
        Write-Output "... patch truncated; inspect the remaining staged diff directly ..."
    }
    Write-Output '```'
}
finally {
    Pop-Location
}
