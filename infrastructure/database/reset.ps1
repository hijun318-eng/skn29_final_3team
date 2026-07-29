[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts\reset.ps1') @PSBoundParameters
