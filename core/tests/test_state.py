from datetime import datetime, timedelta, timezone

import pytest

from pulse_core.state import LastSeen, SeatState, seat_state

NOW = datetime(2027, 1, 4, 17, 0, tzinfo=timezone.utc)


def seen(ago=30, event="heartbeat", active=True, locked=False, idle=0):
    return LastSeen(NOW - timedelta(seconds=ago), event, active, locked, idle)


def test_out_of_service_wins():
    assert seat_state(seen(), NOW, out_of_service=True) is SeatState.OUT_OF_SERVICE


def test_offline_when_never_seen_silent_or_shut_down():
    assert seat_state(None, NOW) is SeatState.OFFLINE
    assert seat_state(seen(ago=301), NOW) is SeatState.OFFLINE
    assert seat_state(seen(event="shutdown"), NOW) is SeatState.OFFLINE


def test_available_when_nobody_signed_in():
    assert seat_state(seen(active=False), NOW) is SeatState.AVAILABLE


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("idle,expected", [(0, SeatState.IN_USE), (899, SeatState.IN_USE),
                                          (900, SeatState.AVAILABLE), (901, SeatState.AVAILABLE)])
def test_availability_uses_inactivity_even_when_locked(locked, idle, expected):
    assert seat_state(seen(locked=locked, idle=idle), NOW) is expected


def test_idle_does_not_override_offline_or_out_of_service():
    assert seat_state(seen(ago=301, idle=900), NOW) is SeatState.OFFLINE
    assert seat_state(seen(event="shutdown", idle=900), NOW) is SeatState.OFFLINE
    assert seat_state(seen(locked=True, idle=900), NOW, out_of_service=True) is SeatState.OUT_OF_SERVICE
