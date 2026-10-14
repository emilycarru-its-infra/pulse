import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from pulse_computers.service import ComputersService, ValidationError
from pulse_computers.simulate import Seat
from pulse_computers.store import MemoryStore

NOW = datetime(2027, 1, 4, 17, 0, tzinfo=timezone.utc)
CATALOG = {"spaces": [{"id": "lab", "name": "Lab", "kind": "lab", "seats": [
    {"hostname": "LAB-01", "platform": "mac", "name": "Front Desk"},
    {"hostname": "LAB-02", "platform": "mac"},
    {"hostname": "LAB-03", "platform": "windows", "outOfService": True},
]}]}


def event(host, kind="heartbeat", active=True, locked=False, idle=0):
    return {"v": 1, "type": kind, "ts": "2027-01-04T16:59:50Z",
            "device": {"hostname": host, "serial": "X"},
            "session": {"active": active, "locked": locked, "idleSeconds": idle},
            "agent": {"version": "t", "platform": "mac"}}


def test_status_and_summary():
    svc = ComputersService(CATALOG, MemoryStore())
    svc.ingest(event("lab-01"), now=NOW - timedelta(seconds=20))
    space = svc.status(NOW)["spaces"][0]
    assert [s["state"] for s in space["seats"]] == ["in_use", "offline", "out_of_service"]
    assert space["seats"][0]["name"] == "Front Desk" and "name" not in space["seats"][1]
    summary = svc.summary(NOW)
    assert summary["line"] == "0 of 3 seats free in 1 space"
    assert summary["level"] == "warn"


def test_ingest_rejects_personal_data_and_bad_shapes():
    svc = ComputersService(CATALOG, MemoryStore())
    bad = event("LAB-01")
    bad["session"]["user"] = "someone"
    with pytest.raises(ValidationError):
        svc.ingest(bad)
    with pytest.raises(ValidationError):
        svc.ingest({"v": 1})


def test_export_returns_events_since():
    svc = ComputersService(CATALOG, MemoryStore())
    svc.ingest(event("LAB-01", "login"), now=NOW - timedelta(minutes=10))
    svc.ingest(event("LAB-02", "logout", active=False), now=NOW)
    out = svc.export(NOW - timedelta(minutes=1))
    assert [e["type"] for e in out] == ["logout"] and out[0]["receivedAt"] == "2027-01-04T17:00:00Z"


def test_simulated_events_match_the_contract():
    svc = ComputersService(CATALOG, MemoryStore())
    rng = random.Random(1)
    seats = [Seat(f"LAB-0{i}", "mac", rng) for i in (1, 2)]
    for _ in range(200):
        for seat in seats:
            svc.ingest(seat.event(seat.step(150) or "heartbeat"))


def test_seat_editor_saves_positions(tmp_path):
    from pulse_computers.devserver import Positions
    catalog = {"spaces": [{"id": "lab", "seats": [{"hostname": "LAB-01", "x": 1, "y": 1}, {"hostname": "LAB-02"}]}]}
    path = tmp_path / "positions.json"
    editor = Positions(path, catalog)
    editor.save({"lab-02": [10.04, 20]})
    assert catalog["spaces"][0]["seats"][1] == {"hostname": "LAB-02", "x": 10.0, "y": 20}
    assert json.loads(path.read_text()) == {"rooms": {}, "seats": {"LAB-02": [10.0, 20]}}
    for bad in ({}, {"NOPE": [1, 2]}, {"LAB-01": [1]}, {"LAB-01": "1,2"},
                {"LAB-01": [True, 2]}, {"LAB-01": [float("nan"), 2]}, ["LAB-01"]):
        with pytest.raises(ValueError):
            editor.save(bad)


def test_room_editor_moves_and_resizes_rooms(tmp_path):
    from pulse_computers.devserver import Positions
    catalog = {"spaces": [{"id": "lab", "room": "A1100", "label": [50, 50], "box": [0, 0, 100, 100], "seats": [
        {"hostname": "LAB-01", "x": 10, "y": 10}, {"hostname": "LAB-02", "x": 20, "y": 20}]}]}
    path = tmp_path / "positions.json"
    path.write_text('{"LAB-01": [10, 10]}')
    editor = Positions(path, catalog)
    editor.save_room({"space": "lab", "box": [100, 0, 200, 100], "move": [100, 0]})
    lab = catalog["spaces"][0]
    assert lab["box"] == [100, 0, 200, 100]
    assert (lab["seats"][0]["x"], lab["seats"][0]["y"]) == (110, 10)
    assert 100 < lab["seats"][1]["x"] < 200 and lab["seatSize"] > 0
    saved = json.loads(path.read_text())
    assert saved == {"rooms": {"A1100": [100, 0, 200, 100]}, "seats": {"LAB-01": [110, 10]}}
    editor.save_room({"space": "lab", "box": [100, 0, 300, 100], "relayout": True})
    assert json.loads(path.read_text())["seats"] == {}
    for bad in ({"space": "nope", "box": [0, 0, 1, 1]}, {"space": "lab", "box": [5, 0, 1, 1]},
                {"space": "lab", "box": [0, 0, 1]}, {"space": "lab", "box": [0, 0, 1, 1], "move": ["a", 1]}):
        with pytest.raises(ValueError):
            editor.save_room(bad)


@pytest.mark.parametrize("locked", [False, True])
def test_idle_seats_count_as_free_in_status_and_summary(locked):
    svc = ComputersService(CATALOG, MemoryStore())
    svc.ingest(event("LAB-01", locked=locked, idle=900), now=NOW)
    svc.ingest(event("LAB-02", locked=True, idle=899), now=NOW)
    space = svc.status(NOW)["spaces"][0]
    assert [s["state"] for s in space["seats"]] == ["available", "in_use", "out_of_service"]
    assert space["counts"]["available"] == 1
    assert space["counts"]["possibly_free"] == 0
    summary = svc.summary(NOW)
    assert summary["line"] == "1 of 3 seats free in 1 space"
    assert summary["counts"]["available"] == 1
