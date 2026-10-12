"""Build a space catalog from an inventory provider and a site config.

The inventory says which devices exist, what they are and which room and group
they belong to. The site config says which groups are shown, where each room is on
which floor (through a plan index), and any seat positions to pin by hand. Seats
with no pinned position are laid out in a grid inside their room.

    PULSE_INVENTORY_TOKEN=... python -m pulse_core.catalog site.toml --out catalog.json
"""

import argparse
import json
import math
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .inventory import PROVIDERS, Device

SEAT = 22  # plan pixels per seat when a room has no measured box


@dataclass
class Report:
    unplaced: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not any(self.unplaced.values()) and not any(self.missing.values()) and not self.unmapped


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _matches(device: Device, match: dict, categories: set[str]) -> bool:
    if categories and device.category not in categories:
        return False
    if match.get("group") and device.group != match["group"]:
        return False
    locations = match.get("locations")
    return not locations or device.location in locations


class Plans:
    """Floors and room geometry from a plan index, in plan pixels."""

    def __init__(self, index: dict | None, extra: dict, pattern: str):
        index = index or {"floors": [], "rooms": {}}
        self.floors = {f["id"]: f for f in index["floors"]}
        self.rooms = {**index["rooms"], **extra}
        self.pattern = re.compile(pattern)

    def room_code(self, location: str) -> str | None:
        m = self.pattern.match(location)
        return m.group(1) if m else None

    def geometry(self, code: str | None) -> tuple[str, list[float], list[float] | None] | None:
        room = self.rooms.get(code or "")
        if not room or room["floor"] not in self.floors:
            return None
        f = self.floors[room["floor"]]
        w, h = f["width"], f["height"]
        label = [room["label"][0] * w, room["label"][1] * h]
        box = room.get("box")
        box = [box[0] * w, box[1] * h, box[2] * w, box[3] * h] if box else None
        return room["floor"], label, box


