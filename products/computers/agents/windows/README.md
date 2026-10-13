# Windows agent

Tells the Computers status page whether this computer is free, in use, locked or off. It sends
the [event contract](../../../../core/contract/event.schema.json) to the product's ingest address
and never sends who is signed in.

Three programs, published together into one folder:

- **The command-line agent** (`managedpresencebeacon.exe`) runs as SYSTEM from boot through a scheduled
  task. Every 15 seconds it reads the console session, the one at the keyboard and screen (a
  remote desktop session leaves the seat free, so it does not count); a sign-in, sign-out, lock or unlock is
  sent at once, and otherwise a heartbeat goes every 60 seconds. A failed send is dropped: the next
  heartbeat catches up, and the server shows a silent computer as off after five minutes.
- **The idle helper** (`managedpresencebeacon-idle.exe`) runs in each signed-in user's session from log on
  and writes that session's keyboard and mouse idle time to `ProgramData\<data>\idle\`. Windows
  does not give a SYSTEM process the console session's input time; without the helper the agent
  falls back to the session's own figure.
- **The GUI** (`Managed Presence Beacon.exe`) has the Prefs, Run and Logs tabs of the other
  management tools.
  - **Prefs** shows the settings and, in a **Services** card, the agent's scheduled tasks with their state, trigger, last result and program. A value set by policy appears in a grey, disabled control, and one line at the top of the tab says so. Every other setting can be edited and saves itself; the settings live in HKLM, so saving asks for an administrator through UAC at that moment.
  - **Run** shows what the agent last saw and sent, and has **Send now**.
  - **Logs** follows the agent's daily log.

The names are all set in [`Directory.Build.props`](Directory.Build.props). The tool is
ComputerPulse (`<product>` below): its install folder, registry and policy keys and scheduled
tasks. Managed Presence Beacon is the GUI and `managedpresencebeacon` the command line, and data and logs
live in `ProgramData\ManagedPresence` (`<data>`).

## Settings

The agent reads each value from policy first, under `HKLM\SOFTWARE\Policies\<product>`, which
Intune or Group Policy writes. Otherwise it uses the machine settings under
`HKLM\SOFTWARE\<product>`, which the GUI writes.

| Value | Type | Default | |
| --- | --- | --- | --- |
| `IngestUrl` | string | none | The product's `POST /api/ingest` address |
| `IngestKey` | string | none | Optional shared key sent as `X-Pulse-Key`, for a pilot. Read only from `HKLM\SOFTWARE\<product>\Secrets`, which SYSTEM and Administrators alone can read; never from policy or the readable keys |
| `CheckIntervalSeconds` | DWORD | 15 | 5 to 300 |
| `HeartbeatIntervalSeconds` | DWORD | 60 | 15 to 3600, never below the check interval |
| `UseDeviceCertificate` | DWORD | 1 | Present the Intune MDM device certificate |
| `VerboseLogging` | DWORD | 0 | Log every event body |

## Authentication

On an Intune-enrolled computer, the agent presents the device's Intune MDM certificate as its
TLS client certificate, as the Mac agent presents the Intune agent's. That certificate is issued
by `Microsoft Intune MDM Device CA`, its subject is the Intune device id, and its key is in the
machine store. The Entra device certificate is not used: its issuer is not published, so the
service has no CA to check it against. The ingest service checks the chain and maps the
device id to a seat. A shared key can be added for a pilot.

## Build

Run this on Windows with the .NET 10 SDK and the Windows SDK installed:

```powershell
.\build.ps1 -Test
```

Each architecture lands in `publish\<arch>\` with `names.json` and the install scripts. Sign the
executables before deploying them. A `v*` tag publishes each install folder unsigned as
`computerpulse-<arch>.zip` on the GitHub release; [`build-info.yaml`](build-info.yaml) and
[`scripts/`](scripts) are the cimipkg package definition a deploying pipeline signs and wraps it
with. A Defender attack surface reduction rule that blocks
unprevalent executables, which is common on managed fleets, refuses unsigned builds.

## Install

From the install folder, as an administrator (a package's postinstall):

```powershell
.\install.ps1
```

It runs only from `Program Files\<product>`, which only administrators can write. If a data
folder is already in ProgramData and is a link, or is owned by anyone but SYSTEM or
Administrators, it stops and says so; otherwise it creates the folder and gives it a protected
ACL before anything is written. Users may read `logs\` (the log and `status.json`), and each
signed-in user may add and change only their own report in `idle\`. It then registers three
tasks (the agent, the idle helper, and a shutdown sender triggered by event 1074) and starts the
agent. `uninstall.ps1` removes the tasks and the install folder and keeps the logs. The agent
reads its settings only from HKLM.

## Commands

```text
managedpresencebeacon                 run the agent loop
managedpresencebeacon status [--json] show what the agent sees and the event it would send
managedpresencebeacon send [--type T] send one event now
managedpresencebeacon --version
```
