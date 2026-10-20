from datetime import datetime, timedelta, timezone

import pytest

from zoneinfo import ZoneInfo

from pulse_computers.alerts import Monitor, Policy, devices, stamp

NOW = datetime(2026, 10, 15, 16, tzinfo=timezone.utc)
CATALOG = {"spaces": [{"id": "studio", "name": "Studio", "room": "Room A", "seats": [
    {"hostname": "SEAT-01", "serial": "SAMPLE001", "platform": "mac"},
]}]}
KEY = next(devices(CATALOG))[0]


class State(dict):
    def put(self, key, value):
        self[key] = value


def observed(when=NOW, kind="heartbeat"):
    return {"SEAT-01": {"receivedAt": stamp(when), "type": kind}}


def run(state, latest=None, now=NOW, send=None, **policy):
    cards = []
    result = Monitor(state, send or cards.append, Policy(dry_run=False, **policy)).run(
        CATALOG, latest or {}, now)
    return result, cards


def test_never_reported_gets_a_grace_period_and_no_repeat_same_day():
    state = State()
    assert run(state)[0]["missing"] == 0
    result, cards = run(state, now=NOW + timedelta(days=1))
    assert result["missing"] == 1 and "Never reported" in str(cards)
    assert run(state, now=NOW + timedelta(days=1, minutes=5))[0]["missing"] == 0
    assert run(state, now=NOW + timedelta(days=2))[0]["missing"] == 1


def test_stale_report_alerts_then_fresh_report_recovers_once():
    state = State()
    assert run(state, observed(NOW - timedelta(days=2)))[0]["missing"] == 1
    assert run(state, observed())[0]["recovered"] == 1
    assert run(state, observed())[0]["recovered"] == 0


def test_shutdown_or_merely_less_stale_is_not_recovery():
    state = State({KEY: {"firstObserved": stamp(NOW - timedelta(days=2)), "alerted": True}})
    assert run(state, observed(kind="shutdown"))[0]["recovered"] == 0
    assert run(state, observed(NOW - timedelta(hours=2)))[0]["recovered"] == 0


def test_delivery_failure_retries_without_marking_alert_delivered():
    state = State()
    def fail(card):
        raise OSError("relay unavailable")
    with pytest.raises(OSError):
        run(state, observed(NOW - timedelta(days=2)), send=fail)
    assert not state[KEY].get("alerted")
    assert run(state, observed(NOW - timedelta(days=2)))[0]["missing"] == 1


def test_dry_run_has_no_writes_or_delivery():
    state = State()
    def fail(card):
        raise AssertionError("must not post")
    result = Monitor(state, fail, Policy()).run(CATALOG, observed(NOW - timedelta(days=2)), NOW)
    assert result["missing"] == 1 and result["cards"] and not state


def test_mobile_and_out_of_service_are_excluded():
    catalog = {"spaces": [{**CATALOG["spaces"][0], "seats": [
        {"hostname": "CART", "mobile": True}, {"hostname": "REPAIR", "outOfService": True}]}]}
    assert Monitor(State(), lambda c: None, Policy()).run(catalog, {}, NOW)["cards"] == []


def test_serial_retains_grace_across_hostname_changes():
    state = State({KEY: {"firstObserved": stamp(NOW - timedelta(days=2)), "alerted": False}})
    catalog = {"spaces": [{**CATALOG["spaces"][0], "seats": [
        {**CATALOG["spaces"][0]["seats"][0], "hostname": "RENAMED"}]}]}
    assert Monitor(state, lambda c: None, Policy(dry_run=False)).run(catalog, {}, NOW)["missing"] == 1


def test_local_digest_time_handles_daylight_saving():
    state = State()
    policy = {"timezone": "America/Vancouver"}
    stale = observed(NOW - timedelta(days=2))
    for month, day in [(7, 1), (12, 1)]:
        before = datetime(2026, month, day, 8, 29, tzinfo=ZoneInfo("America/Vancouver")).astimezone(timezone.utc)
        state = State()
        stale = observed(before - timedelta(days=2))
        assert run(state, stale, now=before, **policy)[0]["missing"] == 0
        assert run(state, stale, now=before + timedelta(minutes=1), **policy)[0]["missing"] == 1



def test_empty_catalog_and_future_timestamp_fail_instead_of_claiming_health():
    with pytest.raises(ValueError):
        Monitor(State(), lambda c: None, Policy()).run({"spaces": []}, {}, NOW)
    with pytest.raises(ValueError):
        run(State(), observed(NOW + timedelta(days=1)))


def test_daily_digest_waits_until_next_day_for_newly_overdue_devices():
    state = State()
    run(state, observed())
    assert run(state, observed(NOW - timedelta(days=2)), now=NOW + timedelta(hours=1))[0]["missing"] == 0
    assert run(state, observed(NOW - timedelta(days=2)), now=NOW + timedelta(days=1))[0]["missing"] == 1


