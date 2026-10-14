import base64
import json
from copy import deepcopy
from types import SimpleNamespace

import azure.functions as func
import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError

import function_app
from pulse_computers.layout import LayoutConflict, MemoryLayouts, TableLayouts
from pulse_computers.service import ComputersService
from pulse_computers.store import MemoryStore
from test_service import CATALOG


def principal(roles):
    return base64.b64encode(json.dumps({"userId": "example-admin", "userRoles": roles}).encode()).decode()


def request(method="POST", body=None, version="0", roles=None, url="/api/positions"):
    headers = {"Content-Type": "application/json", "If-Match": version}
    if roles is not None:
        headers["x-ms-client-principal"] = principal(roles)
    return func.HttpRequest(method, url, headers=headers, body=json.dumps(body).encode())


@pytest.fixture
def editor(monkeypatch):
    catalog = deepcopy(CATALOG)
    catalog["floors"] = [{"id": "ground", "width": 400, "height": 300}]
    catalog["spaces"][0]["floor"] = "ground"
    catalog["spaces"][0]["seats"][0].update(x=10, y=20)
    p = SimpleNamespace(service=ComputersService(catalog, MemoryStore()), edit_role="admin", layouts=MemoryLayouts())
    monkeypatch.setattr(function_app, "pulse", lambda: p)
    return p


@pytest.mark.parametrize("roles", [None, [], ["authenticated", "everyone"], ["authenticated", "its"], ["admin"]])
def test_viewers_cannot_edit_or_write(editor, roles):
    r = request(body={"LAB-01": [30, 40]}, roles=roles)
    assert function_app.save_positions(r).status_code == 403
    status = json.loads(function_app.status(request("GET", roles=roles, url="/api/status")).get_body())
    assert status["editable"] is False
    assert editor.layouts.read() == ({}, "0")


def test_malformed_principal_fails_closed(editor):
    for value in ("not base64", base64.b64encode(b"[]").decode(), base64.b64encode(b'{"userId":true,"userRoles":["authenticated","admin"]}').decode()):
        r = func.HttpRequest("POST", "/api/positions", headers={"x-ms-client-principal": value}, body=b"{}")
        assert function_app.save_positions(r).status_code == 403


ADMIN = ["authenticated", "admin"]


def test_edit_survives_new_service_and_catalog_rebuild(editor):
    result = function_app.save_positions(request(body={"lab-01": [31.04, 42]}, roles=ADMIN))
    assert result.status_code == 200
    assert json.loads(result.get_body())["layoutVersion"] == "1"
    editor.service = ComputersService(deepcopy(editor.service.catalog), MemoryStore())
    status = json.loads(function_app.status(request("GET", roles=ADMIN, url="/api/status")).get_body())
    seat = status["spaces"][0]["seats"][0]
    assert (seat["x"], seat["y"]) == (31, 42)
    assert status["editable"] is True and status["editableRooms"] is False
    assert status["layoutVersion"] == "1"
    assert editor.service.catalog["spaces"][0]["seats"][0]["x"] == 10
    editor.service.catalog["spaces"][0]["floor"] = "other"
    status = json.loads(function_app.status(request("GET", url="/api/status")).get_body())
    assert status["spaces"][0]["seats"][0]["x"] == 10


def test_stale_edit_cannot_overwrite_another_admin(editor):
    assert function_app.save_positions(request(body={"LAB-01": [30, 40]}, roles=ADMIN)).status_code == 200
    assert function_app.save_positions(request(body={"LAB-02": [50, 60]}, roles=ADMIN)).status_code == 409
    assert function_app.save_positions(request(body={"LAB-02": [50, 60]}, version="1", roles=ADMIN)).status_code == 200
    positions, version = editor.layouts.read()
    assert set(positions) == {"LAB-01", "LAB-02"} and version == "2"


@pytest.mark.parametrize("body", [{}, [], {"UNKNOWN": [1, 2]}, {"LAB-01": [1]}, {"LAB-01": [True, 2]},
                                 {"LAB-01": [-1, 20]}, {"LAB-01": [401, 20]}, {"LAB-01": [10, 301]},
                                 {"LAB-01": [float("nan"), 2]}, {"LAB-01": [float("inf"), 2]},
                                 {"LAB-01": [1, 2], "LAB-02": [999, 2]},
                                 {"LAB-01": [1, 2], "lab-01": [3, 4]}])
def test_invalid_layout_is_rejected_without_partial_save(editor, body):
    assert function_app.save_positions(request(body=body, roles=ADMIN)).status_code == 400
    assert editor.layouts.read() == ({}, "0")


def test_writes_require_json_size_limit_and_current_version(editor):
    p = principal(ADMIN)
    for headers, body, expected in [({"Content-Type": "text/plain"}, b"{}", 415),
                                    ({"Content-Type": "application/json"}, b"{}", 428),
                                    ({"Content-Type": "application/json", "If-Match": "0"}, b"{", 400),
                                    ({"Content-Type": "application/json"}, b"x" * 16385, 413)]:
        headers["x-ms-client-principal"] = p
        req = func.HttpRequest("POST", "/api/positions", headers=headers, body=body)
        assert function_app.save_positions(req).status_code == expected


def test_write_cannot_use_an_authentication_exclusion_path(editor):
    for url in ("/api/ingest/../positions", "/api/ingest/%2e%2e/positions", "/API/positions", "/api/%70ositions"):
        assert function_app.save_positions(request(body={"LAB-01": [30, 40]}, roles=ADMIN, url=url)).status_code == 404


class Row(dict):
    def __init__(self, value, version):
        super().__init__(value)
        self.metadata = {"etag": str(version)}


class FakeLayoutTable:
    def __init__(self):
        self.row = None
        self.version = 0

    def get_entity(self, partition, key):
        assert (partition, key) == ("layout", "seats")
        if self.row is None:
            raise ResourceNotFoundError
        return Row(self.row, self.version)

    def create_entity(self, row):
        if self.row is not None:
            raise ResourceExistsError
        self.row, self.version = deepcopy(row), 1
        return {"etag": str(self.version)}

    def update_entity(self, row, mode, etag, match_condition):
        assert mode == "replace" and match_condition == MatchConditions.IfNotModified
        if etag != str(self.version):
            raise ResourceModifiedError
        self.row = deepcopy(row)
        self.version += 1
        return {"etag": str(self.version)}


def test_table_layout_persists_across_instances_and_rejects_races():
    table = FakeLayoutTable()
    first, second = TableLayouts(table), TableLayouts(table)
    assert first.read() == ({}, "0")
    first.write({"LAB-01": {"floor": "ground", "x": 30, "y": 40}}, "0")
    with pytest.raises(LayoutConflict):
        second.write({}, "0")
    positions, version = second.read()
    second.write(positions, version)
    with pytest.raises(LayoutConflict):
        first.write({}, version)
    assert TableLayouts(table).read()[0] == positions


def test_editing_is_disabled_without_role_or_storage(editor):
    editor.edit_role = ""
    assert function_app.save_positions(request(body={"LAB-01": [30, 40]}, roles=ADMIN)).status_code == 403
    editor.edit_role = "admin"
    editor.layouts = None
    assert function_app.save_positions(request(body={"LAB-01": [30, 40]}, roles=ADMIN)).status_code == 403
