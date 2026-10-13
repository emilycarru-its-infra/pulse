import json
from datetime import datetime, timedelta, timezone

from pulse_computers.service import ComputersService
from pulse_computers.store import TableStore

from test_service import CATALOG, NOW, event


class FakeTable:
    """The slice of azure.data.tables.TableClient that TableStore uses, kept in a dict and
    returned in PartitionKey, RowKey order as the service does."""

    def __init__(self):
        self.rows = {}

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        assert key not in self.rows, "row exists"
        self.rows[key] = dict(entity)

    def upsert_entity(self, entity, mode="merge"):
        assert mode == "replace"
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def query_entities(self, query_filter, parameters):
        tests = {
            "PartitionKey eq @pk": lambda r: r["PartitionKey"] == parameters["pk"],
            "PartitionKey ge @day and RowKey ge @stamp":
                lambda r: r["PartitionKey"] >= parameters["day"] and r["RowKey"] >= parameters["stamp"],
        }
        return [r for _, r in sorted(self.rows.items()) if tests[query_filter](r)]


def test_tablestore_keeps_latest_per_seat_and_every_event():
    events, state = FakeTable(), FakeTable()
    svc = ComputersService(CATALOG, TableStore(events, state))
    svc.ingest(event("lab-01", "login"), now=datetime(2027, 1, 3, 23, 59, tzinfo=timezone.utc))
    svc.ingest(event("LAB-01", "lock", locked=True), now=NOW - timedelta(seconds=30))
    svc.ingest(event("LAB-02"), now=NOW)
    assert len(events.rows) == 3 and len(state.rows) == 2
    assert {k[1] for k in state.rows} == {"LAB-01", "LAB-02"}
    assert json.loads(state.rows[("seat", "LAB-01")]["event"])["type"] == "lock"
    seats = svc.status(NOW)["spaces"][0]["seats"]
    assert [s["state"] for s in seats] == ["possibly_free", "in_use", "out_of_service"]
    assert [e["type"] for e in svc.export(datetime(2027, 1, 3, tzinfo=timezone.utc))] == ["login", "lock", "heartbeat"]
    assert [e["type"] for e in svc.export(NOW)] == ["heartbeat"]


class FakeCredential:
    def get_token(self, *scopes, **kwargs):
        raise AssertionError("no network in tests")


def test_from_account_builds_table_clients_with_a_credential():
    store = TableStore.from_account("acct", "ev", "st", credential=FakeCredential())
    assert store.events.table_name == "ev" and store.state.table_name == "st"
    assert store.events.url.startswith("https://acct.table.core.windows.net")
