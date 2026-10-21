"""PrintersPulse on Azure Functions (Python v2 programming model).

Routes, under the default /api prefix:

    GET  /api/status          the page, through the Static Web App
    GET  /api/summary         the hub, through the Static Web App
    POST /api/GetRoles        the Static Web App's sign-in (auth.rolesSource)
    POST /api/ingest/health   the print server's state push (contract pulse.printer-health/1)

Every route is anonymous at the Functions level. The read routes answer only through the Static
Web App and its sign-in. The ingest route is reached directly and authenticates its caller
itself (pulse_printers.auth): an Entra app-only token holding Pulse.Ingest.

App settings:

    PULSE_CATALOG_PATH      catalog JSON deployed with the app (default catalog.json beside this file)
    PULSE_SOURCE            where state comes from: "sample" (made up) or "live" (what was posted)
    PULSE_TITLE             the product title the summary shows (default Printers)
    PULSE_TIMEZONE          the campus time zone the sample day follows (default UTC)
    PULSE_SWA_ROLES         Entra app role to Static Web App role, e.g. Pulse.Everyone=everyone
    PULSE_STORAGE_ACCOUNT   the storage account holding posted state (set by the module)
    PULSE_STATE_TABLE       the table of latest state per printer (default state)
    PULSE_STALE_SECONDS     how old a printer's latest report may be before it is unknown (default 600)
    PULSE_TENANT_ID         the Entra tenant the push token comes from
    PULSE_INGEST_AUDIENCES  comma-separated audiences the push token may carry
"""

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import azure.functions as func

from pulse_printers import auth, live
from pulse_printers.service import PrintersService

HERE = Path(__file__).resolve().parent
SOURCES = ("sample", "live")

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads((HERE / os.environ.get("PULSE_CATALOG_PATH", "catalog.json")).read_text())


@lru_cache(maxsize=1)
def store() -> live.Store:
    account = os.environ.get("PULSE_STORAGE_ACCOUNT")
    if not account:
        return live.MemoryStore()
    return live.TableStore.from_account(account, os.environ.get("PULSE_STATE_TABLE", "state"))


@lru_cache(maxsize=1)
def matcher() -> live.Matcher:
    return live.Matcher(catalog())


@lru_cache(maxsize=1)
def service() -> PrintersService:
    kind = os.environ.get("PULSE_SOURCE", "sample")
    if kind not in SOURCES:
        raise ValueError(f"PULSE_SOURCE must be one of {', '.join(SOURCES)}")
    title, tz = os.environ.get("PULSE_TITLE", "Printers"), os.environ.get("PULSE_TIMEZONE", "UTC")
    if kind == "sample":
        return PrintersService(catalog(), title, tz)
    stale = timedelta(seconds=int(os.environ.get("PULSE_STALE_SECONDS") or live.STALE.total_seconds()))
    return PrintersService(catalog(), title, tz, source=live.LiveSource(store(), stale))


def _json(code: int, obj) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(obj), status_code=code, mimetype="application/json",
                             headers={"Cache-Control": "no-store"})


def status(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, service().status())


def summary(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, service().summary())


def swa_roles(mapping: str, claims: list) -> list[str]:
    """The Static Web App roles for a user's Entra app-role claims; see the computers host."""
    names = dict(pair.split("=", 1) for pair in mapping.split(",") if "=" in pair)
    names = {k.strip(): v.strip() for k, v in names.items()}
    role_types = {"roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"}
    found = {names[c.get("val", "")] for c in claims if isinstance(c, dict)
             and c.get("typ") in role_types and c.get("val") in names}
    return sorted(found)


def get_roles(req: func.HttpRequest) -> func.HttpResponse:
    try:
        claims = json.loads(req.get_body() or b"{}").get("claims") or []
    except (ValueError, AttributeError):
        claims = []
    return _json(200, {"roles": swa_roles(os.environ.get("PULSE_SWA_ROLES", ""), claims)})


def ingest_health(req: func.HttpRequest) -> func.HttpResponse:
    audiences = [a.strip() for a in os.environ.get("PULSE_INGEST_AUDIENCES", "").split(",") if a.strip()]
    try:
        auth.check_ingest_token(
            auth.bearer(req.headers.get("Authorization")), os.environ.get("PULSE_TENANT_ID", ""), audiences
        )
    except auth.Unauthorized:
        return _json(401, {"error": "unauthorized"})
    raw = req.get_body() or b""
    if len(raw) > live.MAX_BODY:
        return _json(413, {"error": f"body is larger than {live.MAX_BODY} bytes"})
    try:
        body = json.loads(raw or b"null")
    except ValueError:
        body = None
    try:
        entries = live.parse_push(body, datetime.now(timezone.utc))
    except live.ContractError as e:
        return _json(400, {"error": str(e)})
    return _json(202, live.record_push(store(), matcher(), entries))


# Registered without rebinding the names, so tests call the plain functions.
app.route(route="GetRoles", methods=["POST"])(get_roles)
app.route(route="status", methods=["GET"])(status)
app.route(route="summary", methods=["GET"])(summary)
app.route(route="ingest/health", methods=["POST"])(ingest_health)
