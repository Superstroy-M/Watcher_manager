"""Тесты activity telemetry: InputCounter, session flush, privacy, screenshots."""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import monitoring_control
import diag_log
from input_counter import InputCounter, get_input_counter, reset_input_counter_for_tests
from screenshot import ScreenshotWorker
from window_tracker import WindowTracker


def setup_function():
    monitoring_control.reset_for_tests("active")
    reset_input_counter_for_tests()
    diag_log.TRACE_FILE.unlink(missing_ok=True)


def teardown_function():
    reset_input_counter_for_tests()


def _win32_pynput_mocks():
    mouse_listener = MagicMock(name="MouseListener")
    keyboard_listener = MagicMock(name="KeyboardListener")
    mock_mouse_mod = MagicMock()
    mock_mouse_mod.Listener = mouse_listener
    mock_keyboard_mod = MagicMock()
    mock_keyboard_mod.Listener = keyboard_listener
    mock_pynput = MagicMock()
    mock_pynput.mouse = mock_mouse_mod
    mock_pynput.keyboard = mock_keyboard_mod
    return mock_pynput, mouse_listener, keyboard_listener


def test_10000_mouse_events_only_counter_no_queue():
    counter = InputCounter()
    for _ in range(10000):
        counter.record_click()
    totals = counter.peek()
    assert totals["mouse_clicks"] == 10000
    assert totals["key_activity"] == 0
    assert totals["scroll_events"] == 0
    assert not hasattr(counter, "_event_queue")


def test_10000_keyboard_events_only_counter():
    counter = InputCounter()
    for _ in range(10000):
        counter.record_key()
    totals = counter.peek()
    assert totals["key_activity"] == 10000
    assert totals["mouse_clicks"] == 0


def test_key_value_not_stored_in_trace_or_events(tmp_path, monkeypatch):
    monkeypatch.setattr(diag_log, "TRACE_FILE", tmp_path / "activity_trace.jsonl")
    monkeypatch.setattr(diag_log, "DEBUG_MODE", True)

    counter = InputCounter()
    secret_key = MagicMock()
    secret_key.char = "X"
    secret_key.vk = 0x58
    counter._on_key_press(secret_key)

    tracker = WindowTracker()
    tracker._current_process = "notepad.exe"
    tracker._current_title = "Secret doc"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=5)

    with patch("window_tracker.log_event", wraps=diag_log.log_event):
        tracker._flush_current()

    events = tracker.pop_events()
    assert len(events) == 1
    blob = json.dumps(events)
    assert "Secret doc" in blob  # business payload to server
    assert "0x58" not in blob
    assert '"char"' not in blob
    assert '"vk"' not in blob

    if diag_log.TRACE_FILE.exists():
        trace = diag_log.TRACE_FILE.read_text(encoding="utf-8")
        assert "Secret doc" not in trace
        assert "0x58" not in trace
        assert '"char"' not in trace


def test_mouse_coordinates_not_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(diag_log, "TRACE_FILE", tmp_path / "activity_trace.jsonl")
    monkeypatch.setattr(diag_log, "DEBUG_MODE", True)

    counter = InputCounter()
    counter._on_click(1920, 1080, MagicMock(), True)
    counter._on_scroll(100, 200, 0, -3)

    tracker = WindowTracker()
    tracker._current_process = "chrome.exe"
    tracker._current_title = "Page"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=5)
    with patch("window_tracker.log_event", wraps=diag_log.log_event):
        tracker._flush_current()

    events = tracker.pop_events()
    blob = json.dumps(events)
    assert "1920" not in blob
    assert "1080" not in blob

    if diag_log.TRACE_FILE.exists():
        trace = diag_log.TRACE_FILE.read_text(encoding="utf-8")
        assert "1920" not in trace
        assert "1080" not in trace
        assert '"x"' not in trace


def test_session_flush_resets_counters():
    counter = InputCounter()
    counter.record_click()
    counter.record_key()
    counter.record_scroll()
    first = counter.take_and_reset()
    assert first["mouse_clicks"] == 1
    assert first["key_activity"] == 1
    assert first["scroll_events"] == 1
    second = counter.peek()
    assert second == {"mouse_clicks": 0, "key_activity": 0, "scroll_events": 0}


def test_paused_counters_do_not_grow():
    monitoring_control.reset_for_tests("paused")
    counter = InputCounter()
    counter.record_click()
    counter.record_key()
    counter.record_scroll()
    assert counter.peek() == {"mouse_clicks": 0, "key_activity": 0, "scroll_events": 0}


