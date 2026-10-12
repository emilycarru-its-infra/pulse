# Pulse core

The contract every Pulse product shares, and the Python package `pulse_core` that
implements the parts of it that are logic rather than data.

## Agent events

A ComputersPulse agent sends one JSON event to `POST /api/ingest` every 60 seconds
(`heartbeat`) and whenever something changes (`login`, `logout`, `lock`, `unlock`,
`boot`, `shutdown`). The shape is [`contract/event.schema.json`](contract/event.schema.json);
[`contract/examples/heartbeat.json`](contract/examples/heartbeat.json) is a full example.

An event never carries a username or anything else about the person at the machine.
The schema rejects unknown fields, so adding one is a contract change, not a quiet extra.

## Seat states

`pulse_core.state.seat_state` turns a seat's last event into one of five states:

| State | When |
|---|---|
| `out_of_service` | The site config marks the seat out of service |
| `offline` | No event for 5 minutes, never seen, or the last event was `shutdown` |
| `available` | Nobody is signed in |
| `possibly_free` | Someone is signed in but the session is locked or idle for 15 minutes or more |
| `in_use` | Someone is signed in and active |

## Space catalog

A product shows spaces (a lab, a row of open-access stations, a kiosk, a podium) and
the seats in each. The catalog is built, not hand-written:

- The **inventory system** supplies every device: hostname, asset tag, serial,
  platform, category, room and group.
- A **site config** (TOML, kept in the deploy repo) says which group and rooms make up
  each space, where each seat sits on the floorplan, and which seats are out of service.
  [`contract/examples/site.toml`](contract/examples/site.toml) shows the format.

Run the builder with a read-only inventory token in the environment:

```bash
PULSE_INVENTORY_TOKEN=... python -m pulse_core.catalog site.toml --out catalog.json
```

It writes the catalog, which follows [`contract/catalog.schema.json`](contract/catalog.schema.json),
and lists on stderr every seat the inventory has but the config has not placed, and
every placed seat the inventory no longer has. `--strict` turns either into a failure.

### Inventory providers

Providers live in `pulse_core/inventory/` and all return the same `Device` record, so
changing inventory systems means adding a provider and changing one line of the site
config. `snipeit` reads `/api/v1/hardware`; the custom-field names it reads for hostname,
platform and group are set under `[inventory.fields]`. Any inventory serving the same
API can use it unchanged.

## History export

Each product keeps every event it receives in an append-only table and serves it to the
data warehouse from `GET /api/export/events?since=<RFC 3339 time>`, as newline-delimited
JSON in the event shape plus a `receivedAt` field, oldest first. Callers authenticate with
an Entra token carrying the export role; there is no shared key. Pulse holds live state;
long-term history and reporting belong to the warehouse.

## Tests

```bash
pip install -e '.[test]' && pytest
```