def grid(n: int, box: list[float] | None, label: list[float]) -> tuple[list[tuple[float, float]], float]:
    """Seat centres for n seats filling a room box, and the seat size, in plan pixels."""
    if not box:
        cols = max(1, math.ceil(math.sqrt(n * 1.5)))
        rows = math.ceil(n / cols)
        w, h = cols * SEAT * 1.25, rows * SEAT * 1.25
        box = [label[0] - w / 2, label[1] + 14, label[0] + w / 2, label[1] + 14 + h]
    x0, y0, x1, y1 = box
    pad = min(x1 - x0, y1 - y0) * 0.08
    x0, y0, x1, y1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    cols = max(1, min(n, round(math.sqrt(n * w / h))))
    rows = math.ceil(n / cols)
    cell = min(w / cols, h / rows)
    size = min(cell * 0.8, SEAT * 1.6)
    ox = x0 + (w - cols * cell) / 2 + cell / 2
    oy = y0 + (h - rows * cell) / 2 + cell / 2
    return [(round(ox + (i % cols) * cell, 1), round(oy + (i // cols) * cell, 1)) for i in range(n)], round(size, 1)


def _auto_spaces(site: dict, devices: list[Device], plans: Plans, categories: set[str]) -> list[dict]:
    auto = site.get("auto")
    if not auto:
        return []
    kinds: dict[str, str] = auto.get("groups", {})
    excluded = set(auto.get("exclude_locations", []))
    by_room: dict[tuple[str, str], list[Device]] = {}
    for d in devices:
        if d.group in kinds and d.location not in excluded and (not categories or d.category in categories):
            by_room.setdefault((d.group, d.location), []).append(d)
    spaces = []
    for (group, location), members in sorted(by_room.items()):
        code = plans.room_code(location)
        spaces.append({"id": slug(f"{group}-{code or location}"), "name": group, "kind": kinds[group],
                       "room": code or location, "_members": members})
    return spaces


def build(site: dict, devices: Iterable[Device], provider: str, now: datetime | None = None,
          plan_index: dict | None = None) -> tuple[dict, Report]:
    devices = [d for d in devices if d.deployed]
    categories = set(site.get("inventory", {}).get("categories", []))
    plan_cfg = site.get("plans", {})
    plans = Plans(plan_index, plan_cfg.get("rooms", {}), plan_cfg.get("room_pattern", r"^(\S+)"))
    pinned = {k.upper(): v for k, v in site.get("positions", {}).items()}
    report = Report()

    spaces_in = []
    for space in site.get("spaces", []):
        members = [d for d in devices if _matches(d, space.get("match", {}), categories)]
        spaces_in.append({**space, "_members": members})
    spaces_in += _auto_spaces(site, devices, plans, categories)

    spaces = []
    for space in spaces_in:
        members = sorted(space.pop("_members"), key=lambda d: d.hostname)
        own = {k.upper(): v for k, v in space.pop("seats", {}).items()}
        positions = {**pinned, **own}
        out_of_service = {h.upper() for h in space.pop("out_of_service", [])}
        space.pop("match", None)
        code = space.get("room") or (plans.room_code(members[0].location) if members else None)
        geo = plans.geometry(code)
        if geo:
            space.setdefault("floor", geo[0])
            space["label"] = [round(v, 1) for v in geo[1]]
            if geo[2]:
                space["box"] = [round(v, 1) for v in geo[2]]
            auto_xy, size = grid(len(members), geo[2], geo[1])
            space["seatSize"] = size
        else:
            auto_xy = []
            report.unmapped.append(space["id"])
        if code:
            space["room"] = code
        seats = []
        for i, d in enumerate(members):
            seat = {"hostname": d.hostname, "assetTag": d.asset_tag, "serial": d.serial,
                    "platform": d.platform, "room": d.location}
            if d.name and d.name.upper() != d.hostname:
                seat["name"] = d.name
            if d.hostname in out_of_service:
                seat["outOfService"] = True
            if d.hostname in positions:
                seat["x"], seat["y"] = positions[d.hostname]
            elif auto_xy:
                seat["x"], seat["y"] = auto_xy[i]
            seats.append(seat)
        found = {d.hostname for d in members}
        report.unplaced[space["id"]] = [s["hostname"] for s in seats if "x" not in s]
        report.missing[space["id"]] = sorted(h for h in own if h not in found)
        space["seats"] = seats
        spaces.append(space)

    generated = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    catalog = {"v": 1, "generatedAt": generated, "source": {"provider": provider}, "spaces": spaces}
    if plans.floors:
        catalog["floors"] = sorted(plans.floors.values(), key=lambda f: f["id"])
    return catalog, report


def load_positions(site: dict, base: Path) -> dict:
    """Hand pins from [positions], overlaid with the seat editor's file named by [plans] positions."""
    pinned = dict(site.get("positions", {}))
    saved = site.get("plans", {}).get("positions")
    if saved and (base / saved).is_file():
        pinned.update(json.loads((base / saved).read_text()))
    return pinned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="site config (TOML)")
    parser.add_argument("--out", help="write the catalog here instead of stdout")
    parser.add_argument("--strict", action="store_true", help="fail when a seat is unplaced or missing")
    args = parser.parse_args(argv)

    site_path = Path(args.site)
    site = tomllib.loads(site_path.read_text())
    inv = site["inventory"]
    token = os.environ.get("PULSE_INVENTORY_TOKEN")
    if not token:
        parser.error("PULSE_INVENTORY_TOKEN is not set")
    provider = PROVIDERS[inv["provider"]](inv["url"], token, **inv.get("fields", {}))
    index_file = site.get("plans", {}).get("index")
    plan_index = json.loads((site_path.parent / index_file).read_text()) if index_file else None
    site["positions"] = load_positions(site, site_path.parent)

    catalog, report = build(site, provider.devices(), provider.name, plan_index=plan_index)
    text = json.dumps(catalog, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    seats = sum(len(s["seats"]) for s in catalog["spaces"])
    print(f"{len(catalog['spaces'])} spaces, {seats} seats", file=sys.stderr)
    for label, items in (("unplaced", report.unplaced), ("missing from inventory", report.missing)):
        for space_id, hosts in items.items():
            if hosts:
                print(f"{space_id}: {len(hosts)} {label}: {', '.join(hosts)}", file=sys.stderr)
    if report.unmapped:
        print(f"not on any floorplan: {', '.join(report.unmapped)}", file=sys.stderr)
    return 1 if args.strict and not report.ok() else 0


if __name__ == "__main__":
    sys.exit(main())
