"""Made-up server health, so the page can be shown before any collector exists.

The health of a server is a pure function of its id and the time: every worker and every reload
agrees on it, and nothing is stored. Most servers are healthy; every twenty minutes a few become
degraded and now and then one goes down, with the alerts each monitoring source would raise.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

ERA = 20 * 60  # seconds an incident lasts
DOWN = 0.012  # share of servers down in an era
DEGRADED = 0.05  # share degraded


def _unit(*parts) -> float:
    """A stable number in [0, 1) for the given parts."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wave(sid: str, metric: str, t: float, base: float, spread: float) -> float:
    phase = _unit(sid, metric, "phase") * 2 * math.pi
    period = 600 + _unit(sid, metric, "period") * 3000
    value = base + spread * math.sin(phase + 2 * math.pi * t / period)
    return max(1.0, min(99.0, round(value, 1)))


PROBLEMS = [
    ("cpu", "CPU above 90% for 15 minutes"),
    ("mem", "Memory above 92% for 10 minutes"),
    ("disk", "System disk {disk:.0f}% full"),
    ("latency", "Response time {ms} ms from 3 of 5 check locations"),
    ("service", "A monitored service stopped and restarted twice in an hour"),
]


def health(server: dict, location: dict, now: datetime) -> dict:
    sid = server["id"]
    sources = location.get("sources") or ["Site24x7"]
    if server.get("stopped"):
        return {
            "state": "stopped",
            "metrics": None,
            "checks": [],
            "alerts": [],
            "lastCheck": None,
            "uptimeDays": None,
        }

    t = now.timestamp()
    era = int(t // ERA)
    since = datetime.fromtimestamp(era * ERA, timezone.utc)
    roll = _unit(sid, era)
    state = "down" if roll < DOWN else "degraded" if roll < DOWN + DEGRADED else "up"

    metrics = {
        "cpu": _wave(sid, "cpu", t, 8 + _unit(sid, "cpu") * 35, 10),
        "mem": _wave(sid, "mem", t, 35 + _unit(sid, "mem") * 35, 6),
        "disk": round(25 + _unit(sid, "disk") * 50, 1),
    }
    alerts = []
    if state == "degraded":
        kind, text = PROBLEMS[int(_unit(sid, era, "kind") * len(PROBLEMS))]
        ms = 1800 + int(_unit(sid, era, "ms") * 2500)
        if kind == "cpu":
            metrics["cpu"] = round(91 + _unit(sid, t // 60) * 7, 1)
        elif kind == "mem":
            metrics["mem"] = round(93 + _unit(sid, t // 60) * 5, 1)
        elif kind == "disk":
            metrics["disk"] = round(91 + _unit(sid, era, "disk") * 7, 1)
        alerts.append(
            {
                "severity": "warning",
                "source": sources[0] if kind in ("latency", "service") else sources[-1],
                "text": text.format(disk=metrics["disk"], ms=ms),
                "since": _iso(since),
            }
        )
    elif state == "down":
        metrics = None
        alerts.append(
            {
                "severity": "critical",
                "source": sources[0],
                "text": "Not answering: every check location failed",
                "since": _iso(since),
            }
        )
        if len(sources) > 1:
            alerts.append(
                {
                    "severity": "critical",
                    "source": sources[1],
                    "text": (
                        "Status check failed"
                        if location.get("kind") == "cloud"
                        else "Guest heartbeat lost"
                    ),
                    "since": _iso(since + timedelta(seconds=40)),
                }
            )

    checks = []
    for i, name in enumerate(sources):
        lag = 15 + int(_unit(sid, name, t // 60) * 75) + i * 20
        failing = state == "down" or (
            state == "degraded" and any(a["source"] == name for a in alerts)
        )
        checks.append(
            {
                "source": name,
                "state": ("down" if state == "down" else "warn") if failing else "ok",
                "at": _iso(now - timedelta(seconds=lag)),
            }
        )
    return {
        "state": state,
        "metrics": metrics,
        "checks": checks,
        "alerts": alerts,
        "lastCheck": max(c["at"] for c in checks),
        "uptimeDays": (
            None if state == "down" else 1 + int(_unit(sid, "uptime", t // 86400) * 120)
        ),
    }


_LINUX = [
    ("nginx", "1.26.2", "/usr/sbin/nginx", "nginx.service", "nginx", "1.26.2-1ubuntu1"),
    ("PHP", "8.3.6", "/usr/sbin/php-fpm8.3", "php8.3-fpm.service", "php8.3-fpm", "8.3.6-0ubuntu0.24.04.3"),
    ("OpenSSL", "3.0.13", "/usr/bin/openssl", None, "openssl", "3.0.13-0ubuntu3.4"),
    ("OpenSSH", "9.6p1", "/usr/sbin/sshd", "ssh.service", "openssh-server", "1:9.6p1-3ubuntu13.5"),
    ("Python", "3.12.3", "/usr/bin/python3.12", None, "python3.12", "3.12.3-1ubuntu0.2"),
    ("Java", "21.0.5", "/usr/lib/jvm/java-21-openjdk-amd64/bin/java", "tomcat10.service", "openjdk-21-jre-headless", "21.0.5+11-1ubuntu1"),
]
_WINDOWS = [
    ("IIS", "10.0.20348.1", "C:\\Windows\\System32\\inetsrv\\w3wp.exe", "W3SVC", None, None),
    ("PowerShell", "7.4.6.500", "C:\\Program Files\\PowerShell\\7\\pwsh.exe", None, None, None),
    (".NET host", "8.0.11.24521", "C:\\Program Files\\dotnet\\dotnet.exe", None, None, None),
    ("OpenSSH", "OpenSSH_9.5p1, LibreSSL 3.8.2", "C:\\Windows\\System32\\OpenSSH\\sshd.exe", "sshd", None, None),
    ("Java", "17.0.13", "C:\\Program Files\\Eclipse Adoptium\\jre-17\\bin\\java.exe", None, None, None),
]


def runtimes(catalog: dict, now: datetime) -> dict:
    """Plausible stored binary observations per server, in the shape runtimes.Store.rows() returns."""
    rows = {}
    for server in catalog.get("servers", []):
        sid = server["id"]
        if _unit(sid, "runtime-gap") < 0.1:
            continue
        windows = "windows" in (server.get("os") or "").lower()
        components = []
        for name, version, exe, service, pkg, pkg_version in _WINDOWS if windows else _LINUX:
            pick = _unit(sid, name)
            if pick < 0.35:
                continue
            running = pick > 0.6
            if pick > 0.9 and name in ("PHP", "Java", "OpenSSL"):
                version = {"PHP": "8.1.2", "Java": "11.0.25", "OpenSSL": "1.1.1w"}[name]
            metadata = windows and name in ("PowerShell", ".NET host", "OpenSSH")
            component = {
                "name": name,
                "version": version,
                "running": running,
                "scope": "host",
                "executable": exe,
                "evidence_kind": ("running_binary_file_metadata" if metadata else "executable_self_report")
                if running
                else ("installed_binary_file_metadata" if metadata else "installed_executable_self_report"),
                "process_count": 1 + int(_unit(sid, name, "procs") * 4) if running else 0,
                "pids": [],
            }
            if running and service:
                component["service"] = service
            if pkg:
                component.update(package_name=pkg, package_version=pkg_version)
            components.append(component)
        observed = _iso(now - timedelta(minutes=int(_unit(sid, "age") * 40)))
        if _unit(sid, "runtime-stale") < 0.08:
            observed = _iso(now - timedelta(hours=3))
        success = {
            "item_id": str(uuid5(NAMESPACE_URL, f"pulse-sample/{sid}")),
            "observation_id": str(uuid5(NAMESPACE_URL, f"pulse-sample/{sid}/{observed}")),
            "observed_at": observed,
            "facts": {"contract": "server-live-runtimes/1", "collection_state": "observed", "components": components},
        }
        rows[sid] = {
            "attempt": {"received_at": observed, "outcome": "accepted", "observation_id": success["observation_id"], "facts": {"reason": None}},
            "success": success,
        }
    return rows
