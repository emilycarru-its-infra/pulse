import json
import time
from pathlib import Path

import pytest

func = pytest.importorskip("azure.functions")
jwt = pytest.importorskip("jwt")

import function_app  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from pulse_websites import auth, live  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "catalog.json"
TENANT = "00000000-0000-0000-0000-000000000001"
AUD = "11111111-1111-1111-1111-111111111111"
SIGNER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    for cached in (function_app.service, function_app.catalog, function_app.matcher, function_app.store):
        cached.cache_clear()
    monkeypatch.setenv("PULSE_CATALOG_PATH", str(EXAMPLE))
    monkeypatch.setenv("PULSE_SWA_ROLES", "Pulse.ITS=its")
    monkeypatch.delenv("PULSE_STORAGE_ACCOUNT", raising=False)
    yield
    for cached in (function_app.service, function_app.store):
        cached.cache_clear()


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


def get(url):
    return func.HttpRequest("GET", url, body=b"")


def post(url, body, headers=None):
    return func.HttpRequest("POST", url, body=json.dumps(body).encode(), headers=headers or {})


def test_status_and_summary_are_marked_as_sample_data():
    status = json.loads(function_app.status(get("/api/status")).get_body())
    summary = json.loads(function_app.summary(get("/api/summary")).get_body())
    assert status["sample"] is True and summary["sample"] is True
    assert len(status["websites"]) == len(json.loads(EXAMPLE.read_text())["websites"])


def test_get_roles_grants_only_mapped_roles():
    body = {"claims": [{"typ": "roles", "val": "Pulse.ITS"}, {"typ": "roles", "val": "Other"}]}
    r = function_app.get_roles(func.HttpRequest("POST", "/api/GetRoles", body=json.dumps(body).encode()))
    assert json.loads(r.get_body()) == {"roles": ["its"]}


def test_an_unknown_source_is_refused(monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "nope")
    with pytest.raises(ValueError):
        function_app.service()


@pytest.mark.parametrize("headers", [{}, {"X-Pulse-Key": "c" * 32}, bearer("Pulse.ITS"), bearer("Pulse.Alerts")])
def test_ingest_refuses_anything_but_an_ingest_token(entra, headers):
    assert function_app.ingest_health(post("/api/ingest/health", {}, headers)).status_code == 401


def test_ingest_records_a_push_the_live_page_shows(entra, monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "live")
    body = {"contract": live.CONTRACT, "generated_at": "2099-01-01T00:00:00Z", "source": "test", "websites": [
        {"key": {"hostname": "www.example.edu"}, "state": "up", "checks": [], "facts": {}},
        {"key": {"hostname": "nowhere.example.net"}, "state": "down", "checks": [], "facts": {}},
    ]}
    r = function_app.ingest_health(post("/api/ingest/health", body, bearer(auth.INGEST_ROLE)))
    assert r.status_code == 202 and json.loads(r.get_body()) == {"matched": 1, "unmatched": 1}
    status = json.loads(function_app.status(get("/api/status")).get_body())
    states = {w["hostname"]: w["state"] for w in status["websites"]}
    assert status["sample"] is False and states["www.example.edu"] == "up"
    assert states["library.example.edu"] == "unknown"


def test_ingest_rejects_a_wrong_contract(entra):
    r = function_app.ingest_health(post("/api/ingest/health", {"contract": "pulse.server-health/1"}, bearer(auth.INGEST_ROLE)))
    assert r.status_code == 400


def test_alerts_need_their_own_key(monkeypatch):
    monkeypatch.setenv("PULSE_SITE24X7_KEY", "s" * 32)
    body = {"STATUS": "DOWN", "MONITORURL": "https://www.example.edu/"}
    assert function_app.alerts_site24x7(post("/api/alerts/site24x7", body, {"X-Pulse-Key": "c" * 32})).status_code == 401
    ok = function_app.alerts_site24x7(post("/api/alerts/site24x7", body, {"X-Pulse-Key": "s" * 32}))
    assert ok.status_code == 202 and json.loads(ok.get_body())["matched"] is True
