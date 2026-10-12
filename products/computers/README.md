# ComputersPulse

Shows which shared computers are free, in use, possibly free or off, space by space.

- `api/pulse_computers/service.py`: the API as plain functions: ingest, status, summary, export.
- `api/pulse_computers/store.py`: where events are kept. `MemoryStore` for local runs; the deployed store has the same two operations.
- `api/pulse_computers/simulate.py`: sends made-up agent events for every seat in a catalog.
- `api/pulse_computers/devserver.py`: runs the hub, this page and the API on one local port.
- `web/`: the page: a tab per floor, the floor's plan with each space and seat drawn on it, pan and zoom (`core/web/viewport.js`), a details drawer, and a list view. Plain HTML, CSS and JavaScript on the shared shell in `core/web`.

## Endpoints

| Method and path | Who calls it | Returns |
|---|---|---|
| `POST /api/ingest` | Agents, with the ingest key in `X-Pulse-Key` | `202`, or `400` for an event that breaks the contract |
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
