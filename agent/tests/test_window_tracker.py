from datetime import datetime, timedelta
from unittest.mock import patch

import monitoring_control
from window_tracker import WindowTracker


def setup_function():
    monitoring_control.reset_for_tests("active")


def test_tick_skipped_when_monitoring_paused():
    monitoring_control.reset_for_tests("paused")
    tracker = WindowTracker()
    tracker._current_process = "excel.exe"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=30)

    with patch("window_tracker.get_idle_seconds", return_value=0), patch(
        "window_tracker.get_active_window_info",
        return_value={"process_name": "word.exe", "window_title": "Doc"},
    ):
        tracker._tick()

    assert tracker.pop_events() == []


def test_window_change_creates_event():
    tracker = WindowTracker()
    tracker._current_process = "excel.exe"
    tracker._current_title = "Book1"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=10)

    with patch("window_tracker.is_online", return_value=True), patch(
        "window_tracker.get_idle_seconds", return_value=0
    ), patch(
        "window_tracker.get_active_window_info",
        return_value={"process_name": "word.exe", "window_title": "Doc"},
    ), patch("window_tracker.log_event"):
        tracker._tick()

    events = tracker.pop_events()
    assert len(events) == 1
    assert events[0]["process_name"] == "excel.exe"
    assert events[0]["event_type"] == "focus"
    assert tracker._current_process == "word.exe"


def test_idle_transition_creates_idle_event():
    tracker = WindowTracker()
    tracker._current_process = "excel.exe"
    tracker._current_title = "Book1"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=60)
    tracker._is_idle = False

    with patch("window_tracker.is_online", return_value=True), patch(
        "window_tracker.get_idle_seconds", return_value=9999
    ), patch("window_tracker.log_event"):
        tracker._tick()

    events = tracker.pop_events()
    assert len(events) == 1
    assert events[0]["process_name"] == "excel.exe"
    assert tracker._is_idle is True
    assert tracker._current_process == "idle"


def test_force_checkpoint_splits_long_session():
    tracker = WindowTracker()
    tracker._current_process = "code.exe"
    tracker._current_title = "main.py"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=120)

    with patch("window_tracker.log_event"):
        tracker.force_checkpoint()

    events = tracker.pop_events()
    assert len(events) == 1
    assert events[0]["process_name"] == "code.exe"
    assert tracker._current_process == "code.exe"
    assert tracker._current_started is not None


def test_tick_skipped_when_server_offline():
    monitoring_control.reset_for_tests("active")
    tracker = WindowTracker()
    with patch("window_tracker.is_online", return_value=False), patch(
        "window_tracker.get_idle_seconds", return_value=0
    ), patch("window_tracker.get_active_window_info") as info_mock:
        tracker._tick()
    info_mock.assert_not_called()


def test_pending_events_capped(monkeypatch):
    monkeypatch.setattr("window_tracker.MAX_PENDING_EVENTS", 3)
    tracker = WindowTracker()
    now = datetime.utcnow()
    with patch("window_tracker.log_event"):
        for i in range(5):
            tracker._current_process = f"app{i}"
            tracker._current_title = ""
            tracker._current_started = now - timedelta(seconds=10)
            tracker._is_idle = False
            tracker._flush_current(now=now)

    assert len(tracker._pending_events) == 3
    assert tracker._pending_events[-1]["process_name"] == "app4"


def test_pop_events_clears_buffer():
    tracker = WindowTracker()
    tracker._pending_events = [{"id": 1}, {"id": 2}]
    first = tracker.pop_events()
    second = tracker.pop_events()
    assert len(first) == 2
    assert second == []
