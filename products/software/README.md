# SoftwarePulse

Find observed software installations on shared computers and see live seat availability on the ComputersPulse map and list. SoftwarePulse is a separate authenticated product; it reuses the computer catalog, presence rules and saved seat positions.

The Function uses managed identity. `PULSE_COMPUTERS_STORAGE_ACCOUNT` supplies read-only access to the computer `state` and `layout` tables. `PULSE_STORAGE_ACCOUNT` holds a private `software` blob container for the minimized installation snapshot. `PULSE_REPORTMATE_URL` names the ReportMate API and `PULSE_REPORTMATE_SCOPE` its OAuth resource scope. The workload needs the source API's read role. `PULSE_INSTALL_MAX_AGE_HOURS` defaults to 48.

A five-minute timer follows every applications page for catalog computers and atomically replaces the snapshot after a complete successful read. Browser requests read that snapshot; a missing snapshot or one older than 15 minutes returns a service error. Installation freshness uses the application's collection time, separately from computer occupancy. Neither installed software nor a free computer proves a licence is available.

The web deployment overlays `products/software/web` onto `products/computers/web`, adds `core/web` under `/core`, and supplies a theme, floorplan assets and site authentication settings. Optional icons use `/software-icons/index.json`, mapping normalized application names to local image paths; unmatched titles have a fallback. The site owns package aliases and icon extraction.

Install the core, computer API and software API into an environment, then run its tests:

```sh
pip install -e core -e products/computers/api -e 'products/software/api[test]'
pytest -q products/software/api
```
