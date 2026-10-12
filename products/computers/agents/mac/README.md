# Managed Presence Beacon (Mac)

The Mac agent for ComputersPulse. It tells the Pulse server whether this Mac's console is
in use, locked or free, and never who is using it.

- `managedpresencebeacon` is the agent. A LaunchDaemon runs `managedpresencebeacon run`, which looks at the
  console every 15 seconds and sends at once when someone signs in or out or the screen
  locks or unlocks, and a heartbeat every 60 seconds otherwise. A failed send is dropped;
  the next heartbeat brings the seat up to date. On shutdown it sends `shutdown`.
- **Managed Presence Beacon.app** in /Applications/Utilities is the Prefs / Run / Logs
  window. A privileged helper inside it writes the machine-level settings and runs
  `managedpresencebeacon send` for Send Now; it trusts only an app signed by its own team.
- Every event follows [`core/contract/event.schema.json`](../../../../core/contract/event.schema.json).

## Settings

Every setting lives in the `com.github.computerpulse` preference domain, so a
configuration profile manages any of them. A managed value shows in the app greyed,
with a lock and the word Managed, and the helper refuses to change it.

| Key | Type | Default | |
|---|---|---|---|
| `IngestURL` | string | none | The server's ingest endpoint |
| `IngestKey` | string | none | Optional shared key, sent as `X-Pulse-Key` |
| `CheckInterval` | integer | 15 | Seconds between looks at the console (5–120) |
| `HeartbeatInterval` | integer | 60 | Seconds between heartbeats (30–600) |
| `VerboseLogging` | boolean | false | Log every check, not only sends |

[`examples/com.github.computerpulse.mobileconfig`](examples/com.github.computerpulse.mobileconfig)
sets them all.

## Proving which Mac is reporting

When the server asks for a client certificate, the agent presents the Intune agent's
identity from the System keychain: subject `IntuneMDMAgent-<Intune device id>`, issued by
`Microsoft Intune MDM Agent CA`. Its key signs without a prompt. Only the System keychain
is searched, never with user interface, so the agent can never raise a keychain dialog.
The server checks the chain and maps the Intune device id to a seat. `managedpresencebeacon status`
shows the certificate it found and whether its key is usable.

## Files

- `/Library/Managed Presence/logs/managedpresencebeacon.log`, rolled at 5 MB.
- `/Library/Managed Presence/last-send.json`, the last send, which the Run tab shows.
- `/usr/local/computerpulse/managedpresencebeacon` and `/usr/local/bin/managedpresencebeacon`, links into the app bundle.

## Build

`swift test` runs the tests, and `make` builds the app bundle into `build/root`. Signing
happens in the internal build:

```bash
make app pkg VERSION=2026.10.12.1342
```

```bash
make app sign pkg notarize SIGNING_IDENTITY_APP="…" SIGNING_IDENTITY_PKG="…" NOTARIZATION_PROFILE="…"
```

A `v*` tag publishes the unsigned app as `ComputerPulse-App-<version>.zip` on the GitHub release,
for a deploying pipeline to sign and package.

The helper accepts only an app signed by its own team, so an unsigned build shows the
helper as unavailable and Send Now stays off; `managedpresencebeacon send` still works from a
root shell.
