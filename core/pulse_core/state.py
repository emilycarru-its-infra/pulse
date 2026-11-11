"""Seat states derived from the last event a ComputersPulse agent sent."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

OFFLINE_AFTER = timedelta(minutes=5)
AVAILABLE_AFTER = timedelta(minutes=15)
# A computer that reported going to sleep is free, not missing: sleep means nobody is using it.
# Past this it counts as offline again, so one unplugged while asleep does not stay free forever.
ASLEEP_FOR = timedelta(days=3)


class SeatState(str, Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    # Retained for consumers of the existing count fields; new readings never emit it.
    POSSIBLY_FREE = "possibly_free"
    OFFLINE = "offline"
    OUT_OF_SERVICE = "out_of_service"


@dataclass(frozen=True)
class LastSeen:
    """The fields of a seat's most recent event that decide its state."""

    received_at: datetime
    event_type: str
    active: bool
    locked: bool
    idle_seconds: int


def seat_state(last: LastSeen | None, now: datetime, out_of_service: bool = False) -> SeatState:
    if out_of_service:
        return SeatState.OUT_OF_SERVICE
    if last is not None and last.event_type == "sleep":
        return SeatState.AVAILABLE if now - last.received_at <= ASLEEP_FOR else SeatState.OFFLINE
    if last is None or last.event_type == "shutdown" or now - last.received_at > OFFLINE_AFTER:
        return SeatState.OFFLINE
    if not last.active or timedelta(seconds=last.idle_seconds) >= AVAILABLE_AFTER:
        return SeatState.AVAILABLE
    return SeatState.IN_USE


def asleep(last: LastSeen | None, now: datetime) -> bool:
    """The seat reported going to sleep and has not been silent past ASLEEP_FOR since."""
    return last is not None and last.event_type == "sleep" and now - last.received_at <= ASLEEP_FOR
