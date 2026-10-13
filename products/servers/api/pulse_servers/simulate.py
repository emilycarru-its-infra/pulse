"""Made-up server health, so the page can be shown before any collector exists.

The health of a server is a pure function of its id and the time: every worker and every reload
agrees on it, and nothing is stored. Most servers are healthy; every twenty minutes a few become
degraded and now and then one goes down, with the alerts each monitoring source would raise.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone

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
