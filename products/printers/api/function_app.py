"""PrintersPulse on Azure Functions (Python v2 programming model).

Routes, under the default /api prefix:

    GET  /api/status     the page, through the Static Web App
    GET  /api/summary    the hub, through the Static Web App
    POST /api/GetRoles   the Static Web App's sign-in (auth.rolesSource)

Every route is anonymous at the Functions level; sign-in is the Static Web App's, the only
caller App Service authentication lets through. The printer states are sample data until a
collector reads the print server (see pulse_printers.service).

App settings:

    PULSE_CATALOG_PATH   catalog JSON deployed with the app (default catalog.json beside this file)
    PULSE_TITLE          the product title the summary shows (default Printers)
    PULSE_TIMEZONE       the campus time zone the sample day follows (default UTC)
    PULSE_SWA_ROLES      Entra app role to Static Web App role, e.g. Pulse.Everyone=everyone
"""

import json
import os
from functools import lru_cache
from pathlib import Path

import azure.functions as func

from pulse_printers.service import PrintersService

HERE = Path(__file__).resolve().parent

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@lru_cache(maxsize=1)
def service() -> PrintersService:
    catalog = json.loads((HERE / os.environ.get("PULSE_CATALOG_PATH", "catalog.json")).read_text())
    return PrintersService(catalog, os.environ.get("PULSE_TITLE", "Printers"), os.environ.get("PULSE_TIMEZONE", "UTC"))


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


app.route(route="GetRoles", methods=["POST"])(get_roles)
app.route(route="status", methods=["GET"])(status)
app.route(route="summary", methods=["GET"])(summary)
