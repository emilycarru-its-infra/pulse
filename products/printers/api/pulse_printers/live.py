"""Real printer state: what the print server reports, kept per catalog printer.

A poller next to the print server posts every queue's state every few minutes (contract
``pulse.printer-health/1``). Each entry names a print queue as ``<server>\\<queue name>``; the
queue name is matched, case-insensitively, to the queues the catalog lists for each printer.
The `live` source then answers for a printer from what is stored: the worst state of its
queues reported within the staleness window, and `unknown` once nothing fresh is left. It
never falls back to sample data.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

CONTRACT = "pulse.printer-health/1"
STATES = {"ready", "printing", "attention", "stopped", "offline", "unknown"}
# The page calls a stopped printer "error" (and words it "Stopped").
PAGE_STATE = {"stopped": "error"}
# How bad a queue's state is when a printer with several queues takes the worst of them.
SEVERITY = {"ready": 0, "printing": 1, "attention": 2, "error": 3, "offline": 4}
STALE = timedelta(minutes=10)
# A sender's clock may run a little ahead; anything later than this is pulled back to the time
# it arrived, so a future-dated report can never stay fresh past STALE.
SKEW = timedelta(minutes=2)

MAX_BODY = 2 * 1024 * 1024
MAX_PRINTERS = 5000
MAX_QUEUE = 256
MAX_DETAIL = 200
MAX_COUNT = 10_000_000


class ContractError(ValueError):
    """The body is not a printer health push this version understands."""


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def queue_name(text: Any) -> str | None:
    """A print queue's name without its server: ``server\\Queue`` and ``lpd://server/Queue``
    both read as ``queue``."""
    if not isinstance(text, str):
        return None
    name = re.split(r"[\\/]", text.strip())[-1].strip().casefold()
    return name or None


class Matcher:
    """Finds the catalog printer a print queue belongs to, from each printer's `queues`."""

    def __init__(self, catalog: dict):
        self.queue: dict[str, str] = {}
        for printer in catalog.get("printers", []):
            for q in printer.get("queues") or []:
                name = queue_name(q)
                if name:
                    self.queue.setdefault(name, printer["id"])

    def match(self, print_queue: Any) -> str | None:
        name = queue_name(print_queue)
        return self.queue.get(name) if name else None


# --- The push -----------------------------------------------------------------------------


def _count(value: Any, where: str) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_COUNT
    ):
        raise ContractError(
            f"{where} must be a whole number from 0 to {MAX_COUNT}, or null"
        )
    return value


