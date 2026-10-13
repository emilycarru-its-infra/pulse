"""The PrintersPulse API as plain functions, so any host (Functions, dev server) can call them.

Until a collector reads the print server, every printer's state is SAMPLE DATA: made up from
the printer's id and the clock, so it is the same on every worker and every poll within a
few minutes, drifts through the day like a real fleet, and needs no storage. Every response
says so with "sample": true, and the page shows it.
"""

import hashlib
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STATES = ["ready", "printing", "attention", "error", "offline"]
BUCKET = 300  # seconds a sampled state holds before it can change

PROBLEMS = {
    "attention": [
        "Toner low",
        "Paper low in tray 2",
        "Waste toner nearly full",
        "Maintenance kit due",
    ],
    "error": ["Paper jam in tray 1", "Out of paper", "Front door open", "Toner empty"],
    "inkjet_attention": [
        "Ink low",
        "Roll paper low",
        "Maintenance cartridge nearly full",
    ],
    "inkjet_error": ["Out of roll paper", "Ink empty", "Head cleaning needed"],
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rng(*parts) -> random.Random:
    seed = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(seed[:8], "big"))


def _busy(local: datetime) -> float:
    """0 to 1: how busy a campus is at this local hour, quiet overnight."""
    h = local.hour + local.minute / 60
    if h < 7 or h >= 23:
        return 0.02
    return max(0.1, 1 - abs(h - 14) / 9)


def sample(printer: dict, now: datetime, tz: ZoneInfo) -> dict:
    """One printer's made-up state at this moment."""
    pid = printer["id"]
    local = now.astimezone(tz)
    bucket = int(now.timestamp()) // BUCKET
    r = _rng(pid, bucket)
    fixed = _rng(pid)
    busy = _busy(local)

    # A few printers stay in trouble for hours, so the page always has something to show.
    troubled = _rng(pid, local.date(), local.hour // 3).random() < 0.06
    roll = r.random()
    if troubled:
        state = (
            "error"
            if fixed.random() < 0.4
            else ("offline" if fixed.random() < 0.3 else "attention")
        )
    elif roll < 0.015:
        state = "offline"
    elif roll < 0.03:
        state = "error"
    elif roll < 0.08:
        state = "attention"
    elif roll < 0.08 + 0.45 * busy:
        state = "printing"
    else:
        state = "ready"

    kind = "inkjet_" if printer.get("inkjet") else ""
    detail = {
        "ready": "Ready",
        "printing": "Printing",
        "offline": "Not responding",
    }.get(state) or r.choice(PROBLEMS[kind + state])

    # Supplies run down through the week and are replaced when they hit bottom.
    week = (now.timestamp() / 86400) % 7
    if printer.get("inkjet"):
        names = ["Photo black", "Matte black", "Cyan", "Magenta", "Yellow", "Grey"]
    elif printer.get("colour"):
        names = ["Black", "Cyan", "Magenta", "Yellow"]
    else:
        names = ["Black"]
    supplies = []
    for n in names:
        start = fixed.uniform(0, 7)
        rate = fixed.uniform(9, 22)
        level = int(100 - ((week + start) * rate) % 100)
        if detail.startswith(("Toner low", "Ink low")) and n == names[0]:
            level = min(level, 8)
        if detail.startswith(("Toner empty", "Ink empty")) and n == names[0]:
            level = 0
        supplies.append({"name": n, "level": level})

    if printer.get("inkjet"):
        trays = [{"name": "Roll", "level": int(100 - ((week + fixed.uniform(0, 7)) * 14) % 100)}]
    else:
        trays = [
            {"name": f"Tray {i}", "level": r.choice([100, 90, 75, 60, 40, 25])}
            for i in (1, 2)
        ]
    if detail.startswith(("Paper low", "Roll paper low")):
        trays[-1]["level"] = 10
    if detail.startswith(("Out of paper", "Out of roll")):
        trays[0]["level"] = 0

    day = local.hour * 60 + local.minute
    jobs = (
        int(fixed.uniform(20, 140) * max(0, min(day - 420, 960)) / 960)
        if day > 420
        else 0
    )
    queue = (
        r.randint(1, 6)
        if state == "printing"
        else (r.randint(1, 9) if state in ("error", "offline") else 0)
    )
    seen = now - timedelta(minutes=r.randint(10, 50)) if state == "offline" else now
    return {
        **{
            k: printer[k]
            for k in (
                "id",
                "name",
                "model",
                "room",
                "location",
                "audience",
                "colour",
                "inkjet",
                "queues",
            )
            if k in printer
        },
        **({k: printer[k] for k in ("floor", "x", "y") if k in printer}),
        "state": state,
        "detail": detail,
        "supplies": supplies,
        "trays": trays,
        "queue": queue,
        "jobsToday": jobs,
        "lastSeen": _iso(seen),
    }


class PrintersService:
    def __init__(self, catalog: dict, title: str = "Printers", tz: str = "UTC"):
        self.catalog = catalog
        self.title = title
        self.tz = ZoneInfo(tz)

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        printers = [sample(p, now, self.tz) for p in self.catalog["printers"]]
        counts = dict.fromkeys(STATES, 0)
        for p in printers:
            counts[p["state"]] += 1
        return {
            "generatedAt": _iso(now),
            "sample": True,
            "floors": self.catalog.get("floors", []),
            "counts": counts,
            "printers": printers,
        }

    def summary(self, now: datetime | None = None) -> dict:
        status = self.status(now)
        c = status["counts"]
        total = sum(c.values())
        working = c["ready"] + c["printing"]
        if total == 0:
            level, line = "idle", "No printers in the catalog"
        elif working == 0:
            level, line = "bad", "No printers available"
        else:
            level = "warn" if c["error"] + c["offline"] > total * 0.15 else "ok"
            problems = c["error"] + c["offline"]
            line = f"{working} of {total} printers available" + (
                f", {problems} need help" if problems else ""
            )
        return {
            "product": "printers",
            "title": self.title,
            "level": level,
            "line": line,
            "sample": True,
            "counts": c,
            "total": total,
            "generatedAt": status["generatedAt"],
        }
