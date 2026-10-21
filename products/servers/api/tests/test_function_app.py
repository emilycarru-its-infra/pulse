import json
from pathlib import Path

import pytest

func = pytest.importorskip("azure.functions")

import function_app  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "catalog.json"


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    for cached in (function_app.service, function_app.catalog, function_app.matcher, function_app.store):
        cached.cache_clear()
    monkeypatch.setenv("PULSE_CATALOG_PATH", str(EXAMPLE))
    monkeypatch.setenv("PULSE_SWA_ROLES", "Pulse.ITS=its")
    yield
    function_app.service.cache_clear()


def get(url):
    return func.HttpRequest("GET", url, body=b"")


def test_status_and_summary_are_marked_as_sample_data():
    status = json.loads(function_app.status(get("/api/status")).get_body())
    summary = json.loads(function_app.summary(get("/api/summary")).get_body())
    assert status["sample"] is True and summary["sample"] is True
    assert len(status["servers"]) == len(json.loads(EXAMPLE.read_text())["servers"])


def test_get_roles_grants_only_mapped_roles():
    body = {"claims": [{"typ": "roles", "val": "Pulse.ITS"}, {"typ": "roles", "val": "Other"}]}
    r = function_app.get_roles(func.HttpRequest("POST", "/api/GetRoles", body=json.dumps(body).encode()))
    assert json.loads(r.get_body()) == {"roles": ["its"]}


def test_an_unknown_source_is_refused(monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "nope")
    with pytest.raises(ValueError):
        function_app.service()


def post(url, body, headers=None):
    return func.HttpRequest("POST", url, body=json.dumps(body).encode(), headers=headers or {})


def test_ingest_without_a_token_is_refused(monkeypatch):
    monkeypatch.setenv("PULSE_TENANT_ID", "t")
    monkeypatch.setenv("PULSE_INGEST_AUDIENCES", "a")
    r = function_app.ingest_health(post("/api/ingest/health", {"contract": "pulse.server-health/1"}))
    assert r.status_code == 401


def test_alerts_need_their_own_key(monkeypatch):
    monkeypatch.setenv("PULSE_SITE24X7_KEY", "s" * 32)
    monkeypatch.setenv("PULSE_CLOUDWATCH_KEY", "c" * 32)
    body = {"STATUS": "DOWN", "MONITORNAME": "nobody"}
    assert function_app.alerts_site24x7(post("/api/alerts/site24x7", body, {"X-Pulse-Key": "c" * 32})).status_code == 401
    ok = function_app.alerts_site24x7(post("/api/alerts/site24x7", body, {"X-Pulse-Key": "s" * 32}))
    assert ok.status_code == 202 and json.loads(ok.get_body())["matched"] is False


def test_the_live_source_is_accepted(monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "live")
    monkeypatch.delenv("PULSE_STORAGE_ACCOUNT", raising=False)
    function_app.store.cache_clear()
    status = json.loads(function_app.status(get("/api/status")).get_body())
    assert status["sample"] is False
    assert {s["state"] for s in status["servers"]} <= {"unknown", "stopped"}
