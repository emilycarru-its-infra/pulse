import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from pulse_computers.alert_store import AlertState
from pulse_computers.alert_relay import Relay


class Row(dict):
    metadata = {"etag": "version-1"}


class Table:
    def __init__(self):
        self.rows = {}

    def create_entity(self, row):
        key = row["PartitionKey"], row["RowKey"]
        if key in self.rows:
            raise ResourceExistsError()
        self.rows[key] = Row(row)

    def get_entity(self, partition, key):
        try:
            return self.rows[partition, key]
        except KeyError:
            raise ResourceNotFoundError()

    def update_entity(self, row, **kw):
        assert kw["etag"] == "version-1"
        self.rows[row["PartitionKey"], row["RowKey"]] = Row(row)

    def delete_entity(self, partition, key, **kw):
        assert kw["etag"] == "version-1"
        del self.rows[partition, key]


def test_running_monitor_excludes_another_run_and_releases_after_failure():
    table = Table()
    with pytest.raises(RuntimeError):
        with AlertState(table).lease() as first:
            assert first
            with AlertState(table).lease() as second:
                assert not second
            raise RuntimeError("failed while posting")
    with AlertState(table).lease() as third:
        assert third


def test_expired_lease_can_be_taken_over_after_a_crash():
    table = Table()
    table.create_entity({"PartitionKey": "control", "RowKey": "lease", "owner": "old",
                         "until": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    with AlertState(table).lease() as acquired:
        assert acquired and table.rows["control", "lease"]["owner"] != "old"


class Credential:
    def get_token(self, scope):
        assert scope == "example-audience/.default"
        return SimpleNamespace(token="test-only-token")


def test_relay_uses_identity_and_exact_channel_and_confirms_delivery(monkeypatch):
    def post(request, timeout):
        assert request.get_header("Authorization") == "Bearer test-only-token"
        payload = json.loads(request.data)
        assert payload["channel"] == "Example" and payload["team"] == "example-team"
        assert timeout == 10
        return io.BytesIO(b'{"ok":true,"channel":"Example","via":"bot"}')
    monkeypatch.setattr("urllib.request.urlopen", post)
    Relay("https://relay.example/api/post-card", "example-audience", "Example", "example-team", Credential())({"type": "AdaptiveCard"})


def test_relay_does_not_acknowledge_delivery_to_the_wrong_channel(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(b'{"ok":true,"channel":"Elsewhere"}'))
    with pytest.raises(RuntimeError):
        Relay("https://relay.example/api/post-card", "example-audience", "Example", credential=Credential())({})
