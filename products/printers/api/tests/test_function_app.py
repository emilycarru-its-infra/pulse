import json

import azure.functions as func

import function_app


def test_roles_map_only_named_app_roles(monkeypatch):
    monkeypatch.setenv("PULSE_SWA_ROLES", "Pulse.Everyone=everyone")
    claims = [{"typ": "roles", "val": "Pulse.Everyone"}, {"typ": "roles", "val": "Other"}]
    req = func.HttpRequest("POST", "/api/GetRoles", body=json.dumps({"claims": claims}).encode())
    assert json.loads(function_app.get_roles(req).get_body()) == {"roles": ["everyone"]}


def test_status_and_summary_read_the_catalog(tmp_path, monkeypatch):
    (tmp_path / "catalog.json").write_text(json.dumps({"floors": [], "printers": [
        {"id": "p", "name": "P", "model": "M", "room": "R", "location": "R", "audience": "staff",
         "colour": False, "inkjet": False, "queues": []}]}))
    monkeypatch.setattr(function_app, "HERE", tmp_path)
    monkeypatch.delenv("PULSE_SOURCE", raising=False)
    function_app.service.cache_clear()
    function_app.catalog.cache_clear()
    status = json.loads(function_app.status(func.HttpRequest("GET", "/api/status", body=b"")).get_body())
    assert status["printers"][0]["id"] == "p" and status["sample"] is True
    summary = json.loads(function_app.summary(func.HttpRequest("GET", "/api/summary", body=b"")).get_body())
    assert summary["total"] == 1


# The live path: a push with an Entra app-only token holding Pulse.Ingest.
import time  # noqa: E402

import pytest  # noqa: E402

jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from pulse_printers import auth, live  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
AUD = "api://printers-example"
SIGNER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CATALOG = {"floors": [], "printers": [
    {"id": "p", "name": "P", "model": "M", "room": "R", "location": "R", "audience": "staff",
     "colour": False, "inkjet": False, "queues": ["Lab-BW"]},
    {"id": "q", "name": "Q", "model": "M", "room": "R", "location": "R", "audience": "staff",
     "colour": False, "inkjet": False, "queues": ["Other"]}]}


class _Keys:
    def get_signing_key_from_jwt(self, _token):
        return type("K", (), {"key": SIGNER.public_key()})()


@pytest.fixture
def live_app(tmp_path, monkeypatch):
    (tmp_path / "catalog.json").write_text(json.dumps(CATALOG))
    monkeypatch.setattr(function_app, "HERE", tmp_path)
    monkeypatch.setenv("PULSE_SOURCE", "live")
    monkeypatch.setenv("PULSE_TENANT_ID", TENANT)
    monkeypatch.setenv("PULSE_INGEST_AUDIENCES", f"other, {AUD}")
    monkeypatch.delenv("PULSE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.setattr(auth, "_jwks", lambda tenant: _Keys())
    for cached in (function_app.service, function_app.catalog, function_app.matcher, function_app.store):
        cached.cache_clear()
    yield
    for cached in (function_app.service, function_app.catalog, function_app.matcher, function_app.store):
        cached.cache_clear()


def bearer(*roles, **claims):
    now = int(time.time())
    tok = jwt.encode({"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": AUD, "tid": TENANT,
                      "iat": now, "exp": now + 600, "roles": list(roles), "idtyp": "app", **claims},
                     SIGNER, algorithm="RS256")
    return {"Authorization": f"Bearer {tok}"}


def ingest(headers, body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return function_app.ingest_health(func.HttpRequest("POST", "/api/ingest/health", body=raw, headers=headers))


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def body():
    return {"contract": live.CONTRACT, "generated_at": now_iso(), "source": "data-platform", "printers": [
        {"key": {"print_queue": "PRINTSRV\\Lab-BW"}, "state": "attention", "detail": "Low toner (0%)",
         "held_jobs": 2, "jobs_today": 10, "pages_today": 40, "checked_at": now_iso()}]}


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Basic abc"},
    bearer("Pulse.ITS"),
    bearer(auth.INGEST_ROLE, aud="api://someone-else"),
    bearer(auth.INGEST_ROLE, idtyp="user"),
])
def test_ingest_refuses_anything_but_an_ingest_token(live_app, headers):
    assert ingest(headers, body()).status_code == 401


def test_ingest_refuses_when_not_configured(live_app, monkeypatch):
    monkeypatch.delenv("PULSE_INGEST_AUDIENCES")
    assert ingest(bearer(auth.INGEST_ROLE), body()).status_code == 401


def test_ingest_refuses_bad_and_oversized_bodies(live_app):
    assert ingest(bearer(auth.INGEST_ROLE), b"not json").status_code == 400
    assert ingest(bearer(auth.INGEST_ROLE), {**body(), "contract": "pulse.server-health/1"}).status_code == 400
    assert ingest(bearer(auth.INGEST_ROLE), b" " * (live.MAX_BODY + 1)).status_code == 413


def test_a_push_shows_on_the_live_page(live_app):
    get = lambda path: json.loads(getattr(function_app, path)(func.HttpRequest("GET", f"/api/{path}", body=b"")).get_body())  # noqa: E731
    before = get("status")
    assert before["sample"] is False and {p["state"] for p in before["printers"]} == {"unknown"}
    r = ingest(bearer(auth.INGEST_ROLE), body())
    assert r.status_code == 202 and json.loads(r.get_body()) == {"matched": 1, "unmatched": 0, "printers": 1}
    function_app.service.cache_clear()  # a fresh read, past the source's short row cache
    status = get("status")
    p = {x["id"]: x for x in status["printers"]}
    assert (p["p"]["state"], p["p"]["detail"], p["p"]["queue"]) == ("attention", "Low toner (0%)", 2)
    assert p["q"]["state"] == "unknown" and p["q"]["stale"] is True
    summary = get("summary")
    assert summary["sample"] is False and summary["counts"]["unknown"] == 1


def test_an_unknown_source_is_refused(monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "nope")
    function_app.service.cache_clear()
    with pytest.raises(ValueError):
        function_app.service()
    function_app.service.cache_clear()
