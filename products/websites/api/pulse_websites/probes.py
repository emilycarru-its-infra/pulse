"""Bounded, unauthenticated reachability checks of operator-owned catalog URLs."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(website, *, opener=None, clock=time.monotonic, now=None):
    url = website.get("url", "")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port
    ):
        return None
    started = clock()
    code = None
    try:
        response = (opener or build_opener(NoRedirect())).open(
            Request(
                url,
                headers={"User-Agent": "Pulse-Availability/1", "Range": "bytes=0-0"},
            ),
            timeout=10,
        )
        code = response.status
        response.close()
    except HTTPError as error:
        code = error.code
        error.close()
    except (URLError, TimeoutError, OSError):
        pass
    state = (
        "ok"
        if code is not None and 200 <= code < 400
        else "warn"
        if code in (401, 403, 429)
        else "down"
    )
    return {
        "source": "HTTP",
        "state": state,
        "at": (now or datetime.now(UTC)).isoformat(),
        "http_status": code,
        "response_ms": round((clock() - started) * 1000),
        "reason": "restricted"
        if code in (401, 403)
        else "rate-limited"
        if code == 429
        else None,
    }


def run(catalog, store):
    def one(website):
        result = check(website)
        if result is not None:
            store.put_probe(website["id"], result)
        return result is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return sum(pool.map(one, catalog.get("websites", [])))
