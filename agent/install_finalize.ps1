#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$AgentPath,
    [string]$AgentDir = $null,
    [switch]$SkipStart,
    [switch]$SkipVerify,
    [switch]$CleanupOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$common = Join-Path $PSScriptRoot 'install_common.ps1'
if (-not (Test-Path $common)) {
    throw "Missing install helper: $common"
}

. $common

try {
    if ($CleanupOnly) {
        if (-not $AgentDir) {
            $AgentDir = Split-Path -Parent $AgentPath
        }
        Remove-LegacySyncLayerInstall -AgentDir $AgentDir -StopProcesses
        Write-Host 'OK: legacy SyncLayer install entries removed.'
        exit 0
    }

    $result = Invoke-SyncLayerInstallFinalize `
        -AgentPath $AgentPath `
        -AgentDir $AgentDir `
        -SkipStart:$SkipStart `
        -SkipVerify:$SkipVerify
    Write-SyncLayerInstallReport -Result $result
    if (-not $result.Ok) {
        exit 1
    }
    exit 0
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    exit 1
}
