#Requires -Version 5.1
param(
    [int]$ExpectedProcessCount = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'install_common.ps1')

$result = Test-SyncLayerInstall -ExpectedProcessCount $ExpectedProcessCount
Write-SyncLayerInstallReport -Result $result
Write-SyncLayerRuntimeReport
if (-not $result.Ok) {
    exit 1
}
exit 0
