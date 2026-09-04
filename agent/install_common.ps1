#Requires -Version 5.1
<#
.SYNOPSIS
    Shared SyncLayer Windows install helpers.

    Target layout: 1 x SyncLayerAgent.exe + 1 x Scheduled Task + 0 services + 0 tray helpers.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Script:TaskName = 'SyncLayerAgent'
$Script:ServiceName = 'SyncLayer'
$Script:LegacyTaskNames = @('SyncLayer', 'SyncLayerTray', 'WatcherManagerTray')
$Script:RunValueNames = @('SyncLayerAgent', 'SyncLayer')
$Script:RunKeyPaths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
)

function Get-SyncLayerProcessCount {
    $agent = @(Get-Process -Name 'SyncLayerAgent' -ErrorAction SilentlyContinue).Count
    if ($agent -gt 0) {
        return $agent
    }

    # Legacy process names from older installers.
    $legacy = @(Get-Process -Name 'SyncLayer' -ErrorAction SilentlyContinue).Count
    return $legacy
}

function Stop-SyncLayerProcesses {
    foreach ($name in @('SyncLayerAgent', 'SyncLayer')) {
        Get-Process -Name $name -ErrorAction SilentlyContinue |
            ForEach-Object {
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
    }

    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object {
            $cmd = $_.CommandLine
            $cmd -and (
                $cmd -like '*SyncLayer*app_main.py*' -or
                $cmd -like '*SyncLayer*run_test.py*' -or
                $cmd -like '*SyncLayer*tray_app.py*'
            )
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    Start-Sleep -Seconds 1
}

function Remove-SyncLayerScheduledTasks {
    param(
        [string[]]$ExtraTaskNames = @()
    )

    $names = @($Script:TaskName) + $Script:LegacyTaskNames + $ExtraTaskNames | Select-Object -Unique
    foreach ($name in $names) {
        & schtasks.exe /Delete /TN $name /F 2>$null | Out-Null
    }
}

function Remove-SyncLayerRunKeys {
    foreach ($path in $Script:RunKeyPaths) {
        if (-not (Test-Path $path)) {
            continue
        }
        foreach ($valueName in $Script:RunValueNames) {
            Remove-ItemProperty -Path $path -Name $valueName -ErrorAction SilentlyContinue
        }
    }
}

function Remove-SyncLayerService {
    param(
        [string]$AgentDir = $null
    )

    & sc.exe stop $Script:ServiceName 2>$null | Out-Null
    Start-Sleep -Seconds 1

    $trackerService = $null
    if ($AgentDir) {
        $candidate = Join-Path $AgentDir 'tracker_service.py'
        if (Test-Path $candidate) {
            $trackerService = $candidate
        }
    }

    if ($trackerService) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($python) {
            & $python.Source $trackerService stop 2>$null | Out-Null
            & $python.Source $trackerService remove 2>$null | Out-Null
        }
    }

    & sc.exe delete $Script:ServiceName 2>$null | Out-Null
}

function Remove-LegacySyncLayerInstall {
    param(
        [string]$AgentDir = $null,
        [switch]$StopProcesses
    )

    if ($StopProcesses) {
        Stop-SyncLayerProcesses
    }

    Remove-SyncLayerService -AgentDir $AgentDir
    Remove-SyncLayerScheduledTasks
    Remove-SyncLayerRunKeys
}

function Get-SyncLayerInteractiveUser {
    $name = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
    if (-not $name) {
        throw 'No interactive user session (Win32_ComputerSystem.UserName is empty)'
    }
    return $name
}

function Assert-SyncLayerScheduledTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AgentPath,
        [Parameter(Mandatory = $true)]
        [string]$RunAs
    )

    if (-not (Test-SyncLayerScheduledTaskExists)) {
        throw "Scheduled task '$($Script:TaskName)' was not created"
    }

    $task = Get-ScheduledTask -TaskName $Script:TaskName -ErrorAction Stop
    $action = $task.Actions | Select-Object -First 1
    if (-not $action -or $action.Execute -ne $AgentPath) {
        $actual = if ($action) { $action.Execute } else { '(none)' }
        throw "Scheduled task action mismatch: expected '$AgentPath', got '$actual'"
    }

    $logonTrigger = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' })
    if ($logonTrigger.Count -lt 1) {
        throw "Scheduled task '$($Script:TaskName)' has no AtLogOn trigger"
    }

    $principalName = $task.Principal.UserId
    if ($principalName -and ($principalName -ne $RunAs)) {
        throw "Scheduled task user mismatch: expected '$RunAs', got '$principalName'"
    }
}

