"""ComputersPulse on Azure Functions (Python v2 programming model).

Routes, under the default /api prefix:

    POST /api/ingest                 agents, with a device certificate (or the ingest key, when one is set)
    GET  /api/status                 the page, through the Static Web App
    GET  /api/summary                the hub, through the Static Web App
    GET  /api/export/events?since=   the data warehouse, through the Static Web App

Every route is anonymous at the Functions level. Sign-in for the read routes is the Static
Web App's: it is the only caller App Service authentication lets through, except on
/api/ingest, which is excluded so agents reach it directly and authenticate with their
certificate here (see pulse_computers.deviceauth).

App settings:

    PULSE_CATALOG_PATH     catalog JSON deployed with the app (default catalog.json beside this file)
    PULSE_STORAGE_ACCOUNT  storage account name or table endpoint; unset keeps events in memory (local runs)
    PULSE_EVENTS_TABLE     table of every event (default events)
    PULSE_STATE_TABLE      table of the latest event per seat (default state)
    PULSE_DEVICE_CA_PEM    PEM bundle of the CAs that issue device certificates
    PULSE_DEVICE_CA_FILE   or a file holding it, relative to this file
    PULSE_DEVICE_MAP       where device ids come from; only "catalog" (each seat's deviceIds) for now
    PULSE_INGEST_KEY       shared key accepted in X-Pulse-Key; unset (the default) turns key auth off
    PULSE_EDIT_ROLE        SWA role allowed to edit seats; unset disables editing
    PULSE_LAYOUT_TABLE     durable seat overrides; unset disables editing
    PULSE_TITLE            the product title the summary shows (default Computers)
"""

import base64
import binascii
import json
import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import azure.functions as func

from pulse_computers.deviceauth import CatalogDeviceMap, authorize, load_bundle
from pulse_computers.service import ComputersService, ValidationError
from pulse_computers.store import MemoryStore, TableStore
from pulse_computers.layout import LayoutConflict, MemoryLayouts, TableLayouts, apply_positions, validate_moves

HERE = Path(__file__).resolve().parent
MAX_EVENT = 16_384
MAPS = {"catalog": CatalogDeviceMap}

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


class Pulse:
    """Everything the routes share, built once per worker from the app settings."""

    def __init__(self, env=os.environ):
        catalog_path = HERE / env.get("PULSE_CATALOG_PATH", "catalog.json")
        catalog = json.loads(catalog_path.read_text())
        account = env.get("PULSE_STORAGE_ACCOUNT", "")
        store = (TableStore.from_account(account, env.get("PULSE_EVENTS_TABLE", "events"),
                                         env.get("PULSE_STATE_TABLE", "state")) if account else MemoryStore())
        self.service = ComputersService(catalog, store, env.get("PULSE_TITLE", "Computers"))
        self.edit_role = env.get("PULSE_EDIT_ROLE", "")
        self.layouts = None
        if env.get("PULSE_LAYOUT_TABLE"):
            self.layouts = (TableLayouts.from_account(account, env["PULSE_LAYOUT_TABLE"])
                            if account else MemoryLayouts())
        kind = env.get("PULSE_DEVICE_MAP", "catalog")
        if kind not in MAPS:
            raise ValueError(f"PULSE_DEVICE_MAP must be one of {', '.join(MAPS)}")
        self.devices = MAPS[kind](catalog)
        pem = env.get("PULSE_DEVICE_CA_PEM", "")
        if env.get("PULSE_DEVICE_CA_FILE"):
            pem += "\n" + (HERE / env["PULSE_DEVICE_CA_FILE"]).read_text()
        self.cas = load_bundle(pem)
        self.ingest_key = env.get("PULSE_INGEST_KEY", "")
        if not self.cas and not self.ingest_key:
            logging.warning("no device CAs and no ingest key are configured; every ingest will be refused")


@lru_cache(maxsize=1)
def pulse() -> Pulse:
    return Pulse()


def _json(code: int, obj) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(obj), status_code=code, mimetype="application/json",
                             headers={"Cache-Control": "no-store"})


INGEST_PATH = "/api/ingest"


