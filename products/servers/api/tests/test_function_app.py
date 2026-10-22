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


# The cloud alarm route takes only an Entra app-only token holding Pulse.Alerts.
jwt = pytest.importorskip("jwt")

import time  # noqa: E402

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from pulse_servers import auth  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
AUD = "11111111-1111-1111-1111-111111111111"
SIGNER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ALARM = {"detail-type": "CloudWatch Alarm State Change",
         "detail": {"alarmName": "x-StatusCheckFailed", "state": {"value": "ALARM"},
                    "configuration": {"metrics": [{"metricStat": {"metric": {
                        "name": "StatusCheckFailed", "dimensions": {"InstanceId": "i-0none"}}}}]}}}


class _Keys:
    def get_signing_key_from_jwt(self, _token):
        return type("K", (), {"key": SIGNER.public_key()})()


@pytest.fixture
def entra(monkeypatch):
    monkeypatch.setenv("PULSE_TENANT_ID", TENANT)
    monkeypatch.setenv("PULSE_INGEST_AUDIENCES", AUD)
    monkeypatch.setattr(auth, "_jwks", lambda tenant: _Keys())


def bearer(*roles):
    now = int(time.time())
    tok = jwt.encode({"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": AUD, "tid": TENANT,
                      "iat": now, "exp": now + 600, "roles": list(roles), "idtyp": "app"}, SIGNER, algorithm="RS256")
    return {"Authorization": f"Bearer {tok}"}


def alarm(headers, body=ALARM):
    return function_app.alerts_cloudwatch(post("/api/alerts/cloudwatch", body, headers))


@pytest.mark.parametrize("headers", [
    {},
    {"X-Pulse-Key": "c" * 32},
    bearer("Pulse.ITS"),
    bearer(auth.INGEST_ROLE),
])
def test_cloudwatch_alerts_refuse_anything_but_an_alerts_token(entra, headers):
    assert alarm(headers).status_code == 401


@pytest.mark.parametrize("body", [ALARM, {"detail": ALARM["detail"]}, ALARM["detail"]])
def test_cloudwatch_alerts_take_an_alerts_token_and_any_event_shape(entra, monkeypatch, body):
    monkeypatch.setenv("PULSE_SOURCE", "live")
    monkeypatch.delenv("PULSE_STORAGE_ACCOUNT", raising=False)
    function_app.store.cache_clear()
    r = alarm(bearer(auth.ALERTS_ROLE), body)
    assert r.status_code == 202
    assert json.loads(r.get_body())["matched"] is False


def test_an_alerts_token_cannot_push_health(entra):
    r = function_app.ingest_health(post("/api/ingest/health", {"contract": "pulse.server-health/1"}, bearer(auth.ALERTS_ROLE)))
    assert r.status_code == 401


def test_runtime_ingest_requires_ingest_role(entra):
    body = {'contract': 'pulse.server-runtimes/1', 'servers': []}
    assert function_app.ingest_runtimes(post('/api/ingest/runtimes', body, bearer(auth.ALERTS_ROLE))).status_code == 401
    assert function_app.ingest_runtimes(post('/api/ingest/runtimes', body, bearer(auth.INGEST_ROLE))).status_code == 401
    assert function_app.ingest_runtimes(post('/api/ingest/runtimes', body, bearer(auth.RUNTIMES_ROLE))).status_code == 202


def test_runtime_ingest_refuses_wrong_contract(entra):
    assert function_app.ingest_runtimes(post('/api/ingest/runtimes', {}, bearer(auth.RUNTIMES_ROLE))).status_code == 400


def test_inventory_publish_requires_its_own_role(monkeypatch):
    from pulse_servers import auth
    roles = []
    def check(req, role):
        roles.append(role)
        raise auth.Unauthorized("denied")
    monkeypatch.setattr(function_app, "_check_token", check)
    response = function_app.ingest_inventory(post("/api/ingest/inventory", {}))
    assert response.status_code == 401
    assert roles == ["Pulse.Inventory"]
