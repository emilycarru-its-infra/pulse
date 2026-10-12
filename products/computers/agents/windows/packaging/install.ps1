<#
.SYNOPSIS
    Registers the agent on this computer, from the folder it was installed to.

.DESCRIPTION
    Run as an administrator (a package's postinstall) from the install folder, which holds the
    published build and names.json. It:
      - refuses to run from a folder users can write to, since its tasks run those programs as SYSTEM;
      - creates the data folder under ProgramData owned by Administrators, writable only by SYSTEM and
        Administrators, taking it over safely if it already exists, with an idle\ folder in which each
        signed-in user may create and change only their own idle report;
      - registers the agent task: the command-line agent as SYSTEM from boot, restarted if it stops;
      - registers the idle task: the idle helper in each user's session at log on;
      - registers the shutdown task: one shutdown event when Windows logs a shutdown or restart;
      - starts the agent now.
    Settings (the ingest address, intervals) come from HKLM\SOFTWARE\<product> or from policy under
    HKLM\SOFTWARE\Policies\<product>; this script does not set them.
#>
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'safety.ps1')
$here = $PSScriptRoot
$names = Get-Content (Join-Path $here 'names.json') -Raw | ConvertFrom-Json
$cli = Join-Path $here "$($names.cli).exe"
$idle = Join-Path $here "$($names.idle).exe"
foreach ($exe in $cli, $idle) { if (-not (Test-Path -LiteralPath $exe)) { throw "Missing $exe" } }
foreach ($path in @($here) + (Get-ChildItem -LiteralPath $here -Filter *.exe | ForEach-Object FullName)) {
    if (Test-UserWritable $path) { throw "$path can be changed by users; install to a folder only administrators can write, such as Program Files." }
}

$data = Join-Path $env:ProgramData $names.product
New-SecureDirectory $data $env:ProgramData @('*S-1-5-32-545:(OI)(CI)RX')
New-SecureDirectory (Join-Path $data 'logs') $data @('*S-1-5-32-545:(OI)(CI)RX')
# Idle reports: signed-in users may add files and change only the ones they created.
New-SecureDirectory (Join-Path $data 'idle') $data @('*S-1-5-11:(RX,WD)', '*S-1-3-0:(OI)(CI)(IO)M')

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