def _exact_path(url: str, path: str) -> bool:
    """True only for exactly path: no other case, no dot segments, no percent-encoding.
    App Service matches certificate exclusion paths by prefix, so a path that only routes
    here after normalising (/api/summary/../ingest) could arrive without a handshake
    certificate and with a header typed by hand. Such a request is refused."""
    raw = url.split("://", 1)[-1]
    raw = raw[raw.find("/"):] if "/" in raw else "/"
    return raw.split("?", 1)[0] == path


def ingest(req: func.HttpRequest) -> func.HttpResponse:
    if not _exact_path(req.url, INGEST_PATH):
        return _json(404, {"error": "not found"})
    p = pulse()
    body = req.get_body()
    if len(body) > MAX_EVENT:
        return _json(413, {"error": "event too large"})
    try:
        event = json.loads(body)
        p.service.validate(event)
    except (ValueError, ValidationError) as e:
        return _json(400, {"error": str(e)})
    host = event["device"]["hostname"]
    decision = authorize(req.headers, host, p.devices, p.cas, p.ingest_key)
    if not decision.ok:
        logging.warning("ingest refused for %s: %s", host, decision.reason)
        return _json(decision.status, {"error": decision.reason})
    p.service.ingest(event)
    return func.HttpResponse(status_code=202)


def status(req: func.HttpRequest) -> func.HttpResponse:
    p = pulse()
    result = p.service.status()
    if p.layouts is not None:
        positions, version = p.layouts.read()
        apply_positions(result, positions)
        result["layoutVersion"] = version
    return _json(200, {**result, "editable": can_edit(req, p), "editableRooms": False})


def can_edit(req: func.HttpRequest, p: Pulse) -> bool:
    if p.layouts is None or not p.edit_role:
        return False
    try:
        principal = json.loads(base64.b64decode(req.headers.get("x-ms-client-principal", ""), validate=True))
        roles = principal.get("userRoles")
        return (isinstance(principal.get("userId"), str) and bool(principal["userId"])
                and isinstance(roles, list) and "authenticated" in roles and p.edit_role in roles)
    except (ValueError, AttributeError, binascii.Error):
        return False


def save_positions(req: func.HttpRequest) -> func.HttpResponse:
    if not _exact_path(req.url, "/api/positions"):
        return _json(404, {"error": "not found"})
    p = pulse()
    if not can_edit(req, p):
        return _json(403, {"error": "seat editing requires an administrator"})
    if req.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
        return _json(415, {"error": "send application/json"})
    if len(req.get_body()) > MAX_EVENT:
        return _json(413, {"error": "layout changes are too large"})
    version = req.headers.get("If-Match")
    if not version:
        return _json(428, {"error": "load the current layout before editing"})
    try:
        moves = validate_moves(p.service.catalog, json.loads(req.get_body()))
        positions, current = p.layouts.read()
        if version != current:
            raise LayoutConflict
        positions.update(moves)
        saved = p.layouts.write(positions, current)
    except LayoutConflict:
        return _json(409, {"error": "another administrator saved changes; reload and try again"})
    except ValueError as e:
        return _json(400, {"error": str(e)})
    return _json(200, {"layoutVersion": saved})


def summary(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, pulse().service.summary())


def export_events(req: func.HttpRequest) -> func.HttpResponse:
    since = req.params.get("since", "1970-01-01T00:00:00Z")
    try:
        when = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError
    except ValueError:
        return _json(400, {"error": "since must be an RFC 3339 time"})
    body = "".join(json.dumps(e) + "\n" for e in pulse().service.export(when))
    return func.HttpResponse(body, status_code=200, mimetype="application/x-ndjson",
                             headers={"Cache-Control": "no-store"})


# Registered without rebinding the names, so tests call the plain functions.
def swa_roles(mapping: str, claims: list) -> list[str]:
    """The Static Web App roles for a user's Entra app-role claims. mapping is
    PULSE_SWA_ROLES, e.g. "Pulse.Everyone=everyone,Pulse.ITS=its"; claims the mapping does
    not name are dropped."""
    names = dict(pair.split("=", 1) for pair in mapping.split(",") if "=" in pair)
    names = {k.strip(): v.strip() for k, v in names.items()}
    role_types = {"roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"}
    found = {names[c.get("val", "")] for c in claims if isinstance(c, dict)
             and c.get("typ") in role_types and c.get("val") in names}
    return sorted(found)


