"""Run WebsitesPulse on one local port with sample health, no cloud and no sign-in.

    python -m pulse_websites.devserver --catalog catalog.json [--theme <dir>] [--port 8402]

Paths: / is the websites page, /api/* the API, /core/* the shared web shell and /theme/* the
site theme (--theme, or the neutral default). Deployed, the page is its own host behind single
sign-on.
"""

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import WebsitesService
from .simulate import health

ROOT = Path(__file__).resolve().parents[4]
STATIC = {
    "/core/": ROOT / "core" / "web",
    "/": ROOT / "products" / "websites" / "web",
}


def make_handler(service: WebsitesService, theme: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(
            self, code: int, body: bytes, ctype: str = "application/json"
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, base: Path, rel: str) -> None:
            path = (base / (rel or "index.html")).resolve()
            if not path.is_relative_to(base.resolve()) or not path.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._send(200, path.read_bytes(), ctype)

        def do_GET(self):
            p = self.path.split("?", 1)[0]
            if p == "/api/status":
                return self._send(200, json.dumps(service.status()).encode())
            if p == "/api/summary":
                return self._send(200, json.dumps(service.summary()).encode())
            if p.startswith("/theme/"):
                return self._file(theme, p[len("/theme/") :])
            for prefix, base in STATIC.items():
                if p.startswith(prefix):
                    return self._file(base, p[len(prefix) :])
            self._send(404, b"not found", "text/plain")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--catalog",
        default=str(ROOT / "products" / "websites" / "examples" / "catalog.json"),
    )
    parser.add_argument("--theme", default=str(ROOT / "core" / "web" / "theme"))
    parser.add_argument("--port", type=int, default=8402)
    args = parser.parse_args()
    catalog = {**json.loads(Path(args.catalog).read_text()), "sample": True}
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(
            WebsitesService(catalog, health),
            Path(args.theme),
        ),
    )
    print(f"WebsitesPulse on http://localhost:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
