"""Real website health: what the monitoring systems send, kept per catalog website.

Two kinds of input arrive:

- a health push, hourly, from the site's data platform: the state, latest checks and hosting
  facts of every monitored website (contract ``pulse.website-health/1``);
- alerts, in seconds, from an uptime service's webhook (Site24x7 URL monitors).

Each input names a website by its hostname, its hosting provider's site id or its monitor id,
and is matched to the catalog in that order. The `live` source then answers for a website from
what is stored: the push, unless an alert arrived after it, and `unknown` once nothing has been
heard for STALE.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

CONTRACT = "pulse.website-health/1"
STATES = {"up", "degraded", "down", "unknown"}
CHECK_STATES = {"ok", "warn", "down"}
STALE = timedelta(hours=2)
ALERT_SEVERITY = {"ok": 0, "warn": 1, "down": 2}
ALERT_TO_STATE = {"ok": "up", "warn": "degraded", "down": "down"}
# Hosting facts a push may carry, and nothing else. Each is a short string or a number.
FACTS = (
    "host",
    "account",
    "php_version",
    "wordpress_version",
    "plugins_vulnerable",
    "last_backup_at",
)
SKEW = timedelta(minutes=2)
HOST = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


class ContractError(ValueError):
    """The body is not a health push this version understands."""


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _received(value: Any, now: datetime) -> datetime | None:
    """A sender-supplied time, no later than `now` plus SKEW."""
    dt = _parse_time(value)
    return None if dt is None else min(dt, now + SKEW)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hostname(value: Any) -> str | None:
    """The host of a URL or hostname, lower case, without scheme, port, path or trailing dot."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value.strip().lower())
    text = (
        re.split(r"[/?#]", text, maxsplit=1)[0].split("@")[-1].split(":")[0].rstrip(".")
    )
    return text if HOST.fullmatch(text) else None


