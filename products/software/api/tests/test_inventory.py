from datetime import datetime, timezone
from copy import deepcopy

import pytest

from pulse_software.inventory import ReportMate, app_id, discovery

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
STATUS = {"spaces": [{"seats": [{"hostname": "SHARED-01", "state": "available"},
                                  {"hostname": "SHARED-02", "state": "in_use"}]}]}


def row(host="SHARED-01", name="Sketch", version="3", stamp="2026-10-14T11:00:00Z"):
    return {"hostname": host, "id": app_id(name), "name": name, "version": version, "collectedAt": stamp}


def test_catalog_boundary_freshness_versions_and_occupancy_are_independent():
    result = discovery(deepcopy(STATUS), [row(), row(version="4"), row("SHARED-02"), row("PRIVATE-01")],
                       app_id("Sketch"), "4", now=NOW)
    seats = result["spaces"][0]["seats"]
    assert [s["softwareMatch"] for s in seats] == [True, False]
    assert seats[0]["state"] == "available" and seats[1]["state"] == "in_use"
    assert result["software"][0]["computers"] == 2
    assert result["software"][0]["versions"] == ["3", "4"]
    assert "PRIVATE-01" not in str(result)


@pytest.mark.parametrize("stamp", [None, "bad", "2026-10-10T12:00:00Z", "2026-10-14T11:00:00", "2026-10-15T12:00:00Z"])
def test_stale_missing_naive_or_future_observations_never_claim_installed(stamp):
    result = discovery(deepcopy(STATUS), [row(stamp=stamp)], app_id("Sketch"), now=NOW)
    assert result["software"][0]["computers"] == 0
    assert not result["spaces"][0]["seats"][0]["softwareMatch"]


def test_source_pages_are_complete_minimized_cached_and_refresh_failures_propagate():
    calls = []
    def fetch(params):
        calls.append(params)
        rows = [{"deviceName": "shared-01", "name": "Sketch", "version": "3", "collectedAt": "2026-10-14T11:00:00Z",
                 "serialNumber": "private-serial", "path": "/private/path"}]
        return rows * 5000 if params["offset"] == 0 else [{"deviceName": "PRIVATE-01", "name": "Hidden"}]
    source = ReportMate("https://reports.example.org", "api://example/.default", ["SHARED-01"], None, fetch=fetch)
    result = source.rows()
    assert len(calls) == 2 and calls[1]["offset"] == 5000
    assert len(result) == 5000 and "serialNumber" not in result[0] and "path" not in result[0]
    assert source.rows() is result and len(calls) == 2
    source._expires = 0
    source.fetch = lambda params: {"error": "source failed"}
    with pytest.raises(ValueError):
        source.rows()


def test_unknown_software_cannot_match_and_id_is_stable():
    assert app_id(" Sketch ") == app_id("sketch")
    result = discovery(deepcopy(STATUS), [row()], "unknown", now=NOW)
    assert not any(s["softwareMatch"] for s in result["spaces"][0]["seats"])


def test_serial_identity_survives_reported_name_changes_without_exposing_serials():
    calls = []
    def fetch(params):
        calls.append(params)
        return [{"serialNumber": "serial-1", "deviceName": "Old display name", "name": "Sketch", "version": "3", "collectedAt": "2026-10-14T11:00:00Z"},
                {"serialNumber": "serial-other", "deviceName": "SHARED-01", "name": "Private application"}]
    source = ReportMate("https://reports.example.org", "api://example/.default",
                        [{"hostname": "SHARED-01", "serial": "SERIAL-1"}], None, fetch=fetch)
    rows = source.rows()
    assert calls[0]["deviceNames"] == "SERIAL-1"
    assert len(rows) == 1 and rows[0]["hostname"] == "SHARED-01"
    assert "serialNumber" not in rows[0] and "Old display name" not in str(rows)


def test_snapshot_publication_is_atomic_and_concurrent_reads_share_one_download():
    from pulse_software.inventory import InstallationSnapshot
    class Blob:
        downloads = 0
        body = '{"fetchedAt":"2026-10-14T12:00:00Z","rows":[]}'
        def download_blob(self):
            self.downloads += 1
            return self
        def readall(self): return self.body.encode()
        def upload_blob(self, body, overwrite):
            assert overwrite is True
            self.body = body
    blob = Blob(); snapshot = InstallationSnapshot(blob)
    assert snapshot.read() == snapshot.read() and blob.downloads == 1
    snapshot.publish([row()])
    assert snapshot.read()["rows"] == [row()] and blob.downloads == 1
