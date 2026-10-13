# Hub

The top-level status page: one overall state, active incidents, scheduled maintenance, a
card per product with its live summary, every system with 90 days of history, and the
past week's incidents.

The site supplies two files next to the page:

- `/hub/products.json`: the products, each with `id`, `title`, `href`, `about` and
  `summary`. `summary` is the product's `/api/summary` URL, or a fixed summary object
  (`level`, `line`, optional `counts` and `seats`) for a mockup. `soon` marks a product
  that is not live yet, and `restricted` marks a narrower audience (`true` or a short label).
- `/hub/status.json`: the systems and incidents, in the shape of `sample/status.json`.

In `status.json`:

- `groups` lists systems by group. Each system has an `id`, a `name`, and optionally
  `about`, `href` and `history`, which holds extra past days (`daysAgo`, `level` warn, bad
  or maint, `minutes`, `note`).
- `incidents` have a `title`, an `impact` (minor, major or maintenance), the `components`
  they affect, a `start`, an optional `end` and their `updates`. A future start with
  maintenance impact is scheduled maintenance.
- Times are ISO 8601, or relative to now (`-2h`, `+3d`, `-40m`), so a sample file always
  looks current.
- `"sample": true` shows a banner saying the data is made up. `sampleNote` replaces its text.

A system's state is the worst impact among the incidents affecting it now. Its uptime
counts outage minutes in full and degraded minutes at 30 percent.

The local dev server serves `sample/status.json` unless `--hub-status` names another file:

```bash
python -m pulse_computers.devserver --catalog catalog.json --hub-status status.json
```