def parse_push(body: Any, now: datetime | None = None) -> list[dict]:
    """The queues of a health push, each validated and normalized, with every time no later
    than its arrival. Raises ContractError."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(body, dict):
        raise ContractError("body must be a JSON object")
    if body.get("contract") != CONTRACT:
        raise ContractError(f"contract must be {CONTRACT}")
    generated = _parse_time(body.get("generated_at"))
    if generated is None:
        raise ContractError("generated_at must be an ISO 8601 time")
    generated = min(generated, now + SKEW)
    printers = body.get("printers")
    if not isinstance(printers, list):
        raise ContractError("printers must be a list")
    if len(printers) > MAX_PRINTERS:
        raise ContractError(f"printers may hold at most {MAX_PRINTERS} entries")
    out = []
    for i, p in enumerate(printers):
        where = f"printers[{i}]"
        if not isinstance(p, dict) or not isinstance(p.get("key"), dict):
            raise ContractError(f"{where} needs a key object")
        queue = p["key"].get("print_queue")
        if not isinstance(queue, str) or not queue.strip() or len(queue) > MAX_QUEUE:
            raise ContractError(
                f"{where}.key.print_queue must be a queue name of at most {MAX_QUEUE} characters"
            )
        if p.get("state") not in STATES:
            raise ContractError(f"{where}.state must be one of {sorted(STATES)}")
        detail = p.get("detail")
        if detail is not None and not isinstance(detail, str):
            raise ContractError(f"{where}.detail must be a string or null")
        checked = p.get("checked_at")
        if checked is None:
            at = generated
        else:
            at = _parse_time(checked)
            if at is None:
                raise ContractError(
                    f"{where}.checked_at must be an ISO 8601 time or null"
                )
            at = min(at, now + SKEW)
        out.append(
            {
                "print_queue": queue.strip(),
                "state": p["state"],
                "detail": detail.strip()[:MAX_DETAIL] or None if detail else None,
                "held_jobs": _count(p.get("held_jobs"), f"{where}.held_jobs"),
                "jobs_today": _count(p.get("jobs_today"), f"{where}.jobs_today"),
                "pages_today": _count(p.get("pages_today"), f"{where}.pages_today"),
                "checked_at": _iso(at),
            }
        )
    return out


# --- Store --------------------------------------------------------------------------------


class Store(Protocol):
    def put_printer(self, printer_id: str, queues: dict[str, dict]) -> None: ...
    def rows(self) -> dict[str, dict[str, dict]]: ...


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, dict]] = {}

    def put_printer(self, printer_id: str, queues: dict[str, dict]) -> None:
        with self._lock:
            self._rows[printer_id] = json.loads(json.dumps(queues))

    def rows(self) -> dict[str, dict[str, dict]]:
        with self._lock:
            return json.loads(json.dumps(self._rows))


class TableStore:
    """One table, one row per catalog printer: its queues' latest reports as JSON in `queues`.
    A push is a snapshot, so each printer's row is replaced by the queues the push carried.
    """

    def __init__(self, table):
        self.table = table

    @classmethod
    def from_account(
        cls, account: str, table: str = "state", credential=None
    ) -> "TableStore":
        from azure.data.tables import TableClient
        from azure.identity import DefaultAzureCredential

        endpoint = (
            account
            if account.startswith("https://")
            else f"https://{account}.table.core.windows.net"
        )
        return cls(
            TableClient(
                endpoint, table, credential=credential or DefaultAzureCredential()
            )
        )

    def put_printer(self, printer_id: str, queues: dict[str, dict]) -> None:
        self.table.upsert_entity(
            {
                "PartitionKey": "printer",
                "RowKey": printer_id,
                "queues": json.dumps(queues, separators=(",", ":")),
            },
            mode="replace",
        )

    def rows(self) -> dict[str, dict[str, dict]]:
        return {
            row["RowKey"]: json.loads(row.get("queues") or "{}")
            for row in self.table.query_entities(
                "PartitionKey eq @pk", parameters={"pk": "printer"}
            )
        }


def record_push(store: Store, matcher: Matcher, entries: list[dict]) -> dict:
    by_printer: dict[str, dict[str, dict]] = {}
    unmatched = 0
    for e in entries:
        pid = matcher.match(e["print_queue"])
        if pid is None:
            unmatched += 1
            continue
        by_printer.setdefault(pid, {})[queue_name(e["print_queue"])] = e
    for pid, queues in by_printer.items():
        store.put_printer(pid, queues)
    return {
        "matched": sum(len(q) for q in by_printer.values()),
        "unmatched": unmatched,
        "printers": len(by_printer),
    }


# --- The live source ----------------------------------------------------------------------


def _total(entries: list[dict], field: str) -> int | None:
    values = [e[field] for e in entries if e.get(field) is not None]
    return sum(values) if values else None


class LiveSource:
    """source(printer, now) from the store, as PrintersService expects. Rows are read once
    per status() call (cached for `ttl`), not once per printer."""

    def __init__(
        self,
        store: Store,
        stale: timedelta = STALE,
        ttl: timedelta = timedelta(seconds=20),
    ):
        self.store = store
        self.stale = stale
        self.ttl = ttl
        self._rows: dict[str, dict] = {}
        self._read: datetime | None = None
        self._lock = threading.Lock()

    def _all(self, now: datetime) -> dict[str, dict]:
        with self._lock:
            if self._read is None or abs(now - self._read) > self.ttl:
                self._rows = self.store.rows()
                self._read = now
            return self._rows

    def __call__(self, printer: dict, now: datetime) -> dict:
        reported = []
        for e in (self._all(now).get(printer["id"]) or {}).values():
            at = _parse_time(e.get("checked_at"))
            if at is not None:
                reported.append((at, e))
        last = max((at for at, _ in reported), default=None)
        fresh = [e for at, e in reported if now - at <= self.stale]
        known = [e for e in fresh if e["state"] != "unknown"]
        out = {
            "supplies": None,
            "trays": None,
            "queue": _total(fresh, "held_jobs"),
            "jobsToday": _total(fresh, "jobs_today"),
            "pagesToday": _total(fresh, "pages_today"),
            "lastSeen": _iso(last) if last else None,
            "stale": not fresh,
        }
        if not known:
            return {
                **out,
                "state": "unknown",
                "detail": None if fresh else "No recent report",
            }
        worst = max(
            known, key=lambda e: SEVERITY[PAGE_STATE.get(e["state"], e["state"])]
        )
        return {
            **out,
            "state": PAGE_STATE.get(worst["state"], worst["state"]),
            "detail": worst.get("detail"),
        }
