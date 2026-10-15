import json

import pytest

func = pytest.importorskip("azure.functions")

import function_app  # noqa: E402
from certs import MAC_CA, header, make, pem  # noqa: E402
from test_service import CATALOG, event  # noqa: E402

DEVICE = "11111111-2222-4333-8444-555555555555"
ca = make(MAC_CA, ca=True)
leaf = make(f"IntuneMDMAgent-{DEVICE}", ca)[0]


@pytest.fixture
def pulse(tmp_path, monkeypatch):
    catalog = json.loads(json.dumps(CATALOG))
    catalog["spaces"][0]["seats"][0]["deviceIds"] = [DEVICE]
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    (tmp_path / "ca.pem").write_text(pem(ca[0]))
    env = {"PULSE_CATALOG_PATH": str(tmp_path / "catalog.json"), "PULSE_DEVICE_CA_FILE": str(tmp_path / "ca.pem")}
    p = function_app.Pulse(env)
    monkeypatch.setattr(function_app, "pulse", lambda: p)
    return p


def post(body, headers=None):
    return func.HttpRequest("POST", "/api/ingest", headers=headers or {}, body=json.dumps(body).encode())


def get(url, params=None):
    return func.HttpRequest("GET", url, body=b"", params=params or {})


def test_ingest_with_device_certificate_then_read_routes(pulse):
    r = function_app.ingest(post(event("LAB-01"), {"X-ARR-ClientCert": header(leaf)}))
    assert r.status_code == 202
    status = json.loads(function_app.status(get("/api/status")).get_body())
    assert status["editable"] is False and status["spaces"][0]["seats"][0]["state"] == "in_use"
    summary = json.loads(function_app.summary(get("/api/summary")).get_body())
    assert summary["product"] == "computers" and summary["seats"] == 3
    lines = function_app.export_events(get("/api/export/events", {"since": "2000-01-01T00:00:00Z"})).get_body()
    assert json.loads(lines.splitlines()[0])["device"]["hostname"] == "LAB-01"
    assert function_app.export_events(get("/api/export/events", {"since": "yesterday"})).status_code == 400


def test_ingest_refusals(pulse):
    cert = {"X-ARR-ClientCert": header(leaf)}
    assert function_app.ingest(post(event("LAB-02"), cert)).status_code == 403
    assert function_app.ingest(post(event("NOT-A-SEAT"), cert)).status_code == 403
    assert function_app.ingest(post(event("LAB-01"))).status_code == 401
    assert function_app.ingest(post(event("LAB-01"), {"X-Pulse-Key": "anything"})).status_code == 401
    assert function_app.ingest(post({"v": 1}, cert)).status_code == 400
    assert function_app.ingest(func.HttpRequest("POST", "/api/ingest", body=b"{")).status_code == 400


def test_ingest_key_when_set(pulse):
    pulse.ingest_key = "pilot"
    assert function_app.ingest(post(event("LAB-02"), {"X-Pulse-Key": "pilot"})).status_code == 202


def test_routes_are_registered(monkeypatch):
    monkeypatch.delenv("PULSE_ALERTS_ENABLED", raising=False)
    functions = function_app.app.get_functions()
    timer = next(f for f in functions if f.get_function_name() == "PulseBeaconAlerts")
    assert timer.get_trigger().type == "timerTrigger"
    timer.get_user_function()(None)
    routes = {f.get_trigger().route for f in functions
              if f.get_trigger().type == "httpTrigger"}
    assert routes == {"ingest", "status", "summary", "export/events", "GetRoles", "positions"}


def test_ingest_refuses_any_path_but_its_own(pulse):
    for url in ["/api/summary/../ingest", "/API/ingest", "/api/%69ngest", "/api/status/%2e%2e/ingest"]:
        req = func.HttpRequest("POST", url, headers={}, body=b"{}")
        assert function_app.ingest(req).status_code == 404, url
    assert function_app._exact_path("https://host.example/api/ingest?x=1", "/api/ingest")


def test_swa_roles_maps_only_known_app_roles():
    claims = [{"typ": "roles", "val": "Pulse.Everyone"}, {"typ": "roles", "val": "Other"},
              {"typ": "name", "val": "Pulse.ITS"},
              {"typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "val": "Pulse.ITS"}]
    assert function_app.swa_roles("Pulse.Everyone=everyone, Pulse.ITS=its", claims) == ["everyone", "its"]
    assert function_app.swa_roles("", claims) == []
