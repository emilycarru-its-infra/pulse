from datetime import datetime, timedelta, timezone

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


def test_in_use_and_possibly_free():
    assert seat_state(seen(idle=899), NOW) is SeatState.IN_USE
    assert seat_state(seen(idle=900), NOW) is SeatState.POSSIBLY_FREE
    assert seat_state(seen(locked=True), NOW) is SeatState.POSSIBLY_FREE
