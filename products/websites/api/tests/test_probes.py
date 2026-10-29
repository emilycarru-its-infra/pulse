from datetime import timedelta
from urllib.error import HTTPError
from pulse_websites import probes, live
from test_live import NOW, push, CATALOG


class Opener:
    def __init__(self, code):
        self.code = code

    def open(self, request, timeout):
        if self.code >= 300:
            raise HTTPError(request.full_url, self.code, "", {}, None)
        return type("Response", (), {"status": self.code, "close": lambda self: None})()


def test_probe_retains_redirect_and_restriction_without_following():
    website = {"url": "https://network.example.org/private/"}
    assert probes.check(website, opener=Opener(302), now=NOW)["http_status"] == 302
    restricted = probes.check(website, opener=Opener(403), now=NOW)
    assert restricted["state"] == "warn" and restricted["reason"] == "restricted"
    assert probes.check(website, opener=Opener(500), now=NOW)["state"] == "down"
    assert probes.check({"url": "http://network.example.org/"}) is None


def test_individual_probe_has_its_own_state_and_does_not_erase_hosting():
    store = live.MemoryStore()
    live.record_push(store, live.Matcher(CATALOG), live.parse_push(push(), NOW))
    store.put_probe(
        "main",
        probes.check({"url": "https://www.example.edu/"}, opener=Opener(200), now=NOW),
    )
    source = live.LiveSource(store)
    result = source({"id": "main"}, {}, NOW)
    assert result["state"] == "degraded"
    assert result["facts"]["php_version"] == "8.3"
    store.put_probe(
        "child",
        probes.check(
            {"url": "https://www.example.edu/art/"}, opener=Opener(200), now=NOW
        ),
    )
    result = live.LiveSource(store)({"id": "child"}, {}, NOW)
    assert result["state"] == "up" and "php_version" not in result["facts"]
    assert (
        live.LiveSource(store)({"id": "child"}, {}, NOW + timedelta(minutes=16))[
            "state"
        ]
        == "unknown"
    )