def _bare(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def _fact(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:80]
    return None


# --- Matching -----------------------------------------------------------------------------


class Matcher:
    """Finds the catalog website an input names: hostname, then provider site id, then monitor id.

    Hostnames come from each website's `hostname`, `url` and `aliases`, compared lower case;
    `www.` and the bare name are the same site unless the catalog lists both separately.
    """

    def __init__(self, catalog: dict):
        self.host: dict[str, str] = {}
        self.bare: dict[str, str] = {}
        self.site: dict[str, str] = {}
        self.monitor: dict[str, str] = {}
        for w in catalog.get("websites", []):
            wid = w["id"]
            for name in (w.get("hostname"), w.get("url"), *(w.get("aliases") or [])):
                host = hostname(name)
                if host:
                    self.host.setdefault(host, wid)
                    self.bare.setdefault(_bare(host), wid)
            if w.get("kinsta_site_id"):
                self.site[str(w["kinsta_site_id"])] = wid
            if w.get("site24x7_monitor_id"):
                self.monitor[str(w["site24x7_monitor_id"])] = wid

    def match(
        self, host: Any = None, site_id: Any = None, monitor_id: Any = None
    ) -> str | None:
        name = hostname(host)
        if name:
            if name in self.host:
                return self.host[name]
            if _bare(name) in self.bare:
                return self.bare[_bare(name)]
        if site_id is not None and str(site_id) in self.site:
            return self.site[str(site_id)]
        if monitor_id is not None and str(monitor_id) in self.monitor:
            return self.monitor[str(monitor_id)]
        return None


# --- Inputs -------------------------------------------------------------------------------


def parse_push(body: Any, now: datetime | None = None) -> list[dict]:
    """The websites of a health push, validated and normalized, with every time no later than
    its arrival. Raises ContractError."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(body, dict):
        raise ContractError("body must be a JSON object")
    if body.get("contract") != CONTRACT:
        raise ContractError(f"contract must be {CONTRACT}")
    websites = body.get("websites")
    if not isinstance(websites, list):
        raise ContractError("websites must be a list")
    if len(websites) > 5000:
        raise ContractError("too many websites in one push")
    generated = _received(body.get("generated_at"), now)
    if generated is None:
        raise ContractError("generated_at must be an ISO 8601 time")
    out = []
    for i, w in enumerate(websites):
        if not isinstance(w, dict) or not isinstance(w.get("key"), dict):
            raise ContractError(f"websites[{i}] needs a key object")
        state = w.get("state")
        if state not in STATES:
            raise ContractError(f"websites[{i}].state must be one of {sorted(STATES)}")
        checks = []
        for c in w.get("checks") or []:
            if not isinstance(c, dict) or c.get("state") not in CHECK_STATES:
                continue
            at = _received(c.get("at"), now)
            reason = c.get("reason")
            checks.append(
                {
                    "source": str(c.get("source") or "monitor")[:40],
                    "state": c["state"],
                    "at": _iso(at) if at else None,
                    "reason": (
                        str(reason)[:80] if isinstance(reason, str) and reason else None
                    ),
                }
            )
        facts = w.get("facts") if isinstance(w.get("facts"), dict) else {}
        last = _received(w.get("last_check"), now) or generated
        out.append(
            {
                "key": w["key"],
                "state": state,
                "checks": checks,
                "facts": {k: _fact(facts.get(k)) for k in FACTS},
                "last_check": _iso(last),
            }
        )
    return out


@dataclass
class Alert:
    """One state change from a monitoring system."""

    source: str
    state: str  # ok | warn | down
    at: str
    text: str
    monitor_id: str | None = None
    hostname: str | None = None


def _first(d: dict, *names: str) -> Any:
    lowered = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        v = lowered.get(n.lower())
        if v not in (None, ""):
            return v
    return None


SITE24X7_STATES = {
    "down": "down",
    "critical": "down",
    "trouble": "warn",
    "warning": "warn",
    "up": "ok",
    "clear": "ok",
    "ok": "ok",
}


def parse_site24x7(body: Any, now: datetime) -> Alert | None:
    """A Site24x7 alert webhook (its default JSON body) for a website monitor. A body without a
    recognizable status is ignored."""
    if not isinstance(body, dict):
        return None
    status = str(_first(body, "STATUS", "MONITOR_STATUS") or "").strip().lower()
    state = SITE24X7_STATES.get(status)
    if state is None:
        return None
    at = _received(_first(body, "INCIDENT_TIME_ISO", "OUTAGE_TIME_ISO"), now) or now
    reason = _first(body, "INCIDENT_REASON", "REASON", "INCIDENT_DETAILS")
    return Alert(
        source="Site24x7",
        state=state,
        at=_iso(at),
        text=str(reason or f"Monitor {status}")[:200],
        monitor_id=str(_first(body, "MONITOR_ID", "MONITORID") or "") or None,
        hostname=hostname(_first(body, "MONITORURL", "HOSTNAME", "HOST")),
    )


# --- Store --------------------------------------------------------------------------------


class Store(Protocol):
    def put_push(self, website_id: str, push: dict) -> None: ...
    def put_alert(self, website_id: str, alert: Alert) -> None: ...
    def rows(self) -> dict[str, dict]: ...


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def put_push(self, website_id: str, push: dict) -> None:
        with self._lock:
            self._rows.setdefault(website_id, {"alerts": {}})["push"] = push

    def put_alert(self, website_id: str, alert: Alert) -> None:
        with self._lock:
            self._rows.setdefault(website_id, {"alerts": {}})["alerts"][
                alert.source
            ] = alert.__dict__

    def rows(self) -> dict[str, dict]:
        with self._lock:
            return json.loads(json.dumps(self._rows))


class TableStore:
    """One table, one row per catalog website: the latest push as JSON in `push`, and the latest
    alert from each monitoring system in `alerts`. A second, append-only table keeps every alert,
    partitioned by UTC day, for history."""

    PARTITION = "website"

    def __init__(self, health, history=None):
        self.health = health
        self.history = history

    @classmethod
    def from_account(
        cls,
        account: str,
        health_table: str = "state",
        history_table: str = "events",
        credential=None,
    ):
        from azure.data.tables import TableClient
        from azure.identity import DefaultAzureCredential

        endpoint = (
            account
            if account.startswith("https://")
            else f"https://{account}.table.core.windows.net"
        )
        credential = credential or DefaultAzureCredential()
        return cls(
            TableClient(endpoint, health_table, credential=credential),
            TableClient(endpoint, history_table, credential=credential),
        )

    def _get(self, website_id: str) -> dict:
        try:
            return dict(self.health.get_entity(self.PARTITION, website_id))
        except Exception:  # noqa: BLE001 - a missing row reads as empty
            return {}

    def put_push(self, website_id: str, push: dict) -> None:
        self.health.upsert_entity(
            {
                "PartitionKey": self.PARTITION,
                "RowKey": website_id,
                "push": json.dumps(push, separators=(",", ":")),
            },
            mode="merge",
        )

    def put_alert(self, website_id: str, alert: Alert) -> None:
        alerts = json.loads(self._get(website_id).get("alerts") or "{}")
        alerts[alert.source] = alert.__dict__
        self.health.upsert_entity(
            {
                "PartitionKey": self.PARTITION,
                "RowKey": website_id,
                "alerts": json.dumps(alerts, separators=(",", ":")),
            },
            mode="merge",
        )
        if self.history is not None:
            self.history.create_entity(
                {
                    "PartitionKey": alert.at[:10],
                    "RowKey": f"{alert.at}_{website_id}_{alert.source}",
                    "website": website_id,
                    "alert": json.dumps(alert.__dict__, separators=(",", ":")),
                }
            )

    def rows(self) -> dict[str, dict]:
        out = {}
        for row in self.health.query_entities(
            "PartitionKey eq @pk", parameters={"pk": self.PARTITION}
        ):
            out[row["RowKey"]] = {
                "push": json.loads(row["push"]) if row.get("push") else None,
                "alerts": json.loads(row.get("alerts") or "{}"),
            }
        return out


# --- Recording ----------------------------------------------------------------------------


def record_push(store: Store, matcher: Matcher, websites: list[dict]) -> dict:
    matched = unmatched = 0
    for w in websites:
        key = w["key"]
        wid = matcher.match(
            key.get("hostname"),
            key.get("kinsta_site_id"),
            key.get("site24x7_monitor_id"),
        )
        if wid is None:
            unmatched += 1
            continue
        store.put_push(
            wid, {k: w[k] for k in ("state", "checks", "facts", "last_check")}
        )
        matched += 1
    return {"matched": matched, "unmatched": unmatched}


def record_alert(store: Store, matcher: Matcher, alert: Alert) -> str | None:
    wid = matcher.match(alert.hostname, None, alert.monitor_id)
    if wid is not None:
        store.put_alert(wid, alert)
    return wid


# --- The live source ----------------------------------------------------------------------


class LiveSource:
    """source(website, group, now) from the store, as WebsitesService expects. Rows are read once
    per status() call (cached for `ttl`), not once per website."""

    def __init__(self, store: Store, ttl: timedelta = timedelta(seconds=20)):
        self.store = store
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

    def __call__(self, website: dict, group: dict, now: datetime) -> dict:
        row = self._all(now).get(website["id"]) or {}
        push = row.get("push")
        pushed_at = _parse_time(push.get("last_check")) if push else None
        fresh = pushed_at is not None and now - pushed_at <= STALE
        state = push["state"] if fresh else "unknown"
        checks = {c["source"]: c for c in (push.get("checks") or [])} if push else {}
        facts = (push.get("facts") or {}) if push else {}

        newer, alerts_out = [], []
        heard = [pushed_at] if pushed_at else []
        for a in (row.get("alerts") or {}).values():
            at = _parse_time(a.get("at"))
            if at is None:
                continue
            heard.append(at)
            checks[a["source"]] = {
                "source": a["source"],
                "state": a["state"],
                "at": _iso(at),
                "reason": None,
            }
            if pushed_at is None or at > pushed_at:
                newer.append(a)
            if a["state"] != "ok" and now - at <= STALE * 12:
                alerts_out.append(
                    {
                        "severity": "critical" if a["state"] == "down" else "warning",
                        "source": a["source"],
                        "text": a.get("text") or "",
                        "since": _iso(at),
                    }
                )
        for c in checks.values():
            if c.get("reason") and c["state"] != "ok":
                alerts_out.append(
                    {
                        "severity": "critical" if c["state"] == "down" else "warning",
                        "source": c["source"],
                        "text": REASONS.get(c["reason"], c["reason"]),
                        "since": c.get("at"),
                    }
                )
        fresh_alerts = [a for a in newer if now - _parse_time(a["at"]) <= STALE]
        if fresh_alerts:
            worst = max(fresh_alerts, key=lambda a: ALERT_SEVERITY[a["state"]])
            state = ALERT_TO_STATE[worst["state"]]
        last = max(heard) if heard else None
        return {
            "state": state,
            "checks": sorted(checks.values(), key=lambda c: c["source"]),
            "alerts": alerts_out,
            "facts": facts,
            "lastCheck": _iso(last) if last else None,
        }


#: Plain words for the reasons a hosting check gives.
REASONS = {
    "blocked": "The hosting provider has blocked the site",
    "vulnerable-plugins": "A plugin or theme with a known vulnerability is installed",
    "no-recent-backup": "No backup in the last 48 hours",
}
