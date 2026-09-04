from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import memory_guard
import monitoring_control
import screenshot
from screenshot import CaptureMeta, ScreenshotWorker


def setup_function():
    memory_guard.reset_for_tests()
    monitoring_control.reset_for_tests("active")


def test_screenshot_skips_when_monitoring_paused():
    monitoring_control.reset_for_tests("paused")
    worker = ScreenshotWorker()
    worker._sct = MagicMock()

    with patch("screenshot.is_online", return_value=True), patch.object(
        worker, "_capture_jpeg"
    ) as capture_mock:
        worker._capture_and_send()

    capture_mock.assert_not_called()


def test_screenshot_skips_when_memory_guard_disabled():
    memory_guard.check_memory(force_ram_mb=520.0)
    worker = ScreenshotWorker()
    worker._sct = MagicMock()

    with patch("screenshot.is_online", return_value=True), patch.object(
        worker, "_capture_jpeg"
    ) as capture_mock:
        worker._capture_and_send()

    capture_mock.assert_not_called()
    assert memory_guard.screenshots_allowed() is False


def test_screenshot_loop_skips_when_memory_guard_disabled():
    worker = ScreenshotWorker()
    worker._running = True
    memory_guard.check_memory(force_ram_mb=600.0)
    capture = MagicMock()

    with patch("screenshot.is_online", return_value=True), patch.object(
        worker, "_capture_and_send", capture
    ), patch("screenshot.time.sleep", side_effect=StopIteration):
        import pytest

        with pytest.raises(StopIteration):
            worker._loop()

    capture.assert_not_called()
