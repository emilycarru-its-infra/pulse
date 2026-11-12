"""Printer alerts: an alert opens when a printer stays in a fault and closes once it recovers.

Every health push carries each queue's state. A printer's state is the worst of the queues the
push names for it (the same rule the page uses), and each printer keeps one alert record that
moves through four phases:

=============  ================================================================================
clear          healthy, or never reported a fault
pending        in a fault (``attention``, ``error`` or ``offline``) for less than ``hold``
open           in a fault for at least ``hold``: the alert is raised
recovering     back to ``ready`` or ``printing`` after an open alert, for less than ``clear``
=============  ================================================================================

``hold`` keeps a jam someone clears in a minute, or one bad poll, from raising anything.
``clear`` keeps a printer that flaps between ready and a fault on one alert rather than many.
A fault that ends before ``hold`` never opens. ``unknown``, or a printer the push does not
name, changes nothing: a gap in reporting is not a printer fault, and the page already shows
staleness on its own.

While open, a change of fault (``attention`` to ``offline``, or a new detail such as ``Paper
jam`` to ``Door open``) updates the alert in place and is recorded as a ``changed`` event; the
alert keeps the time it first opened. Each printer keeps its last closed alert, so the page can
show what recovered recently.

Machine facts only: printer, state, PaperCut's status text and times. No person.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .live import PAGE_STATE, SEVERITY, Matcher, _iso, _parse_time

FAULTS = {"attention", "error", "offline"}
HEALTHY = {"ready", "printing"}
EMPTY = {"phase": "clear"}


@dataclass(frozen=True)
class Policy:
    hold: timedelta = timedelta(minutes=5)
    clear: timedelta = timedelta(minutes=2)
    # How long a closed alert stays listed as recent.
    recent: timedelta = timedelta(hours=24)

    def __post_init__(self):
        if (
            self.hold < timedelta(0)
            or self.clear < timedelta(0)
            or self.recent < timedelta(0)
        ):
            raise ValueError("alert periods must not be negative")


def printer_states(
    matcher: Matcher, entries: list[dict]
) -> dict[str, tuple[str, str | None]]:
    """Each matched printer's page state and detail in this push: the worst known queue."""
    by_printer: dict[str, list[dict]] = {}
    for e in entries:
        pid = matcher.match(e["print_queue"])
        if pid is not None and e["state"] != "unknown":
            by_printer.setdefault(pid, []).append(e)
    out: dict[str, tuple[str, str | None]] = {}
    for pid, queues in by_printer.items():
        worst = max(
            queues, key=lambda e: SEVERITY[PAGE_STATE.get(e["state"], e["state"])]
        )
        out[pid] = (PAGE_STATE.get(worst["state"], worst["state"]), worst.get("detail"))
    return out


def advance(
    record: dict | None, state: str, detail: str | None, now: datetime, policy: Policy
) -> tuple[dict, str | None]:
    """The printer's next alert record and the event this report causes, if any
    (``opened``, ``changed`` or ``closed``)."""
    rec: dict[str, Any] = dict(record or EMPTY)
    phase = rec.get("phase", "clear")
    at = _iso(now)
    if state in FAULTS:
        if phase == "clear":
            rec.update(phase="pending", state=state, detail=detail, since=at)
            return _settle(rec, now, policy)
        if phase == "pending":
            rec.update(state=state, detail=detail)
            return _settle(rec, now, policy)
        changed = (rec.get("state"), rec.get("detail")) != (state, detail)
        rec.update(phase="open", state=state, detail=detail, healthy_since=None)
        if changed:
            rec["changed_at"] = at
        return rec, "changed" if changed else None
    if state in HEALTHY:
        if phase == "pending":
            return _cleared(rec), None
        if phase == "open":
            rec.update(phase="recovering", healthy_since=at)
            phase = "recovering"
        if phase == "recovering":
            healthy = _parse_time(rec.get("healthy_since")) or now
            if now - healthy >= policy.clear:
                last = {
                    k: rec.get(k) for k in ("state", "detail", "since", "opened_at")
                }
                last["closed_at"] = at
                out = _cleared(rec)
                out["last_closed"] = last
                return out, "closed"
        return rec, None
    return rec, None


