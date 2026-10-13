# ServersPulse

Server and service health for IT staff: every server, where it runs (a cloud account, an
on-premises cluster, the racks) and the services it carries, with the state, load and alerts
the monitoring systems report.

Servers report nothing themselves. Collectors read what already watches them: an uptime
service such as Site24x7 for every server, CloudWatch for cloud instances and the hypervisor's
API for on-premises virtual machines. Until those collectors exist, the `sample` source makes
up plausible health for every server in the catalog, and the page says so.

## Layout

- `api/pulse_servers/service.py`: status and summary from a catalog and a health source
- `api/pulse_servers/simulate.py`: the `sample` source, a pure function of server and time
- `api/function_app.py`: the Azure Functions host (`/api/status`, `/api/summary`, `/api/GetRoles`)
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
                "os": "…", "site": "…", "host": "…", "services": ["sis"], "stopped": false }]
}
```

A server marked `stopped` is off on purpose and never counts against its group.

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
single sign-on, linked to the Function App the `pulse-product` Terraform module creates; the
module's agent ingest path goes unused.
