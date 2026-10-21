from datetime import datetime, timedelta, timezone

import pytest

from pulse_printers import live
from pulse_printers.service import PrintersService

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
CATALOG = {"floors": [], "printers": [
    {"id": "lab", "name": "Lab", "model": "M", "room": "R1", "location": "R1", "audience": "students",
     "colour": True, "inkjet": False, "queues": ["Lab-Colour", "Lab-Colour-Staff"]},
    {"id": "office", "name": "Office", "model": "M", "room": "R2", "location": "R2", "audience": "staff",
     "colour": False, "inkjet": False, "queues": ["Office-BW"]},
    {"id": "quiet", "name": "Quiet", "model": "M", "room": "R3", "location": "R3", "audience": "staff",
     "colour": False, "inkjet": False, "queues": ["Quiet"]},
]}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(queue, state="ready", at=NOW, **extra):
    return {"key": {"print_queue": f"PRINTSRV\\{queue}"}, "state": state, "detail": None,
            "held_jobs": 0, "jobs_today": 3, "pages_today": 12, "checked_at": iso(at), **extra}


def push(printers, generated=NOW):
    return {"contract": live.CONTRACT, "generated_at": iso(generated), "source": "data-platform", "printers": printers}


def stored(*entries, now=NOW):
    store = live.MemoryStore()
    result = live.record_push(store, live.Matcher(CATALOG), live.parse_push(push(list(entries)), now))
    return store, result


def status(store, now=NOW, stale=live.STALE):
    s = PrintersService(CATALOG, source=live.LiveSource(store, stale)).status(now)
    return s, {p["id"]: p for p in s["printers"]}


@pytest.mark.parametrize("body", [
    "nope",
    {**push([]), "contract": "pulse.printer-health/2"},
    {**push([]), "generated_at": "yesterday"},
    {**push([]), "printers": {}},
    push([{"state": "ready"}]),
    push([{"key": {"print_queue": ""}, "state": "ready"}]),
    push([{"key": {"print_queue": "x" * 300}, "state": "ready"}]),
    push([entry("Lab-Colour", state="error")]),
    push([entry("Lab-Colour", detail=5)]),
    push([entry("Lab-Colour", held_jobs=-1)]),
    push([entry("Lab-Colour", jobs_today=1.5)]),
    push([entry("Lab-Colour", pages_today=True)]),
    push([entry("Lab-Colour", checked_at="soon")]),
    push([entry("Lab-Colour")] * (live.MAX_PRINTERS + 1)),
])
def test_bad_pushes_are_refused(body):
    with pytest.raises(live.ContractError):
        live.parse_push(body, NOW)


def test_nulls_are_accepted_and_long_detail_is_cut():
    (e,) = live.parse_push(push([entry("Lab-Colour", detail="x" * 500, held_jobs=None, jobs_today=None,
                                       pages_today=None, checked_at=None)]), NOW)
    assert len(e["detail"]) == live.MAX_DETAIL and e["held_jobs"] is None and e["checked_at"] == iso(NOW)


def test_queues_match_the_catalog_by_name_without_the_server():
    m = live.Matcher(CATALOG)
    assert m.match("PRINTSRV\\lab-colour") == "lab"
    assert m.match("lpd://printsrv/Office-BW") == "office"
    assert m.match("Office-BW") == "office"
    assert m.match("PRINTSRV\\Nobody") is None


def test_live_status_joins_posted_state_to_the_catalog():
    store, result = stored(entry("Lab-Colour", "printing", held_jobs=2, jobs_today=5),
                           entry("Lab-Colour-Staff", "attention", detail="Low toner (0%)", held_jobs=1, jobs_today=4),
                           entry("Office-BW", "stopped", detail="Device door is open"),
                           entry("Unknown-Queue"))
    assert result == {"matched": 3, "unmatched": 1, "printers": 2}
    s, p = status(store)
    assert s["sample"] is False
    assert (p["lab"]["state"], p["lab"]["detail"]) == ("attention", "Low toner (0%)")
    assert (p["lab"]["queue"], p["lab"]["jobsToday"], p["lab"]["pagesToday"]) == (3, 9, 24)
    assert p["lab"]["supplies"] is None and p["lab"]["trays"] is None and p["lab"]["stale"] is False
    assert p["lab"]["queues"] == ["Lab-Colour", "Lab-Colour-Staff"]
    assert (p["office"]["state"], p["office"]["detail"]) == ("error", "Device door is open")
    assert p["quiet"]["state"] == "unknown" and p["quiet"]["stale"] is True and p["quiet"]["lastSeen"] is None
    assert s["counts"] == {"ready": 0, "printing": 0, "attention": 1, "error": 1, "offline": 0, "unknown": 1}


def test_a_stale_report_is_unknown_never_its_old_state():
    store, _ = stored(entry("Office-BW", "offline", detail="Not responding"))
    later = NOW + live.STALE + timedelta(seconds=1)
    _, p = status(store, later)
    office = p["office"]
    assert office["state"] == "unknown" and office["stale"] is True
    assert office["detail"] == "No recent report" and office["lastSeen"] == iso(NOW)
    assert office["queue"] is None and office["jobsToday"] is None
    _, p = status(store, NOW + timedelta(minutes=3), stale=timedelta(minutes=2))
    assert p["office"]["state"] == "unknown"


def test_a_fresh_unknown_report_is_unknown_but_not_stale():
    store, _ = stored(entry("Office-BW", "unknown"))
    _, p = status(store)
    assert p["office"]["state"] == "unknown" and p["office"]["stale"] is False


def test_future_dated_reports_are_pulled_back_to_their_arrival():
    later = NOW + timedelta(days=30)
    (e,) = live.parse_push(push([entry("Office-BW", at=later)], generated=later), NOW)
    assert e["checked_at"] == iso(NOW + live.SKEW)
    store, _ = stored(entry("Office-BW", at=later))
    _, p = status(store, NOW + live.SKEW + live.STALE + timedelta(seconds=1))
    assert p["office"]["state"] == "unknown"


def test_a_push_replaces_a_printers_queues():
    store = live.MemoryStore()
    m = live.Matcher(CATALOG)
    live.record_push(store, m, live.parse_push(push([entry("Lab-Colour", "attention"), entry("Lab-Colour-Staff")]), NOW))
    live.record_push(store, m, live.parse_push(push([entry("Lab-Colour")]), NOW))
    assert set(store.rows()["lab"]) == {"lab-colour"}


def test_live_summary_says_when_nothing_reports():
    s = PrintersService(CATALOG, source=live.LiveSource(live.MemoryStore())).summary(NOW)
    assert s["sample"] is False and s["level"] == "warn" and "No recent report" in s["line"]
    store, _ = stored(entry("Lab-Colour"), entry("Office-BW", "offline"))
    s = PrintersService(CATALOG, source=live.LiveSource(store)).summary(NOW)
    assert s["line"] == "1 of 3 printers available, 1 need help, 1 not reporting"
