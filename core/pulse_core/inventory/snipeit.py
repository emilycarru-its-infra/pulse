"""Snipe-IT provider. Reads /api/v1/hardware with a bearer token.

Any inventory that serves the same API can use this provider unchanged.
"""

import html
import json
import urllib.parse
import urllib.request
from typing import Callable, Iterable

from .base import Device

PLATFORMS = {"macintosh": "mac", "macos": "mac", "mac": "mac", "windows": "windows"}

Fetch = Callable[[str, dict], dict]


def _http_get(url: str, headers: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
        return json.load(resp)


class SnipeItProvider:
    name = "snipeit"

    def __init__(
        self,
        base_url: str,
        token: str,
        hostname_field: str = "Hostname",
        platform_field: str = "Platform",
        group_field: str = "Fleet",
        device_id_fields: Iterable[str] = (),
        page_size: int = 500,
        fetch: Fetch = _http_get,
        catalog_field: str = "Catalog",
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.hostname_field = hostname_field
        self.platform_field = platform_field
        self.group_field = group_field
        self.catalog_field = catalog_field
        self.device_id_fields = tuple(device_id_fields)
        self.page_size = page_size
        self.fetch = fetch

    def _rows(self) -> Iterable[dict]:
        offset = 0
        while True:
            query = urllib.parse.urlencode({"limit": self.page_size, "offset": offset})
            page = self.fetch(f"{self.base_url}/hardware?{query}", self.headers)
            if page.get("status") == "error":
                raise RuntimeError(f"inventory returned an error: {page.get('messages')}")
            rows = page.get("rows", [])
            yield from rows
            offset += len(rows)
            if not rows or offset >= page.get("total", 0):
                return

    def _custom(self, row: dict, field: str) -> str:
        value = (row.get("custom_fields") or {}).get(field, {}).get("value")
        return html.unescape(value or "").strip()

    def devices(self) -> Iterable[Device]:
        for row in self._rows():
            hostname = self._custom(row, self.hostname_field)
            if not hostname:
                continue
            platform = self._custom(row, self.platform_field).lower()
            yield Device(
                hostname=hostname.upper(),
                asset_tag=row.get("asset_tag") or "",
                serial=row.get("serial") or "",
                platform=PLATFORMS.get(platform, "other"),
                category=((row.get("category") or {}).get("name") or ""),
                location=html.unescape((row.get("location") or {}).get("name") or ""),
                group=self._custom(row, self.group_field),
                catalog=self._custom(row, self.catalog_field),
                deployed=((row.get("status_label") or {}).get("status_meta") == "deployed"),
                name=html.unescape(row.get("name") or "").strip(),
                device_ids=tuple(v.lower() for v in (self._custom(row, f) for f in self.device_id_fields) if v),
            )
