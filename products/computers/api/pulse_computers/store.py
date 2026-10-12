"""Where events and the latest state per seat are kept.

MemoryStore is for local runs and tests. The deployed API uses Table Storage with
the same two operations, so the service code never knows which one it has.
"""

import threading
from datetime import datetime
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
