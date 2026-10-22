# ServersPulse

Server and service health for IT staff: every server, where it runs (a cloud account, an
on-premises cluster, the racks) and the services it carries, with the state, load and alerts
the monitoring systems report.

Servers report nothing themselves. Health comes from what already watches them, an uptime
service such as Site24x7 for every server and CloudWatch for cloud instances, in two ways:

- an hourly push of every server's state, load and latest checks from the site's data platform
  to `POST /api/ingest/health`, with an Entra ID app-only token holding the `Pulse.Ingest` role
  (contract `pulse.server-health/1`, below);
- alerts in seconds, straight from the monitoring systems:
  - cloud alarm state changes to `POST /api/alerts/cloudwatch`, from a federated sender (for
    example a function on the alarm rule) holding an Entra ID app-only token with the
    `Pulse.Alerts` role. The body is the EventBridge "CloudWatch Alarm State Change" event,
    `{"detail": ...}`, or the bare detail. No shared key is accepted on this route;
  - the uptime service's webhook to `POST /api/alerts/site24x7`, which cannot obtain a token,
    with its own shared key in `X-Pulse-Key`.

With `PULSE_SOURCE=live` the page shows what was posted. An alert newer than the push decides a
server's state, and a server nothing has been heard from for two hours is `unknown`. With
`PULSE_SOURCE=sample` the page makes up plausible health for every server and says so.

## Health push

```json
{
  "contract": "pulse.server-health/1",
  "generated_at": "2026-01-05T15:00:00Z",
  "source": "data-platform",
  "servers": [{
    "key": { "site24x7_monitor_id": "123", "aws_instance_id": "i-0abc", "hostname": "app-01" },
    "state": "up",
    "metrics": { "cpu": 12.5, "mem": 40, "disk": 55 },
    "checks": [{ "source": "Site24x7", "state": "ok", "at": "2026-01-05T14:58:00Z" }],
    "last_check": "2026-01-05T14:58:00Z"
  }]
}
```

`state` is one of `up`, `degraded`, `down`, `stopped` and `unknown`; a check's is `ok`, `warn`
or `down`. Metrics are percentages and may be null; `disk` is the fullest volume's use. The
reply is `202` with the number of servers matched and unmatched. A server is matched to the
catalog by `site24x7_monitor_id`, then `aws_instance_id`, then hostname against the server's
`hostname` or `name` (case-insensitive, short name).

## Layout

- `api/pulse_servers/service.py`: status and summary from a catalog and a health source
- `api/pulse_servers/simulate.py`: the `sample` source, a pure function of server and time
- `api/pulse_servers/live.py`: the `live` source, matching, the push and alert parsers, the store
- `api/pulse_servers/auth.py`: the push token and webhook key checks
- `api/function_app.py`: the Azure Functions host (`/api/status`, `/api/summary`, `/api/GetRoles`,
  `/api/ingest/health`, `/api/alerts/site24x7`, `/api/alerts/cloudwatch`)
- `api/pack.sh`: the Functions package, with the site's catalog added by the deploy
- `web/`: the page
- `examples/catalog.json`: a made-up catalog in the shape the site supplies

## Catalog

```json
{
  "title": "Servers",
  "locations": [{ "id": "cloud", "name": "Cloud", "detail": "…", "kind": "cloud", "sources": ["Site24x7", "CloudWatch"] }],
  "services": [{ "id": "sis", "name": "Student information system" }],
  "servers": [{ "id": "cloud-sis-01", "name": "SIS-APP", "location": "cloud", "role": "…", "env": "Production",
                "os": "…", "site": "…", "host": "…", "services": ["sis"], "stopped": false,
                "hostname": "sis-app", "site24x7_monitor_id": "…", "aws_instance_id": "…" }]
}
```

A server marked `stopped` is off on purpose and never counts against its group. `host` is the
machine a virtual server runs on. `hostname`, `site24x7_monitor_id` and `aws_instance_id` are
optional and match posted health to the server; the site fills them from its system of record.

## Run it locally

Install the package:

```bash
pip install -e 'products/servers/api[test]'
```

Serve the page with the example catalog on http://localhost:8401/:

```bash
python -m pulse_servers.devserver
```

Pass `--catalog` and `--theme` for a site's own. Deployed, the page is a Static Web App behind
single sign-on, linked to the Function App the `pulse-product` Terraform module creates. The
ingest and alert paths are reached directly, so the site's root lists them in the module's
`browser_paths` (no client certificate) and `unauthenticated_paths` (no Static Web App sign-in);
the code authenticates those callers itself.

## Active runtime observations

`POST /api/ingest/runtimes` accepts `pulse.server-runtimes/1` with an app-only `Pulse.Runtimes`
token. The deployment must explicitly allow that path through the host's client-certificate and
sign-in gates; application token verification still applies. Each row contains the canonical
item, reference and observation UUIDs, the API receipt time and effective observation time,
its accepted or collection-failed outcome, an exact `aws_instance_id` key and bounded runtime
facts. The sender exports the canonical observation response after acceptance. Receipt UUIDs
are provenance supplied by the trusted publisher, not independently dereferenced by Pulse.

Runtime observations match only a unique instance id in the site's catalog. Missing or ambiguous
matches are counted as unmatched; there is no hostname fallback. Runtime evidence never changes
server health. The latest successful component list remains visible as last observed after a
failed collection, and ages stale after one hour even when delivery is recent. A failed runtime
store read leaves health available and labels runtime collection unavailable.

The page filters running binaries by family with a dropdown, alongside searchable versions and
inline executable/service/container evidence. Selecting a family shows every matching server
and its reported versions; multiple versions on one server remain visible.
Installed packages do not prove a process is running. Windows executable file metadata is
labelled separately from a version command against an active executable image. Missing access,
embedded runtimes, linked libraries and unassessed containers must remain explicit gaps.

Binary observations include active executable evidence and installed host binaries. Each binary has a collapsible detail row with an inline Running or Inactive label; inactive means installed but not observed running at the check. Rows group matching binary/version/path evidence and list its services together. Package builds, when supplied, remain distinct from executable versions for advisory review. Freshness and collection gaps apply to both states.

Server service groups can be projected from authoritative inventory through
`POST /api/ingest/inventory`, authenticated by the dedicated `Pulse.Inventory` application
role. The bounded `pulse.server-inventory/1` snapshot contains a retrieval timestamp and
canonical item IDs, item versions and nullable `service_group` values. It contains no category
mapping. The receiver matches only configured `cellarum_item_id` identities; outside-catalog
items are counted separately and missing bindings remain unknown. Older versions cannot undo
newer classifications, and a newer blank value clears the previous group. Inventory failures
remain separate from health and runtime evidence.

The service view groups each server once by its inventory-owned `service_group` text field. Group labels come directly from that field, with no dashboard-owned category list or hostname inference. A missing value appears under No service recorded. Specific service relationships remain in the server details and search.

Binary links use `?binary=PHP` for a family, with optional `version` and `server` parameters for a particular reported version on one server. Selecting a family updates the address. Each expanded binary provides a shareable link; opening it filters the family/version, expands the server and opens its binary evidence. Clearing the version keeps the family filter. Existing `#server=...` links remain supported. A family link with no `server` opens every matching server inline, showing only that binary, so versions can be compared side by side; each server collapses on its own, and a version summary filters by version. The page groups by location by default.