function Register-SyncLayerScheduledTaskViaApi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AgentPath,
        [Parameter(Mandatory = $true)]
        [string]$RunAs,
        [Parameter(Mandatory = $true)]
        [string]$AgentDir
    )

    Unregister-ScheduledTask -TaskName $Script:TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

    $action = New-ScheduledTaskAction -Execute $AgentPath -WorkingDirectory $AgentDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $RunAs
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask `
        -TaskName $Script:TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
}

function Register-SyncLayerScheduledTaskViaSchtasks {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AgentPath,
        [Parameter(Mandatory = $true)]
        [string]$RunAs
    )

    $command = "`"$AgentPath`""
    $output = & schtasks.exe /Create /F /TN $Script:TaskName /TR $command /SC ONLOGON /RL HIGHEST /RU $RunAs /IT /NP 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed ($LASTEXITCODE): $output"
    }
}

function Register-SyncLayerScheduledTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AgentPath
    )

    if (-not (Test-Path $AgentPath)) {
        throw "Agent executable not found: $AgentPath"
    }

    $runAs = Get-SyncLayerInteractiveUser
    $agentDir = Split-Path -Parent $AgentPath
    $errors = @()

    try {
        Register-SyncLayerScheduledTaskViaApi -AgentPath $AgentPath -RunAs $runAs -AgentDir $agentDir
    } catch {
        $errors += "Register-ScheduledTask: $($_.Exception.Message)"
        try {
            Register-SyncLayerScheduledTaskViaSchtasks -AgentPath $AgentPath -RunAs $runAs
        } catch {
            $errors += "schtasks.exe: $($_.Exception.Message)"
            throw ($errors -join '; ')
        }
    }

    Assert-SyncLayerScheduledTask -AgentPath $AgentPath -RunAs $runAs
}

