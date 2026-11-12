from datetime import datetime, timedelta, timezone

from pulse_printers import alerts, live

T0 = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
CATALOG = {
    "floors": [],
    "printers": [
        {
            "id": "lab",
            "name": "Lab",
            "room": "R1",
            "location": "Level 1",
            "queues": ["Lab-Colour", "Lab-BW"],
        },
        {
            "id": "office",
            "name": "Office",
            "room": "R2",
            "location": "Level 2",
            "queues": ["Office-BW"],
        },
    ],
}
POLICY = alerts.Policy(hold=timedelta(minutes=5), clear=timedelta(minutes=2))


def entries(states, at):
    """states: {queue: (state, detail)}"""
    body = {
        "contract": live.CONTRACT,
        "generated_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "printers": [
            {"key": {"print_queue": f"SRV\\{q}"}, "state": s, "detail": d}
            for q, (s, d) in states.items()
        ],
    }
    return live.parse_push(body, at)


def run(store, states, minutes):
    at = T0 + timedelta(minutes=minutes)
    return alerts.record_alerts(
        store, live.Matcher(CATALOG), entries(states, at), at, POLICY
    )


def test_a_fault_opens_only_after_the_hold():
    store = alerts.MemoryAlertStore()
    assert run(store, {"Office-BW": ("attention", "Paper jam")}, 0) == []
    assert store.records()["office"]["phase"] == "pending"
    assert run(store, {"Office-BW": ("attention", "Paper jam")}, 4) == []
    events = run(store, {"Office-BW": ("attention", "Paper jam")}, 6)
    assert events == [
        {
            "printer": "office",
            "event": "opened",
            "state": "attention",
            "detail": "Paper jam",
        }
    ]
    rec = store.records()["office"]
    assert rec["phase"] == "open" and rec["since"] == "2026-01-05T15:00:00Z"


def test_a_fault_cleared_within_the_hold_never_opens():
    store = alerts.MemoryAlertStore()
    run(store, {"Office-BW": ("attention", "Paper jam")}, 0)
    assert run(store, {"Office-BW": ("ready", None)}, 2) == []
    assert run(store, {"Office-BW": ("attention", "Paper jam")}, 3) == []
    assert store.records()["office"]["since"] == "2026-01-05T15:03:00Z"


def test_recovery_closes_after_the_clear_period_and_flapping_keeps_one_alert():
    store = alerts.MemoryAlertStore()
    run(store, {"Office-BW": ("offline", "Offline")}, 0)
    run(store, {"Office-BW": ("offline", "Offline")}, 6)
    assert run(store, {"Office-BW": ("ready", None)}, 8) == []
    assert store.records()["office"]["phase"] == "recovering"
    assert run(store, {"Office-BW": ("offline", "Offline")}, 9) == []
    assert store.records()["office"]["phase"] == "open"
    run(store, {"Office-BW": ("ready", None)}, 10)
    events = run(store, {"Office-BW": ("printing", None)}, 12)
    assert [e["event"] for e in events] == ["closed"]
    rec = store.records()["office"]
    assert rec["phase"] == "clear"
    assert rec["last_closed"]["opened_at"] == "2026-01-05T15:06:00Z"
    assert rec["last_closed"]["closed_at"] == "2026-01-05T15:12:00Z"


def test_a_changed_fault_updates_the_open_alert():
    store = alerts.MemoryAlertStore()
    run(store, {"Office-BW": ("attention", "Paper jam")}, 0)
    run(store, {"Office-BW": ("attention", "Paper jam")}, 6)
    events = run(store, {"Office-BW": ("attention", "Door open")}, 8)
    assert [e["event"] for e in events] == ["changed"]
    assert store.records()["office"]["opened_at"] == "2026-01-05T15:06:00Z"
    assert run(store, {"Office-BW": ("attention", "Door open")}, 10) == []


def test_unknown_and_missing_reports_change_nothing():
    store = alerts.MemoryAlertStore()
    run(store, {"Office-BW": ("attention", "Paper jam")}, 0)
    run(store, {"Office-BW": ("attention", "Paper jam")}, 6)
    before = store.records()
    assert run(store, {"Office-BW": ("unknown", None)}, 20) == []
    assert run(store, {}, 30) == []
    assert store.records() == before


def test_a_printer_takes_its_worst_queue():
    store = alerts.MemoryAlertStore()
    run(store, {"Lab-Colour": ("ready", None), "Lab-BW": ("stopped", "Paused")}, 0)
    run(store, {"Lab-Colour": ("ready", None), "Lab-BW": ("stopped", "Paused")}, 5)
    assert store.records()["lab"]["state"] == "error"


def test_stopped_reads_as_the_page_error_state():
    states = alerts.printer_states(
        live.Matcher(CATALOG), entries({"Office-BW": ("stopped", "Paused")}, T0)
    )
    assert states == {"office": ("error", "Paused")}


def test_listing_orders_open_alerts_and_keeps_recent_closures_for_a_day():
    store = alerts.MemoryAlertStore()
    run(
        store,
        {"Office-BW": ("attention", "Toner low"), "Lab-BW": ("offline", "Offline")},
        0,
    )
    run(
        store,
        {"Office-BW": ("attention", "Toner low"), "Lab-BW": ("offline", "Offline")},
        6,
    )
    out = alerts.listing(store, CATALOG, T0 + timedelta(minutes=7), POLICY)
    assert [a["id"] for a in out["open"]] == ["lab", "office"]
    assert out["open"][0]["location"] == "Level 1" and out["recent"] == []
    run(store, {"Office-BW": ("ready", None)}, 8)
    run(store, {"Office-BW": ("ready", None)}, 10)
    out = alerts.listing(store, CATALOG, T0 + timedelta(minutes=11), POLICY)
    assert [a["id"] for a in out["open"]] == ["lab"]
    assert (
        out["recent"][0]["id"] == "office"
        and out["recent"][0]["closedAt"] == "2026-01-05T15:10:00Z"
    )
    later = alerts.listing(store, CATALOG, T0 + timedelta(hours=25), POLICY)
    assert later["recent"] == []


def test_unchanged_records_are_not_rewritten():
    class Counting(alerts.MemoryAlertStore):
        def __init__(self):
            super().__init__()
            self.writes = 0

        def put(self, printer_id, record):
            self.writes += 1
            super().put(printer_id, record)

    store = Counting()
    run(store, {"Office-BW": ("ready", None)}, 0)
    assert store.writes == 0
    run(store, {"Office-BW": ("attention", "Paper jam")}, 1)
    run(store, {"Office-BW": ("attention", "Paper jam")}, 2)
    assert store.writes == 1
