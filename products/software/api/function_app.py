"""Software discovery, served only through an authenticated Static Web App."""
import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from azure.storage.blob import BlobServiceClient

import azure.functions as func
from azure.identity import DefaultAzureCredential
from pulse_computers.service import ComputersService
from pulse_computers.store import TableStore
from pulse_software.inventory import ReportMate, discovery, recent, InstallationSnapshot
from pulse_software.managed import identity

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# The snapshot refreshes hourly. Browsers keep reading it for two and a half hours, so one
# failed refresh leaves the last good snapshot in place instead of an error page.
SNAPSHOT_MAX_AGE = int(os.environ.get("PULSE_SNAPSHOT_MAX_AGE_SECONDS", "9000"))


@lru_cache(maxsize=1)
def runtime():
    catalog = json.loads((Path(__file__).parent / "catalog.json").read_text())
    credential = DefaultAzureCredential()
    account = os.environ["PULSE_COMPUTERS_STORAGE_ACCOUNT"]
    service = ComputersService(catalog, TableStore.from_account(account, credential=credential))
    products = json.loads((Path(__file__).parent / "managed-software.json").read_text())["products"]
    devices = [s for space in catalog["spaces"] for s in space["seats"]]
    inventory = ReportMate(os.environ["PULSE_REPORTMATE_URL"], os.environ["PULSE_REPORTMATE_SCOPE"], devices, credential)
    blob = BlobServiceClient(f"https://{os.environ['PULSE_STORAGE_ACCOUNT']}.blob.core.windows.net", credential=credential)
    return service, products, inventory, InstallationSnapshot(blob.get_blob_client("software", "installations.json"))


def response(code, body):
    return func.HttpResponse(json.dumps(body), status_code=code, mimetype="application/json",
                             headers={"Cache-Control": "no-store"})


def status(req):
    try:
        service, products, _, snapshot = runtime()
        state = service.status()
        saved = snapshot.read()
        if not recent(saved.get("fetchedAt"), datetime.now(timezone.utc), SNAPSHOT_MAX_AGE):
            raise ValueError("application snapshot is stale")
        result = discovery(state, saved["rows"], products,
                           max_age=int(os.environ.get("PULSE_INSTALL_MAX_AGE_HOURS", "48")) * 3600)
        result["inventoryFetchedAt"] = saved["fetchedAt"]
        return response(200, result)
    except Exception:
        logging.exception("software discovery source read failed")
        return response(503, {"error": "Software availability is temporarily unavailable. Please try again shortly."})


def get_roles(req):
    try:
        claims = json.loads(req.get_body() or b"{}").get("claims") or []
        mapping = {"Pulse.Everyone": "everyone", "Pulse.ITS": "its"}
        role_types = {"roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"}
        roles = sorted({mapping[c.get("val")] for c in claims if isinstance(c, dict)
                        and c.get("typ") in role_types and c.get("val") in mapping})
        return response(200, {"roles": roles})
    except (ValueError, AttributeError, TypeError):
        return response(400, {"roles": []})


app.route(route="status", methods=["GET"])(status)
app.route(route="GetRoles", methods=["POST"])(get_roles)


@app.timer_trigger(schedule="0 0 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def refresh_installations(timer):
    _, products, inventory, snapshot = runtime()
    rows = inventory.rows()
    aliases = {a for p in products for a in p["aliases"]}
    snapshot.publish([row for row in rows if identity(row["name"]) in aliases])
