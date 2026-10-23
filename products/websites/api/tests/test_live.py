from datetime import UTC, datetime, timedelta

import pytest
from pulse_websites import live

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
CATALOG = {
    "websites": [
        {"id": "main", "hostname": "www.example.edu", "url": "https://www.example.edu/", "kinsta_site_id": "k-1"},
        {"id": "lib", "url": "https://library.example.edu/news", "site24x7_monitor_id": "77"},
    ]
}


def push(**over):
    site = {
        "key": {"hostname": "www.example.edu", "kinsta_site_id": None, "site24x7_monitor_id": None},
        "state": "degraded",
        "checks": [
            {"source": "Site24x7", "state": "ok", "at": "2026-01-05T14:58:00Z"},
            {"source": "Kinsta", "state": "warn", "at": "2026-01-05T14:50:00Z", "reason": "vulnerable-plugins"},
        ],
        "facts": {"host": "Kinsta", "php_version": "8.3", "plugins_vulnerable": 2, "secret": "x" * 500},
        "last_check": "2026-01-05T14:58:00Z",
    }
    site.update(over)
    return {"contract": live.CONTRACT, "generated_at": "2026-01-05T15:00:00Z", "source": "test", "websites": [site]}


def test_hostname_normalizes_urls():
    assert live.hostname("HTTPS://WWW.Example.edu:443/a?b") == "www.example.edu"
    assert live.hostname("not a host") is None
    assert live.hostname(None) is None


def test_matching_order_and_www():
    m = live.Matcher(CATALOG)
    assert m.match("example.edu") == "main"
    assert m.match("https://library.example.edu") == "lib"
    assert m.match(None, "k-1") == "main"
    assert m.match("unknown.example.edu", None, "77") == "lib"
    assert m.match("unknown.example.edu") is None


def test_push_is_validated():
    with pytest.raises(live.ContractError):
        live.parse_push({"contract": "pulse.server-health/1"}, NOW)
    with pytest.raises(live.ContractError):
        live.parse_push(push(state="sideways"), NOW)


def test_push_keeps_only_known_facts_and_shows_reasons():
    store, m = live.MemoryStore(), live.Matcher(CATALOG)
    assert live.record_push(store, m, live.parse_push(push(), NOW)) == {"matched": 1, "unmatched": 0}
    got = live.LiveSource(store)({"id": "main"}, {}, NOW)
    assert got["state"] == "degraded"
    assert "secret" not in got["facts"] and got["facts"]["plugins_vulnerable"] == 2
    assert any("vulnerability" in a["text"] for a in got["alerts"])


def test_stale_push_reads_unknown_and_newer_alert_wins():
    store, m = live.MemoryStore(), live.Matcher(CATALOG)
    live.record_push(store, m, live.parse_push(push(state="up"), NOW))
    assert live.LiveSource(store)({"id": "main"}, {}, NOW + timedelta(hours=3))["state"] == "unknown"
    alert = live.parse_site24x7({"STATUS": "DOWN", "MONITORURL": "https://www.example.edu/"}, NOW)
    assert live.record_alert(store, m, alert) == "main"
    assert live.LiveSource(store)({"id": "main"}, {}, NOW + timedelta(minutes=1))["state"] == "down"


def test_future_times_are_pulled_back():
    out = live.parse_push(push(last_check="2030-01-01T00:00:00Z"), NOW)
    assert out[0]["last_check"] <= "2026-01-05T15:02:00Z"
