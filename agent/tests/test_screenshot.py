import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from screenshot import (
    BLACK_FRAME_RATIO,
    CaptureMeta,
    ScreenshotWorker,
    _black_ratio,
    _black_ratio_rgb,
    _imagegrab_fallback,
)


def _rgb_bytes(width: int, height: int, color=(120, 140, 160)) -> bytes:
    r, g, b = color
    return bytes([r, g, b] * (width * height))


def _make_raw(width: int, height: int, color=(120, 140, 160)):
    rgb = _rgb_bytes(width, height, color)
    return SimpleNamespace(width=width, height=height, rgb=rgb)


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


def test_single_grab_uses_virtual_desktop(worker):
    worker._sct.grab.return_value = _make_raw(1920, 1080)

    img, meta = worker._capture_image()

    worker._sct.grab.assert_called_once_with(worker._sct.monitors[0])
    assert img.size == (1920, 1080)
    assert meta.fallback is False
    assert meta.black_ratio < BLACK_FRAME_RATIO
    img.close()


def test_no_imagegrab_on_normal_frame(worker):
    worker._sct.grab.return_value = _make_raw(2560, 1440)

    with patch("screenshot._imagegrab_fallback") as fallback:
        img, meta = worker._capture_image()

    fallback.assert_not_called()
    assert meta.fallback is False
    img.close()


def test_imagegrab_only_for_almost_black_frame(worker):
    worker._sct.grab.return_value = _make_raw(1920, 1080, color=(0, 0, 0))
    fallback_img = Image.new("RGB", (1920, 1080), color=(200, 210, 220))

    with patch("screenshot._imagegrab_fallback", return_value=fallback_img) as fallback:
        img, meta = worker._capture_image()

    fallback.assert_called_once()
    assert meta.fallback is True
    assert img is fallback_img
    img.close()


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
    ), patch.object(worker, "_flush_offline"), patch.object(
        worker, "_capture_and_send"
    ), patch("screenshot.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            worker._loop()

    assert len(created) == 1
    assert created[0].closed is True


def test_capture_and_send_logs_metrics(worker):
    img = Image.new("RGB", (800, 600), color=(10, 20, 30))
    meta = CaptureMeta(800, 600, 0.1, False, 12.5)

    with patch.object(worker, "_capture_image", return_value=(img, meta)), patch(
        "screenshot.requests.post", return_value=SimpleNamespace(status_code=200, raise_for_status=lambda: None)
    ), patch("screenshot.logger") as log_mock:
        worker._capture_and_send()

    log_mock.info.assert_called_once()
    message = log_mock.info.call_args[0][0]
    assert "capture_ms=" in message
    assert "encode_ms=" in message
    assert "width=" in message
    assert "height=" in message
    assert "black_ratio=" in message
    assert "fallback=" in message
    assert "jpeg_bytes=" in message


def test_black_ratio_rgb_detects_black_and_color():
    assert _black_ratio_rgb(_rgb_bytes(100, 100, (0, 0, 0)), 100, 100) >= BLACK_FRAME_RATIO
    assert _black_ratio_rgb(_rgb_bytes(100, 100, (200, 210, 220)), 100, 100) < BLACK_FRAME_RATIO


def test_black_ratio_on_image():
    black = Image.new("RGB", (100, 100), color=(0, 0, 0))
    color = Image.new("RGB", (100, 100), color=(200, 210, 220))
    try:
        assert _black_ratio(black) >= BLACK_FRAME_RATIO
        assert _black_ratio(color) < BLACK_FRAME_RATIO
    finally:
        black.close()
        color.close()


def test_imagegrab_fallback_closes_non_rgb():
    grabbed = Image.new("RGBA", (10, 10), color=(255, 0, 0, 255))
    with patch("PIL.ImageGrab.grab", return_value=grabbed):
        img = _imagegrab_fallback()
    assert img is not None
    assert img.mode == "RGB"
    img.close()


def test_jpeg_encoding_closes_image(worker):
    img = MagicMock()
    img.save = Image.new("RGB", (640, 480), color=(30, 40, 50)).save
    meta = CaptureMeta(640, 480, 0.0, False, 1.0)

    with patch.object(worker, "_capture_image", return_value=(img, meta)), patch(
        "screenshot.requests.post", return_value=SimpleNamespace(status_code=200, raise_for_status=lambda: None)
    ):
        worker._capture_and_send()

    img.close.assert_called_once()
