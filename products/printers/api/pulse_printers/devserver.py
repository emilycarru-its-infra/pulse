"""Run PrintersPulse on one local port, with no cloud and no sign-in.

    python -m pulse_printers.devserver --catalog catalog.json --assets <folder with floorplans/>

Paths: /printers/ is the page, /printers/api/* the API, /core/* the shared web shell,
/theme/* the site theme (--theme, or the neutral default) and /printers/catalog/* the
floorplan images.
"""

import argparse
import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import PrintersService

ROOT = Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--assets", help="folder the catalog's plan images are under (default: the catalog's)")
    parser.add_argument("--theme", default=str(ROOT / "core" / "web" / "theme"))
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--port", type=int, default=8401)
    args = parser.parse_args(argv)
    catalog_path = Path(args.catalog)
    service = PrintersService(json.loads(catalog_path.read_text()), tz=args.timezone)
    static = {
        "/core/": ROOT / "core" / "web",
        "/theme/": Path(args.theme),
        "/printers/catalog/": Path(args.assets or catalog_path.parent),
        "/printers/": ROOT / "products" / "printers" / "web",
    }

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, kind: str):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/printers"):
                self.send_response(302)
                self.send_header("Location", "/printers/")
                return self.end_headers()
            if path == "/printers/api/status":
                return self._send(200, json.dumps(service.status()).encode(), "application/json")
            if path == "/printers/api/summary":
                return self._send(200, json.dumps(service.summary()).encode(), "application/json")
            for prefix, base in static.items():
                if path.startswith(prefix):
                    rel = path[len(prefix):] or "index.html"
                    f = (base / rel).resolve()
                    if f.is_relative_to(base.resolve()) and f.is_file():
                        return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self._send(404, b"not found", "text/plain")

        def log_message(self, *a):
            pass

    print(f"PrintersPulse on http://localhost:{args.port}/printers/")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