def test_partial_delivery_retries_only_unacknowledged_devices():
    catalog = {"spaces": [{**CATALOG["spaces"][0], "seats": [
        {"hostname": f"SEAT-{n:02}", "serial": f"SAMPLE{n:03}"} for n in range(11)]}]}
    latest = {s["hostname"]: {"receivedAt": stamp(NOW - timedelta(days=2)), "type": "heartbeat"}
              for s in catalog["spaces"][0]["seats"]}
    state, sent = State(), []
    def partial(card):
        if sent:
            raise OSError("second batch failed")
        sent.append(card)
    with pytest.raises(OSError):
        Monitor(state, partial, Policy(dry_run=False)).run(catalog, latest, NOW)
    retry = Monitor(state, sent.append, Policy(dry_run=False)).run(catalog, latest, NOW)
    assert retry["missing"] == 1 and len(retry["cards"]) == 1


def test_setup_notice_is_previewed_in_dry_run_and_delivered_only_once():
    state, sent = State(), []
    preview = Monitor(state, sent.append, Policy(announce=True)).run(CATALOG, {}, NOW)
    assert len(preview["cards"]) == 1 and not sent and not state
    monitor = Monitor(state, sent.append, Policy(announce=True, dry_run=False))
    monitor.run(CATALOG, {}, NOW)
    monitor.run(CATALOG, {}, NOW + timedelta(minutes=5))
    assert len(sent) == 1 and state["setup"]["at"] == stamp(NOW)


DROP = {"spaces": [{"id": "lab", "name": "Lab", "room": "Room B", "seats": [
    {"hostname": f"LAB-{n:02}", "serial": f"DROP{n:03}"} for n in range(12)]}]}


def heard(at, kind="heartbeat", active=True, idle=0, seats=range(12)):
    return {f"LAB-{n:02}": {"receivedAt": stamp(at), "type": kind,
                            "session": {"active": active, "locked": False, "idleSeconds": idle}}
            for n in seats}


def drop_run(state, latest, now=NOW, **policy):
    sent = []
    result = Monitor(state, sent.append, Policy(dry_run=False, **policy)).run(DROP, latest, now)
    return result, sent


def test_in_use_seats_going_silent_together_alert_once_then_recover():
    state = State()
    stopped = heard(NOW - timedelta(minutes=20))
    result, sent = drop_run(state, stopped)
    assert result["dropped"] == 12 and len(sent) == 1 and "stopped together" in str(sent[0])
    assert len(sent[0]["body"]) == 14 and "And 2 more." in str(sent[0])
    assert drop_run(state, stopped, now=NOW + timedelta(minutes=5))[1] == []
    back = {**stopped, **heard(NOW + timedelta(minutes=9), seats=range(6))}
    result, sent = drop_run(state, back, now=NOW + timedelta(minutes=10))
    assert len(sent) == 1 and "reporting again" in str(sent[0]) and not state["drop"]["active"]


def test_shutdown_idle_empty_or_recent_seats_are_not_a_drop():
    quiet = NOW - timedelta(minutes=20)
    for latest in [heard(quiet, kind="shutdown"), heard(quiet, idle=1800), heard(quiet, active=False),
                   heard(NOW - timedelta(minutes=5))]:
        assert drop_run(State(), latest)[0]["dropped"] == 0


def test_seats_stopping_hours_apart_are_not_a_drop_and_threshold_holds():
    spread = {}
    for n in range(12):
        spread.update(heard(NOW - timedelta(minutes=20 + 15 * n), seats=[n]))
    assert drop_run(State(), spread)[0]["dropped"] == 0
    assert drop_run(State(), heard(NOW - timedelta(minutes=20), seats=range(9)))[0]["dropped"] == 0
    assert drop_run(State(), heard(NOW - timedelta(minutes=20)), drop_count=0)[0]["dropped"] == 0


def test_drop_is_previewed_in_dry_run_and_failed_delivery_retries():
    state = State()
    preview = Monitor(state, lambda c: None, Policy()).run(DROP, heard(NOW - timedelta(minutes=20)), NOW)
    assert preview["dropped"] == 12 and preview["cards"] and "drop" not in state
    def fail(card):
        raise OSError("relay unavailable")
    with pytest.raises(OSError):
        Monitor(state, fail, Policy(dry_run=False)).run(DROP, heard(NOW - timedelta(minutes=20)), NOW)
    assert "drop" not in state
    assert len(drop_run(state, heard(NOW - timedelta(minutes=20)))[1]) == 1


def test_unrecovered_drop_expires_quietly_into_the_digest():
    state = State()
    drop_run(state, heard(NOW - timedelta(minutes=20)))
    later = NOW + timedelta(hours=25)
    result, sent = drop_run(state, heard(NOW - timedelta(minutes=20)), now=later)
    assert not state["drop"]["active"] and not any("reporting again" in str(c) for c in sent)