function Start-SyncLayerAgentOnce {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AgentPath
    )

    if (-not (Test-Path $AgentPath)) {
        throw "Agent executable not found: $AgentPath"
    }

    $running = Get-SyncLayerProcessCount
    if ($running -eq 1) {
        return
    }

    if ($running -gt 1) {
        Stop-SyncLayerProcesses
    }

    $agentDir = Split-Path -Parent $AgentPath
    $proc = Start-Process `
        -FilePath $AgentPath `
        -WorkingDirectory $agentDir `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 5

    if ($proc.HasExited) {
        $logFile = Join-Path $agentDir 'agent.log'
        $tail = @()
        if (Test-Path $logFile) {
            $tail = @(Get-Content $logFile -Tail 20 -Encoding UTF8 -ErrorAction SilentlyContinue)
        }
        $hint = if ($tail.Count) { ($tail -join ' | ') } else { '(agent.log missing — exe may be blocked by antivirus)' }
        throw "SyncLayerAgent exited immediately (code $($proc.ExitCode)). Recent log: $hint"
    }

    $running = Get-SyncLayerProcessCount
    if ($running -lt 1) {
        throw 'SyncLayerAgent process not found after start (may have been killed by antivirus)'
    }
}

function Test-SyncLayerScheduledTaskExists {
    & schtasks.exe /Query /TN $Script:TaskName /FO LIST 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-SyncLayerLegacyScheduledTasks {
    $found = @()
    foreach ($name in $Script:LegacyTaskNames) {
        & schtasks.exe /Query /TN $name /FO LIST 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $found += $name
        }
    }
    return $found
}

function Get-SyncLayerRunKeyEntries {
    $found = @()
    foreach ($path in $Script:RunKeyPaths) {
        if (-not (Test-Path $path)) {
            continue
        }
        foreach ($valueName in $Script:RunValueNames) {
            $value = Get-ItemProperty -Path $path -Name $valueName -ErrorAction SilentlyContinue
            if ($null -ne $value) {
                $found += "${path}::$valueName"
            }
        }
    }
    return $found
}

function Test-SyncLayerServiceInstalled {
    & sc.exe query $Script:ServiceName 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Test-SyncLayerInstall {
    param(
        [int]$ExpectedProcessCount = 1,
        [bool]$RequireScheduledTask = $true
    )

    $errors = @()
    $processCount = Get-SyncLayerProcessCount

    if ($processCount -ne $ExpectedProcessCount) {
        $errors += "Expected $ExpectedProcessCount SyncLayerAgent.exe process(es), found $processCount"
    }

    if (Test-SyncLayerServiceInstalled) {
        $errors += 'SyncLayer Windows Service is still installed'
    }

    $taskExists = Test-SyncLayerScheduledTaskExists
    if ($RequireScheduledTask -and -not $taskExists) {
        $errors += "Scheduled task '$($Script:TaskName)' is missing"
    }
    if (-not $RequireScheduledTask -and $taskExists) {
        $errors += "Scheduled task '$($Script:TaskName)' is still present"
    }

    $legacyTasks = Get-SyncLayerLegacyScheduledTasks
    if ($legacyTasks.Count -gt 0) {
        $errors += "Legacy scheduled tasks still present: $($legacyTasks -join ', ')"
    }

    $runEntries = Get-SyncLayerRunKeyEntries
    if ($runEntries.Count -gt 0) {
        $errors += "Registry Run entries still present: $($runEntries -join '; ')"
    }

    return [PSCustomObject]@{
        Ok = ($errors.Count -eq 0)
        Errors = $errors
        ProcessCount = $processCount
        ServiceInstalled = (Test-SyncLayerServiceInstalled)
        ScheduledTaskExists = $taskExists
        LegacyScheduledTasks = $legacyTasks
        RunKeyEntries = $runEntries
    }
}

function Invoke-SyncLayerInstallFinalize {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AgentPath,
        [string]$AgentDir = $null,
        [switch]$SkipStart,
        [switch]$SkipVerify
    )

    if (-not $AgentDir) {
        $AgentDir = Split-Path -Parent $AgentPath
    }

    Remove-LegacySyncLayerInstall -AgentDir $AgentDir -StopProcesses
    Register-SyncLayerScheduledTask -AgentPath $AgentPath

    if (-not $SkipStart) {
        Start-SyncLayerAgentOnce -AgentPath $AgentPath
    }

    if ($SkipVerify) {
        return (Test-SyncLayerInstall -ExpectedProcessCount $(if ($SkipStart) { 0 } else { 1 }))
    }

    $expected = if ($SkipStart) { 0 } else { 1 }
    $result = Test-SyncLayerInstall -ExpectedProcessCount $expected
    if (-not $result.Ok) {
        throw ($result.Errors -join '; ')
    }
    return $result
}

function Get-SyncLayerScheduledTaskState {
    $output = & schtasks.exe /Query /TN $Script:TaskName /FO LIST /V 2>$null
    if ($LASTEXITCODE -ne 0) {
        return 'Missing'
    }
    $statusLine = $output | Where-Object { $_ -match '^Status:' } | Select-Object -First 1
    if ($statusLine) {
        return ($statusLine -replace '^Status:\s*', '').Trim()
    }
    return 'Present'
}

function Get-SyncLayerAgentDir {
    $candidates = @(
        (Join-Path $env:ProgramData 'SyncLayer'),
        (Join-Path ${env:ProgramFiles} 'SyncLayer')
    )
    foreach ($dir in $candidates) {
        if (Test-Path (Join-Path $dir 'SyncLayerAgent.exe')) {
            return $dir
        }
    }
    return $candidates[0]
}

function Get-SyncLayerAgentDiagnostics {
    $agentDir = Get-SyncLayerAgentDir
    $logFile = Join-Path $agentDir 'agent.log'
    $traceFile = Join-Path $agentDir 'activity_trace.jsonl'
    $procs = @(Get-Process -Name 'SyncLayerAgent' -ErrorAction SilentlyContinue)

    $diag = [PSCustomObject]@{
        ProcessCount = $procs.Count
        Pids = @($procs | ForEach-Object { $_.Id })
        RamMb = if ($procs.Count -gt 0) {
            [math]::Round((($procs | Measure-Object WorkingSet64 -Sum).Sum / 1MB), 1)
        } else { 0 }
        TaskState = Get-SyncLayerScheduledTaskState
        AgentDir = $agentDir
        AgentLog = $logFile
        ActivityTrace = $traceFile
        DebugMode = $env:SYNCLAYER_DEBUG
        AgentLogTail = @()
    }

    if (Test-Path $logFile) {
        $diag.AgentLogTail = @(Get-Content $logFile -Tail 20 -Encoding UTF8 -ErrorAction SilentlyContinue)
    }

    return $diag
}

function Write-SyncLayerRuntimeReport {
    $diag = Get-SyncLayerAgentDiagnostics

    Write-Host ''
    Write-Host 'SyncLayer runtime diagnostics'
    Write-Host "  Process count     : $($diag.ProcessCount)"
    Write-Host "  PID(s)            : $(if ($diag.Pids.Count) { $diag.Pids -join ', ' } else { '(none)' })"
    Write-Host "  Task state        : $($diag.TaskState)"
    Write-Host "  RAM_MB (WorkingSet): $($diag.RamMb)"
    Write-Host "  SYNCLAYER_DEBUG   : $(if ($diag.DebugMode) { $diag.DebugMode } else { '(not set)' })"
    Write-Host "  agent.log         : $($diag.AgentLog)"
    Write-Host "  activity_trace    : $($diag.ActivityTrace)"
    Write-Host ''
    Write-Host 'Last 20 lines of agent.log:'
    if ($diag.AgentLogTail.Count -eq 0) {
        Write-Host '  (log file missing or empty)'
    } else {
        foreach ($line in $diag.AgentLogTail) {
            Write-Host "  $line"
        }
    }
    Write-Host ''
}

function Write-SyncLayerInstallReport {
    param(
        [Parameter(Mandatory = $true)]
        $Result
    )

    Write-Host ''
    Write-Host 'SyncLayer install verification'
    Write-Host "  SyncLayerAgent.exe processes : $($Result.ProcessCount)"
    Write-Host "  SyncLayer service installed  : $($Result.ServiceInstalled)"
    Write-Host "  SyncLayerAgent task present  : $($Result.ScheduledTaskExists)"
    Write-Host "  Legacy scheduled tasks       : $(if ($Result.LegacyScheduledTasks.Count) { $Result.LegacyScheduledTasks -join ', ' } else { '(none)' })"
    Write-Host "  Registry Run entries         : $(if ($Result.RunKeyEntries.Count) { $Result.RunKeyEntries -join '; ' } else { '(none)' })"
    Write-Host ''

    if ($Result.Ok) {
        Write-Host 'OK: install layout is clean (1 process + 1 task + 0 services).'
    } else {
        Write-Host 'FAILED:'
        foreach ($err in $Result.Errors) {
            Write-Host "  - $err"
        }
    }
}
