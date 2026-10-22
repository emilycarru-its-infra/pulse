from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pulse_servers import inventory
from pulse_servers.service import ServersService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def snapshot(uid=None, version=1, group="Directory"):
    return {
        "contract": inventory.CONTRACT,
        "retrieved_at": NOW.isoformat(),
        "servers": [
            {"item_id": uid or str(uuid4()), "version": version, "service_group": group}
        ],
    }


def test_source_versions_prevent_replays_rolling_back_or_conflicting_with_inventory():
    newer = inventory.parse(snapshot(version=2), NOW)[0]
    older = {**newer, "version": 1, "service_group": "Old"}
    assert inventory.combined(newer, older) == newer
    with pytest.raises(inventory.ContractError, match="conflicting"):
        inventory.combined(newer, {**newer, "service_group": "Other"})
    assert (
        inventory.combined(newer, {**newer, "version": 3, "service_group": None})[
            "service_group"
        ]
        is None
    )


def test_only_canonical_bindings_match_and_unknown_inventory_stays_unknown():
    uid = str(uuid4())
    catalog = {
        "servers": [
            {
                "id": "one",
                "cellarum_item_id": uid,
                "service_group": "Old dashboard grouping",
                "services": ["dns", "identity"],
            },
            {"id": "unbound", "service_group": "Guess"},
        ]
    }
    store = inventory.Store()
    rows = inventory.parse(snapshot(uid), NOW)
    assert inventory.record(store, catalog, rows) == {
        "matched": 1,
        "outside_catalog": 0,
        "unbound_catalog": ["unbound"],
    }
    service = ServersService(
        catalog, lambda *args: {"state": "up"}, inventory_store=store
    )
    view = service.status(NOW)
    assert view["servers"][0]["service_group"] == "Directory"
    assert "service_group" not in view["servers"][1]
    assert view["serviceGroups"][0]["servers"] == 1
    assert (
        inventory.record(store, catalog, inventory.parse(snapshot(), NOW))[
            "outside_catalog"
        ]
        == 1
    )
    inventory.record(
        store, catalog, inventory.parse(snapshot(uid, version=2, group=None), NOW)
    )
    assert "service_group" not in service.status(NOW)["servers"][0]


def test_malformed_or_duplicate_rows_are_not_accepted():
    valid = snapshot()
    for change in ("version", "extra", "duplicate", "long"):
        body = deepcopy(valid)
        if change == "version":
            body["servers"][0]["version"] = True
        if change == "extra":
            body["servers"][0]["hostname"] = "no fallback"
        if change == "duplicate":
            body["servers"].append(deepcopy(body["servers"][0]))
        if change == "long":
            body["servers"][0]["service_group"] = "x" * 101
        with pytest.raises(inventory.ContractError):
            inventory.parse(body, NOW)


def test_inventory_outage_does_not_hide_server_health():
    class Broken:
        def rows(self):
            raise OSError("unavailable")

    service = ServersService(
        {"servers": [{"id": "one"}]},
        lambda *args: {"state": "up"},
        inventory_store=Broken(),
    )
    row = service.status(NOW)["servers"][0]
    assert row["state"] == "up"
    assert row["inventorySource"]["freshness"] == "unavailable"
