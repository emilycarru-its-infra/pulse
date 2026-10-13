"""Run the hub and ComputersPulse on one local port, with no cloud and no sign-in.

    python -m pulse_computers.devserver --catalog catalog.json --simulate

Paths: / is the hub, /computers/ the computers page, /computers/api/* the API,
/core/* the shared web shell and /theme/* the site theme (--theme, or the neutral
default). Deployed, each product is its own host behind single sign-on.

With --positions, the computers page gets an Edit seats button: dragging a seat, or a room's
outline or corners, writes plan positions to that JSON file, which the catalog build reads
through [plans] positions.
"""

import argparse
import json
import math
import mimetypes
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pulse_core.catalog import editor_file, grid

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


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class Positions:
    """The seat editor's file, seat positions and room outlines in plan pixels, and the catalog
    seats and rooms it moves."""

    def __init__(self, path: Path, catalog: dict):
        self.path = path
        data = editor_file(json.loads(path.read_text()) if path.is_file() else {})
        self.saved, self.rooms = data["seats"], data["rooms"]
        self.lock = threading.Lock()
        self.spaces = catalog["spaces"]
        self.seats = {seat["hostname"].upper(): seat for space in catalog["spaces"] for seat in space["seats"]}

    def _write(self) -> None:
        text = json.dumps({"rooms": dict(sorted(self.rooms.items())), "seats": dict(sorted(self.saved.items()))},
                          indent=1) + "\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(self.path)

    def save_room(self, body: dict) -> None:
        """Give a room a new outline. Its seats nobody placed are laid out again inside it; with
        move [dx, dy] the placed ones travel with it, and with relayout every seat is laid out again."""
        if not isinstance(body, dict):
            raise ValueError("send {space, box}")
        space = next((s for s in self.spaces if s["id"] == body.get("space")), None)
        if not space or not space.get("room") or "label" not in space:
            raise ValueError("that space has no room on a plan")
        box, move = body.get("box"), body.get("move")
        if not (isinstance(box, list) and len(box) == 4 and all(map(_number, box))
                and box[0] < box[2] and box[1] < box[3]):
            raise ValueError("box must be [x0, y0, x1, y1]")
        if move is not None and not (isinstance(move, list) and len(move) == 2 and all(map(_number, move))):
            raise ValueError("move must be [dx, dy]")
        box = [round(v, 1) for v in box]
        with self.lock:
            self.rooms[space["room"]] = box
            for each in (s for s in self.spaces if s.get("room") == space["room"]):
                each["box"] = box
                seats = each["seats"]
                for seat in seats:
                    if body.get("relayout") is True:
                        self.saved.pop(seat["hostname"], None)
                    elif move and seat["hostname"] in self.saved:
                        seat["x"], seat["y"] = round(seat["x"] + move[0], 1), round(seat["y"] + move[1], 1)
                        self.saved[seat["hostname"]] = [seat["x"], seat["y"]]
                slots, each["seatSize"] = grid(len(seats), box, each["label"])
                for seat, (x, y) in zip(seats, slots):
                    if seat["hostname"] not in self.saved:
                        seat["x"], seat["y"] = x, y
            self._write()

    def save(self, moves: dict) -> None:
        if not isinstance(moves, dict) or not moves:
            raise ValueError("send {hostname: [x, y]}")
        for host, xy in moves.items():
            if host.upper() not in self.seats:
                raise ValueError(f"{host} is not in the catalog")
            if not (isinstance(xy, list) and len(xy) == 2 and all(map(_number, xy))):
                raise ValueError(f"{host}: position must be [x, y]")
        with self.lock:
            for host, (x, y) in moves.items():
                seat = self.seats[host.upper()]
                seat["x"], seat["y"] = round(x, 1), round(y, 1)
                self.saved[seat["hostname"]] = [seat["x"], seat["y"]]
            self._write()


LOCAL = {"localhost", "127.0.0.1"}


def make_handler(service: ComputersService, theme: Path, key: str, assets: Path, positions: Positions | None = None,
                 hub_status: Path = ROOT / "hub" / "sample" / "status.json"):
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

        def _local(self) -> bool:
            # Any other Host is a page on some domain that resolves to this machine (DNS rebinding);
            # turn it away so it cannot read the seats or move them.
            host = urllib.parse.urlsplit("//" + self.headers.get("Host", "")).hostname
            if host in LOCAL:
                return True
            self._json(421, {"error": "use http://localhost"})
            return False

        def do_GET(self):
            if not self._local():
                return
            url = urllib.parse.urlparse(self.path)
            p = url.path
            if p == "/computers/api/status":
                return self._json(200, {**service.status(), "editable": positions is not None})
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
            if p == "/hub/status.json":
                return self._file(hub_status.parent, hub_status.name)
            if p == "/computers":
                self.send_response(301)
                self.send_header("Location", "/computers/")
                return self.end_headers()
            if p.startswith("/computers/catalog/"):
                return self._file(assets, p[len("/computers/catalog/"):])
            if p.startswith("/theme/"):
                return self._file(theme, p[len("/theme/"):])
            for prefix, base in STATIC.items():
                if p.startswith(prefix):
                    return self._file(base, p[len(prefix):])
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._local():
                return
            if self.path in ("/computers/api/positions", "/computers/api/rooms") and positions:
                # A JSON content type forces a CORS preflight, which this server never answers, so
                # another site open in the browser cannot post here.
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self._json(415, {"error": "send application/json"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(min(length, 65_536)))
                    if self.path.endswith("/rooms"):
                        positions.save_room(body)
                    else:
                        positions.save(body)
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._send(204, b"")
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
    parser.add_argument("--assets", help="folder the catalog's plan paths are relative to (default: the catalog's)")
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--key", default="dev", help="ingest key the agents must send")
    parser.add_argument("--simulate", action="store_true", help="feed made-up events for every seat")
    parser.add_argument("--speed", type=float, default=30.0)
    parser.add_argument("--positions", help="JSON file the seat editor saves to; turns the editor on")
    parser.add_argument("--hub-status", default=str(ROOT / "hub" / "sample" / "status.json"),
                        help="the hub's systems and incidents (default: the generic sample)")
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

    editor = Positions(Path(args.positions), catalog) if args.positions else None
    handler = make_handler(service, Path(args.theme), args.key, Path(args.assets or Path(args.catalog).parent), editor,
                           Path(args.hub_status))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    seats = sum(len(s["seats"]) for s in catalog["spaces"])
    print(f"Pulse on http://localhost:{args.port}/  ({len(catalog['spaces'])} spaces, {seats} seats"
          f"{', simulated' if args.simulate else ''}{', seat editor on' if editor else ''})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
