import json
from datetime import datetime, timedelta, timezone

from pulse_core.catalog import Plans
from pulse_printers.catalog import build, printers_from_rows
from pulse_printers.service import STATES, PrintersService

INDEX = {"floors": [{"id": "1", "name": "1st Floor", "plan": "f1.png", "width": 1000, "height": 500}],
         "rooms": {"R101": {"floor": "1", "label": [0.5, 0.5], "box": None}}}
SITE = {"inventory": {"categories": ["Printer"], "exclude_locations": ["Storage"],
                      "fields": {"queues_field": "Queues", "audience_field": "Catalog"}},
        "audiences": {"Students": "students"}, "plans": {"room_pattern": r"^(R\d+)"}}


def row(name, model, location, catalog="Students", queues="lpd://print/one\r\nlpd://print/two", category="Printer"):
    return {"name": name, "asset_tag": "T1", "model": {"name": model}, "category": {"name": category},
            "location": {"name": location},
            "custom_fields": {"Queues": {"value": queues}, "Catalog": {"value": catalog}}}


ROWS = [
    row("Lab Colour", "Ricoh IM C3500", "R101 - Lab"),
    row("Office BW", "HP LaserJet M426", "R999", catalog="Staff"),
    row("Photo Inkjet", "Canon PRO 2100", "R101 - Lab"),
    row("Old one", "HP LaserJet", "Storage"),
    row("A screen", "Monitor", "R101", category="Display"),
]


def catalog():
    return build(SITE, ROWS, INDEX)


def test_catalog_keeps_printers_in_service_with_kind_audience_and_place():
    c = catalog()
    names = {p["name"]: p for p in c["printers"]}
    assert set(names) == {"Lab Colour", "Office BW", "Photo Inkjet"}
    lab = names["Lab Colour"]
    assert lab["colour"] and not lab["inkjet"] and lab["audience"] == "students"
    assert lab["queues"] == ["one", "two"] and lab["floor"] == "1" and (lab["x"], lab["y"]) == (500.0, 250.0)
    assert names["Photo Inkjet"]["inkjet"] and names["Photo Inkjet"]["colour"]
    office = names["Office BW"]
    assert not office["colour"] and office["audience"] == "staff" and "floor" not in office
    assert [f["id"] for f in c["floors"]] == ["1"]


def test_duplicate_names_get_distinct_ids():
    plans = Plans(INDEX, {}, r"^(R\d+)")
    ps = printers_from_rows([row("Same", "X", "R101"), row("Same", "X", "R101")], SITE, plans)
    assert len({p["id"] for p in ps}) == 2


def test_sample_state_is_stable_within_minutes_and_marked_sample():
    svc = PrintersService(catalog(), tz="America/Vancouver")
    now = datetime(2026, 3, 4, 20, 0, 5, tzinfo=timezone.utc)
    a, b = svc.status(now), svc.status(now + timedelta(seconds=30))
    assert a["sample"] is True
    assert [p["state"] for p in a["printers"]] == [p["state"] for p in b["printers"]]
    for p in a["printers"]:
        assert p["state"] in STATES and p["detail"]
        assert all(0 <= s["level"] <= 100 for s in p["supplies"] + p["trays"])
    assert sum(a["counts"].values()) == 3


def test_summary_line_and_level():
    s = PrintersService(catalog()).summary(datetime(2026, 3, 4, 20, 0, tzinfo=timezone.utc))
    assert s["product"] == "printers" and s["total"] == 3 and s["sample"] is True
    assert s["level"] in ("ok", "warn", "bad")
    assert "printer" in s["line"]
    json.dumps(s)


def test_empty_catalog_is_idle():
    assert PrintersService({"printers": []}).summary()["level"] == "idle"
