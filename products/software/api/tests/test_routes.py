import importlib.util
import json
from pathlib import Path

import azure.functions as func
import pytest

spec = importlib.util.spec_from_file_location("software_function_app", Path(__file__).parents[1] / "function_app.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def test_routes_are_read_only_and_source_failure_is_explicit(monkeypatch):
    routes = {f.get_trigger().route for f in api.app.get_functions() if f.get_trigger().type == "httpTrigger"}
    assert routes == {"status", "GetRoles"}
    monkeypatch.setattr(api, "runtime", lambda: (_ for _ in ()).throw(RuntimeError("private source error")))
    response = api.status(func.HttpRequest("GET", "/api/status", body=b""))
    assert response.status_code == 503
    assert b"private source error" not in response.get_body()


def test_only_expected_roles_are_mapped():
    req = func.HttpRequest("POST", "/api/GetRoles", body=json.dumps({"claims": [
        {"typ": "roles", "val": "Pulse.Everyone"}, {"typ": "roles", "val": "Pulse.Admin"},
        {"typ": "name", "val": "Pulse.ITS"}]}).encode())
    assert json.loads(api.get_roles(req).get_body()) == {"roles": ["everyone"]}


def test_refresh_failure_cannot_publish_a_successful_empty_snapshot(monkeypatch):
    class Source:
        def rows(self):
            raise RuntimeError("source offline")
    class Snapshot:
        def publish(self, *args, **kwargs):
            pytest.fail("a failed collection must not replace the last snapshot")
    monkeypatch.setattr(api, "runtime", lambda: (None, None, Source(), Snapshot()))
    with pytest.raises(RuntimeError):
        api.refresh_installations(None)


@pytest.mark.parametrize("stamp,expected", [("2000-01-01T00:00:00Z", 503), (None, 503)])
def test_stale_or_missing_snapshot_never_returns_an_empty_success(monkeypatch, stamp, expected):
    class Service:
        def status(self): return {"spaces": []}
    class Snapshot:
        def read(self): return {"fetchedAt": stamp, "rows": []}
    monkeypatch.setattr(api, "runtime", lambda: (Service(), [], None, Snapshot()))
    assert api.status(func.HttpRequest("GET", "/api/status", body=b"")).status_code == expected
