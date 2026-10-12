import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from pulse_computers.service import ComputersService, ValidationError
from pulse_computers.simulate import Seat
from pulse_computers.store import MemoryStore

NOW = datetime(2027, 1, 4, 17, 0, tzinfo=timezone.utc)
CATALOG = {"spaces": [{"id": "lab", "name": "Lab", "kind": "lab", "seats": [
    {"hostname": "LAB-01", "platform": "mac"},
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
    assert json.loads(path.read_text()) == {"LAB-02": [10.0, 20]}
    for bad in ({}, {"NOPE": [1, 2]}, {"LAB-01": [1]}, {"LAB-01": "1,2"}):
        with pytest.raises(ValueError):
            editor.save(bad)
