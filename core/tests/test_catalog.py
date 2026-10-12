import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pulse_core.catalog import build
from pulse_core.inventory import SnipeItProvider

CONTRACT = Path(__file__).parents[1] / "contract"


def asset(tag, hostname, group="Open Mac Lab", location="A1100", category="Desktop",
          platform="Macintosh", meta="deployed"):
    return {
        "asset_tag": tag, "serial": f"S{tag}",
        "category": {"name": category}, "location": {"name": location},
        "status_label": {"status_meta": meta},
        "custom_fields": {"Hostname": {"value": hostname}, "Platform": {"value": platform},
                          "Fleet": {"value": group}},
    }


ROWS = [
    asset("A1", "lab-mac-01"),
    asset("A2", "LAB-MAC-03"),
    asset("A3", "LAB-MAC-04"),
    asset("A4", "LAB-MAC-05", category="Display"),
    asset("A5", "LAB-MAC-06", meta="archived"),
    asset("A6", "LAB-MAC-07", location="B2200"),
    asset("A7", "", category="Desktop"),
    asset("A8", "OFFICE-01", group="Staff &amp; Faculty"),
]


def fake_fetch(pages):
    calls = []

    def fetch(url, headers):
        calls.append(url)
        return pages[len(calls) - 1]
    fetch.calls = calls
    return fetch


def provider(rows=ROWS, page_size=500):
    pages = [{"total": len(rows), "rows": rows[i:i + page_size]} for i in range(0, len(rows), page_size)]
    return SnipeItProvider("https://inv.example/api/v1/", "t", page_size=page_size, fetch=fake_fetch(pages))


def test_provider_pages_and_normalises():
    p = provider(page_size=3)
    devices = list(p.devices())
    assert len(p.fetch.calls) == 3
    assert "offset=3" in p.fetch.calls[1]
    assert devices[0].hostname == "LAB-MAC-01" and devices[0].platform == "mac"
    assert all(d.hostname for d in devices)
    assert devices[-1].group == "Staff & Faculty"


def test_provider_raises_on_error_envelope():
    p = SnipeItProvider("https://inv.example/api/v1", "t",
                        fetch=lambda u, h: {"status": "error", "messages": "nope"})
    try:
        list(p.devices())
    except RuntimeError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_build_matches_places_and_reports():
    site = tomllib.loads((CONTRACT / "examples" / "site.toml").read_text())
    catalog, report = build(site, provider().devices(), "snipeit",
                            now=datetime(2027, 1, 4, tzinfo=timezone.utc))
    jsonschema.validate(catalog, json.loads((CONTRACT / "catalog.schema.json").read_text()))
    seats = {s["hostname"]: s for s in catalog["spaces"][0]["seats"]}
    assert sorted(seats) == ["LAB-MAC-01", "LAB-MAC-03", "LAB-MAC-04"]
    assert (seats["LAB-MAC-01"]["x"], seats["LAB-MAC-01"]["y"]) == (120, 340)
    assert seats["LAB-MAC-03"]["outOfService"] is True
    assert report.unplaced["open-mac-lab"] == ["LAB-MAC-03", "LAB-MAC-04"]
    assert report.missing["open-mac-lab"] == ["LAB-MAC-02"]
    assert not report.ok()


def test_example_event_matches_schema():
    schema = json.loads((CONTRACT / "event.schema.json").read_text())
    jsonschema.validate(json.loads((CONTRACT / "examples" / "heartbeat.json").read_text()), schema)
    bad = json.loads((CONTRACT / "examples" / "heartbeat.json").read_text())
    bad["session"]["username"] = "someone"
    try:
        jsonschema.validate(bad, schema)
    except jsonschema.ValidationError:
        pass
    else:
        raise AssertionError("a username must be rejected")
