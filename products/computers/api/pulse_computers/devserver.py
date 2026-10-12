"""Run the hub and ComputersPulse on one local port, with no cloud and no sign-in.

    python -m pulse_computers.devserver --catalog catalog.json --simulate

Paths: / is the hub, /computers/ the computers page, /computers/api/* the API,
/core/* the shared web shell and /theme/* the site theme (--theme, or the neutral
default). Deployed, each product is its own host behind single sign-on.
"""

import argparse
import json
import mimetypes
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import ComputersService, ValidationError
from .simulate import run as simulate
from .store import MemoryStore

ROOT = Path(__file__).resolve().parents[4]
STATIC = {
    "/core/": ROOT / "core" / "web",
    "/computers/": ROOT / "products" / "computers" / "web",
    "/": ROOT / "hub",
}

PRODUCTS = [
    {"id": "computers", "title": "Computers", "href": "/computers/", "summary": "/computers/api/summary",
     "about": "Free seats in labs, open-access stations, kiosks and podiums"},
    {"id": "printers", "title": "Printers", "about": "Printer state, queues and supplies", "soon": True},
    {"id": "servers", "title": "Servers", "about": "Server and service health, for IT staff", "soon": True,
     "restricted": True},
]


def make_handler(service: ComputersService, theme: Path, key: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if not self.path.startswith("/computers/api/ingest"):
                super().log_message(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode())

        def _file(self, base: Path, rel: str) -> None:
            path = (base / (rel or "index.html")).resolve()
            if path.is_dir():
                path = path / "index.html"
            if base.resolve() not in path.parents or not path.is_file():
                return self._json(404, {"error": "not found"})
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._send(200, path.read_bytes(), ctype)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            p = url.path
            if p == "/computers/api/status":
                return self._json(200, service.status())
            if p == "/computers/api/summary":
                return self._json(200, service.summary())
            if p == "/computers/api/export/events":
                since = urllib.parse.parse_qs(url.query).get("since", ["1970-01-01T00:00:00Z"])[0]
                try:
                    when = datetime.fromisoformat(since.replace("Z", "+00:00"))
                except ValueError:
                    return self._json(400, {"error": "since must be an RFC 3339 time"})
                body = "".join(json.dumps(e) + "\n" for e in service.export(when)).encode()
                return self._send(200, body, "application/x-ndjson")
            if p == "/hub/products.json":
                return self._json(200, PRODUCTS)
            if p == "/computers":
                self.send_response(301)
                self.send_header("Location", "/computers/")
                return self.end_headers()
            if p.startswith("/theme/"):
                return self._file(theme, p[len("/theme/"):])
            for prefix, base in STATIC.items():
                if p.startswith(prefix):
                    return self._file(base, p[len(prefix):])
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/computers/api/ingest":
                return self._json(404, {"error": "not found"})
            if self.headers.get("X-Pulse-Key") != key:
                return self._json(401, {"error": "bad ingest key"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                service.ingest(json.loads(self.rfile.read(min(length, 16_384))))
            except (ValueError, ValidationError) as e:
                return self._json(400, {"error": str(e)})
            self._send(202, b"")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", required=True, help="catalog.json from pulse_core.catalog")
    parser.add_argument("--theme", default=str(ROOT / "core" / "web" / "theme"))
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--key", default="dev", help="ingest key the agents must send")
    parser.add_argument("--simulate", action="store_true", help="feed made-up events for every seat")
    parser.add_argument("--speed", type=float, default=30.0)
    args = parser.parse_args()

    with open(args.catalog) as f:
        catalog = json.load(f)
    service = ComputersService(catalog, MemoryStore())
    if args.simulate:
        def send(event):
            try:
                service.ingest(event)
            except ValidationError as e:
                print("simulator sent a bad event:", e)
        threading.Thread(target=simulate, args=(catalog, send, 5.0, args.speed), daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, Path(args.theme), args.key))
    seats = sum(len(s["seats"]) for s in catalog["spaces"])
    print(f"Pulse on http://localhost:{args.port}/  ({len(catalog['spaces'])} spaces, {seats} seats"
          f"{', simulated' if args.simulate else ''})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
