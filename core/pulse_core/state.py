"""Seat states derived from the last event a ComputersPulse agent sent."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

OFFLINE_AFTER = timedelta(minutes=5)
AVAILABLE_AFTER = timedelta(minutes=15)


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
    if last is None or last.event_type == "shutdown" or now - last.received_at > OFFLINE_AFTER:
        return SeatState.OFFLINE
    if not last.active or timedelta(seconds=last.idle_seconds) >= AVAILABLE_AFTER:
        return SeatState.AVAILABLE
    return SeatState.IN_USE
