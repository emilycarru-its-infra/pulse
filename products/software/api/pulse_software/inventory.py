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


def discovery(status, rows, products, max_age=172800, now=None):
    from .managed import identity

    now = now or datetime.now(timezone.utc)
    seats, spaces = {}, {}
    for space in status["spaces"]:
        spaces[space["id"]] = space
        for seat in space["seats"]:
            seats[seat["hostname"].upper()] = (space["id"], seat)
    aliases = {}
    for product in products:
        for alias in product["aliases"]:
            aliases.setdefault(alias, set()).add(product["id"])
    installed = {p["id"]: {} for p in products}
    recent_hosts = set()
    for row in rows:
        host = row["hostname"].upper()
        if host not in seats or not recent(row["collectedAt"], now, max_age):
            continue
        recent_hosts.add(host)
        matching = aliases.get(identity(row["name"]), set())
        if len(matching) != 1:
            continue
        product_id = next(iter(matching))
        installed[product_id].setdefault(host, set()).add(row["version"])

    def counts(hosts):
        hosts = set(hosts)
        return {"computers": len(hosts), "available": sum(seats[h][1]["state"] == "available" for h in hosts),
                "platforms": sorted({seats[h][1]["platform"] for h in hosts})}

    result = []
    for product in products:
        found = installed[product["id"]]
        locations = []
        for space_id in sorted({seats[h][0] for h in found}):
            space = spaces[space_id]
            hosts = {h for h in found if seats[h][0] == space_id}
            versions = sorted({v for h in hosts for v in found[h]})
            locations.append({"id": space_id, "name": space["name"], "room": space.get("room", ""),
                "floor": space.get("floor", ""), **counts(hosts),
                "versions": [{"version": v, **counts(h for h in hosts if v in found[h])} for v in versions]})
        result.append({**{k: product[k] for k in ("id", "name", "icon", "category", "platforms")},
                       "computers": len(found), "locations": locations,
                       "platforms": sorted(set(product["platforms"]) | {seats[h][1]["platform"] for h in found}),
                       "versions": sorted({v for values in found.values() for v in values})})
    return {"software": result, "inventoryComputers": len(recent_hosts), "catalogComputers": len(seats),
            "inventoryMaxAgeHours": max_age / 3600, "generatedAt": now.isoformat()}


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
