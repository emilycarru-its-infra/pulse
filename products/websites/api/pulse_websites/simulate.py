"""Made-up website health, so the page can be shown before any push arrives.

A website's health is a pure function of its id and the time: every worker and every reload
agrees on it, and nothing is stored. Most sites are up; every twenty minutes a few become
degraded and now and then one goes down, with the alerts each source would raise.
"""

import hashlib
from datetime import datetime, timedelta, timezone

ERA = 20 * 60
DOWN = 0.015
DEGRADED = 0.07

PROBLEMS = [
    ("Site24x7", "Response time {ms} ms from 3 of 5 check locations", None),
    ("Site24x7", "Certificate expires in {days} days", None),
    (
        "Hosting",
        "A plugin or theme with a known vulnerability is installed",
        "vulnerable-plugins",
    ),
    ("Hosting", "No backup in the last 48 hours", "no-recent-backup"),
]


def _unit(*parts) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def health(website: dict, group: dict, now: datetime) -> dict:
    wid = website["id"]
    t = now.timestamp()
    era = int(t // ERA)
    since = datetime.fromtimestamp(era * ERA, timezone.utc)
    roll = _unit(wid, era)
    state = "down" if roll < DOWN else "degraded" if roll < DOWN + DEGRADED else "up"
    alerts = []
    failing = None
    if state == "degraded":
        failing, text, _ = PROBLEMS[int(_unit(wid, era, "kind") * len(PROBLEMS))]
        alerts.append(
            {
                "severity": "warning",
                "source": failing,
                "text": text.format(
                    ms=1800 + int(_unit(wid, era, "ms") * 2500),
                    days=3 + int(_unit(wid, era) * 10),
                ),
                "since": _iso(since),
            }
        )
    elif state == "down":
        failing = "Site24x7"
        alerts.append(
            {
                "severity": "critical",
                "source": "Site24x7",
                "text": "Not answering: every check location failed",
                "since": _iso(since),
            }
        )
    checks = []
    for i, name in enumerate(("Hosting", "Site24x7")):
        bad = (
            state == "down"
            and name == "Site24x7"
            or state == "degraded"
            and name == failing
        )
        checks.append(
            {
                "source": name,
                "state": ("down" if state == "down" else "warn") if bad else "ok",
                "at": _iso(
                    now
                    - timedelta(
                        seconds=30 + int(_unit(wid, name, t // 60) * 600) + i * 20
                    )
                ),
                "reason": None,
            }
        )
    minor = int(_unit(wid, "wp") * 4)
    return {
        "state": state,
        "checks": checks,
        "alerts": alerts,
        "facts": {
            "host": group.get("name"),
            "account": None,
            "php_version": "8.3" if _unit(wid, "php") > 0.15 else "7.4",
            "wordpress_version": f"6.{6 + minor // 2}.{minor}",
            "plugins_vulnerable": (
                1 if state == "degraded" and failing == "Hosting" else 0
            ),
            "last_backup_at": _iso(
                now - timedelta(hours=1 + int(_unit(wid, "backup", t // 86400) * 20))
            ),
        },
        "lastCheck": max(c["at"] for c in checks),
    }
