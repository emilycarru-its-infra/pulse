"""Minimized application observations for computers in the shared catalog."""
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def app_id(name):
    return hashlib.sha256(name.strip().casefold().encode()).hexdigest()[:20]


def recent(stamp, now, max_age):
    try:
        age = (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds()
        return -300 <= age <= max_age
    except (ValueError, TypeError, AttributeError):
        return False


class ReportMate:
    def __init__(self, url, scope, devices, credential, fetch=None, ttl=300):
        if not url.startswith("https://"):
            raise ValueError("ReportMate requires HTTPS")
        self.url, self.scope = url.rstrip("/"), scope
        devices = [d if isinstance(d, dict) else {"hostname": d} for d in devices]
        self.serial_hosts = {d["serial"].strip().upper(): d["hostname"].strip().upper()
                             for d in devices if d.get("serial")}
        self.name_hosts = {d["hostname"].strip().upper() for d in devices if not d.get("serial")}
        self.identifiers = sorted({d.get("serial") or d["hostname"] for d in devices})
        self.credential = credential
        self.fetch = fetch or self._fetch
        self.ttl = ttl
        self._lock = threading.Lock()
        self._rows, self._expires = [], 0

    def _fetch(self, params):
        token = self.credential.get_token(self.scope).token
        req = Request(self.url + "/api/v1/applications?" + urlencode(params),
                      headers={"Authorization": "Bearer " + token})
        with urlopen(req, timeout=30) as response:
            return json.load(response)

    def rows(self):
        with self._lock:
            if time.monotonic() < self._expires:
                return self._rows
            rows = []
            allowed = self.name_hosts | set(self.serial_hosts.values())
            for start in range(0, len(self.identifiers), 25):
                offset = 0
                while True:
                    page = self.fetch({"deviceNames": ",".join(self.identifiers[start:start + 25]),
                                       "limit": 5000, "offset": offset, "deviceLimit": 5000})
                    if not isinstance(page, list):
                        raise ValueError("ReportMate returned an invalid applications page")
                    for row in page:
                        serial = str(row.get("serialNumber") or "").strip().upper()
                        name_host = str(row.get("deviceName", "")).strip().upper()
                        host = self.serial_hosts.get(serial) or (name_host if name_host in self.name_hosts else "")
                        name = str(row.get("name") or "").strip()
                        if host in allowed and name and name != "Unknown Application":
                            rows.append({"hostname": host, "id": app_id(name), "name": name,
                                         "version": str(row.get("version") or "Unknown"),
                                         "collectedAt": row.get("collectedAt")})
                    if len(page) < 5000:
                        break
                    offset += len(page)
                    if offset >= 500000:
                        raise ValueError("ReportMate applications exceeded the pagination bound")
            self._rows, self._expires = rows, time.monotonic() + self.ttl
            return rows


def discovery(status, rows, selected="", version="", max_age=172800, now=None):
    now = now or datetime.now(timezone.utc)
    allowed = {s["hostname"].upper() for space in status["spaces"] for s in space["seats"]}
    apps, matches, observed = {}, {}, set()
    for row in rows:
        host = row["hostname"].upper()
        if host not in allowed:
            continue
        fresh = recent(row["collectedAt"], now, max_age)
        item = apps.setdefault(row["id"], {"id": row["id"], "name": row["name"],
                                           "versions": set(), "hosts": set(), "staleHosts": set()})
        item["versions"].add(row["version"])
        item["hosts" if fresh else "staleHosts"].add(host)
        if fresh:
            observed.add(host)
            if row["id"] == selected and (not version or version == row["version"]):
                matches.setdefault(host, []).append({"version": row["version"], "collectedAt": row["collectedAt"]})
    for space in status["spaces"]:
        for seat in space["seats"]:
            seat["softwareMatch"] = seat["hostname"].upper() in matches if selected else True
            if selected:
                seat["installations"] = matches.get(seat["hostname"].upper(), [])
    index = [{"id": a["id"], "name": a["name"], "versions": sorted(a["versions"]),
              "computers": len(a["hosts"]), "staleComputers": len(a["staleHosts"] - a["hosts"])}
             for a in sorted(apps.values(), key=lambda a: a["name"].casefold())]
    status.update({"software": index, "selectedSoftware": selected, "inventoryComputers": len(observed),
                   "catalogComputers": len(allowed), "inventoryMaxAgeHours": max_age / 3600,
                   "editable": False, "editableRooms": False})
    return status


class InstallationSnapshot:
    """Share a parsed snapshot across concurrent readers in one worker."""
    def __init__(self, blob, ttl=30):
        self.blob, self.ttl = blob, ttl
        self._lock = threading.Lock()
        self._saved, self._expires = None, 0

    def read(self):
        with self._lock:
            if time.monotonic() >= self._expires:
                saved = json.loads(self.blob.download_blob().readall())
                if not isinstance(saved, dict) or not isinstance(saved.get("rows"), list):
                    raise ValueError("invalid application snapshot")
                self._saved, self._expires = saved, time.monotonic() + self.ttl
            return self._saved

    def publish(self, rows):
        saved = {"fetchedAt": datetime.now(timezone.utc).isoformat(), "rows": rows}
        with self._lock:
            self.blob.upload_blob(json.dumps(saved, separators=(",", ":")), overwrite=True)
            self._saved, self._expires = saved, time.monotonic() + self.ttl
