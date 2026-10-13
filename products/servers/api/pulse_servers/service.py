"""The ServersPulse API as plain functions, so any host (Functions, dev server) can call them.

A site catalog names the servers, where each one runs (a cloud account, an on-premises cluster,
a rack) and the services it carries. Health comes from a source: today the simulator, later
the collectors that read Site24x7, CloudWatch and the hypervisors. The page and the hub read
status() and summary(); neither knows which source answered.
"""

from datetime import datetime, timezone

STATES = ["up", "degraded", "down", "stopped", "unknown"]
# How bad a state is when a group takes the worst of its servers. A stopped server is stopped on
# purpose, so it never makes a group look worse.
SEVERITY = {"up": 0, "stopped": 0, "unknown": 1, "degraded": 2, "down": 3}
LEVEL = {0: "ok", 1: "idle", 2: "warn", 3: "bad"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ServersService:
    def __init__(self, catalog: dict, source, title: str = "Servers"):
        """source(server, location, now) returns the server's health: state, metrics, checks
        and alerts, as pulse_servers.simulate.health does."""
        self.catalog = catalog
        self.source = source
        self.title = title
        self.locations = {loc["id"]: loc for loc in catalog.get("locations", [])}

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        servers = []
        for server in self.catalog.get("servers", []):
            location = self.locations.get(server.get("location"), {})
            health = self.source(server, location, now)
            servers.append({**server, **health})

        def group(items: list[dict]) -> dict:
            counts = dict.fromkeys(STATES, 0)
            for s in items:
                counts[s["state"]] += 1
            worst = max((SEVERITY[s["state"]] for s in items), default=1)
            return {
                "counts": counts,
                "level": LEVEL[worst],
                "servers": len(items),
                "alerts": sum(len(s.get("alerts", [])) for s in items),
            }

        locations = [
            {**loc, **group([s for s in servers if s.get("location") == loc["id"]])}
            for loc in self.catalog.get("locations", [])
        ]
        services = []
        for svc in self.catalog.get("services", []):
            members = [s for s in servers if svc["id"] in s.get("services", [])]
            if members:
                services.append({**svc, **group(members)})
        return {
            "generatedAt": _iso(now),
            "sample": bool(self.catalog.get("sample", False)),
            "locations": locations,
            "services": services,
            "servers": servers,
        }

    def summary(self, now: datetime | None = None) -> dict:
        status = self.status(now)
        counts = dict.fromkeys(STATES, 0)
        for s in status["servers"]:
            counts[s["state"]] += 1
        running = len(status["servers"]) - counts["stopped"]
        alerts = sum(len(s.get("alerts", [])) for s in status["servers"])
        if running == 0:
            level, line = "idle", "No servers in the catalog"
        else:
            level = (
                "bad"
                if counts["down"]
                else "warn" if counts["degraded"] or counts["unknown"] else "ok"
            )
            where = len([loc for loc in status["locations"] if loc["servers"]])
            line = (
                f"{counts['up']} of {running} servers healthy across {where} location{'s' if where != 1 else ''}"
                + (f", {alerts} alert{'s' if alerts != 1 else ''}" if alerts else "")
            )
        return {
            "product": "servers",
            "title": self.title,
            "level": level,
            "line": line,
            "counts": counts,
            "servers": running,
            "alerts": alerts,
            "sample": status["sample"],
            "generatedAt": status["generatedAt"],
        }
