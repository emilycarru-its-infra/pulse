import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pulse_servers import live
from pulse_servers.service import ServersService

EXAMPLE = json.loads((Path(__file__).resolve().parents[2] / "examples" / "catalog.json").read_text())
NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def catalog():
    servers = [dict(s) for s in EXAMPLE["servers"]]
    servers[0]["site24x7_monitor_id"] = "m-1"
    servers[1]["aws_instance_id"] = "i-0abc"
    return {**EXAMPLE, "servers": servers}


def push(servers, generated=NOW):
    return {"contract": live.CONTRACT, "generated_at": iso(generated), "source": "vantage", "servers": servers}


def entry(key, state="up", at=NOW, cpu=10.0):
    return {"key": key, "state": state, "metrics": {"cpu": cpu, "mem": 40, "disk": 55.5},
            "checks": [{"source": "Site24x7", "state": "ok", "at": iso(at)}], "last_check": iso(at)}


def test_unknown_contract_is_refused():
    with pytest.raises(live.ContractError):
        live.parse_push({**push([]), "contract": "pulse.server-health/2"})
    with pytest.raises(live.ContractError):
        live.parse_push(push([{"key": {}, "state": "sideways"}]))
    with pytest.raises(live.ContractError):
        live.parse_push("nope")


def test_matching_prefers_monitor_then_instance_then_hostname():
    cat = catalog()
    m = live.Matcher(cat)
    first, second, third = (s["id"] for s in cat["servers"][:3])
    assert m.match("m-1", "i-0abc", cat["servers"][2]["name"]) == first
    assert m.match("nope", "i-0abc") == second
    host = cat["servers"][2]["name"]
    assert m.match(None, None, host.upper() + ".example.org") == third
    assert m.match("nope", "nope", "nope") is None


def test_push_records_matched_and_counts_unmatched():
    cat = catalog()
    store = live.MemoryStore()
    servers = live.parse_push(push([entry({"site24x7_monitor_id": "m-1"}), entry({"hostname": "nobody"})]))
    assert live.record_push(store, live.Matcher(cat), servers) == {"matched": 1, "unmatched": 1}
    row = store.rows()[cat["servers"][0]["id"]]
    assert row["push"]["metrics"] == {"cpu": 10.0, "mem": 40.0, "disk": 55.5}


def status_of(cat, store, sid, now=NOW):
    status = ServersService(cat, live.LiveSource(store)).status(now)
    return next(s for s in status["servers"] if s["id"] == sid)


def test_live_source_reads_the_push_and_goes_unknown_when_stale():
    cat = catalog()
    store = live.MemoryStore()
    sid = cat["servers"][0]["id"]
    live.record_push(store, live.Matcher(cat), live.parse_push(push([entry({"site24x7_monitor_id": "m-1"}, "degraded")])))
    s = status_of(cat, store, sid)
    assert s["state"] == "degraded" and s["metrics"]["cpu"] == 10.0
    stale = status_of(cat, store, sid, NOW + live.STALE + timedelta(minutes=1))
    assert stale["state"] == "unknown" and stale["metrics"] is None
    never = status_of(cat, store, cat["servers"][2]["id"])
    assert never["state"] in ("unknown", "stopped")


def test_an_alert_newer_than_the_push_wins_and_an_ok_clears_it():
    cat = catalog()
    store = live.MemoryStore()
    m = live.Matcher(cat)
    sid = cat["servers"][1]["id"]
    live.record_push(store, m, live.parse_push(push([entry({"aws_instance_id": "i-0abc"})])))
    down = live.parse_cloudwatch(cloudwatch("ALARM", "web-StatusCheckFailed", NOW + timedelta(minutes=5)), NOW)
    assert live.record_alert(store, m, down) == sid
    s = status_of(cat, store, sid, NOW + timedelta(minutes=6))
    assert s["state"] == "down" and s["metrics"] is None and s["alerts"][0]["severity"] == "critical"
    ok = live.parse_cloudwatch(cloudwatch("OK", "web-StatusCheckFailed", NOW + timedelta(minutes=9)), NOW)
    live.record_alert(store, m, ok)
    s = status_of(cat, store, sid, NOW + timedelta(minutes=10))
    assert s["state"] == "up" and s["alerts"] == []


def cloudwatch(value, alarm, at, instance="i-0abc", metric="StatusCheckFailed"):
    return {"detail-type": "CloudWatch Alarm State Change", "time": iso(at),
            "detail": {"alarmName": alarm, "state": {"value": value, "reason": "Threshold crossed", "timestamp": iso(at)},
                       "configuration": {"metrics": [{"metricStat": {"metric": {
                           "name": metric, "dimensions": {"InstanceId": instance}}}}]}}}


def test_cloudwatch_events_map_to_alert_states():
    assert live.parse_cloudwatch(cloudwatch("ALARM", "x-StatusCheckFailed", NOW), NOW).state == "down"
    assert live.parse_cloudwatch(cloudwatch("ALARM", "x-mem-high", NOW, metric="mem_used_percent"), NOW).state == "warn"
    assert live.parse_cloudwatch(cloudwatch("OK", "x-mem-high", NOW, metric="mem_used_percent"), NOW).state == "ok"
    assert live.parse_cloudwatch(cloudwatch("INSUFFICIENT_DATA", "x", NOW), NOW) is None
    assert live.parse_cloudwatch({"detail-type": "Something else"}, NOW) is None


def test_site24x7_webhooks_parse_and_tolerate_missing_fields():
    a = live.parse_site24x7({"MONITOR_ID": 123, "MONITORNAME": "app-01", "STATUS": "DOWN",
                             "INCIDENT_REASON": "Connection timed out"}, NOW)
    assert (a.state, a.monitor_id, a.text, a.at) == ("down", "123", "Connection timed out", iso(NOW))
    assert live.parse_site24x7({"STATUS": "Trouble"}, NOW).state == "warn"
    assert live.parse_site24x7({"STATUS": "UP", "MONITORNAME": "app-01"}, NOW).hostname == "app-01"
    assert live.parse_site24x7({"MONITORNAME": "app-01"}, NOW) is None
    assert live.parse_site24x7([], NOW) is None
