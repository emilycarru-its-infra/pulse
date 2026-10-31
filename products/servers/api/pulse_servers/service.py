"""The ServersPulse API as plain functions, so any host (Functions, dev server) can call them.

A site catalog names the servers, where each one runs (a cloud account, an on-premises cluster,
a rack) and the services it carries. Health comes from a source: today the simulator, later
the collectors that read Site24x7, CloudWatch and the hypervisors. The page and the hub read
status() and summary(); neither knows which source answered.
"""

import logging
import os
import re
from datetime import UTC, datetime, timedelta

from pulse_servers.patches import assessments
from pulse_servers.runtimes import time, view

STATES = ["up", "degraded", "down", "stopped", "unknown"]
# How bad a state is when a group takes the worst of its servers. A stopped server is stopped on
# purpose, so it never makes a group look worse.
SEVERITY = {"up": 0, "stopped": 0, "unknown": 1, "degraded": 2, "down": 3}
LEVEL = {0: "ok", 1: "idle", 2: "warn", 3: "bad"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ServersService:
    def __init__(
        self,
        catalog: dict,
        source,
        title: str = "Servers",
        runtime_store=None,
        inventory_store=None,
    ):
        """source(server, location, now) returns the server's health: state, metrics, checks
        and alerts, as pulse_servers.simulate.health does."""
        self.patch_cves = [
            v.strip()
            for v in os.environ.get("PULSE_KERNEL_CVES", "").split(",")
            if re.fullmatch(r"CVE-[0-9]{4}-[0-9]{4,8}", v.strip())
        ]
        self.inventory_store = inventory_store
        self.runtime_store = runtime_store
        self.catalog = catalog
        self.source = source
        self.title = title
        self.locations = {loc["id"]: loc for loc in catalog.get("locations", [])}

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        runtime_error = False
        try:
            runtime_rows = self.runtime_store.rows() if self.runtime_store else {}
        except Exception:  # noqa: BLE001 - runtime collection failure must not hide server health
            logging.getLogger(__name__).warning(
                "Runtime projection storage unavailable"
            )
            runtime_rows, runtime_error = {}, True
        inventory_error = False
        try:
            inventory_rows = self.inventory_store.rows() if self.inventory_store else {}
        except Exception:  # noqa: BLE001 - inventory outage must not hide server health
            logging.getLogger(__name__).warning(
                "Inventory projection storage unavailable"
            )
            inventory_rows, inventory_error = {}, True
        servers = []
        for server in self.catalog.get("servers", []):
            location = self.locations.get(server.get("location"), {})
            health = self.source(server, location, now)
            runtime = view(runtime_rows.get(server["id"], {}), now)
            if runtime_error:
                runtime.update(
                    freshness="unavailable",
                    gaps=["Runtime observation storage unavailable"],
                )
            row = {
                **server,
                **health,
                "runtimeInventory": runtime,
                "patches": assessments(server, runtime, self.patch_cves, now),
            }
            if self.inventory_store is not None:
                row.pop("service_group", None)
                source = inventory_rows.get(server["id"])
                if source and source["item_id"] == server.get("cellarum_item_id"):
                    if source["service_group"]:
                        row["service_group"] = source["service_group"]
                    row["inventorySource"] = {
                        "source": "Cellarum",
                        "version": source["version"],
                        "retrieved_at": source["retrieved_at"],
                        "freshness": "fresh"
                        if now - time(source["retrieved_at"]) <= timedelta(hours=1)
                        else "stale",
                    }
                else:
                    row["inventorySource"] = {
                        "source": "Cellarum",
                        "freshness": "unavailable" if inventory_error else "unassessed",
                    }
            servers.append(row)

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
        service_groups = []
        for name in sorted(
            {
                s.get("service_group", "").strip()
                for s in servers
                if s.get("service_group")
            }
        ):
            if name:
                service_groups.append(
                    {
                        "name": name,
                        **group(
                            [
                                s
                                for s in servers
                                if (s.get("service_group") or "").strip() == name
                            ]
                        ),
                    }
                )
        return {
            "patching": {"cves": self.patch_cves},
            "serviceGroups": service_groups,
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
                else "warn"
                if counts["degraded"] or counts["unknown"]
                else "ok"
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
