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
    function_app.service.cache_clear()
    status = json.loads(function_app.status(func.HttpRequest("GET", "/api/status", body=b"")).get_body())
    assert status["printers"][0]["id"] == "p" and status["sample"] is True
    summary = json.loads(function_app.summary(func.HttpRequest("GET", "/api/summary", body=b"")).get_body())
    assert summary["total"] == 1
