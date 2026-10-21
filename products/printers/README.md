# PrintersPulse

Shows which printers are ready, printing, need attention, are stopped or are not responding,
on the same floorplans as ComputersPulse, with each printer's supplies, paper and queue.

The printers, their models, rooms and queues come from the inventory. What each one is doing
comes from a source, chosen with `PULSE_SOURCE`:

- `live`: what a poller beside the print server posts to `POST /api/ingest/health` (below).
- `sample` (the default): made up from the printer's id and the clock
  (`api/pulse_printers/service.py`), so the page can be shown before a sender exists. Every
  API response then carries `"sample": true` and the page says so in a banner.

- `api/pulse_printers/catalog.py`: builds the catalog from the inventory: printers in service, their kind (colour, inkjet), audience, queues and place on the plans.
- `api/pulse_printers/service.py`: status and summary from a catalog and a source; the sample generator.
- `api/pulse_printers/live.py`: the `live` source, the push parser, queue matching and the store.
- `api/pulse_printers/auth.py`: the push token check.
- `api/function_app.py`: the Azure Functions host; `api/pack.sh` builds its package.
- `api/pulse_printers/devserver.py`: the page and the API on one local port.
- `web/`: the page, on the shared shell in `core/web`: a tab per floor with each printer on the plan, a room drawer, and a list view.

## Endpoints

| Method and path | Who calls it | Returns |
|---|---|---|
| `GET /api/status` | The page, every 15 seconds | Every printer with its state, detail, supplies, trays, queue and jobs today |
| `GET /api/summary` | The hub | One line, a level (`ok`, `warn`, `bad`, `idle`) and the counts |
| `POST /api/GetRoles` | The Static Web App's sign-in | The Static Web App roles for the user's app roles |
| `POST /api/ingest/health` | The print server's poller, directly on the Function App host | `202` with the queues matched and unmatched |

## Run it locally

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e core -e 'products/printers/api[test]'
```

Build the catalog from the inventory with the site config the module docstring describes:

```bash
PULSE_INVENTORY_TOKEN=... python -m pulse_printers.catalog site/printers.toml --out site/catalog.json
```

```bash
python -m pulse_printers.devserver --catalog site/catalog.json --assets site
```

Open http://localhost:8401/printers/. `--assets` is the folder holding the catalog's plan
images, `--theme` a site theme and `--timezone` the campus time zone the sample day follows.

## Deploy on Azure

The same [`pulse-product`](../../core/terraform/pulse-product) module as ComputersPulse; the
module's example has a printers call in live mode. App settings: `PULSE_CATALOG_PATH`,
`PULSE_TITLE`, `PULSE_TIMEZONE` (the time zone the sample day follows), `PULSE_SWA_ROLES`,
and for the live source `PULSE_SOURCE=live`, `PULSE_TENANT_ID`, `PULSE_INGEST_AUDIENCES` and
optionally `PULSE_STALE_SECONDS`. The module sets `PULSE_STORAGE_ACCOUNT` and
`PULSE_STATE_TABLE`. The push is reached directly rather than through the Static Web App, so
the site lists `/api/ingest/health` in the module's `browser_paths` (no client certificate)
and `unauthenticated_paths` (no Static Web App sign-in); the code checks the token.

## Live state

A poller beside the print server reads every queue's state every couple of minutes and posts
it to `POST /api/ingest/health` with an Entra ID app-only access token for this API's
application holding the `Pulse.Ingest` app role. The token's signature, issuer (the tenant in
`PULSE_TENANT_ID`), audience (one of `PULSE_INGEST_AUDIENCES`) and expiry are checked; a
delegated (user) token is refused.

```json
{
  "contract": "pulse.printer-health/1",
  "generated_at": "2026-01-05T15:00:00Z",
  "source": "data-platform",
  "printers": [{
    "key": { "print_queue": "PRINTSRV\\Lab-Colour" },
    "state": "attention",
    "detail": "Low toner (0%)",
    "held_jobs": 2,
    "jobs_today": 41,
    "pages_today": 180,
    "checked_at": "2026-01-05T14:59:30Z"
  }]
}
```

`state` is one of `ready`, `printing`, `attention`, `stopped`, `offline` and `unknown`;
`detail`, the counts and `checked_at` may be null (a null `checked_at` means `generated_at`).
Anything else is refused with `400`, as is a body over 2 MB or more than 5000 entries. A
queue is matched to the printer whose catalog `queues` list its name, without the server and
case-insensitively; unmatched queues are counted and dropped. A push is a snapshot: each
matched printer's stored queues are replaced by the ones it carried.

The live page shows the worst state among a printer's queues reported within
`PULSE_STALE_SECONDS` (default 600), with held jobs, jobs and pages today summed across them.
A printer with no report that recent is `unknown`, marked `"stale": true`, and keeps only when
it was last heard from; its old state is never shown as current. `stopped` reads as the page's
"Stopped". The print server reports no supplies or trays, so `supplies` and `trays` are null and
the page leaves them out. Responses carry `"sample": false`.

Links preserve the list/map view, floor, audience, selected room and individual printer together. A printer link opens the room drawer and highlights that printer. Copy-link icons appear on room headings, printer names and the filter toolbar on hover or keyboard focus, and remain visible on touch devices. Browser Back/Forward restores the selected view.
