"""Missing-beacon digests. Silence is a reporting gap, not proof of power state."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def stamp(now):
    return now.astimezone(timezone.utc).isoformat()


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Policy:
    silence_hours: int = 24
    timezone: str = "UTC"
    digest_hour: int = 8
    digest_minute: int = 30
    site_url: str = ""
    title: str = "Computer beacon coverage"
    dry_run: bool = True

    def __post_init__(self):
        if self.silence_hours < 1 or not 0 <= self.digest_hour <= 23 or not 0 <= self.digest_minute <= 59:
            raise ValueError("invalid alert window or digest time")
        ZoneInfo(self.timezone)


def devices(catalog):
    for space in catalog["spaces"]:
        for seat in space["seats"]:
            if seat.get("mobile") or seat.get("outOfService"):
                continue
            identity = seat.get("serial") or seat["hostname"].upper()
            key = hashlib.sha256(identity.upper().encode()).hexdigest()
            yield key, {**seat, "space": space["name"], "room": space.get("room", ""),
                        "spaceId": space["id"], "floor": space.get("floor", "")}


def card_for(seats, kind, policy, now):
    heading = {"missing": "Missing beacons", "recovered": "Beacons reporting again"}[kind]
    body = [{"type": "TextBlock", "text": f"{policy.title}: {heading}", "weight": "Bolder",
             "size": "Medium", "color": "Warning" if kind == "missing" else "Good", "wrap": True},
            {"type": "TextBlock", "text": (
                f"No report for at least {policy.silence_hours} hours. Devices may be powered off, "
                "unreachable, or unable to report. Mobile and out-of-service seats are excluded."
                if kind == "missing" else "Fresh beacon reports have resumed for previously alerted devices."),
             "wrap": True}]
    for seat in seats:
        facts = [{"title": "Device", "value": seat["hostname"]},
                 {"title": "Location", "value": f"{seat['space']} · {seat['room']}".strip(" ·")},
                 {"title": "Last report (UTC)", "value": seat.get("lastSeen") or "Never reported"}]
        body.append({"type": "FactSet", "facts": facts})
    body.append({"type": "TextBlock", "text": f"Checked {stamp(now)}", "isSubtle": True, "wrap": True})
    card = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4", "body": body}
    if policy.site_url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Open computer status", "url": policy.site_url}]
    return card


class Monitor:
    """State advances only after delivery succeeds. A failed batch is retried next tick.

    The caller serializes runs. State is keyed by serial so a catalog hostname correction
    does not reset a device's grace period. Only receivedAt (server time) is trusted.
    """

    def __init__(self, state, send, policy):
        self.state, self.send, self.policy = state, send, policy

    def run(self, catalog, latest, now):
        if not catalog.get("spaces") or not any(s.get("seats") for s in catalog["spaces"]):
            raise ValueError("catalog has no devices; coverage cannot be evaluated")
        local = now.astimezone(ZoneInfo(self.policy.timezone))
        day = local.date().isoformat()
        due = ((local.hour, local.minute) >= (self.policy.digest_hour, self.policy.digest_minute)
               and (self.state.get("digest") or {}).get("day") != day)
        cutoff = now - timedelta(hours=self.policy.silence_hours)
        fresh_cutoff = now - timedelta(minutes=5)
        missing, recovered = [], []
        for key, seat in devices(catalog):
            previous = self.state.get(key) or {"firstObserved": stamp(now), "alerted": False}
            event = latest.get(seat["hostname"].upper())
            heard = event.get("receivedAt") if event else None
            last = parse(heard) if heard else parse(previous["firstObserved"])
            if last > now + timedelta(minutes=5):
                raise ValueError("report timestamp is in the future")
            item = {**seat, "key": key, "lastSeen": heard, "previous": previous}
            if last <= cutoff and due and previous.get("digestDay") != day:
                missing.append(item)
            elif (previous.get("alerted") and heard and last > fresh_cutoff
                  and event.get("type") != "shutdown"):
                recovered.append(item)
            if not self.policy.dry_run and not self.state.get(key):
                self.state.put(key, previous)
        planned = []
        for kind, seats in [("missing", missing), ("recovered", recovered)]:
            seats.sort(key=lambda s: (s["room"], s["hostname"]))
            for start in range(0, len(seats), 10):
                batch = seats[start:start + 10]
                card = card_for(batch, kind, self.policy, now)
                planned.append(card)
                if self.policy.dry_run:
                    continue
                self.send(card)
                for seat in batch:
                    record = {**seat["previous"], "alerted": kind == "missing"}
                    if kind == "missing":
                        record["digestDay"] = day
                    else:
                        record.pop("digestDay", None)
                    self.state.put(seat["key"], record)
        if not self.policy.dry_run:
            if due:
                self.state.put("digest", {"day": day})
            self.state.put("health", {"lastChecked": stamp(now), "missing": len(missing),
                                      "recovered": len(recovered), "failed": False})
        return {"missing": len(missing), "recovered": len(recovered), "cards": planned,
                "dryRun": self.policy.dry_run}
