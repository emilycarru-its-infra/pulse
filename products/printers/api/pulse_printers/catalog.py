"""Build the printers catalog from the inventory: one entry per printer in service, with its
model, room and place on the floorplans.

    PULSE_INVENTORY_TOKEN=... python -m pulse_printers.catalog site.toml --out catalog.json

The site config names the inventory, the printer categories, which custom fields hold the
print queues and the audience, and the floorplan index the computers catalog uses:

    [inventory]
    provider = "snipeit"
    url = "https://inventory.example.edu/api/v1"
    categories = ["Printer"]
    exclude_locations = ["Storage"]          # printers waiting for recycling, spares

    [inventory.fields]
    queues_field = "Queues"                  # one queue per line
    audience_field = "Catalog"               # mapped through [audiences]

    [audiences]
    Curriculum = "students"
    Staff = "staff"

    [plans]
    index = "floorplans/rooms.json"
    room_pattern = '^(\\S+)'

A printer is colour when its model or name says so (colour_pattern) or it is an inkjet, and an
inkjet when its model or name matches inkjet_pattern; both can be overridden under [kinds].
"""

import argparse
import html
import json
import os
import re
import sys
import tomllib
from pathlib import Path

from pulse_core.catalog import Plans
from pulse_core.inventory.snipeit import SnipeItProvider

COLOUR = r"(?i)\bcolou?r\b|\bIM C\d|VersaLink C\d"
INKJET = r"(?i)inkjet|\bPRO[- ]?\d{3,4}\b|\bGP[- ]?\d{3}\b|\biPF\d+"


def _custom(row: dict, field: str) -> str:
    value = ((row.get("custom_fields") or {}).get(field) or {}).get("value")
    return html.unescape(value or "").strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def printers_from_rows(rows, site: dict, plans: Plans) -> list[dict]:
    inv = site["inventory"]
    fields = inv.get("fields", {})
    categories = set(inv.get("categories", []))
    excluded = tuple(inv.get("exclude_locations", []))
    audiences = site.get("audiences", {})
    kinds = site.get("kinds", {})
    colour = re.compile(kinds.get("colour_pattern", COLOUR))
    inkjet = re.compile(kinds.get("inkjet_pattern", INKJET))
    out, seen = [], set()
    for row in rows:
        category = (row.get("category") or {}).get("name") or ""
        if categories and category not in categories:
            continue
        location = html.unescape((row.get("location") or {}).get("name") or "")
        if not location or any(location.startswith(x) for x in excluded):
            continue
        name = html.unescape(row.get("name") or "").strip()
        model = html.unescape((row.get("model") or {}).get("name") or "").strip()
        if not name:
            continue
        queues = [
            q.rsplit("/", 1)[-1]
            for q in re.split(
                r"[\r\n]+", _custom(row, fields.get("queues_field", "Queues"))
            )
            if q.strip()
        ]
        audience = audiences.get(
            _custom(row, fields.get("audience_field", "Catalog")), "staff"
        )
        code = plans.room_code(location)
        geo = plans.geometry(code)
        pid = _slug(name)
        while pid in seen:
            pid += "-2"
        seen.add(pid)
        text = f"{model} {name}"
        entry = {
            "id": pid,
            "name": name,
            "model": model,
            "assetTag": row.get("asset_tag") or "",
            "room": code or location,
            "location": location,
            "audience": audience,
            "colour": bool(colour.search(text) or inkjet.search(text)),
            "inkjet": bool(inkjet.search(text)),
            "queues": queues,
        }
        if geo:
            entry["floor"], (entry["x"], entry["y"]) = geo[0], (
                round(geo[1][0], 1),
                round(geo[1][1], 1),
            )
        out.append(entry)
    return sorted(out, key=lambda p: (p.get("floor") or "~", p["room"], p["name"]))


def build(site: dict, rows, plan_index: dict | None) -> dict:
    plan_cfg = site.get("plans", {})
    plans = Plans(
        plan_index, plan_cfg.get("rooms", {}), plan_cfg.get("room_pattern", r"^(\S+)")
    )
    printers = printers_from_rows(rows, site, plans)
    used = {p.get("floor") for p in printers}
    floors = [
        f
        for f in sorted(plans.floors.values(), key=lambda f: f["id"])
        if f["id"] in used
    ]
    return {"floors": floors, "printers": printers}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="site config (TOML)")
    parser.add_argument("--out", help="write the catalog here instead of stdout")
    args = parser.parse_args(argv)
    site_path = Path(args.site)
    site = tomllib.loads(site_path.read_text())
    inv = site["inventory"]
    token = os.environ.get("PULSE_INVENTORY_TOKEN")
    if not token:
        parser.error("PULSE_INVENTORY_TOKEN is not set")
    if inv.get("provider", "snipeit") != "snipeit":
        parser.error("only the snipeit provider is supported")
    # The provider's paging; printers carry none of the computer fields its devices() reads.
    rows = SnipeItProvider(inv["url"], token)._rows()
    index_file = site.get("plans", {}).get("index")
    plan_index = (
        json.loads((site_path.parent / index_file).read_text()) if index_file else None
    )
    catalog = build(site, rows, plan_index)
    text = json.dumps(catalog, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    mapped = sum(1 for p in catalog["printers"] if "floor" in p)
    print(
        f"{len(catalog['printers'])} printers, {mapped} on a floorplan", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
