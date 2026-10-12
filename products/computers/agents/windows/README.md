# Windows agent

Tells the Computers status page whether this computer is free, in use, locked or off. It sends
the [event contract](../../../../core/contract/event.schema.json) to the product's ingest address
and never sends who is signed in.

Three programs, published together into one folder:

- **The command-line agent** (`managedpulse.exe`) runs as SYSTEM from boot through a scheduled
  task. Every 15 seconds it reads the signed-in session; a sign-in, sign-out, lock or unlock is
  sent at once, and otherwise a heartbeat goes every 60 seconds. A failed send is dropped: the next
  heartbeat catches up, and the server shows a silent computer as off after five minutes.
- **The idle helper** (`managedpulse-idle.exe`) runs in each signed-in user's session from log on
  and writes that session's keyboard and mouse idle time to `ProgramData\<product>\idle\`. Windows
  does not give a SYSTEM process the console session's input time; without the helper the agent
  falls back to the session's own figure, which is reliable for remote sessions only.
- **The GUI** (`Managed Presence Beacon.exe`) has the Prefs, Run and Logs tabs of the other
  management tools.
  - **Prefs** shows the settings. A value set by policy appears greyed out with a lock and the word *Managed*. Prefs is read-only until **Unlock** relaunches the app as administrator.
  - **Run** shows what the agent last saw and sent, and has **Send now**.
  - **Logs** follows the agent's daily log.

The product's names (executables, registry keys, data folder, task names) are all set in
[`Directory.Build.props`](Directory.Build.props).

## Settings

The agent reads each value from policy first, under `HKLM\SOFTWARE\Policies\<product>`, which
Intune or Group Policy writes. Otherwise it uses the machine settings under
`HKLM\SOFTWARE\<product>`, which the GUI writes.

| Value | Type | Default | |
| --- | --- | --- | --- |
| `IngestUrl` | string | none | The product's `POST /api/ingest` address |
| `IngestKey` | string | none | Optional shared key sent as `X-Pulse-Key`, for a pilot |
| `CheckIntervalSeconds` | DWORD | 15 | 5 to 300 |
| `HeartbeatIntervalSeconds` | DWORD | 60 | 15 to 3600, never below the check interval |
| `UseDeviceCertificate` | DWORD | 1 | Present the Entra device certificate |
| `VerboseLogging` | DWORD | 0 | Log every event body |

## Authentication

On an Entra-joined computer, the agent presents the device's Entra certificate as its TLS
client certificate. That certificate is issued by `MS-Organization-Access`, its subject is the
Entra device id, and its key is held by the TPM. The ingest service checks the chain and maps the
device id to a seat. A shared key can be added for a pilot.

## Build

Run this on Windows with the .NET 10 SDK and the Windows SDK installed:

```powershell
.\build.ps1 -Test
```

Each architecture lands in `publish\<arch>\` with `names.json` and the install scripts. Sign the
executables before deploying them. A Defender attack surface reduction rule that blocks
unprevalent executables, which is common on managed fleets, refuses unsigned builds.

## Install

From the install folder, as an administrator (a package's postinstall):

```powershell
.\install.ps1
```

It refuses an install folder users can write to, takes over the data folder safely (owned by
Administrators, links never followed), and registers three tasks: the agent, the idle helper and a
shutdown sender triggered by event 1074. Then it starts the agent. `uninstall.ps1` reverses this.

## Commands

```text
managedpulse                 run the agent loop
managedpulse status [--json] show what the agent sees and the event it would send
managedpulse send [--type T] send one event now
managedpulse --version
```
