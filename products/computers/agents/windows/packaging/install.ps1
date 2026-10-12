<#
.SYNOPSIS
    Registers the agent on this computer, from the folder it was installed to.

.DESCRIPTION
    Run as an administrator (a package's postinstall) from Program Files\<product>, which only
    administrators can write. It:
      - checks the data folder under ProgramData: if one is already there and is a link or is owned
        by anyone but SYSTEM or Administrators, it stops and says so; otherwise it creates the folder
        and at once gives it a protected ACL (SYSTEM and Administrators full control), before anything
        is written in it;
      - creates logs\ inside it, which users may read (the agent's log and status.json), and idle\,
        where each signed-in user may add and change only their own idle report;
      - registers the agent task (SYSTEM, from boot), the idle task (each user's session, at log on)
        and the shutdown task (Windows event 1074), and starts the agent.
    The agent reads its settings only from HKLM, never from ProgramData.
#>
$ErrorActionPreference = 'Stop'
$names = Get-Content (Join-Path $PSScriptRoot 'names.json') -Raw | ConvertFrom-Json
if ($names.product -notmatch '^[A-Za-z0-9]+$') { throw 'Unexpected product name in names.json' }

$here = Join-Path $env:ProgramFiles $names.product
if ([IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') -ne $here) { throw "Install to $here; this copy is in $PSScriptRoot." }
$cli = Join-Path $here "$($names.cli).exe"
$idle = Join-Path $here "$($names.idle).exe"
foreach ($exe in $cli, $idle) { if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Missing $exe" } }

function New-Rule([string]$Sid, [string]$Rights, [string]$Inherit = 'ContainerInherit,ObjectInherit', [string]$Propagate = 'None') {
    New-Object System.Security.AccessControl.FileSystemAccessRule(
        (New-Object Security.Principal.SecurityIdentifier $Sid), $Rights, $Inherit, $Propagate, 'Allow')
}

# Uses the folder at $Path, creating it if needed, and gives it a protected ACL: owned by
# Administrators, SYSTEM and Administrators full control, plus $Extra rules. An existing folder
# that is a link or that anyone else owns stops the install; it is never repaired or deleted.
function Set-ProtectedDirectory([string]$Path, [object[]]$Extra = @()) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        $owner = $item.GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or @('S-1-5-18', 'S-1-5-32-544') -notcontains $owner) {
            throw "$Path already exists and is a link or is not owned by SYSTEM or Administrators. Remove it, then install again."
        }
    } else {
        $item = New-Item -ItemType Directory -Path $Path
    }
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'))
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @((New-Rule 'S-1-5-18' 'FullControl'), (New-Rule 'S-1-5-32-544' 'FullControl')) + $Extra) { $acl.AddAccessRule($rule) }
    $item.SetAccessControl($acl)
}

$data = Join-Path $env:ProgramData $names.product
Set-ProtectedDirectory $data
Set-ProtectedDirectory (Join-Path $data 'logs') @(New-Rule 'S-1-5-32-545' 'ReadAndExecute')
Set-ProtectedDirectory (Join-Path $data 'idle') @(
    (New-Rule 'S-1-5-11' 'ReadAndExecute, CreateFiles' 'None'),
    (New-Rule 'S-1-3-0' 'Modify' 'ObjectInherit' 'InheritOnly'))

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$system = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $names.product -Force `
    -Description 'Sends this computer''s seat state (free, in use, locked, idle) to the campus status page. Sends no usernames.' `
    -Action (New-ScheduledTaskAction -Execute "`"$cli`"" -Argument 'run' -WorkingDirectory $here) `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $system -Settings $settings | Out-Null

Register-ScheduledTask -TaskName "$($names.product) Idle" -Force `
    -Description 'Reports keyboard and mouse idle time for this session to the agent. Sends nothing itself.' `
    -Action (New-ScheduledTaskAction -Execute "`"$idle`"" -WorkingDirectory $here) `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
    -Principal (New-ScheduledTaskPrincipal -GroupId 'S-1-5-32-545' -RunLevel Limited) `
    -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances Parallel) | Out-Null

# Windows logs event 1074 (User32) when a shutdown or restart starts.
$shutdownTask = "$($names.product) Shutdown"
Register-ScheduledTask -TaskName $shutdownTask -Force `
    -Description 'Sends one shutdown event so the status page shows this computer off at once.' `
    -Action (New-ScheduledTaskAction -Execute "`"$cli`"" -Argument 'send --type shutdown' -WorkingDirectory $here) `
    -Principal $system -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 1)) | Out-Null
$task = Get-ScheduledTask -TaskName $shutdownTask
$task.Triggers = @(Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskEventTrigger |
    New-CimInstance -ClientOnly -Property @{
        Enabled = $true
        Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''User32''] and EventID=1074]]</Select></Query></QueryList>'
    })
$task | Set-ScheduledTask | Out-Null

Stop-ScheduledTask -TaskName $names.product -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $names.product
Write-Host "Registered $($names.product), $($names.product) Idle and $shutdownTask; the agent is running."
