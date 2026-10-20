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
    announce: bool = False
    # A correlated drop: at least drop_count seats, in use when last heard, whose last
    # reports fall within drop_window_minutes and which are silent drop_silence_minutes
    # without a shutdown. 0 turns it off. Idle and empty seats are left out, so labs
    # sleeping or emptying at night do not count; the daily digest still covers them.
    drop_count: int = 10
    drop_window_minutes: int = 10
    drop_silence_minutes: int = 15
    drop_idle_seconds: int = 600

    def __post_init__(self):
        if self.silence_hours < 1 or not 0 <= self.digest_hour <= 23 or not 0 <= self.digest_minute <= 59:
            raise ValueError("invalid alert window or digest time")
        if self.drop_count < 0 or self.drop_window_minutes < 1 or self.drop_silence_minutes < 5:
            raise ValueError("invalid drop alert settings")
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


def drop_card(seats, total, policy, now):
    body = [{"type": "TextBlock", "text": f"{policy.title}: Beacons stopped together", "weight": "Bolder",
             "size": "Medium", "color": "Attention", "wrap": True},
            {"type": "TextBlock", "text": (
                f"{total} seats in use stopped reporting within {policy.drop_window_minutes} minutes and have "
                f"been silent for at least {policy.drop_silence_minutes} minutes, without a shutdown. They are "
                "probably still on: look for a configuration, policy or network change at that time."),
             "wrap": True}]
    for seat in seats:
        body.append({"type": "FactSet", "facts": [
            {"title": "Device", "value": seat["hostname"]},
            {"title": "Location", "value": f"{seat['space']} · {seat['room']}".strip(" ·")},
            {"title": "Last report (UTC)", "value": seat["lastSeen"]}]})
    if total > len(seats):
        body.append({"type": "TextBlock", "text": f"And {total - len(seats)} more.", "wrap": True})
    body.append({"type": "TextBlock", "text": f"Checked {stamp(now)}", "isSubtle": True, "wrap": True})
    card = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4", "body": body}
    if policy.site_url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Open computer status", "url": policy.site_url}]
    return card


def cluster(seats, window):
    """The largest set of seats whose last reports fall within one window."""
    ordered = sorted(seats, key=lambda s: s["lastSeen"])
    best, start = [], 0
    for end, seat in enumerate(ordered):
        while parse(seat["lastSeen"]) - parse(ordered[start]["lastSeen"]) > window:
            start += 1
        if end - start + 1 > len(best):
            best = ordered[start:end + 1]
    return best


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
        missing, recovered, quiet, heard_at = [], [], [], {}
        drop_cutoff = now - timedelta(minutes=self.policy.drop_silence_minutes)
        for key, seat in devices(catalog):
            previous = self.state.get(key) or {"firstObserved": stamp(now), "alerted": False}
            event = latest.get(seat["hostname"].upper())
            heard = event.get("receivedAt") if event else None
            last = parse(heard) if heard else parse(previous["firstObserved"])
            if last > now + timedelta(minutes=5):
                raise ValueError("report timestamp is in the future")
            item = {**seat, "key": key, "lastSeen": heard, "previous": previous}
            if heard:
                heard_at[key] = last
                session = event.get("session") or {}
                if (event.get("type") != "shutdown" and session.get("active")
                        and int(session.get("idleSeconds") or 0) < self.policy.drop_idle_seconds
                        and now - timedelta(hours=self.policy.silence_hours) < last <= drop_cutoff):
                    quiet.append(item)
            if last <= cutoff and due and previous.get("digestDay") != day:
                missing.append(item)
            elif (previous.get("alerted") and heard and last > fresh_cutoff
                  and event.get("type") != "shutdown"):
                recovered.append(item)
            if not self.policy.dry_run and not self.state.get(key):
                self.state.put(key, previous)
        planned = []
        dropped = self._drop(quiet, heard_at, now, fresh_cutoff, planned)
        if self.policy.announce and not self.state.get("setup"):
            setup = {"type": "AdaptiveCard", "version": "1.4", "body": [
                {"type": "TextBlock", "text": "Computer beacon monitoring enabled", "weight": "Bolder",
                 "color": "Good", "wrap": True},
                {"type": "TextBlock", "text": (
                    f"Missing-beacon digest daily at {self.policy.digest_hour:02}:{self.policy.digest_minute:02} "
                    f"({self.policy.timezone}) after {self.policy.silence_hours} hours without a report. "
                    "Mobile and out-of-service seats are excluded. Newly observed devices receive "
                    "the same grace period; recovery is checked every five minutes."), "wrap": True}]}
            planned.append(setup)
            if not self.policy.dry_run:
                self.send(setup)
                self.state.put("setup", {"at": stamp(now)})
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
        return {"missing": len(missing), "recovered": len(recovered), "dropped": dropped,
                "cards": planned, "dryRun": self.policy.dry_run}

    def _drop(self, quiet, heard_at, now, fresh_cutoff, planned):
        """One card when many in-use seats go silent together, one when most report again."""
        if not self.policy.drop_count:
            return 0
        episode = self.state.get("drop") or {}
        group = cluster(quiet, timedelta(minutes=self.policy.drop_window_minutes))
        if not episode.get("active"):
            if len(group) < self.policy.drop_count:
                return 0
            group.sort(key=lambda s: (s["room"], s["hostname"]))
            card = drop_card(group[:10], len(group), self.policy, now)
            planned.append(card)
            if not self.policy.dry_run:
                self.send(card)
                self.state.put("drop", {"active": True, "at": stamp(now), "keys": [s["key"] for s in group]})
            return len(group)
        keys = episode.get("keys") or []
        back = sum(1 for k in keys if k in heard_at and heard_at[k] > fresh_cutoff)
        expired = parse(episode["at"]) <= now - timedelta(hours=self.policy.silence_hours)
        if back * 2 >= len(keys) or expired:
            if not expired:
                card = {"type": "AdaptiveCard", "version": "1.4", "body": [
                    {"type": "TextBlock", "text": f"{self.policy.title}: Beacons reporting again",
                     "weight": "Bolder", "color": "Good", "wrap": True},
                    {"type": "TextBlock", "text": (
                        f"{back} of the {len(keys)} seats that stopped together at {episode['at']} "
                        "are reporting again."), "wrap": True}]}
                planned.append(card)
                if not self.policy.dry_run:
                    self.send(card)
            if not self.policy.dry_run:
                self.state.put("drop", {"active": False, "at": episode["at"], "clearedAt": stamp(now)})
        return len(keys)
