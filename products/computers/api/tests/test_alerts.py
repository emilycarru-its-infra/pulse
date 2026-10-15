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
