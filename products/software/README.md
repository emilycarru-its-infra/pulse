# SoftwarePulse

The default Software view is a curated icon grid with Mac / Windows toggles, category filtering and search. Cards flow independently down their columns, and names scale to fit a single line. The Locations view shows larger room cards containing the software installed there, with app links and room/software search. Room numbers lead location listings. Each card expands in place to show a short location list, with a version filter that narrows its locations, an app link and a copy-link action; selecting another card or clicking outside closes it. Platform glyphs appear below software names and at the top-right of location cards, without backgrounds, and hide while a platform filter is active. Location names use larger text, room identifiers appear without repeated Room/Rooms labels, and software cards have no chevrons. Shareable `?app=<title-slug>` URLs open a dedicated view that groups rooms under each location name and offers a reported-version filter. The interface shows locations and platforms without computer grids or computer/free-seat counts.

`pulse_software.managed.build_suite` compiles the collection from each platform's `manifests/ManagedApps.yaml` and production package metadata. Site policy owns editorial exclusions, product aliases, package variants and bundle expansions. Only manifest-referenced software is eligible. ReportMate supplies installation evidence for that collection; raw observations cannot add titles. Curated titles remain visible when they have no recent installation reports. Matching uses explicit normalized aliases; ambiguous observations are omitted.

The deployment packages `managed-software.json` with the API and copies its selected icons under `/software-icons`. Background agents, management tools and other excluded packages stay out through site policy, without product-specific exclusions in generic code.

The Function uses managed identity. `PULSE_COMPUTERS_STORAGE_ACCOUNT` supplies read-only access to the computer `state` table; its catalog supplies locations and device identity. `PULSE_STORAGE_ACCOUNT` holds a private `software` container for minimized installation snapshots. `PULSE_REPORTMATE_URL` names the source API and `PULSE_REPORTMATE_SCOPE` its OAuth scope. The workload needs the source API's read role. `PULSE_INSTALL_MAX_AGE_HOURS` defaults to 48.

A five-minute timer follows every applications page for catalog computers, joins by serial and atomically replaces the snapshot after successful collection. Browser requests read that snapshot; a missing snapshot or one older than 15 minutes returns a service error. Responses contain software and location aggregates, without device identifiers, application paths or usage records. Installation freshness is separate from computer occupancy. A free computer does not establish licence availability.

The web deployment publishes `products/software/web`, `core/web` under `/core`, a theme and site authentication settings.

```sh
pip install -e core -e products/computers/api -e 'products/software/api[test]'
pytest -q products/software/api
```

An app link can include `&version=<reported-version>` to open its dedicated page with that version selected. Version controls belong to a selected app, rather than the global browse filters. Both browse modes recalculate their masonry columns immediately when the container width changes.

Links preserve `view`, `category`, `platform`, `q` and `location` together. `app` opens a dedicated application page, `open` restores an expanded grid card, and `version` narrows the selected application. Location cards and individual room identifiers have dedicated links; app links from a location retain that location. Copy-link icons on apps, locations and the toolbar appear on hover or keyboard focus and remain visible on touch devices. Browser Back/Forward restores filter and selection state.
