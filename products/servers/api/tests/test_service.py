import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pulse_servers.service import ServersService
from pulse_servers.simulate import health

CATALOG = json.loads((Path(__file__).resolve().parents[2] / "examples" / "catalog.json").read_text())
NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def test_health_is_the_same_for_every_caller_at_the_same_time():
    server = CATALOG["servers"][0]
    location = CATALOG["locations"][0]
    assert health(server, location, NOW) == health(server, location, NOW)


def test_a_stopped_server_has_no_checks_and_never_worsens_its_group():
    service = ServersService(CATALOG, health)
    status = service.status(NOW)
    stopped = next(s for s in status["servers"] if s.get("stopped"))
    assert stopped["state"] == "stopped" and stopped["checks"] == [] and stopped["alerts"] == []
    files = next(g for g in status["services"] if g["id"] == "files")
    assert files["counts"]["stopped"] == 1


def test_every_server_gets_a_known_state_and_checks_from_its_location_sources():
    status = ServersService(CATALOG, health).status(NOW)
    sources = {loc["id"]: loc["sources"] for loc in CATALOG["locations"]}
    for s in status["servers"]:
        assert s["state"] in ("up", "degraded", "down", "stopped")
        if s["state"] != "stopped":
            assert [c["source"] for c in s["checks"]] == sources[s["location"]]


def test_over_a_day_some_servers_have_problems_and_most_are_up():
    service = ServersService(CATALOG, health)
    seen = {"up": 0, "degraded": 0, "down": 0}
    for i in range(72):
        for s in service.status(NOW + timedelta(minutes=20 * i))["servers"]:
            if s["state"] in seen:
                seen[s["state"]] += 1
    assert seen["degraded"] and seen["down"]
    assert seen["up"] > 0.85 * sum(seen.values())


def test_a_problem_carries_an_alert_and_the_group_takes_the_worst_level():
    service = ServersService(CATALOG, health)
    for i in range(72):
        status = service.status(NOW + timedelta(minutes=20 * i))
        bad = [s for s in status["servers"] if s["state"] in ("degraded", "down")]
        if bad:
            assert all(s["alerts"] for s in bad)
            loc = next(loc for loc in status["locations"] if loc["id"] == bad[0]["location"])
            assert loc["level"] in ("warn", "bad")
            return
    raise AssertionError("no problem in a day")


def test_summary_counts_running_servers_only():
    summary = ServersService(CATALOG, health).summary(NOW)
    assert summary["product"] == "servers"
    assert summary["servers"] == len(CATALOG["servers"]) - 1
    assert summary["level"] in ("ok", "warn", "bad")
