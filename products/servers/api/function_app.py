"""ServersPulse on Azure Functions (Python v2 programming model).

Routes, under the default /api prefix:

    GET  /api/status     the page, through the Static Web App
    GET  /api/summary    the hub, through the Static Web App
    POST /api/GetRoles   the Static Web App's sign-in (auth.rolesSource)

Every route is anonymous at the Functions level. Sign-in is the Static Web App's: it is the only
caller App Service authentication lets through. Servers report nothing themselves; collectors
read the monitoring systems, so there is no ingest route.

App settings:

    PULSE_CATALOG_PATH   catalog JSON deployed with the app (default catalog.json beside this file)
    PULSE_SOURCE         where health comes from; only "sample" (pulse_servers.simulate) for now
    PULSE_TITLE          the product title the summary shows (default Servers)
    PULSE_SWA_ROLES      Entra app roles to Static Web App roles, e.g. "Pulse.ITS=its"
"""

import json
import os
from functools import lru_cache
from pathlib import Path

import azure.functions as func

from pulse_servers.service import ServersService
from pulse_servers.simulate import health

HERE = Path(__file__).resolve().parent
SOURCES = {"sample": health}

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@lru_cache(maxsize=1)
def service(env=None) -> ServersService:
    env = env or os.environ
    catalog = json.loads(
        (HERE / env.get("PULSE_CATALOG_PATH", "catalog.json")).read_text()
    )
    kind = env.get("PULSE_SOURCE", "sample")
    if kind not in SOURCES:
        raise ValueError(f"PULSE_SOURCE must be one of {', '.join(SOURCES)}")
    if kind == "sample":
        catalog = {**catalog, "sample": True}
    return ServersService(catalog, SOURCES[kind], env.get("PULSE_TITLE", "Servers"))


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


# Registered without rebinding the names, so tests call the plain functions.
app.route(route="GetRoles", methods=["POST"])(get_roles)
app.route(route="status", methods=["GET"])(status)
app.route(route="summary", methods=["GET"])(summary)