def get_roles(req: func.HttpRequest) -> func.HttpResponse:
    """Static Web Apps posts the signed-in user's claims here (auth.rolesSource) and grants
    the roles returned. It is behind the link's sign-in like the read routes."""
    try:
        claims = json.loads(req.get_body() or b"{}").get("claims") or []
    except (ValueError, AttributeError):
        claims = []
    return _json(200, {"roles": swa_roles(os.environ.get("PULSE_SWA_ROLES", ""), claims)})


app.route(route="ingest", methods=["POST"])(ingest)
app.route(route="GetRoles", methods=["POST"])(get_roles)
app.route(route="status", methods=["GET"])(status)
app.route(route="positions", methods=["POST"])(save_positions)
app.route(route="summary", methods=["GET"])(summary)
app.route(route="export/events", methods=["GET"])(export_events)


# Register consistently during Azure indexing; opt in to work at invocation time.
@app.function_name(name="PulseBeaconAlerts")
@app.schedule(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def beacon_alerts(timer: func.TimerRequest) -> None:
    if os.environ.get("PULSE_ALERTS_ENABLED", "false").lower() != "true":
        return
    from datetime import timedelta, timezone
    from pulse_computers.alert_store import AlertState
    from pulse_computers.alert_relay import Relay
    from pulse_computers.alerts import Monitor, Policy, parse, stamp

    state = AlertState.from_account(os.environ["PULSE_STORAGE_ACCOUNT"], os.environ["PULSE_ALERTS_TABLE"])
    policy = Policy(
        silence_hours=int(os.environ.get("PULSE_ALERTS_SILENCE_HOURS", "24")),
        timezone=os.environ.get("PULSE_ALERTS_TIMEZONE", "UTC"),
        digest_hour=int(os.environ.get("PULSE_ALERTS_DIGEST_HOUR", "8")),
        digest_minute=int(os.environ.get("PULSE_ALERTS_DIGEST_MINUTE", "30")),
        site_url=os.environ.get("PULSE_ALERTS_SITE_URL", ""),
        dry_run=os.environ.get("PULSE_ALERTS_DRY_RUN", "true").lower() != "false",
        announce=os.environ.get("PULSE_ALERTS_SETUP_NOTICE", "false").lower() == "true",
    )
    relay = Relay(os.environ["PULSE_ALERTS_RELAY_URL"], os.environ["PULSE_ALERTS_RELAY_AUDIENCE"],
                  os.environ["PULSE_ALERTS_CHANNEL"], os.environ.get("PULSE_ALERTS_TEAM", ""))
    now = datetime.now(timezone.utc)
    with state.lease() as acquired:
        if not acquired:
            logging.info("Beacon alert monitor already running")
            return
        try:
            p = pulse()
            result = Monitor(state, relay, policy).run(p.service.catalog, p.service.store.latest(), now)
            logging.warning("Beacon alert check: missing=%d recovered=%d dryRun=%s cards=%d",
                            result["missing"], result["recovered"], policy.dry_run, len(result["cards"]))
            if policy.dry_run:
                logging.warning("Beacon alert dry-run cards: %s", json.dumps(result["cards"]))
        except Exception as error:
            logging.exception("Beacon alert check failed")
            if not policy.dry_run:
                previous = state.get("failure") or {}
                if not previous.get("at") or parse(previous["at"]) <= now - timedelta(days=1):
                    relay({"type": "AdaptiveCard", "version": "1.4", "body": [
                        {"type": "TextBlock", "text": "Computer beacon coverage check failed",
                         "weight": "Bolder", "color": "Attention", "wrap": True},
                        {"type": "TextBlock", "text": f"{type(error).__name__}: check Function telemetry. "
                         "Coverage has not been confirmed.", "wrap": True}]})
                    state.put("failure", {"at": stamp(now)})
            raise
