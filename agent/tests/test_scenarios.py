import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import memory_guard
import process_monitor
import screenshot
import sender
import server_link
from screenshot import CaptureMeta, ScreenshotWorker


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


@pytest.fixture(autouse=True)
def reset_state():
    server_link.reset_state(start_online=False)
    memory_guard.reset_for_tests()
    try:
        import monitoring_control
        monitoring_control.reset_for_tests("active")
    except ImportError:
        pass
    yield


def _ok_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


def test_startup_server_down_agent_stays_light():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}]
    event_sender = sender.EventSender(tracker)

    with patch("sender.post") as post_mock, patch("sender.try_probe", return_value=False), patch(
        "sender.sleep_interval", return_value=0
    ), patch("sender.time.sleep", side_effect=StopIteration):
        event_sender._running = True
        with pytest.raises(StopIteration):
            event_sender._loop()

    post_mock.assert_not_called()
    tracker.pop_events.assert_called()


def test_server_down_up_recovery(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(server_link.time, "monotonic", clock.monotonic)
    server_link.reset_state(start_online=True)

    server_up = True
    post_calls = []
    probe_calls = []

    def fake_post(url, **kwargs):
        post_calls.append((clock.monotonic(), url))
        if not server_up:
            raise ConnectionError("server down")
        return _ok_response()

    def fake_get(url, **kwargs):
        probe_calls.append(clock.monotonic())
        if not server_up:
            raise ConnectionError("server down")
        return _ok_response()

    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}]
    event_sender = sender.EventSender(tracker)

    with patch("sender.post", side_effect=fake_post), patch(
        "server_link.get", side_effect=fake_get
    ), patch("sender.sleep_interval", side_effect=lambda: 30):
        for _ in range(3):
            event_sender._send_cycle()
        assert server_link.is_online() is True
        online_posts = len(post_calls)

        server_up = False
        with pytest.raises(ConnectionError):
            event_sender._send_cycle()
        assert server_link.is_online() is False

        posts_after_fail = len(post_calls)
        for _ in range(5):
            clock.advance(120)
            if server_link.try_probe():
                break
        assert server_link.is_online() is False
        assert len(probe_calls) >= 1
        assert len(post_calls) == posts_after_fail

        server_up = True
        clock.advance(120)
        assert server_link.try_probe() is True
        event_sender._send_cycle()
        assert server_link.is_online() is True
        assert len(post_calls) > online_posts


def test_upload_failure_drops_payload_without_retry_storm():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}, {"id": 2}]
    event_sender = sender.EventSender(tracker)

    with patch("sender.post", side_effect=ConnectionError("mid upload")), patch(
        "sender.log_event"
    ):
        server_link.mark_online()
        with pytest.raises(ConnectionError):
            event_sender._send_events()

    assert server_link.is_online() is False
    assert tracker.pop_events.call_count == 1


def test_offline_period_only_health_probes_not_full_uploads(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(server_link.time, "monotonic", clock.monotonic)
    server_link.mark_offline("down")

    get_calls = 0
    post_calls = 0

    def fake_get(*args, **kwargs):
        nonlocal get_calls
        get_calls += 1
        raise ConnectionError("still down")

    def fake_post(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        return _ok_response()

    with patch("server_link.get", side_effect=fake_get), patch("sender.post", side_effect=fake_post):
        for _ in range(3):
            clock.advance(120)
            server_link.try_probe()
            assert not server_link.is_online()

    assert get_calls == 3
    assert post_calls == 0


def test_screenshot_single_flight_skips_overlapping_capture(worker=None):
    worker = ScreenshotWorker()
    worker._flight_lock.acquire()

    with patch("screenshot.is_online", return_value=True), patch(
        "screenshot.screenshots_allowed", return_value=True
    ), patch.object(worker, "_capture_jpeg") as capture_mock:
        worker._capture_and_send()
        capture_mock.assert_not_called()

    worker._flight_lock.release()


def test_two_hour_screenshot_cycles_ram_plateau():
    import tracemalloc

    worker = ScreenshotWorker()
    meta = CaptureMeta(
        width=640,
        height=480,
        source_width=640,
        source_height=480,
        black_ratio=0.1,
        skipped_black=False,
        skipped_reason="",
        capture_ms=1.0,
        encode_ms=1.0,
        jpeg_bytes=1000,
        ram_mb=120.0,
    )

    tracemalloc.start()
    with patch("screenshot.is_online", return_value=True), patch(
        "screenshot.screenshots_allowed", return_value=True
    ), patch("screenshot.post", return_value=_ok_response()), patch.object(
        worker, "_capture_jpeg", return_value=(meta, b"j" * 100_000)
    ):
        for _ in range(240):
            worker._capture_and_send()

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert worker._flight_lock.locked() is False
    assert current < 10_000_000
    assert peak < 20_000_000


def test_process_monitor_skips_when_offline():
    monitor = process_monitor.ProcessMonitor()
    with patch("process_monitor.post") as post_mock:
        monitor._snapshot()
    post_mock.assert_not_called()
