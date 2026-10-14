# SoftwarePulse

Browse a curated software collection, then choose a title to see where it is installed. The product has its own software list and location detail view. Location rows show versions, platforms and aggregate computer availability.

`pulse_software.managed.build_suite` compiles the collection from each platform's `manifests/ManagedApps.yaml` and production package metadata. Site policy owns editorial exclusions, product aliases, package variants and bundle expansions. Only manifest-referenced software is eligible. ReportMate supplies installation evidence for that collection; raw observations cannot add titles. Curated titles remain visible when they have no recent installation reports. Matching uses explicit normalized aliases; ambiguous observations are omitted.

The deployment packages `managed-software.json` with the API and copies its selected icons under `/software-icons`. Background agents, management tools and other excluded packages stay out through site policy, without product-specific exclusions in generic code.

The Function uses managed identity. `PULSE_COMPUTERS_STORAGE_ACCOUNT` supplies read-only access to the computer `state` table; its catalog supplies locations and device identity. `PULSE_STORAGE_ACCOUNT` holds a private `software` container for minimized installation snapshots. `PULSE_REPORTMATE_URL` names the source API and `PULSE_REPORTMATE_SCOPE` its OAuth scope. The workload needs the source API's read role. `PULSE_INSTALL_MAX_AGE_HOURS` defaults to 48.

A five-minute timer follows every applications page for catalog computers, joins by serial and atomically replaces the snapshot after successful collection. Browser requests read that snapshot; a missing snapshot or one older than 15 minutes returns a service error. Responses contain software and location aggregates, without device identifiers, application paths or usage records. Installation freshness is separate from computer occupancy. A free computer does not establish licence availability.

The web deployment publishes `products/software/web`, `core/web` under `/core`, a theme and site authentication settings.

```sh
pip install -e core -e products/computers/api -e 'products/software/api[test]'
pytest -q products/software/api
```
