# ComputersPulse

Shows which shared computers are free, in use or off, space by space.

- `api/pulse_computers/service.py`: the API as plain functions: ingest, status, summary, export.
- `api/pulse_computers/store.py`: where events are kept. `MemoryStore` for local runs; `TableStore`, on Azure Table Storage, deployed.
- `api/pulse_computers/deviceauth.py`: checks an agent's device certificate and that it belongs to the seat its event names.
- `api/function_app.py`: the Azure Functions host for the API; `api/pack.sh` builds its package.
- `api/pulse_computers/simulate.py`: sends made-up agent events for every seat in a catalog.
- `api/pulse_computers/devserver.py`: runs the hub, this page and the API on one local port.
- `web/`: the page: a tab per floor, the floor's plan with each space and seat drawn on it, pan and zoom (`core/web/viewport.js`), a details drawer, and a list view. Plain HTML, CSS and JavaScript on the shared shell in `core/web`.

## Endpoints

| Method and path | Who calls it | Returns |
|---|---|---|
| `POST /api/ingest` | Agents, with a device certificate (deployed) or the ingest key in `X-Pulse-Key` | `202`; `400` for an event that breaks the contract, `401` with no credential, `403` for a certificate that is not the seat's or a hostname not in the catalog |
| `GET /api/status` | The page, every 15 seconds | Every space with its counts and each seat's state |
| `GET /api/summary` | The hub | One line, a level (`ok`, `warn`, `bad`, `idle`) and the counts |
| `GET /api/export/events?since=` | The data warehouse | Events received since then, newline-delimited JSON |

## Run it locally

Build a catalog first (see `core/README.md`), or start from the example. Then install both packages and start the server with the simulator:

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e core -e 'products/computers/api[test]'
```

```bash
python -m pulse_computers.devserver --catalog catalog.json --simulate
```

Open http://localhost:8400/ for the hub and http://localhost:8400/computers/ for this page. `--assets <folder>` is where the catalog's plan images are (the catalog's own folder by default). `--theme <folder>` swaps in a site theme: a `tokens.css` with the same token names as `core/web/theme`, a `brand.json` and its logos. `--speed` makes simulated idle time pass faster.

To place seats where the desks really are, add `--positions <file>.json`. The page then shows **Edit seats**: drag a seat, or focus it and use the arrow keys (Shift for 10 px), and it is saved to that file as you go. Point the site config's `[plans] positions` at the same file and commit it; the next catalog build puts the seats there.

## Deploy on Azure

[`core/terraform/pulse-product`](../../core/terraform/pulse-product) creates the Function App,
Static Web App and storage. The page and the read routes are served through the Static Web
App, behind its sign-in; agents post to `https://<function host>/api/ingest` directly.

`api/pack.sh <out-dir> catalog.json [device-cas.pem]` builds `function.zip`: `function_app.py`,
both packages, the contract and the files you add. Deploy it with a remote build, which
installs `requirements.txt`. The page's files (`web/`, `core/web/`, a theme and the catalog's
plan images under `catalog/`) go to the Static Web App.

The masthead menu lists the products in `/nav.json` when the site deploys one: an array of
`{ "id", "title", "href", "soon" }`. An entry with `soon` or no `href` is named but not linked,
marked "Coming soon". Without the file the menu links the hub's Overview and every live
product the hub lists. Leave out any product this page's audience may not see.

### App settings

The module sets the storage ones; the rest come from its `app_settings`.

| Setting | Default | |
|---|---|---|
| `PULSE_CATALOG_PATH` | `catalog.json` | The catalog deployed beside `function_app.py` |
| `PULSE_STORAGE_ACCOUNT` | none | Storage account name or table endpoint; unset keeps events in memory, for local runs |
| `PULSE_EVENTS_TABLE` | `events` | Every event |
| `PULSE_STATE_TABLE` | `state` | Latest event per seat |
| `PULSE_DEVICE_CA_PEM` | none | PEM bundle of the CAs that issue device certificates |
| `PULSE_DEVICE_CA_FILE` | none | Or a file in the package holding that bundle; both may be set |
| `PULSE_DEVICE_MAP` | `catalog` | Where a seat's device ids come from; `catalog` is the only source so far |
| `PULSE_INGEST_KEY` | none | A shared key accepted in `X-Pulse-Key`. Unset, key auth is off |
| `PULSE_TITLE` | `Computers` | Title in the summary |
| `PULSE_SWA_ROLES` | unset | Entra app role to Static Web App role, e.g. `Pulse.Everyone=everyone,Pulse.ITS=its`, for `/api/GetRoles` (the Static Web App's `rolesSource`) |

### Device certificates

`/api/ingest` requires a TLS client certificate: App Service completes the handshake only
when the agent proves it holds the certificate's key, then forwards the certificate in
`X-ARR-ClientCert`. It does not check the issuer. The API accepts an event when the certificate is signed by a CA in the bundle and
in date, and the device id in its subject is one the catalog lists for the event's hostname:

- Mac: subject `IntuneMDMAgent-<Intune device id>`, issued by `Microsoft Intune MDM Agent CA`.
- Windows: subject the Intune device id, issued by `Microsoft Intune MDM Device CA`.

Both CAs issue for every Microsoft tenant, so the seat mapping is what limits ingest to
your own computers. Fill it by naming the inventory fields that hold the ids in the site
config, `device_id_fields` under `[inventory.fields]`; the catalog build copies them into each
seat's `deviceIds`. A seat with no `deviceIds` can report only with the ingest key. Events
for hostnames not in the catalog are always refused.

The bundle holds the issuing CA certificates themselves, since the agents send only their
own certificate. Take each from a managed computer and check it on a second one. Export the
device certificate, then show its issuer and where the issuer's certificate is published:

```bash
security find-certificate -a -c IntuneMDMAgent- -p /Library/Keychains/System.keychain > mac-device.pem
```

```powershell
Get-ChildItem Cert:\LocalMachine\My | Where-Object Issuer -eq 'CN=Microsoft Intune MDM Device CA' | Select-Object -First 1 | Export-Certificate -FilePath win-device.cer
```

```bash
python -m pulse_computers.deviceauth mac-device.pem
```

Download the `issuer certificate` URL it prints and convert it to PEM. When the device
certificate carries no such URL, export the issuer from the chain Windows builds
(`certutil -verify win-device.cer`) or Keychain Access shows. On Windows the Intune MDM
Device CA is in the machine's intermediate store, `Cert:\LocalMachine\CA`.

```bash
openssl x509 -inform der -in issuer.cer -out issuer.pem
```

Put both issuers in one bundle and confirm devices of each platform verify against it:

```bash
python -m pulse_computers.deviceauth win-device.cer --ca device-cas.pem
```

Keep the old and new CA in the bundle across a CA renewal.

### Run the Functions host locally

With [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
and the venv above, put a catalog at `api/catalog.json` and a `local.settings.json` beside it:

```json
{"IsEncrypted": false, "Values": {"FUNCTIONS_WORKER_RUNTIME": "python", "AzureWebJobsStorage": "", "PULSE_INGEST_KEY": "dev"}}
```

```bash
cd products/computers/api && func start
```

Events stay in memory, and the key stands in for a certificate. Set `PULSE_STORAGE_ACCOUNT`
to use real tables through your own Azure sign-in.
