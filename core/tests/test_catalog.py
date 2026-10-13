import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pulse_core.catalog import build, load_positions, load_rooms
from pulse_core.inventory import SnipeItProvider

CONTRACT = Path(__file__).parents[1] / "contract"


def asset(tag, hostname, group="Open Mac Lab", location="A1100", category="Desktop",
          platform="Macintosh", meta="deployed", name=None):
    return {
        "asset_tag": tag, "serial": f"S{tag}", "name": hostname if name is None else name,
        "category": {"name": category}, "location": {"name": location},
        "status_label": {"status_meta": meta},
        "custom_fields": {"Hostname": {"value": hostname}, "Platform": {"value": platform},
                          "Fleet": {"value": group}},
    }


ROWS = [
    asset("A1", "lab-mac-01"),
    asset("A2", "LAB-MAC-03", name="Front Desk &amp; Scanner"),
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
    assert devices[1].name == "Front Desk & Scanner"


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
    assert seats["LAB-MAC-03"]["name"] == "Front Desk & Scanner" and "name" not in seats["LAB-MAC-01"]
    assert report.unplaced["open-mac-lab"] == ["LAB-MAC-03", "LAB-MAC-04"]
    assert report.missing["open-mac-lab"] == ["LAB-MAC-02"]
    assert not report.ok()


def test_device_ids_pass_through_to_seats():
    row = asset("A1", "LAB-MAC-01")
    row["custom_fields"]["Intune Id"] = {"value": " ABC-123 "}
    row["custom_fields"]["Entra Id"] = {"value": ""}
    p = SnipeItProvider("https://inv.example/api/v1", "t", device_id_fields=["Intune Id", "Entra Id"],
                        fetch=fake_fetch([{"total": 2, "rows": [row, asset("A2", "LAB-MAC-03")]}]))
    site = {"spaces": [{"id": "lab", "name": "Lab", "kind": "lab", "match": {"group": "Open Mac Lab"}}]}
    catalog, _ = build(site, p.devices(), "snipeit", now=datetime(2027, 1, 4, tzinfo=timezone.utc))
    jsonschema.validate(catalog, json.loads((CONTRACT / "catalog.schema.json").read_text()))
    seats = {s["hostname"]: s for s in catalog["spaces"][0]["seats"]}
    assert seats["LAB-MAC-01"]["deviceIds"] == ["abc-123"]
    assert "deviceIds" not in seats["LAB-MAC-03"]


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


PLANS = {
    "floors": [{"id": "1", "name": "1st Floor", "plan": "floor-1.png", "width": 1000, "height": 500},
               {"id": "2", "name": "2nd Floor", "plan": "floor-2.png", "width": 1000, "height": 500}],
    "rooms": {"A1100": {"floor": "1", "label": [0.2, 0.2], "box": [0.1, 0.1, 0.3, 0.5]},
              "B2200": {"floor": "2", "label": [0.5, 0.5], "box": None}},
}


def test_auto_spaces_sit_in_their_rooms():
    site = {
        "inventory": {"categories": ["Desktop"]},
        "plans": {"room_pattern": r"^([A-Z]\d{4})"},
        "auto": {"groups": {"Open Mac Lab": "lab"}, "exclude_locations": []},
        "positions": {"LAB-MAC-04": [111, 222]},
    }
    catalog, report = build(site, provider().devices(), "snipeit", plan_index=PLANS,
                            now=datetime(2027, 1, 4, tzinfo=timezone.utc))
    jsonschema.validate(catalog, json.loads((CONTRACT / "catalog.schema.json").read_text()))
    assert [f["name"] for f in catalog["floors"]] == ["1st Floor", "2nd Floor"]
    by_id = {s["id"]: s for s in catalog["spaces"]}
    assert sorted(by_id) == ["open-mac-lab-a1100", "open-mac-lab-b2200"]
    a = by_id["open-mac-lab-a1100"]
    assert a["floor"] == "1" and a["box"] == [100.0, 50.0, 300.0, 250.0]
    for seat in a["seats"]:
        if seat["hostname"] == "LAB-MAC-04":
            assert (seat["x"], seat["y"]) == (111, 222)
        else:
            assert 100 < seat["x"] < 300 and 50 < seat["y"] < 250
    b = by_id["open-mac-lab-b2200"]
    assert b["floor"] == "2" and "box" not in b and b["seats"][0]["x"] == 500.0
    assert report.ok()


def test_editor_positions_overlay_hand_pins(tmp_path):
    (tmp_path / "positions.json").write_text('{"LAB-MAC-04": [5, 6], "LAB-MAC-05": [7, 8]}')
    site = {"plans": {"positions": "positions.json"}, "positions": {"LAB-MAC-04": [1, 2], "LAB-MAC-01": [3, 4]}}
    assert load_positions(site, tmp_path) == {"LAB-MAC-01": [3, 4], "LAB-MAC-04": [5, 6], "LAB-MAC-05": [7, 8]}
    assert load_positions({"plans": {"positions": "gone.json"}}, tmp_path) == {}


def test_editor_rooms_replace_plan_boxes(tmp_path):
    (tmp_path / "positions.json").write_text('{"seats": {"LAB-MAC-01": [1, 2]}, "rooms": {"A1100": [400, 100, 600, 300]}}')
    site = {"plans": {"positions": "positions.json", "room_pattern": r"^([A-Z]\d{4})"},
            "inventory": {"categories": ["Desktop"]}, "auto": {"groups": {"Open Mac Lab": "lab"}}}
    assert load_positions(site, tmp_path) == {"LAB-MAC-01": [1, 2]}
    boxes = load_rooms(site, tmp_path)
    catalog, _ = build(site, provider().devices(), "snipeit", plan_index=PLANS, boxes=boxes)
    a = next(s for s in catalog["spaces"] if s["room"] == "A1100")
    assert a["box"] == [400, 100, 600, 300]
    assert all(400 < s["x"] < 600 for s in a["seats"])