def _settle(rec: dict[str, Any], now: datetime, policy: Policy) -> tuple[dict, str | None]:
    since = _parse_time(rec.get("since")) or now
    if now - since >= policy.hold:
        rec.update(phase="open", opened_at=_iso(now), healthy_since=None)
        return rec, "opened"
    return rec, None


def _cleared(rec: dict) -> dict:
    out = {"phase": "clear"}
    if rec.get("last_closed"):
        out["last_closed"] = rec["last_closed"]
    return out


# --- Store --------------------------------------------------------------------------------


class AlertStore(Protocol):
    def records(self) -> dict[str, dict]: ...
    def put(self, printer_id: str, record: dict) -> None: ...


class MemoryAlertStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def records(self) -> dict[str, dict]:
        with self._lock:
            return json.loads(json.dumps(self._rows))

    def put(self, printer_id: str, record: dict) -> None:
        with self._lock:
            self._rows[printer_id] = json.loads(json.dumps(record))


class TableAlertStore:
    """The live state table, partition ``alert``: one row per printer, its record as JSON."""

    def __init__(self, table):
        self.table = table

    @classmethod
    def from_account(
        cls, account: str, table: str = "state", credential=None
    ) -> "TableAlertStore":
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

    def records(self) -> dict[str, dict]:
        return {
            row["RowKey"]: json.loads(row.get("alert") or "{}")
            for row in self.table.query_entities(
                "PartitionKey eq @pk", parameters={"pk": "alert"}
            )
        }

    def put(self, printer_id: str, record: dict) -> None:
        self.table.upsert_entity(
            {
                "PartitionKey": "alert",
                "RowKey": printer_id,
                "alert": json.dumps(record, separators=(",", ":")),
            },
            mode="replace",
        )


def record_alerts(
    store: AlertStore,
    matcher: Matcher,
    entries: list[dict],
    now: datetime | None = None,
    policy: Policy = Policy(),
) -> list[dict]:
    """Advance every printer this push names; write only records that changed. Returns the
    events, ``[{"printer": id, "event": ..., "state": ..., "detail": ...}]``."""
    now = now or datetime.now(timezone.utc)
    current = store.records()
    events = []
    for pid, (state, detail) in sorted(printer_states(matcher, entries).items()):
        before = current.get(pid)
        after, event = advance(before, state, detail, now, policy)
        if after != (before or EMPTY):
            store.put(pid, after)
        if event:
            events.append(
                {
                    "printer": pid,
                    "event": event,
                    "state": after.get("state", state),
                    "detail": after.get("detail", detail),
                }
            )
    return events


# --- Reading ------------------------------------------------------------------------------


def listing(
    store: AlertStore,
    catalog: dict,
    now: datetime | None = None,
    policy: Policy = Policy(),
) -> dict[str, Any]:
    """Open alerts, worst and oldest first, and alerts closed within ``policy.recent``."""
    now = now or datetime.now(timezone.utc)
    printers = {p["id"]: p for p in catalog.get("printers", [])}

    def about(pid: str) -> dict:
        p = printers.get(pid, {})
        return {
            "id": pid,
            "name": p.get("name") or pid,
            "room": p.get("room"),
            "location": p.get("location"),
        }

    open_, recent = [], []
    for pid, rec in store.records().items():
        if pid not in printers:
            continue
        if rec.get("phase") in ("open", "recovering"):
            open_.append(
                {
                    **about(pid),
                    "state": rec.get("state"),
                    "detail": rec.get("detail"),
                    "since": rec.get("since"),
                    "openedAt": rec.get("opened_at"),
                    "recovering": rec.get("phase") == "recovering",
                }
            )
        last: dict[str, Any] = rec.get("last_closed") or {}
        closed = _parse_time(last.get("closed_at"))
        if closed and now - closed <= policy.recent:
            recent.append(
                {
                    **about(pid),
                    "state": last.get("state"),
                    "detail": last.get("detail"),
                    "since": last.get("since"),
                    "openedAt": last.get("opened_at"),
                    "closedAt": last.get("closed_at"),
                }
            )
    open_.sort(key=lambda a: (-SEVERITY.get(a["state"] or "", 0), a["since"] or ""))
    recent.sort(key=lambda a: a["closedAt"], reverse=True)
    return {"generatedAt": _iso(now), "open": open_, "recent": recent}
