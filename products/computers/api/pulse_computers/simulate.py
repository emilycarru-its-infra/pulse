"""Send made-up agent events for every seat in a catalog, so the pages have something to show.

    python -m pulse_computers.simulate catalog.json --url http://localhost:8400/computers/api/ingest

Each seat plays a simple day: some machines stay off, the rest move between free,
in use, idle and locked. --speed makes idle time pass faster than real time.
"""

import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone

VERSION = "dev"


class Seat:
    def __init__(self, hostname: str, platform: str, rng: random.Random):
        self.hostname = hostname
        self.platform = platform if platform in ("mac", "windows") else "mac"
        self.rng = rng
        self.dead = rng.random() < 0.06
        self.active = rng.random() < 0.55
        self.locked = False
        self.idle = rng.randint(0, 600) if self.active else 0

    def step(self, seconds: float) -> str | None:
        """Advance the seat; return a change event type, if one happened."""
        r = self.rng.random()
        if not self.active:
            if r < 0.04:
                self.active, self.idle, self.locked = True, 0, False
                return "login"
            return None
        if self.locked:
            if r < 0.05:
                self.locked, self.idle = False, 0
                return "unlock"
            if r < 0.08:
                self.active, self.locked, self.idle = False, False, 0
                return "logout"
            self.idle += seconds
            return None
        if r < 0.03:
            self.active, self.idle = False, 0
            return "logout"
        if r < 0.05:
            self.locked = True
            return "lock"
        if r < 0.70:
            self.idle = self.rng.randint(0, 20)
        else:
            self.idle += seconds
        return None

    def event(self, kind: str) -> dict:
        return {
            "v": 1,
            "type": kind,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "device": {"hostname": self.hostname, "serial": f"SIM-{self.hostname}"[:64]},
            "session": {"active": self.active, "locked": self.locked, "idleSeconds": int(self.idle)},
            "agent": {"version": VERSION, "platform": self.platform},
        }


def seats_from(catalog: dict, rng: random.Random) -> list[Seat]:
    return [Seat(s["hostname"], s["platform"], rng) for sp in catalog["spaces"] for s in sp["seats"]]


def post(url: str, key: str, event: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(event).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Pulse-Key": key})
    urllib.request.urlopen(req, timeout=10).read()


def run(catalog: dict, send, interval: float = 5.0, speed: float = 30.0, seed: int | None = None,
        stop=lambda: False) -> None:
    rng = random.Random(seed)
    seats = seats_from(catalog, rng)
    while not stop():
        for seat in seats:
            if seat.dead:
                continue
            change = seat.step(interval * speed)
            send(seat.event(change or "heartbeat"))
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("catalog")
    parser.add_argument("--url", default="http://localhost:8400/computers/api/ingest")
    parser.add_argument("--key", default="dev")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--speed", type=float, default=30.0)
    args = parser.parse_args()
    with open(args.catalog) as f:
        catalog = json.load(f)
    run(catalog, lambda e: post(args.url, args.key, e), args.interval, args.speed)


if __name__ == "__main__":
    main()
