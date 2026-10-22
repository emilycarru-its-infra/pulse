from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pulse_servers import runtimes as runtime

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def row(at=NOW):
    return {
        "item_id": str(uuid4()),
        "reference_id": str(uuid4()),
        "observation_id": str(uuid4()),
        "key": {"aws_instance_id": "i-0123456789abcdef0"},
        "received_at": at.isoformat(),
        "observed_at": at.isoformat(),
        "outcome": "accepted",
        "facts": {
            "contract": "server-live-runtimes/1",
            "instance_id": "i-0123456789abcdef0",
            "collection_state": "observed",
            "components": [
                {"name": "PHP", "version": "8.4.1", "running": True, "scope": "host"}
            ],
        },
    }


def test_freshness_uses_observation_not_delivery_time():
    incoming = row(NOW - timedelta(hours=3))
    incoming["received_at"] = NOW.isoformat()
    stored = runtime.combined({}, incoming)
    assert runtime.view(stored, NOW)["freshness"] == "stale"


def test_failure_retains_last_success_and_marks_it_stale():
    success = row()
    failure = row(NOW + timedelta(minutes=1))
    failure.update(outcome="collection_failed", observed_at=None)
    failure["facts"].update(
        components=[], collection_state="unavailable", reason="ssm_not_online"
    )
    stored = runtime.combined(runtime.combined({}, success), failure)
    view = runtime.view(stored, NOW + timedelta(minutes=2))
    assert view["components"][0]["version"] == "8.4.1"
    assert view["freshness"] == "stale"
    assert view["last_attempt"] == "collection_failed"
    assert view["observed_at"] == success["observed_at"]


def test_replay_and_older_delivery_cannot_replace_newer():
    latest = row()
    state = runtime.combined({}, latest)
    assert runtime.combined(state, latest) == state
    assert runtime.combined(state, row(NOW - timedelta(minutes=5))) == state


def test_strict_matching_rejects_ambiguous_instance_and_hostname_fallback():
    store = runtime.Store()
    catalog = {
        "servers": [
            {"id": "one", "aws_instance_id": "i-0123456789abcdef0"},
            {"id": "two", "aws_instance_id": "i-0123456789abcdef0"},
        ]
    }
    assert runtime.record(store, catalog, [row()]) == {"matched": 0, "unmatched": 1}
    assert store.rows() == {}


def test_projection_contract_requires_canonical_receipts_running_evidence_and_time():
    valid = {"contract": runtime.CONTRACT, "servers": [row()]}
    assert runtime.parse(valid, NOW) == valid["servers"]
    for change in (
        "receipt",
        "installed",
        "future",
        "failure_with_components",
        "duplicate",
    ):
        body = deepcopy(valid)
        entry = body["servers"][0]
        if change == "receipt":
            entry["observation_id"] = "not-a-receipt"
        if change == "installed":
            entry["facts"]["components"][0]["running"] = False
        if change == "future":
            entry["observed_at"] = (NOW + timedelta(days=1)).isoformat()
        if change == "failure_with_components":
            entry.update(outcome="collection_failed", observed_at=None)
        if change == "duplicate":
            body["servers"].append(deepcopy(entry))
        with pytest.raises(runtime.ContractError):
            runtime.parse(body, NOW)


def test_runtime_storage_failure_keeps_health_available():
    from pulse_servers.service import ServersService
    class BrokenStore:
        def rows(self): raise OSError('unavailable')
    service = ServersService({'servers': [{'id': 'example'}]},
                             lambda *args: {'state': 'up'}, runtime_store=BrokenStore())
    server = service.status(NOW)['servers'][0]
    assert server['state'] == 'up'
    assert server['runtimeInventory']['freshness'] == 'unavailable'
