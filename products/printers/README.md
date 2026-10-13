# PrintersPulse

Shows which printers are ready, printing, need attention, are stopped or are not responding,
on the same floorplans as ComputersPulse, with each printer's supplies, paper and queue.

**Today every state is sample data.** The printers, their models, rooms and queues come from
the inventory; what each one is doing is made up from its id and the clock
(`api/pulse_printers/service.py`), so the page can be shown before a collector exists. Every
API response carries `"sample": true` and the page says so in a banner.

- `api/pulse_printers/catalog.py`: builds the catalog from the inventory: printers in service, their kind (colour, inkjet), audience, queues and place on the plans.
- `api/pulse_printers/service.py`: status and summary, from the sample generator.
- `api/function_app.py`: the Azure Functions host; `api/pack.sh` builds its package.
- `api/pulse_printers/devserver.py`: the page and the API on one local port.
- `web/`: the page, on the shared shell in `core/web`: a tab per floor with each printer on the plan, a room drawer, and a list view.

## Endpoints

| Method and path | Who calls it | Returns |
|---|---|---|
| `GET /api/status` | The page, every 15 seconds | Every printer with its state, detail, supplies, trays, queue and jobs today |
| `GET /api/summary` | The hub | One line, a level (`ok`, `warn`, `bad`, `idle`) and the counts |
| `POST /api/GetRoles` | The Static Web App's sign-in | The Static Web App roles for the user's app roles |

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

The same [`pulse-product`](../../core/terraform/pulse-product) module as ComputersPulse. With
no agents, nothing posts to `/api/ingest` and the product's tables stay empty. App settings:
`PULSE_CATALOG_PATH`, `PULSE_TITLE`, `PULSE_TIMEZONE` (the time zone the sample day follows)
and `PULSE_SWA_ROLES`.

## Next: real state

A collector reads the print server's API on a timer (printer status, toner, paper and queue
lengths, jobs today) and replaces `sample()`; the response shape stays the same.
