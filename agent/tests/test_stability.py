"""
Долгие циклы и защита от разрастания памяти / restart loop.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import memory_guard
import monitoring_control
import network_monitor
import sender
import server_link
from network_monitor import NetworkMonitor
from screenshot import ScreenshotWorker


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def time(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    server_link.reset_state(start_online=False)
    memory_guard.reset_for_tests()
    monitoring_control.reset_for_tests("active")
    monkeypatch.setattr(memory_guard, "RESTART_STATE_FILE", tmp_path / "restart_guard.json")
    yield


def _ok_response(**extra):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"monitoring_state": "active", **extra}
    return resp


def test_network_connections_truncated_at_max(monkeypatch):
    monitor = NetworkMonitor()
    monkeypatch.setattr(network_monitor, "MAX_CONNECTIONS", 3)

    class FakeConn:
        status = "ESTABLISHED"
        pid = 1
        raddr = MagicMock(ip="8.8.8.8", port=443)
        laddr = MagicMock(port=50000)

    fake_proc = MagicMock()
    fake_proc.pid = 1
    fake_proc.name = MagicMock(return_value="app.exe")

    conns = [FakeConn() for _ in range(10)]
    monkeypatch.setattr(network_monitor.psutil, "process_iter", lambda attrs: [fake_proc])
    monkeypatch.setattr(network_monitor.psutil, "net_connections", lambda kind: conns)

    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch("network_monitor.is_online", return_value=True), patch(
        "network_monitor.post", return_value=response
    ) as post_mock, patch("network_monitor.log_event") as log_mock:
        monitor._snapshot()

    payload = post_mock.call_args.kwargs["json"]
    assert len(payload["connections"]) == 3
    log_mock.assert_called()
    assert log_mock.call_args.kwargs["total_found"] == 10


def test_screenshot_exception_1000_cycles_no_lock_leak():
    worker = ScreenshotWorker()
    worker._sct = MagicMock()
    worker._sct.monitors = [{"left": 0, "top": 0, "width": 100, "height": 100}]

    with patch("screenshot.is_online", return_value=True), patch(
        "screenshot.screenshots_allowed", return_value=True
    ), patch.object(worker, "_capture_jpeg", side_effect=RuntimeError("capture failed")):
        for _ in range(1000):
            worker._capture_and_send()

    assert worker._flight_lock.locked() is False


def test_upload_exception_1000_cycles_no_buffer_growth():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}]
    event_sender = sender.EventSender(tracker)

    with patch("sender.post", side_effect=ConnectionError("down")), patch(
        "sender.log_event"
    ), patch("sender.apply_server_state"):
        server_link.mark_online()
        for _ in range(1000):
            try:
                event_sender._send_events()
            except ConnectionError:
                pass

    assert tracker.pop_events.call_count == 1000
    assert server_link.is_online() is False


def test_repeated_memory_threshold_triggers_restart_once(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_guard, "RESTART_COOLDOWN_SEC", 0)

    with patch("memory_guard.subprocess.Popen") as popen_mock, patch(
        "memory_guard.os._exit"
    ) as exit_mock:
        for _ in range(5):
            memory_guard.check_memory(force_ram_mb=760.0)

    assert popen_mock.call_count == 1
    exit_mock.assert_called_once_with(0)


def test_restart_loop_protection_after_max_restarts(tmp_path, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(memory_guard.time, "time", clock.time)
    monkeypatch.setattr(memory_guard, "MAX_RESTARTS", 3)
    monkeypatch.setattr(memory_guard, "RESTART_WINDOW_SEC", 3600)
    monkeypatch.setattr(memory_guard, "RESTART_COOLDOWN_SEC", 0)

    for _ in range(3):
        memory_guard._register_restart(clock.time())
        clock.advance(10)

    with patch("memory_guard.subprocess.Popen") as popen_mock, patch(
        "memory_guard.os._exit"
    ), patch("memory_guard.log_event") as log_mock:
        memory_guard.check_memory(force_ram_mb=800.0)

    popen_mock.assert_not_called()
    assert memory_guard.is_degraded_mode() is True
    assert memory_guard.screenshots_allowed() is False
    assert any(
        call.args[0] == "restart_loop_protection"
        for call in log_mock.call_args_list
    )


def test_restart_loop_protection_respects_cooldown(tmp_path, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(memory_guard.time, "time", clock.time)
    monkeypatch.setattr(memory_guard, "MAX_RESTARTS", 10)
    monkeypatch.setattr(memory_guard, "RESTART_COOLDOWN_SEC", 600)

    with patch("memory_guard.subprocess.Popen") as popen_mock, patch(
        "memory_guard.os._exit"
    ):
        memory_guard.check_memory(force_ram_mb=760.0)
        memory_guard._restart_requested = False
        memory_guard.check_memory(force_ram_mb=760.0)

    assert popen_mock.call_count == 1
    assert memory_guard.is_degraded_mode() is False
    assert memory_guard.screenshots_allowed() is False


def test_paused_1000_cycles_no_event_accumulation():
    monitoring_control.reset_for_tests("paused")
    tracker = MagicMock()
    tracker.pop_events.return_value = []
    event_sender = sender.EventSender(tracker)

    with patch("sender.is_online", return_value=True), patch(
        "sender.post", return_value=_ok_response()
    ), patch("sender.apply_server_state"), patch("sender.sleep_interval", return_value=0), patch(
        "sender.time.sleep"
    ):
        server_link.mark_online()
        for _ in range(1000):
            event_sender._send_cycle()

    assert tracker.pop_events.call_count == 1000


def test_offline_1000_cycles_discards_events():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}]
    event_sender = sender.EventSender(tracker)

    with patch("sender.post") as post_mock:
        for _ in range(1000):
            event_sender._discard_pending()

    assert post_mock.call_count == 0
    assert tracker.pop_events.call_count == 1000


def test_online_offline_100_toggles():
    tracker = MagicMock()
    tracker.pop_events.return_value = []
    event_sender = sender.EventSender(tracker)

    with patch("sender.post", return_value=_ok_response()), patch(
        "sender.apply_server_state"
    ), patch("sender.sleep_interval", return_value=0):
        for i in range(100):
            if i % 2 == 0:
                server_link.mark_online()
                event_sender._send_cycle()
                assert server_link.is_online() is True
            else:
                server_link.mark_offline("toggle")
                event_sender._discard_pending()
                assert server_link.is_online() is False


def test_heartbeat_includes_diagnostics():
    tracker = MagicMock()
    event_sender = sender.EventSender(tracker)
    memory_guard.check_memory(force_ram_mb=123.4)
    monitoring_control.reset_for_tests("paused")

    with patch("sender.post", return_value=_ok_response()) as post_mock, patch(
        "sender.apply_server_state"
    ):
        server_link.mark_online()
        event_sender._send_heartbeat()

    payload = post_mock.call_args.kwargs["json"]
    assert payload["agent_version"] == sender.AGENT_VERSION
    assert payload["ram_mb"] == 123.4
    assert payload["screenshots_enabled"] is True
    assert payload["monitoring_state"] == "paused"


def test_screenshot_encode_releases_raw_on_frombytes_failure():
    worker = ScreenshotWorker()
    worker._sct = MagicMock()
    worker._sct.monitors = [{"left": 0, "top": 0, "width": 10, "height": 10}]
    raw = SimpleNamespace(
        width=10,
        height=10,
        raw=bytes(10 * 10 * 4),
        rgb=b"bad",
    )
    worker._sct.grab.return_value = raw

    with patch("screenshot._black_ratio_bgra", return_value=0.1), patch(
        "screenshot.Image.frombytes", side_effect=ValueError("bad rgb")
    ):
        with pytest.raises(ValueError):
            worker._capture_jpeg()
