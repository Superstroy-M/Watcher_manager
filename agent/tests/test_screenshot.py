import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from screenshot import (
    BLACK_FRAME_RATIO,
    CaptureMeta,
    MAX_CAPTURE_WIDTH,
    MAX_SOURCE_PIXELS,
    ScreenshotWorker,
    _black_ratio_bgra,
    _black_ratio_rgb,
    _pick_monitor,
)


def _rgb_bytes(width: int, height: int, color=(120, 140, 160)) -> bytes:
    r, g, b = color
    return bytes([r, g, b] * (width * height))


def _bgra_bytes(width: int, height: int, color=(120, 140, 160, 255)) -> bytearray:
    r, g, b, a = color
    buf = bytearray(width * height * 4)
    for i in range(0, len(buf), 4):
        buf[i] = b
        buf[i + 1] = g
        buf[i + 2] = r
        buf[i + 3] = a
    return buf


def _make_raw(width: int, height: int, color=(120, 140, 160)):
    bgra = _bgra_bytes(width, height, (*color, 255))
    rgb = _rgb_bytes(width, height, color)
    return SimpleNamespace(width=width, height=height, raw=bgra, rgb=rgb)


@pytest.fixture
def worker():
    w = ScreenshotWorker()
    w._sct = MagicMock()
    w._sct.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
    return w


def test_captureblt_disabled_on_windows():
    if sys.platform == "win32":
        import mss.windows

        assert mss.windows.CAPTUREBLT == 0


def test_single_grab_uses_primary_monitor_when_available(worker):
    worker._sct.monitors = [
        {"left": 0, "top": 0, "width": 3840, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
    ]
    worker._sct.grab.return_value = _make_raw(1920, 1080)

    meta, jpeg = worker._capture_jpeg()

    worker._sct.grab.assert_called_once_with(worker._sct.monitors[1])
    assert jpeg is not None
    assert meta.skipped_black is False
    assert meta.width <= MAX_CAPTURE_WIDTH


def test_single_monitor_uses_only_monitor(worker):
    worker._sct.grab.return_value = _make_raw(1920, 1080)

    meta, jpeg = worker._capture_jpeg()

    worker._sct.grab.assert_called_once_with(worker._sct.monitors[0])
    assert jpeg is not None


def test_black_frame_is_skipped_without_rgb_conversion(worker):
    worker._sct.grab.return_value = _make_raw(1920, 1080, color=(0, 0, 0))

    meta, jpeg = worker._capture_jpeg()

    assert jpeg is None
    assert meta.skipped_black is True


def test_large_frame_is_downscaled(worker):
    worker._sct.grab.return_value = _make_raw(2800, 2000)

    meta, jpeg = worker._capture_jpeg()

    assert jpeg is not None
    assert meta.width == MAX_CAPTURE_WIDTH
    assert meta.height < 2000


def test_mss_instance_reused_not_recreated_each_cycle():
    created = []

    class FakeMSS:
        def __init__(self):
            created.append(self)
            self.monitors = [{"left": 0, "top": 0, "width": 100, "height": 100}]
            self.closed = False

        def grab(self, monitor):
            return _make_raw(100, 100)

        def close(self):
            self.closed = True

    worker = ScreenshotWorker()
    worker._running = True

    with patch("screenshot.sys.platform", "win32"), patch(
        "screenshot.mss.mss", FakeMSS
    ), patch("screenshot.is_online", return_value=True), patch(
        "screenshot.screenshots_allowed", return_value=True
    ), patch.object(
        worker, "_capture_and_send"
    ), patch("screenshot.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            worker._loop()

    assert len(created) == 1
    assert created[0].closed is True


def test_screenshot_loop_skips_capture_when_server_offline(worker):
    worker._running = True
    capture = MagicMock()

    with patch("screenshot.is_online", return_value=False), patch.object(
        worker, "_capture_and_send", capture
    ), patch("screenshot.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            worker._loop()

    capture.assert_not_called()


def test_capture_and_send_drops_on_upload_failure(worker):
    meta = CaptureMeta(
        width=1280,
        height=720,
        source_width=1920,
        source_height=1080,
        black_ratio=0.1,
        skipped_black=False,
        skipped_reason="",
        capture_ms=10.0,
        encode_ms=5.0,
        jpeg_bytes=1000,
        ram_mb=80.0,
    )

    with patch.object(worker, "_capture_jpeg", return_value=(meta, b"jpeg")), patch(
        "screenshot.post", side_effect=ConnectionError("down")
    ), patch("screenshot.mark_offline") as mark_offline_mock, patch(
        "screenshot.is_online", return_value=True
    ), patch("screenshot.screenshots_allowed", return_value=True):
        worker._capture_and_send()

    mark_offline_mock.assert_called_once()


def test_capture_and_send_logs_metrics(worker):
    meta = CaptureMeta(
        width=1280,
        height=720,
        source_width=3840,
        source_height=2160,
        black_ratio=0.1,
        skipped_black=False,
        skipped_reason="",
        capture_ms=12.5,
        encode_ms=8.0,
        jpeg_bytes=12345,
        ram_mb=90.0,
    )

    with patch.object(worker, "_capture_jpeg", return_value=(meta, b"jpegdata")), patch(
        "screenshot.post",
        return_value=SimpleNamespace(status_code=200, raise_for_status=lambda: None),
    ), patch("screenshot.is_online", return_value=True), patch(
        "screenshot.screenshots_allowed", return_value=True
    ), patch("screenshot.logger") as log_mock:
        worker._capture_and_send()

    message = log_mock.info.call_args[0][0]
    assert "capture_ms=" in message
    assert "encode_ms=" in message
    assert "source=" in message
    assert "jpeg_bytes=" in message
    assert "ram_mb=" in message


def test_black_ratio_bgra_detects_black_and_color():
    assert _black_ratio_bgra(_bgra_bytes(100, 100, (0, 0, 0, 255)), 100, 100) >= BLACK_FRAME_RATIO
    assert _black_ratio_bgra(_bgra_bytes(100, 100, (200, 210, 220, 255)), 100, 100) < BLACK_FRAME_RATIO


def test_black_ratio_rgb_detects_black_and_color():
    assert _black_ratio_rgb(_rgb_bytes(100, 100, (0, 0, 0)), 100, 100) >= BLACK_FRAME_RATIO
    assert _black_ratio_rgb(_rgb_bytes(100, 100, (200, 210, 220)), 100, 100) < BLACK_FRAME_RATIO


def test_oversized_source_frame_is_skipped(worker):
    side = int(MAX_SOURCE_PIXELS ** 0.5) + 100
    worker._sct.grab.return_value = _make_raw(side, side)

    meta, jpeg = worker._capture_jpeg()

    assert jpeg is None
    assert meta.skipped_reason == "source_too_large"


def test_pick_monitor_prefers_primary():
    sct = SimpleNamespace(
        monitors=[
            {"left": 0, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
    )
    assert _pick_monitor(sct) is sct.monitors[1]


def test_jpeg_encoding_closes_image(worker):
    worker._sct.grab.return_value = _make_raw(2800, 2000)
    closed_sizes = []
    original_close = Image.Image.close

    def track_close(self):
        closed_sizes.append(self.size)
        return original_close(self)

    with patch.object(Image.Image, "close", track_close):
        meta, jpeg = worker._capture_jpeg()

    assert jpeg is not None
    assert closed_sizes
