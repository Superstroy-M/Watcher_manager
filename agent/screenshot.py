"""
Захват скриншотов экрана и отправка на сервер.
"""
import io
import os
import sys
import time
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import mss
import requests
from PIL import Image

from config import SERVER_URL, API_KEY

if sys.platform == "win32":
    import mss.windows

    mss.windows.CAPTUREBLT = 0

logger = logging.getLogger("screenshot")

HEADERS = {"X-API-Key": API_KEY}
SCREENSHOT_INTERVAL = int(os.environ.get("SCREENSHOT_INTERVAL", "30"))  # секунд
JPEG_QUALITY = 50   # 40-60 оптимально: хорошее качество, малый размер
OFFLINE_DIR = Path(__file__).parent / "screenshots_offline"
BLACK_FRAME_RATIO = 0.98


@dataclass
class CaptureMeta:
    width: int
    height: int
    black_ratio: float
    fallback: bool
    capture_ms: float


class ScreenshotWorker:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sct: Optional[mss.mss] = None

    def start(self):
        self._running = True
        OFFLINE_DIR.mkdir(exist_ok=True)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=SCREENSHOT_INTERVAL + 5)

    def _loop(self):
        try:
            import ctypes

            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -2
            )
        except Exception:
            pass

        if sys.platform == "win32":
            self._sct = mss.mss()

        try:
            while self._running:
                try:
                    self._flush_offline()
                    self._capture_and_send()
                except Exception as e:
                    logger.warning(f"Screenshot error: {e}")
                time.sleep(SCREENSHOT_INTERVAL)
        finally:
            if self._sct is not None:
                self._sct.close()
                self._sct = None

    def _capture_and_send(self):
        import socket

        timestamp = datetime.utcnow()
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        hostname = socket.gethostname()

        img: Optional[Image.Image] = None
        jpeg_bytes: Optional[bytes] = None
        encode_ms = 0.0
        meta = CaptureMeta(0, 0, 1.0, False, 0.0)

        try:
            img, meta = self._capture_image()
            encode_start = time.perf_counter()
            with io.BytesIO() as buf:
                img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                jpeg_bytes = buf.getvalue()
            encode_ms = (time.perf_counter() - encode_start) * 1000
        finally:
            if img is not None:
                img.close()

        logger.info(
            "screenshot capture_ms=%.1f encode_ms=%.1f width=%d height=%d "
            "black_ratio=%.3f fallback=%s jpeg_bytes=%d",
            meta.capture_ms,
            encode_ms,
            meta.width,
            meta.height,
            meta.black_ratio,
            meta.fallback,
            len(jpeg_bytes or b""),
        )

        try:
            resp = requests.post(
                f"{SERVER_URL}/api/screenshot",
                files={"file": (f"{ts_str}.jpg", jpeg_bytes, "image/jpeg")},
                data={"hostname": hostname, "timestamp": timestamp.isoformat()},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
        except Exception:
            offline_path = OFFLINE_DIR / f"{hostname}_{ts_str}.jpg"
            offline_path.write_bytes(jpeg_bytes or b"")
            raise
        finally:
            jpeg_bytes = None

    def _capture_image(self) -> tuple[Image.Image, CaptureMeta]:
        if self._sct is None:
            raise RuntimeError("Screenshot capture is only supported on Windows")

        capture_start = time.perf_counter()
        monitor = self._sct.monitors[0]
        raw = self._sct.grab(monitor)
        width, height = raw.width, raw.height
        rgb_bytes = raw.rgb
        del raw

        black_ratio = _black_ratio_rgb(rgb_bytes, width, height)
        capture_ms = (time.perf_counter() - capture_start) * 1000
        meta = CaptureMeta(width, height, black_ratio, False, capture_ms)

        if black_ratio < BLACK_FRAME_RATIO:
            img = Image.frombytes("RGB", (width, height), rgb_bytes)
            del rgb_bytes
            return img, meta

        del rgb_bytes
        meta.fallback = True
        fallback_img = _imagegrab_fallback()
        if fallback_img is not None:
            meta.width, meta.height = fallback_img.size
            meta.black_ratio = _black_ratio(fallback_img)
            return fallback_img, meta

        return Image.new("RGB", (width, height), color=(0, 0, 0)), meta

    def _flush_offline(self):
        """Отправляем скриншоты накопленные офлайн."""
        import socket

        hostname = socket.gethostname()
        files = sorted(OFFLINE_DIR.glob("*.jpg"))
        if not files:
            return
        for f in files:
            try:
                ts_str = f.stem.replace(f"{hostname}_", "")
                ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                with open(f, "rb") as fp:
                    resp = requests.post(
                        f"{SERVER_URL}/api/screenshot",
                        files={"file": (f.name, fp, "image/jpeg")},
                        data={"hostname": hostname, "timestamp": ts.isoformat()},
                        headers=HEADERS,
                        timeout=20,
                    )
                    resp.raise_for_status()
                f.unlink()
            except Exception:
                break


def _imagegrab_fallback() -> Optional[Image.Image]:
    """Редкий fallback только для почти полностью чёрного mss-кадра."""
    try:
        from PIL import ImageGrab

        grabbed = ImageGrab.grab(all_screens=True)
        try:
            if grabbed.mode != "RGB":
                img = grabbed.convert("RGB")
                grabbed.close()
                grabbed = img
            if _is_mostly_black(grabbed):
                grabbed.close()
                return None
            return grabbed
        except Exception:
            grabbed.close()
            raise
    except Exception:
        return None


def _is_mostly_black(img: Image.Image, threshold: int = 8, min_dark_ratio: float = BLACK_FRAME_RATIO) -> bool:
    return _black_ratio(img, threshold=threshold) >= min_dark_ratio


def _black_ratio(img: Image.Image, threshold: int = 8) -> float:
    sample = img.resize((160, 90))
    if sample.mode != "RGB":
        sample = sample.convert("RGB")
    try:
        pixels = sample.getdata()
        total = len(pixels)
        if total == 0:
            return 1.0
        dark = sum(
            1 for r, g, b in pixels if r <= threshold and g <= threshold and b <= threshold
        )
        return dark / total
    finally:
        sample.close()


def _black_ratio_rgb(
    rgb_bytes: bytes,
    width: int,
    height: int,
    threshold: int = 8,
    sample_w: int = 160,
    sample_h: int = 90,
) -> float:
    if width <= 0 or height <= 0 or not rgb_bytes:
        return 1.0

    step_x = max(1, width // sample_w)
    step_y = max(1, height // sample_h)
    dark = 0
    total = 0
    row_stride = width * 3

    for y in range(0, height, step_y):
        row_start = y * row_stride
        for x in range(0, width, step_x):
            i = row_start + x * 3
            r = rgb_bytes[i]
            g = rgb_bytes[i + 1]
            b = rgb_bytes[i + 2]
            if r <= threshold and g <= threshold and b <= threshold:
                dark += 1
            total += 1

    return dark / total if total else 1.0
