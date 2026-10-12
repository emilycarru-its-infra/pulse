"""The ComputersPulse API as plain functions, so any host (Functions, dev server) can call them."""

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pulse_core.state import LastSeen, SeatState, seat_state

from .store import Store

CONTRACT = Path(__file__).resolve().parents[4] / "core" / "contract"
_VALIDATOR = jsonschema.Draft202012Validator(json.loads((CONTRACT / "event.schema.json").read_text()))

COUNTED = [s.value for s in SeatState]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


class ValidationError(ValueError):
    pass


class ComputersService:
    def __init__(self, catalog: dict, store: Store, title: str = "Computers"):
        self.catalog = catalog
        self.store = store
        self.title = title

    def ingest(self, event: dict, now: datetime | None = None) -> None:
        errors = sorted(_VALIDATOR.iter_errors(event), key=lambda e: list(e.path))
        if errors:
            raise ValidationError("; ".join(e.message for e in errors[:3]))
        stored = dict(event)
        stored["receivedAt"] = _iso(now or datetime.now(timezone.utc))
        self.store.append(stored)

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        latest = self.store.latest()
        spaces = []
        for space in self.catalog["spaces"]:
            counts = dict.fromkeys(COUNTED, 0)
            seats = []
            for seat in space["seats"]:
                event = latest.get(seat["hostname"].upper())
                last = None
                if event:
                    s = event["session"]
                    last = LastSeen(_parse(event["receivedAt"]), event["type"], s["active"], s["locked"], s["idleSeconds"])
                state = seat_state(last, now, seat.get("outOfService", False))
                counts[state.value] += 1
                seats.append({
                    "hostname": seat["hostname"],
                    "platform": seat["platform"],
                    "state": state.value,
                    "lastSeen": event["receivedAt"] if event else None,
                    **({"x": seat["x"], "y": seat["y"]} if "x" in seat else {}),
                })
            spaces.append({
                **{k: space[k] for k in ("id", "name", "kind", "building", "floor", "floorplan") if k in space},
                "counts": counts,
                "seats": seats,
            })
        return {"generatedAt": _iso(now), "spaces": spaces}

    def summary(self, now: datetime | None = None) -> dict:
        status = self.status(now)
        totals = dict.fromkeys(COUNTED, 0)
        for space in status["spaces"]:
            for k, v in space["counts"].items():
                totals[k] += v
        seats = sum(totals.values())
        free = totals["available"]
        if seats == 0:
            level, line = "idle", "No seats in the catalog"
        elif totals["offline"] + totals["out_of_service"] == seats:
            level, line = "bad", "No seats reporting"
        else:
            level = "warn" if totals["offline"] > seats * 0.25 else "ok"
            n = len(status["spaces"])
            line = f"{free} of {seats} seats free in {n} space{'s' if n != 1 else ''}"
        return {"product": "computers", "title": self.title, "level": level, "line": line,
                "counts": totals, "seats": seats, "generatedAt": status["generatedAt"]}

    def export(self, since: datetime) -> list[dict]:
        return list(self.store.events_since(since))
