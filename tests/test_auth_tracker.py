"""Testy `auth_tracker.py` — bez HA, importováno jako bare modul."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import auth_tracker
finally:
    sys.path.remove(str(INTEGRATION_DIR))

START = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def make(grace_minutes=3):
    clock = Clock()
    return auth_tracker.AuthFailureTracker(timedelta(minutes=grace_minutes), clock), clock


def test_first_failure_is_tolerated():
    tracker, _ = make()
    assert tracker.failed("entry") is False
    assert tracker.since("entry") == START


def test_failure_series_becomes_permanent_after_grace():
    tracker, clock = make()
    assert tracker.failed("entry") is False
    clock.advance(minutes=2, seconds=59)
    assert tracker.failed("entry") is False
    clock.advance(seconds=1)
    assert tracker.failed("entry") is True  # přesně po 3 minutách
    clock.advance(minutes=10)
    assert tracker.failed("entry") is True  # a dál


def test_series_start_is_not_moved_by_repeated_failures():
    tracker, clock = make()
    tracker.failed("entry")
    clock.advance(minutes=1)
    tracker.failed("entry")
    assert tracker.since("entry") == START


def test_success_resets_the_series():
    tracker, clock = make()
    tracker.failed("entry")
    clock.advance(minutes=2)
    tracker.ok("entry")
    assert tracker.since("entry") is None
    clock.advance(minutes=5)
    assert tracker.failed("entry") is False  # nová série začíná znovu


def test_entries_are_independent():
    tracker, clock = make()
    tracker.failed("a")
    clock.advance(minutes=5)
    assert tracker.failed("a") is True
    assert tracker.failed("b") is False
    tracker.ok("a")
    assert tracker.failed("b") is False


def test_ok_without_failure_is_harmless():
    tracker, _ = make()
    tracker.ok("never-failed")
    assert tracker.since("never-failed") is None
