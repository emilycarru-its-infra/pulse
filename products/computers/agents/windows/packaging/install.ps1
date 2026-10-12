<#
.SYNOPSIS
    Registers the agent on this computer, from the folder it was installed to.

.DESCRIPTION
    Run as an administrator (a package's postinstall) from the install folder, which holds the
    published build and names.json. It:
      - creates the data folder under ProgramData, readable by users, with an idle\ folder signed-in
        users can write their idle reports to;
      - registers the agent task: the command-line agent as SYSTEM from boot, restarted if it stops;
      - registers the idle task: the idle helper in each user's session at log on;
      - registers the shutdown task: one shutdown event when Windows logs a shutdown or restart;
      - starts the agent now.
    Settings (the ingest address, intervals) come from HKLM\SOFTWARE\<product> or from policy under
    HKLM\SOFTWARE\Policies\<product>; this script does not set them.
#>
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$names = Get-Content (Join-Path $here 'names.json') -Raw | ConvertFrom-Json
$cli = Join-Path $here "$($names.cli).exe"
$idle = Join-Path $here "$($names.idle).exe"
foreach ($exe in $cli, $idle) { if (-not (Test-Path $exe)) { throw "Missing $exe" } }

$data = Join-Path $env:ProgramData $names.product
$idleDir = Join-Path $data 'idle'
New-Item -ItemType Directory $data, (Join-Path $data 'logs'), $idleDir -Force | Out-Null
# Data: SYSTEM and Administrators full, Users read. Idle reports: authenticated users may write.
icacls $data /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
icacls $idleDir /grant '*S-1-5-11:(OI)(CI)M' | Out-Null

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

# The agent: SYSTEM, from boot, for as long as the computer runs.
Register-ScheduledTask -TaskName $names.product -Force `
    -Description 'Sends this computer''s seat state (free, in use, locked, idle) to the campus status page. Sends no usernames.' `
    -Action (New-ScheduledTaskAction -Execute $cli -Argument 'run' -WorkingDirectory $here) `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Principal (New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest) `
    -Settings $settings | Out-Null

# The idle helper: in each signed-in user's session, from log on.
$idleSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances Parallel
Register-ScheduledTask -TaskName "$($names.product) Idle" -Force `
    -Description 'Reports keyboard and mouse idle time for this session to the agent. Sends nothing itself.' `
    -Action (New-ScheduledTaskAction -Execute $idle -WorkingDirectory $here) `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
    -Principal (New-ScheduledTaskPrincipal -GroupId 'S-1-5-32-545' -RunLevel Limited) `
    -Settings $idleSettings | Out-Null

# Shutdown: Windows logs event 1074 (User32) when a shutdown or restart starts.
$shutdownTask = "$($names.product) Shutdown"
Register-ScheduledTask -TaskName $shutdownTask -Force `
    -Description 'Sends one shutdown event so the status page shows this computer off at once.' `
    -Action (New-ScheduledTaskAction -Execute $cli -Argument 'send --type shutdown' -WorkingDirectory $here) `
    -Principal (New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest) `
    -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 1)) | Out-Null
$task = Get-ScheduledTask -TaskName $shutdownTask
$trigger = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskEventTrigger |
    New-CimInstance -ClientOnly -Property @{
        Enabled = $true
        Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''User32''] and EventID=1074]]</Select></Query></QueryList>'
    }
$task.Triggers = @($trigger)
$task | Set-ScheduledTask | Out-Null

Stop-ScheduledTask -TaskName $names.product -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $names.product
Write-Host "Registered $($names.product), $($names.product) Idle and $shutdownTask; the agent is running."
