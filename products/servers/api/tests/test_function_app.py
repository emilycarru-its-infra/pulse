import json
from pathlib import Path

import pytest

func = pytest.importorskip("azure.functions")

import function_app  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "catalog.json"


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    function_app.service.cache_clear()
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
