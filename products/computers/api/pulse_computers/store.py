"""Where events and the latest state per seat are kept.

MemoryStore is for local runs and tests. The deployed API uses TableStore, on Azure Table
Storage, with the same operations, so the service code never knows which one it has.
"""

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Iterable, Protocol


class Store(Protocol):
    def append(self, event: dict) -> None: ...
    def latest(self) -> dict[str, dict]: ...
    def events_since(self, since: datetime) -> Iterable[dict]: ...


class MemoryStore:
    def __init__(self, keep: int = 100_000):
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._latest: dict[str, dict] = {}
        self._keep = keep

    def append(self, event: dict) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._keep:
                del self._events[: len(self._events) - self._keep]
            self._latest[event["device"]["hostname"].upper()] = event

    def latest(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._latest)

    def events_since(self, since: datetime) -> Iterable[dict]:
        stamp = since.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            return [e for e in self._events if e["receivedAt"] >= stamp]


class TableStore:
    """Two tables: every event, append-only, and the latest event per seat.

    Events are partitioned by the UTC day they arrived and keyed by arrival time, so a
    query from a day onwards comes back oldest first. The seat table has one row per
    hostname, replaced on every event. Each row keeps the event as JSON in `event`.
    """

    def __init__(self, events, state):
        self.events = events
        self.state = state

    @classmethod
    def from_account(cls, account: str, events_table: str = "events", state_table: str = "state",
                     credential=None) -> "TableStore":
        """Tables in a storage account, reached with the app's managed identity (or any
        DefaultAzureCredential source when run locally). No keys or connection strings."""
        from azure.data.tables import TableClient
        from azure.identity import DefaultAzureCredential

        endpoint = account if account.startswith("https://") else f"https://{account}.table.core.windows.net"
        credential = credential or DefaultAzureCredential()
        return cls(TableClient(endpoint, events_table, credential=credential),
                   TableClient(endpoint, state_table, credential=credential))

    def append(self, event: dict) -> None:
        received = event["receivedAt"]
        host = event["device"]["hostname"].upper()
        body = json.dumps(event, separators=(",", ":"))
        self.events.create_entity({"PartitionKey": received[:10], "RowKey": f"{received}_{host}_{uuid.uuid4().hex[:8]}",
                                   "event": body})
        self.state.upsert_entity({"PartitionKey": "seat", "RowKey": host, "event": body}, mode="replace")

    def latest(self) -> dict[str, dict]:
        rows = self.state.query_entities("PartitionKey eq @pk", parameters={"pk": "seat"})
        return {row["RowKey"]: json.loads(row["event"]) for row in rows}

    def events_since(self, since: datetime) -> Iterable[dict]:
        stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        rows = self.events.query_entities("PartitionKey ge @day and RowKey ge @stamp",
                                          parameters={"day": stamp[:10], "stamp": stamp})
        return [json.loads(row["event"]) for row in rows]
