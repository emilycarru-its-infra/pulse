"""ServersPulse on Azure Functions (Python v2 programming model).

Routes, under the default /api prefix:

    GET  /api/status             the page, through the Static Web App
    GET  /api/summary            the hub, through the Static Web App
    POST /api/GetRoles           the Static Web App's sign-in (auth.rolesSource)
    POST /api/ingest/health      the hourly health push (contract pulse.server-health/1)
    POST /api/alerts/site24x7    an uptime service's alert webhook
    POST /api/alerts/cloudwatch  cloud alarm state changes, posted by a federated sender

Every route is anonymous at the Functions level. The read routes answer only through the Static
Web App and its sign-in. The ingest and alert routes are reached directly and authenticate
their callers themselves (pulse_servers.auth): an Entra app-only token holding Pulse.Ingest for
the push and Pulse.Alerts for cloud alarms, and a shared key for the uptime webhook, which cannot
obtain a token.

App settings:

    PULSE_CATALOG_PATH       catalog JSON deployed with the app (default catalog.json beside this file)
    PULSE_SOURCE             where health comes from: "sample" (made up) or "live" (what was posted)
    PULSE_TITLE              the product title the summary shows (default Servers)
    PULSE_SWA_ROLES          Entra app roles to Static Web App roles, e.g. "Pulse.ITS=its"
    PULSE_STORAGE_ACCOUNT    the storage account holding posted health (set by the module)
    PULSE_STATE_TABLE        the table of latest health per server (default state)
    PULSE_EVENTS_TABLE       the append-only table of alerts (default events)
    PULSE_TENANT_ID          the Entra tenant the push token comes from
    PULSE_INGEST_AUDIENCES   comma-separated audiences the push and alarm tokens may carry
    PULSE_SITE24X7_KEY       the shared key of the uptime service's webhook
"""

import json
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import azure.functions as func
from pulse_servers import auth, inventory, live, runtimes
from pulse_servers.service import ServersService
from pulse_servers.simulate import health

HERE = Path(__file__).resolve().parent
SOURCES = ("sample", "live")

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(
        (HERE / os.environ.get("PULSE_CATALOG_PATH", "catalog.json")).read_text()
    )


@lru_cache(maxsize=1)
def store() -> live.Store:
    account = os.environ.get("PULSE_STORAGE_ACCOUNT")
    if not account:
        return live.MemoryStore()
    return live.TableStore.from_account(
        account,
        health_table=os.environ.get("PULSE_STATE_TABLE", "state"),
        history_table=os.environ.get("PULSE_EVENTS_TABLE", "events"),
    )


@lru_cache(maxsize=1)
def runtime_store():
    return runtimes.Store(getattr(store(), "health", None))


@lru_cache(maxsize=1)
def inventory_store():
    return inventory.Store(getattr(store(), "health", None))


@lru_cache(maxsize=1)
def matcher() -> live.Matcher:
    return live.Matcher(catalog())


@lru_cache(maxsize=1)
def service(env=None) -> ServersService:
    env = env or os.environ
    kind = env.get("PULSE_SOURCE", "sample")
    if kind not in SOURCES:
        raise ValueError(f"PULSE_SOURCE must be one of {', '.join(SOURCES)}")
    title = env.get("PULSE_TITLE", "Servers")
    if kind == "sample":
        return ServersService({**catalog(), "sample": True}, health, title)
    return ServersService(
        catalog(), live.LiveSource(store()), title, runtime_store(), inventory_store()
    )


def _json(code: int, obj) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(obj),
        status_code=code,
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


def status(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, service().status())


def summary(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, service().summary())


def swa_roles(mapping: str, claims: list) -> list[str]:
    """The Static Web App roles for a user's Entra app-role claims; claims the mapping does not
    name are dropped."""
    names = dict(pair.split("=", 1) for pair in mapping.split(",") if "=" in pair)
    names = {k.strip(): v.strip() for k, v in names.items()}
    role_types = {
        "roles",
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
    }
    found = {
        names[c.get("val", "")]
        for c in claims
        if isinstance(c, dict) and c.get("typ") in role_types and c.get("val") in names
    }
    return sorted(found)


