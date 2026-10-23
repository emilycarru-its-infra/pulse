"""The WebsitesPulse API as plain functions, so any host (Functions, dev server) can call them.

A site catalog names the websites and the group each belongs to (usually where it is hosted).
Health comes from a source: the simulator, or what the monitoring systems posted. The page and
the hub read status() and summary(); neither knows which source answered.
"""

from datetime import UTC, datetime

STATES = ["up", "degraded", "down", "unknown"]
SEVERITY = {"up": 0, "unknown": 1, "degraded": 2, "down": 3}
LEVEL = {0: "ok", 1: "idle", 2: "warn", 3: "bad"}
#: Catalog fields the page may show. Anything else in a catalog entry stays server-side.
PUBLIC = ("id", "name", "url", "hostname", "group", "owner", "note", "environment")


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class WebsitesService:
    def __init__(self, catalog: dict, source, title: str = "Websites"):
        """source(website, group, now) returns the website's health: state, checks, alerts and
        facts, as pulse_websites.simulate.health does."""
        self.catalog = catalog
        self.source = source
        self.title = title
        self.groups = {g["id"]: g for g in catalog.get("groups", [])}

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        websites = []
        for w in self.catalog.get("websites", []):
            group = self.groups.get(w.get("group"), {})
            health = self.source(w, group, now)
            websites.append({**{k: w[k] for k in PUBLIC if k in w}, **health})

        def summarize(items: list[dict]) -> dict:
            counts = dict.fromkeys(STATES, 0)
            for w in items:
                counts[w["state"]] += 1
            worst = max((SEVERITY[w["state"]] for w in items), default=1)
            return {
                "counts": counts,
                "level": LEVEL[worst],
                "websites": len(items),
                "alerts": sum(len(w.get("alerts", [])) for w in items),
            }

        groups = [
            {**g, **summarize([w for w in websites if w.get("group") == g["id"]])}
            for g in self.catalog.get("groups", [])
        ]
        return {
            "generatedAt": _iso(now),
            "sample": bool(self.catalog.get("sample", False)),
            "groups": groups,
            "websites": websites,
        }

    def summary(self, now: datetime | None = None) -> dict:
        status = self.status(now)
        counts = dict.fromkeys(STATES, 0)
        for w in status["websites"]:
            counts[w["state"]] += 1
        total = len(status["websites"])
        alerts = sum(len(w.get("alerts", [])) for w in status["websites"])
        if total == 0:
            level, line = "idle", "No websites in the catalog"
        else:
            level = (
                "bad"
                if counts["down"]
                else "warn" if counts["degraded"] or counts["unknown"] else "ok"
            )
            line = f"{counts['up']} of {total} websites healthy" + (
                f", {alerts} alert{'s' if alerts != 1 else ''}" if alerts else ""
            )
        return {
            "product": "websites",
            "title": self.title,
            "level": level,
            "line": line,
            "counts": counts,
            "websites": total,
            "alerts": alerts,
            "sample": status["sample"],
            "generatedAt": status["generatedAt"],
        }
