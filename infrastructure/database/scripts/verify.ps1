[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
& (Join-Path (Split-Path -Parent $PSScriptRoot) 'verify.ps1')