def test_offline_no_disk_queue_for_input(tmp_path, monkeypatch):
    """InputCounter не пишет на диск; offline sender отбрасывает события."""
    monkeypatch.setattr(diag_log, "DEBUG_MODE", False)
    trace = tmp_path / "activity_trace.jsonl"
    monkeypatch.setattr(diag_log, "TRACE_FILE", trace)

    counter = InputCounter()
    for _ in range(500):
        counter.record_click()

    tracker = WindowTracker()
    tracker._current_process = "app.exe"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=10)
    with patch("window_tracker.log_event"):
        tracker._flush_current()

    assert not trace.exists()

    import sender

    event_sender = sender.EventSender(tracker)
    tracker.pop_events()
    tracker._pending_events = [{"id": 1}]
    with patch("sender.is_online", return_value=False), patch(
        "sender.try_probe", return_value=False
    ), patch("sender.log_event"):
        event_sender._discard_pending()
    assert tracker.pop_events() == []


def test_active_paused_toggle_single_listener():
    mock_pynput, mouse_cls, keyboard_cls = _win32_pynput_mocks()
    patches = [
        patch("input_counter.sys.platform", "win32"),
        patch.dict(
            sys.modules,
            {
                "pynput": mock_pynput,
                "pynput.mouse": mock_pynput.mouse,
                "pynput.keyboard": mock_pynput.keyboard,
            },
        ),
    ]
    for p in patches:
        p.start()
    try:
        counter = get_input_counter()
        for _ in range(100):
            monitoring_control.reset_for_tests("active")
            counter.sync_monitoring_state()
            monitoring_control.reset_for_tests("paused")
            counter.sync_monitoring_state()
        assert mouse_cls.call_count == 1
        assert keyboard_cls.call_count == 1
        assert counter.listener_started is True
    finally:
        for p in patches:
            p.stop()
        reset_input_counter_for_tests()


def test_window_event_includes_aggregated_telemetry():
    counter = get_input_counter()
    counter.record_click()
    counter.record_key()
    counter.record_scroll()

    tracker = WindowTracker()
    tracker._current_process = "excel.exe"
    tracker._current_title = "Sheet"
    tracker._current_started = datetime.utcnow() - timedelta(seconds=10)

    with patch("window_tracker.log_event"):
        tracker._flush_current()

    events = tracker.pop_events()
    assert len(events) == 1
    assert events[0]["mouse_clicks"] == 1
    assert events[0]["key_activity"] == 1
    assert events[0]["scroll_events"] == 1
    assert "idle_seconds" in events[0]


def test_context_screenshot_respects_15s_debounce():
    worker = ScreenshotWorker()
    worker._running = True
    worker._last_context_shot_at = time.monotonic()

    with patch("screenshot.is_online", return_value=True), patch(
        "screenshot.is_monitoring_active", return_value=True
    ), patch("screenshot.screenshots_allowed", return_value=True), patch(
        "screenshot.threading.Thread"
    ) as thread_mock:
        worker._on_context_change("chrome.exe", "Tab")
        thread_mock.assert_not_called()


def test_context_screenshot_fires_after_debounce():
    worker = ScreenshotWorker()
    worker._running = True
    worker._last_context_shot_at = 0.0

    with patch("screenshot.is_online", return_value=True), patch(
        "screenshot.is_monitoring_active", return_value=True
    ), patch("screenshot.screenshots_allowed", return_value=True), patch(
        "screenshot.threading.Thread"
    ) as thread_mock:
        worker._on_context_change("chrome.exe", "Tab")
        thread_mock.assert_called_once()


def test_input_does_not_trigger_screenshot():
    counter = InputCounter()
    with patch("context_events.notify_context_change") as notify_mock, patch(
        "screenshot.ScreenshotWorker._capture_and_send"
    ) as capture_mock:
        for _ in range(100):
            counter.record_click()
            counter.record_key()
            counter.record_scroll()
        notify_mock.assert_not_called()
        capture_mock.assert_not_called()


def test_input_counter_debug_events_without_sensitive_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(diag_log, "TRACE_FILE", tmp_path / "activity_trace.jsonl")
    monkeypatch.setattr(diag_log, "DEBUG_MODE", True)

    mock_pynput, _, _ = _win32_pynput_mocks()
    with patch("input_counter.sys.platform", "win32"), patch.dict(
        sys.modules,
        {
            "pynput": mock_pynput,
            "pynput.mouse": mock_pynput.mouse,
            "pynput.keyboard": mock_pynput.keyboard,
        },
    ):
        counter = InputCounter()
        counter.start()
        counter.record_click()
        counter.take_and_reset()
        counter.stop()

    lines = tmp_path.joinpath("activity_trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    types = {json.loads(line)["type"] for line in lines}
    assert "input_counter_started" in types
    assert "input_session_flush" in types
    assert "input_counter_stopped" in types
    for line in lines:
        assert "window_title" not in line.lower()
