# WebsitesPulse

Website health for IT staff: every website the organization runs, where it is hosted, whether it
answers, and the hosting facts that need attention.

Websites report nothing themselves. Health comes from what already watches them, in two ways:

- an hourly push of every website's state, latest checks and hosting facts from the site's data
  platform to `POST /api/ingest/health`, with an Entra ID app-only token holding the
  `Pulse.Ingest` role (contract `pulse.website-health/1`, below);
- alerts in seconds from an uptime service's URL monitors to `POST /api/alerts/site24x7`, which
  cannot obtain a token, with its own shared key in `X-Pulse-Key`.

With `PULSE_SOURCE=live` the page shows what was posted. An alert newer than the push decides a
website's state, and a website nothing has been heard from for two hours is `unknown`. With
`PULSE_SOURCE=sample` the page makes up plausible health for every website and says so.

## Health push

```json
{
  "contract": "pulse.website-health/1",
  "generated_at": "2026-01-05T15:00:00Z",
  "source": "data-platform",
  "websites": [{
    "key": { "hostname": "www.example.edu", "kinsta_site_id": "…", "site24x7_monitor_id": "123" },
    "state": "degraded",
    "checks": [
      { "source": "Site24x7", "state": "ok", "at": "2026-01-05T14:58:00Z" },
      { "source": "Kinsta", "state": "warn", "at": "2026-01-05T14:50:00Z", "reason": "vulnerable-plugins" }
    ],
    "facts": { "host": "Kinsta", "account": "MAIN", "php_version": "8.3", "wordpress_version": "6.8.3",
               "plugins_vulnerable": 1, "last_backup_at": "2026-01-05T09:00:00Z" },
    "last_check": "2026-01-05T14:58:00Z"
  }]
}
```

`state` is one of `up`, `degraded`, `down` and `unknown`; a check's is `ok`, `warn` or `down`, with
an optional `reason` (`blocked`, `vulnerable-plugins`, `no-recent-backup`) that the page turns
into an alert. Only the facts above are kept; anything else in `facts` is dropped. The reply is
`202` with the number of websites matched and unmatched. A website is matched to the catalog by
hostname (`www.` and the bare name are the same site), then the hosting provider's site id, then
the uptime monitor id.

## Catalog

```json
{
  "title": "Websites",
  "groups": [{ "id": "managed-wordpress", "name": "Managed WordPress", "detail": "…" }],
  "websites": [{ "id": "www-example-edu", "name": "Main website", "url": "https://www.example.edu/",
                 "hostname": "www.example.edu", "aliases": [], "group": "managed-wordpress",
                 "owner": "Communications", "kinsta_site_id": "…", "site24x7_monitor_id": "…" }]
}
```

The site builds it from its inventory. `kinsta_site_id`, `site24x7_monitor_id` and `aliases` are
optional and only match posted health; the page never receives them.

## Layout

- `api/pulse_websites/service.py`: status and summary from a catalog and a health source
- `api/pulse_websites/simulate.py`: the `sample` source, a pure function of website and time
- `api/pulse_websites/live.py`: the `live` source, matching, the push and alert parsers, the store
- `api/pulse_websites/auth.py`: the push token and webhook key checks
- `api/function_app.py`: the Azure Functions host (`/api/status`, `/api/summary`, `/api/GetRoles`,
  `/api/ingest/health`, `/api/alerts/site24x7`)
- `api/pack.sh`: the Functions package, with the site's catalog added by the deploy
- `web/`: the page
- `examples/catalog.json`: a made-up catalog in the shape the site supplies

## Run it locally

Install the package:

```bash
pip install -e 'products/websites/api[test]'
```

Serve the page with the example catalog on http://localhost:8402/:

```bash
python -m pulse_websites.devserver
```

Deployed, the page is a Static Web App behind single sign-on, linked to the Function App the
`pulse-product` Terraform module creates. The ingest and alert paths are reached directly, so the
site's root lists them in the module's `browser_paths` and `unauthenticated_paths`; the code
authenticates those callers itself.


URL availability checks are opt-in through `PULSE_URL_CHECKS_ENABLED=true`. The Function timer
checks the trusted catalog URLs every five minutes with at most eight concurrent requests and
a ten-second timeout. It sends no credentials, follows no redirects, and stores only response
status, duration and check time. Redirects indicate reachability; restricted and rate-limited
responses are warnings. A check becomes unknown after fifteen minutes without a result.

A catalog subsite can name `hosting_parent`, the catalog ID of its shared installation.
The API exposes shared versions, backup and vulnerability context under `hosting`, without
copying parent health or analytics totals. Installation analytics remain on the parent entry;
optional aggregate facts include visits and server/CDN bytes over a stated 24-hour window,
response-code totals, disk usage and collection time.
