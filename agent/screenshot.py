"""
Захват скриншотов экрана и отправка на сервер.
"""
import gc
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
SCREENSHOT_INTERVAL = int(os.environ.get("SCREENSHOT_INTERVAL", "30"))
SCREENSHOT_ENABLED = os.environ.get("SCREENSHOT_ENABLED", "1").strip() != "0"
JPEG_QUALITY = int(os.environ.get("SCREENSHOT_JPEG_QUALITY", "50"))
MAX_CAPTURE_WIDTH = int(os.environ.get("SCREENSHOT_MAX_WIDTH", "1280"))
OFFLINE_DIR = Path(__file__).parent / "screenshots_offline"
BLACK_FRAME_RATIO = 0.98
OFFLINE_FLUSH_LIMIT = 3
GC_EVERY_N_CYCLES = 5


@dataclass
class CaptureMeta:
    width: int
    height: int
    source_width: int
    source_height: int
    black_ratio: float
    skipped_black: bool
    capture_ms: float
    encode_ms: float
    jpeg_bytes: int
    ram_mb: float


class ScreenshotWorker:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sct: Optional[mss.mss] = None
        self._cycle = 0

    def start(self):
        if not SCREENSHOT_ENABLED:
            logger.info("Screenshot capture disabled (SCREENSHOT_ENABLED=0)")
            return
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
                    logger.warning("Screenshot error: %s", e)
                self._cycle += 1
                if self._cycle % GC_EVERY_N_CYCLES == 0:
                    gc.collect()
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

        meta, jpeg_bytes = self._capture_jpeg()
        if jpeg_bytes is None:
            logger.info(
                "screenshot skipped capture_ms=%.1f source=%dx%d black_ratio=%.3f ram_mb=%.1f",
                meta.capture_ms,
                meta.source_width,
                meta.source_height,
                meta.black_ratio,
                meta.ram_mb,
            )
            return

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
            offline_path.write_bytes(jpeg_bytes)
            raise
        finally:
            jpeg_bytes = None

        logger.info(
            "screenshot capture_ms=%.1f encode_ms=%.1f source=%dx%d out=%dx%d "
            "black_ratio=%.3f skipped_black=%s jpeg_bytes=%d ram_mb=%.1f",
            meta.capture_ms,
            meta.encode_ms,
            meta.source_width,
            meta.source_height,
            meta.width,
            meta.height,
            meta.black_ratio,
            meta.skipped_black,
            meta.jpeg_bytes,
            meta.ram_mb,
        )

    def _capture_jpeg(self) -> tuple[CaptureMeta, Optional[bytes]]:
        if self._sct is None:
            raise RuntimeError("Screenshot capture is only supported on Windows")

        capture_start = time.perf_counter()
        raw = self._sct.grab(self._sct.monitors[0])
        source_w, source_h = raw.width, raw.height
        black_ratio = _black_ratio_bgra(raw.raw, source_w, source_h)
        capture_ms = (time.perf_counter() - capture_start) * 1000
        ram_mb = _process_ram_mb()

        meta = CaptureMeta(
            width=0,
            height=0,
            source_width=source_w,
            source_height=source_h,
            black_ratio=black_ratio,
            skipped_black=black_ratio >= BLACK_FRAME_RATIO,
            capture_ms=capture_ms,
            encode_ms=0.0,
            jpeg_bytes=0,
            ram_mb=ram_mb,
        )

        if black_ratio >= BLACK_FRAME_RATIO:
            del raw
            return meta, None

        encode_start = time.perf_counter()
        img: Optional[Image.Image] = None
        jpeg_bytes: Optional[bytes] = None
        try:
            img = Image.frombytes("RGB", (source_w, source_h), raw.rgb)
            del raw

            out_w, out_h = source_w, source_h
            if source_w > MAX_CAPTURE_WIDTH:
                out_h = max(1, round(source_h * MAX_CAPTURE_WIDTH / source_w))
                resized = img.resize((MAX_CAPTURE_WIDTH, out_h), Image.Resampling.LANCZOS)
                img.close()
                img = resized
                out_w, out_h = img.size

            with io.BytesIO() as buf:
                img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=False)
                jpeg_bytes = buf.getvalue()

            meta.width = out_w
            meta.height = out_h
            meta.encode_ms = (time.perf_counter() - encode_start) * 1000
            meta.jpeg_bytes = len(jpeg_bytes)
            meta.ram_mb = _process_ram_mb()
            return meta, jpeg_bytes
        finally:
            if img is not None:
                img.close()

    def _flush_offline(self):
        import socket

        hostname = socket.gethostname()
        files = sorted(OFFLINE_DIR.glob("*.jpg"))
        if not files:
            return
        for f in files[:OFFLINE_FLUSH_LIMIT]:
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


def _process_ram_mb() -> float:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return 0.0


def _black_ratio_bgra(
    bgra,
    width: int,
    height: int,
    threshold: int = 8,
    sample_w: int = 160,
    sample_h: int = 90,
) -> float:
    if width <= 0 or height <= 0 or not bgra:
        return 1.0

    step_x = max(1, width // sample_w)
    step_y = max(1, height // sample_h)
    dark = 0
    total = 0
    row_stride = width * 4

    for y in range(0, height, step_y):
        row_start = y * row_stride
        for x in range(0, width, step_x):
            i = row_start + x * 4
            b = bgra[i]
            g = bgra[i + 1]
            r = bgra[i + 2]
            if r <= threshold and g <= threshold and b <= threshold:
                dark += 1
            total += 1

    return dark / total if total else 1.0


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