def get_roles(req: func.HttpRequest) -> func.HttpResponse:
    try:
        claims = json.loads(req.get_body() or b"{}").get("claims") or []
    except (ValueError, AttributeError):
        claims = []
    return _json(
        200, {"roles": swa_roles(os.environ.get("PULSE_SWA_ROLES", ""), claims)}
    )


def _body(req: func.HttpRequest):
    try:
        return json.loads(req.get_body() or b"null")
    except ValueError:
        return None


def _check_token(req: func.HttpRequest, role: str) -> None:
    audiences = [
        a.strip()
        for a in os.environ.get("PULSE_INGEST_AUDIENCES", "").split(",")
        if a.strip()
    ]
    auth.check_ingest_token(
        auth.bearer(req.headers.get("Authorization")),
        os.environ.get("PULSE_TENANT_ID", ""),
        audiences,
        role=role,
    )


def ingest_health(req: func.HttpRequest) -> func.HttpResponse:
    try:
        _check_token(req, auth.INGEST_ROLE)
    except auth.Unauthorized:
        return _json(401, {"error": "unauthorized"})
    try:
        servers = live.parse_push(_body(req), datetime.now(UTC))
    except live.ContractError as e:
        return _json(400, {"error": str(e)})
    return _json(202, live.record_push(store(), matcher(), servers))


def ingest_runtimes(req: func.HttpRequest) -> func.HttpResponse:
    try:
        _check_token(req, auth.RUNTIMES_ROLE)
    except auth.Unauthorized:
        return _json(401, {"error": "unauthorized"})
    try:
        if len(req.get_body()) > 2_000_000:
            raise runtimes.ContractError("runtime body exceeds byte bound")
        rows = runtimes.parse(_body(req), datetime.now(UTC))
        return _json(202, runtimes.record(runtime_store(), catalog(), rows))
    except runtimes.ContractError as error:
        return _json(400, {"error": str(error)})


def ingest_inventory(req: func.HttpRequest) -> func.HttpResponse:
    try:
        _check_token(req, auth.INVENTORY_ROLE)
    except auth.Unauthorized:
        return _json(401, {"error": "unauthorized"})
    try:
        if len(req.get_body()) > 2_000_000:
            raise inventory.ContractError("inventory body exceeds byte bound")
        rows = inventory.parse(_body(req), datetime.now(UTC))
        return _json(202, inventory.record(inventory_store(), catalog(), rows))
    except inventory.ContractError as error:
        return _json(400, {"error": str(error)})


def _alert(req: func.HttpRequest, check, parse) -> func.HttpResponse:
    try:
        check(req)
    except auth.Unauthorized:
        return _json(401, {"error": "unauthorized"})
    alert = parse(_body(req), datetime.now(UTC))
    if alert is None:
        return _json(
            202, {"recorded": False, "reason": "not an alert this route understands"}
        )
    sid = live.record_alert(store(), matcher(), alert)
    return _json(202, {"recorded": sid is not None, "matched": sid is not None})


def alerts_site24x7(req: func.HttpRequest) -> func.HttpResponse:
    return _alert(
        req,
        lambda r: auth.check_key(
            r.headers.get("X-Pulse-Key"), os.environ.get("PULSE_SITE24X7_KEY")
        ),
        live.parse_site24x7,
    )


def alerts_cloudwatch(req: func.HttpRequest) -> func.HttpResponse:
    return _alert(
        req, lambda r: _check_token(r, auth.ALERTS_ROLE), live.parse_cloudwatch
    )


# Registered without rebinding the names, so tests call the plain functions.
app.route(route="GetRoles", methods=["POST"])(get_roles)
app.route(route="status", methods=["GET"])(status)
app.route(route="summary", methods=["GET"])(summary)
app.route(route="ingest/health", methods=["POST"])(ingest_health)
app.route(route="alerts/site24x7", methods=["POST"])(alerts_site24x7)
app.route(route="alerts/cloudwatch", methods=["POST"])(alerts_cloudwatch)

app.route(route="ingest/runtimes", methods=["POST"])(ingest_runtimes)

app.route(route="ingest/inventory", methods=["POST"])(ingest_inventory)
