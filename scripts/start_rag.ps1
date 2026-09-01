[CmdletBinding()]
param(
    [switch]$ForceReindex,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BootstrapScript = Join-Path $RepositoryRoot "infrastructure\rag\bootstrap_portable_e2e.py"
$Python = Get-Command python -ErrorAction Stop
$BootstrapArguments = @($BootstrapScript, "--approve-local-manuals")

if ($ForceReindex) {
    $BootstrapArguments += "--force-reindex"
}
if ($Verify) {
    $BootstrapArguments += "--verify"
}

Push-Location $RepositoryRoot
try {
    & $Python.Source @BootstrapArguments
    if ($LASTEXITCODE -ne 0) {
        throw "RAG bootstrap exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
