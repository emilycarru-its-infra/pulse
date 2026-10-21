"""Real server health: what the monitoring systems send, kept per catalog server.

Two kinds of input arrive:

- a health push, hourly, from the site's data platform: state, load and the latest check of
  every monitored server (contract ``pulse.server-health/1``);
- alerts, in seconds, straight from the monitoring systems: an uptime service's webhook
  (Site24x7) and cloud alarm state changes (CloudWatch through an EventBridge API destination).

Each input names a server by its monitor id, its cloud instance id or its hostname, and is
matched to the catalog in that order. The `live` source then answers for a server from what
is stored: the push, unless an alert arrived after it, and `unknown` once nothing has been
heard for STALE.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol

CONTRACT = "pulse.server-health/1"
STATES = {"up", "degraded", "down", "stopped", "unknown"}
CHECK_STATES = {"ok", "warn", "down"}
STALE = timedelta(hours=2)
# How bad an alert state is, and the server state it stands for.
ALERT_SEVERITY = {"ok": 0, "warn": 1, "down": 2}
ALERT_TO_STATE = {"ok": "up", "warn": "degraded", "down": "down"}


class ContractError(ValueError):
    """The body is not a health push this version understands."""


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# A sender's clock may run a little ahead; anything later than this is pulled back to the time
# it arrived, so a future-dated input can never stay fresh past STALE.
SKEW = timedelta(minutes=2)


def _received(value: Any, now: datetime) -> datetime | None:
    """A sender-supplied time, no later than `now` plus SKEW."""
    dt = _parse_time(value)
    if dt is None:
        return None
    return min(dt, now + SKEW)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def _short(host: Any) -> str | None:
    if not isinstance(host, str) or not host.strip():
        return None
    return host.strip().split(".")[0].lower()


# --- Matching -----------------------------------------------------------------------------


class Matcher:
    """Finds the catalog server an input names: monitor id, then instance id, then hostname.

    The ids come from the catalog (site24x7_monitor_id, aws_instance_id), which the site builds
    from its system of record. Hostnames compare case-insensitively on the short name, from the
    server's `hostname` and `name` (never `host`, which names the machine it runs on).
    """

    def __init__(self, catalog: dict):
        self.monitor: dict[str, str] = {}
        self.instance: dict[str, str] = {}
        self.host: dict[str, str] = {}
        for server in catalog.get("servers", []):
            sid = server["id"]
            if server.get("site24x7_monitor_id"):
                self.monitor[str(server["site24x7_monitor_id"])] = sid
            if server.get("aws_instance_id"):
                self.instance[str(server["aws_instance_id"])] = sid
            for name in (server.get("hostname"), server.get("name")):
                short = _short(name)
                if short:
                    self.host.setdefault(short, sid)

    def match(
        self, monitor_id: Any = None, instance_id: Any = None, hostname: Any = None
    ) -> str | None:
        if monitor_id is not None and str(monitor_id) in self.monitor:
            return self.monitor[str(monitor_id)]
        if instance_id is not None and str(instance_id) in self.instance:
            return self.instance[str(instance_id)]
        short = _short(hostname)
        return self.host.get(short) if short else None


# --- Inputs -------------------------------------------------------------------------------


def parse_push(body: Any, now: datetime | None = None) -> list[dict]:
    """The servers of a health push, each validated and normalized, with every time no later
    than its arrival. Raises ContractError."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(body, dict):
        raise ContractError("body must be a JSON object")
    if body.get("contract") != CONTRACT:
        raise ContractError(f"contract must be {CONTRACT}")
    servers = body.get("servers")
    if not isinstance(servers, list):
        raise ContractError("servers must be a list")
    generated = _received(body.get("generated_at"), now)
    if generated is None:
        raise ContractError("generated_at must be an ISO 8601 time")
    out = []
    for i, s in enumerate(servers):
        if not isinstance(s, dict) or not isinstance(s.get("key"), dict):
            raise ContractError(f"servers[{i}] needs a key object")
        state = s.get("state")
        if state not in STATES:
            raise ContractError(f"servers[{i}].state must be one of {sorted(STATES)}")
        metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
        checks = []
        for c in s.get("checks") or []:
            if not isinstance(c, dict) or c.get("state") not in CHECK_STATES:
                continue
            at = _received(c.get("at"), now)
            checks.append(
                {
                    "source": str(c.get("source") or "monitor")[:40],
                    "state": c["state"],
                    "at": _iso(at) if at else None,
                }
            )
        last = _received(s.get("last_check"), now) or generated
        out.append(
            {
                "key": s["key"],
                "state": state,
                "metrics": {k: _num(metrics.get(k)) for k in ("cpu", "mem", "disk")},
                "checks": checks,
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
    instance_id: str | None = None
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
    """A Site24x7 alert webhook (its default JSON body). Fields it may leave out are tolerated;
    a body without a recognizable status is ignored."""
    if not isinstance(body, dict):
        return None
    status = str(_first(body, "STATUS", "MONITOR_STATUS") or "").strip().lower()
    state = SITE24X7_STATES.get(status)
    if state is None:
        return None
    at = _received(_first(body, "INCIDENT_TIME_ISO", "OUTAGE_TIME_ISO"), now) or now
    reason = _first(body, "INCIDENT_REASON", "REASON", "INCIDENT_DETAILS")
    name = _first(body, "MONITORNAME", "MONITOR_NAME", "DISPLAYNAME")
    text = str(reason or f"Monitor {status}")[:200]
    return Alert(
        source="Site24x7",
        state=state,
        at=_iso(at),
        text=text,
        monitor_id=str(_first(body, "MONITOR_ID", "MONITORID") or "") or None,
        hostname=str(_first(body, "MONITORURL", "HOSTNAME", "HOST") or name or "")
        or None,
    )


def _alarm_is_down(alarm: str, metrics: Iterable[str]) -> bool:
    text = " ".join([alarm, *metrics]).lower()
    return "statuscheckfailed" in text or "status-check" in text or "down" in text


def parse_cloudwatch(body: Any, now: datetime) -> Alert | None:
    """An EventBridge "CloudWatch Alarm State Change" event. ALARM on a status check is down,
    any other ALARM is warn, OK clears; INSUFFICIENT_DATA is ignored."""
    if (
        not isinstance(body, dict)
        or body.get("detail-type") != "CloudWatch Alarm State Change"
    ):
        return None
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
    value = ((detail.get("state") or {}).get("value") or "").upper()
    if value not in ("ALARM", "OK"):
        return None
    alarm = str(detail.get("alarmName") or "")
    instance = None
    metric_names: list[str] = []
    for m in (detail.get("configuration") or {}).get("metrics") or []:
        stat = ((m or {}).get("metricStat") or {}).get("metric") or {}
        if stat.get("name"):
            metric_names.append(str(stat["name"]))
        dims = stat.get("dimensions") or {}
        if isinstance(dims, dict) and dims.get("InstanceId"):
            instance = str(dims["InstanceId"])
    if instance is None:
        return None
    if value == "OK":
        state = "ok"
    else:
        state = "down" if _alarm_is_down(alarm, metric_names) else "warn"
    at = (
        _received((detail.get("state") or {}).get("timestamp"), now)
        or _received(body.get("time"), now)
        or now
    )
    reason = (detail.get("state") or {}).get("reason")
    return Alert(
        source="CloudWatch",
        state=state,
        at=_iso(at),
        text=str(reason or alarm or "Alarm")[:200],
        instance_id=instance,
    )


# --- Store --------------------------------------------------------------------------------


class Store(Protocol):
    def put_push(self, server_id: str, push: dict) -> None: ...
    def put_alert(self, server_id: str, alert: Alert) -> None: ...
    def rows(self) -> dict[str, dict]: ...


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def put_push(self, server_id: str, push: dict) -> None:
        with self._lock:
            self._rows.setdefault(server_id, {"alerts": {}})["push"] = push

    def put_alert(self, server_id: str, alert: Alert) -> None:
        with self._lock:
            self._rows.setdefault(server_id, {"alerts": {}})["alerts"][
                alert.source
            ] = alert.__dict__

    def rows(self) -> dict[str, dict]:
        with self._lock:
            return json.loads(json.dumps(self._rows))


class TableStore:
    """One table, one row per catalog server: the latest push as JSON in `push`, and the latest
    alert from each monitoring system in `alerts`. A second, append-only table keeps every
    alert, partitioned by UTC day, for history."""

    def __init__(self, health, history=None):
        self.health = health
        self.history = history

    @classmethod
    def from_account(
        cls,
        account: str,
        health_table: str = "health",
        history_table: str = "alerts",
        credential=None,
    ) -> "TableStore":
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

    def _get(self, server_id: str) -> dict:
        try:
            return dict(self.health.get_entity("server", server_id))
        except Exception:  # noqa: BLE001 - a missing row reads as empty
            return {}

    def put_push(self, server_id: str, push: dict) -> None:
        self.health.upsert_entity(
            {
                "PartitionKey": "server",
                "RowKey": server_id,
                "push": json.dumps(push, separators=(",", ":")),
            },
            mode="merge",
        )

    def put_alert(self, server_id: str, alert: Alert) -> None:
        row = self._get(server_id)
        alerts = json.loads(row.get("alerts") or "{}")
        alerts[alert.source] = alert.__dict__
        self.health.upsert_entity(
            {
                "PartitionKey": "server",
                "RowKey": server_id,
                "alerts": json.dumps(alerts, separators=(",", ":")),
            },
            mode="merge",
        )
        if self.history is not None:
            self.history.create_entity(
                {
                    "PartitionKey": alert.at[:10],
                    "RowKey": f"{alert.at}_{server_id}_{alert.source}",
                    "server": server_id,
                    "alert": json.dumps(alert.__dict__, separators=(",", ":")),
                }
            )

    def rows(self) -> dict[str, dict]:
        out = {}
        for row in self.health.query_entities(
            "PartitionKey eq @pk", parameters={"pk": "server"}
        ):
            out[row["RowKey"]] = {
                "push": json.loads(row["push"]) if row.get("push") else None,
                "alerts": json.loads(row.get("alerts") or "{}"),
            }
        return out


# --- Recording ----------------------------------------------------------------------------


def record_push(store: Store, matcher: Matcher, servers: list[dict]) -> dict:
    matched = unmatched = 0
    for s in servers:
        key = s["key"]
        sid = matcher.match(
            key.get("site24x7_monitor_id"),
            key.get("aws_instance_id"),
            key.get("hostname"),
        )
        if sid is None:
            unmatched += 1
            continue
        store.put_push(
            sid, {k: s[k] for k in ("state", "metrics", "checks", "last_check")}
        )
        matched += 1
    return {"matched": matched, "unmatched": unmatched}


def record_alert(store: Store, matcher: Matcher, alert: Alert) -> str | None:
    sid = matcher.match(alert.monitor_id, alert.instance_id, alert.hostname)
    if sid is not None:
        store.put_alert(sid, alert)
    return sid


# --- The live source ----------------------------------------------------------------------


class LiveSource:
    """source(server, location, now) from the store, as ServersService expects. Rows are read
    once per status() call (cached for `ttl`), not once per server."""

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

    def __call__(self, server: dict, location: dict, now: datetime) -> dict:
        if server.get("stopped"):
            return {
                "state": "stopped",
                "metrics": None,
                "checks": [],
                "alerts": [],
                "lastCheck": None,
                "uptimeDays": None,
            }
        row = self._all(now).get(server["id"]) or {}
        push = row.get("push")
        pushed_at = _parse_time(push.get("last_check")) if push else None
        fresh_push = pushed_at is not None and now - pushed_at <= STALE

        state = push["state"] if fresh_push else "unknown"
        metrics = push.get("metrics") if fresh_push else None
        if metrics is not None and all(v is None for v in metrics.values()):
            metrics = None
        checks = {c["source"]: c for c in (push.get("checks") or [])} if push else {}

        # Alerts newer than the push decide the state: the worst current alert from any system.
        newer = []
        alerts_out = []
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
        # An alert newer than the push wins: the worst of the fresh ones, an OK clearing.
        fresh_alerts = [a for a in newer if now - _parse_time(a["at"]) <= STALE]
        if fresh_alerts:
            worst = max(fresh_alerts, key=lambda a: ALERT_SEVERITY[a["state"]])
            state = ALERT_TO_STATE[worst["state"]]
        last = max(heard) if heard else None
        return {
            "state": state,
            "metrics": metrics if state != "down" else None,
            "checks": sorted(checks.values(), key=lambda c: c["source"]),
            "alerts": alerts_out,
            "lastCheck": _iso(last) if last else None,
            "uptimeDays": None,
        }
