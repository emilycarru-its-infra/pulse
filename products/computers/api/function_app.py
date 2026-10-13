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
    PULSE_TITLE            the product title the summary shows (default Computers)
"""

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
    return _json(200, {**pulse().service.status(), "editable": False})


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
app.route(route="ingest", methods=["POST"])(ingest)
app.route(route="status", methods=["GET"])(status)
app.route(route="summary", methods=["GET"])(summary)
app.route(route="export/events", methods=["GET"])(export_events)
