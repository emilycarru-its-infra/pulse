"""Build a space catalog from an inventory provider and a site config.

The inventory says which devices exist, what they are and which room and group
they belong to. The site config says which groups make up each space and where
each seat sits on its floorplan. Nothing else is stored in the config.

    PULSE_INVENTORY_TOKEN=... python -m pulse_core.catalog site.toml --out catalog.json
"""

import argparse
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .inventory import PROVIDERS, Device


@dataclass
class Report:
    unplaced: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)

    def ok(self) -> bool:
        return not any(self.unplaced.values()) and not any(self.missing.values())


def _matches(device: Device, match: dict, categories: set[str]) -> bool:
    if categories and device.category not in categories:
        return False
    if match.get("group") and device.group != match["group"]:
        return False
    locations = match.get("locations")
    return not locations or device.location in locations


def build(site: dict, devices: Iterable[Device], provider: str, now: datetime | None = None) -> tuple[dict, Report]:
    devices = [d for d in devices if d.deployed]
    categories = set(site.get("inventory", {}).get("categories", []))
    report = Report()
    spaces = []
    for space in site.get("spaces", []):
        positions = {k.upper(): v for k, v in space.get("seats", {}).items()}
        out_of_service = {h.upper() for h in space.get("out_of_service", [])}
        members = sorted(
            (d for d in devices if _matches(d, space.get("match", {}), categories)),
            key=lambda d: d.hostname,
        )
        seats = []
        for d in members:
            seat = {"hostname": d.hostname, "assetTag": d.asset_tag, "serial": d.serial,
                    "platform": d.platform, "room": d.location}
            if d.hostname in out_of_service:
                seat["outOfService"] = True
            if d.hostname in positions:
                seat["x"], seat["y"] = positions[d.hostname]
            seats.append(seat)
        found = {d.hostname for d in members}
        report.unplaced[space["id"]] = [d.hostname for d in members if d.hostname not in positions]
        report.missing[space["id"]] = sorted(h for h in positions if h not in found)
        entry = {k: space[k] for k in ("id", "name", "kind", "building", "floor", "floorplan") if k in space}
        entry["seats"] = seats
        spaces.append(entry)
    generated = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"v": 1, "generatedAt": generated, "source": {"provider": provider}, "spaces": spaces}, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="site config (TOML)")
    parser.add_argument("--out", help="write the catalog here instead of stdout")
    parser.add_argument("--strict", action="store_true", help="fail when a seat is unplaced or missing")
    args = parser.parse_args(argv)

    with open(args.site, "rb") as f:
        site = tomllib.load(f)
    inv = site["inventory"]
    token = os.environ.get("PULSE_INVENTORY_TOKEN")
    if not token:
        parser.error("PULSE_INVENTORY_TOKEN is not set")
    provider = PROVIDERS[inv["provider"]](inv["url"], token, **inv.get("fields", {}))

    catalog, report = build(site, provider.devices(), provider.name)
    text = json.dumps(catalog, indent=2) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    for label, items in (("unplaced", report.unplaced), ("missing from inventory", report.missing)):
        for space_id, hosts in items.items():
            if hosts:
                print(f"{space_id}: {len(hosts)} {label}: {', '.join(hosts)}", file=sys.stderr)
    return 1 if args.strict and not report.ok() else 0


if __name__ == "__main__":
    sys.exit(main())
