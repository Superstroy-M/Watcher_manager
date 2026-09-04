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
from typing import Optional

from PIL import Image

from config import SERVER_URL, API_KEY, CONTEXT_SCREENSHOT_DEBOUNCE_SEC
from context_events import register_context_listener, unregister_context_listener
from diag_log import is_debug_mode, log_event
from http_client import is_transport_error, post
from memory_guard import check_memory, process_ram_mb, screenshots_allowed
from monitoring_control import is_monitoring_active
from server_link import is_online

logger = logging.getLogger("screenshot")

HEADERS = {"X-API-Key": API_KEY}
SCREENSHOT_INTERVAL = int(os.environ.get("SCREENSHOT_INTERVAL", "30"))
SCREENSHOT_ENABLED = os.environ.get("SCREENSHOT_ENABLED", "1").strip() != "0"
JPEG_QUALITY = int(os.environ.get("SCREENSHOT_JPEG_QUALITY", "50"))
MAX_CAPTURE_WIDTH = int(os.environ.get("SCREENSHOT_MAX_WIDTH", "1280"))
MAX_SOURCE_PIXELS = int(os.environ.get("SCREENSHOT_MAX_PIXELS", "6000000"))
BLACK_FRAME_RATIO = 0.98
GC_EVERY_N_CYCLES = 5
CAPTURE_TIMEOUT_SEC = int(os.environ.get("SCREENSHOT_CAPTURE_TIMEOUT", "45"))
MSS_CAPTURE_FAILURE_LIMIT = int(os.environ.get("SCREENSHOT_MSS_FAILURE_LIMIT", "3"))


def _configure_mss_windows() -> None:
    if sys.platform != "win32":
        return
    import mss.windows

    mss.windows.CAPTUREBLT = 0


def _is_mss_capture_error(exc: BaseException) -> bool:
    if isinstance(exc, AttributeError) and "srcdc" in str(exc):
        return True
    if isinstance(exc, RuntimeError) and "wrong thread" in str(exc).lower():
        return True
    return False


@dataclass
class CaptureMeta:
    width: int
    height: int
    source_width: int
    source_height: int
    black_ratio: float
    skipped_black: bool
    skipped_reason: str
    capture_ms: float
    encode_ms: float
    jpeg_bytes: int
    ram_mb: float


class ScreenshotWorker:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cycle = 0
        self._flight_lock = threading.Lock()
        self._last_context_shot_at = 0.0
        self._context_handler = self._on_context_change
        self._context_lock = threading.Lock()
        self._context_pending = False
        self._worker_thread_id: Optional[int] = None
        self._mss_failures = 0
        self._mss_capture_disabled = False

    def start(self):
        if not SCREENSHOT_ENABLED:
            logger.info("Screenshot capture disabled (SCREENSHOT_ENABLED=0)")
            return
        register_context_listener(self._context_handler)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ScreenshotWorker")
        self._thread.start()

    def stop(self):
        self._running = False
        unregister_context_listener(self._context_handler)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=SCREENSHOT_INTERVAL + 5)

    def _on_context_change(self, _process_name: str, _window_title: str) -> None:
        now = time.monotonic()
        if now - self._last_context_shot_at < CONTEXT_SCREENSHOT_DEBOUNCE_SEC:
            if is_debug_mode():
                log_event("screenshot_skipped", "screenshot", reason="context_debounce")
            return
        if not self._running:
            return
        if not is_online() or not is_monitoring_active() or not screenshots_allowed():
            return
        self._last_context_shot_at = now
        with self._context_lock:
            self._context_pending = True

    def _loop(self):
        self._worker_thread_id = threading.get_ident()
        _configure_mss_windows()
        try:
            import ctypes

            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -2
            )
        except Exception:
            pass

        while self._running:
            try:
                check_memory()
                if not is_online() or not is_monitoring_active():
                    time.sleep(SCREENSHOT_INTERVAL)
                    continue
                if not screenshots_allowed() or self._mss_capture_disabled:
                    time.sleep(SCREENSHOT_INTERVAL)
                    continue

                trigger = "interval"
                with self._context_lock:
                    if self._context_pending:
                        self._context_pending = False
                        trigger = "context"

                self._capture_and_send(trigger=trigger)
            except Exception as e:
                logger.warning("Screenshot error: %s", e)
                log_event("screenshot_error", "screenshot", error=str(e))
            self._cycle += 1
            if self._cycle % GC_EVERY_N_CYCLES == 0:
                gc.collect()
            time.sleep(SCREENSHOT_INTERVAL)

    def _capture_and_send(self, trigger: str = "interval"):
        import socket

        if (
            not is_online()
            or not is_monitoring_active()
            or not screenshots_allowed()
            or self._mss_capture_disabled
        ):
            return

        if not self._flight_lock.acquire(blocking=False):
            logger.info("Screenshot skipped: previous capture still running")
            log_event("screenshot_skipped", "screenshot", reason="single_flight_busy")
            return

        jpeg_bytes: Optional[bytes] = None
        try:
            timestamp = datetime.utcnow()
            ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
            hostname = socket.gethostname()

            meta, jpeg_bytes = self._capture_jpeg()
            if jpeg_bytes is None:
                if meta.skipped_reason:
                    logger.info(
                        "screenshot skipped reason=%s capture_ms=%.1f source=%dx%d black_ratio=%.3f ram_mb=%.1f",
                        meta.skipped_reason,
                        meta.capture_ms,
                        meta.source_width,
                        meta.source_height,
                        meta.black_ratio,
                        meta.ram_mb,
                    )
                    log_event(
                        "screenshot_skipped",
                        "screenshot",
                        reason=meta.skipped_reason,
                        source_width=meta.source_width,
                        source_height=meta.source_height,
                        black_ratio=round(meta.black_ratio, 3),
                        capture_ms=round(meta.capture_ms, 1),
                        ram_mb=meta.ram_mb,
                        trigger=trigger,
                    )
                return

            resp = post(
                f"{SERVER_URL}/api/screenshot",
                files={"file": (f"{ts_str}.jpg", jpeg_bytes, "image/jpeg")},
                data={"hostname": hostname, "timestamp": timestamp.isoformat()},
                headers=HEADERS,
            )
            resp.raise_for_status()

            logger.info(
                "screenshot capture_ms=%.1f encode_ms=%.1f source=%dx%d out=%dx%d "
                "black_ratio=%.3f jpeg_bytes=%d ram_mb=%.1f",
                meta.capture_ms,
                meta.encode_ms,
                meta.source_width,
                meta.source_height,
                meta.width,
                meta.height,
                meta.black_ratio,
                meta.jpeg_bytes,
                meta.ram_mb,
            )
            log_event(
                "screenshot_sent",
                "screenshot",
                source_width=meta.source_width,
                source_height=meta.source_height,
                out_width=meta.width,
                out_height=meta.height,
                capture_ms=round(meta.capture_ms, 1),
                encode_ms=round(meta.encode_ms, 1),
                jpeg_bytes=meta.jpeg_bytes,
                ram_mb=meta.ram_mb,
                trigger=trigger,
            )
        except Exception as e:
            if _is_mss_capture_error(e):
                self._mss_failures += 1
                if self._mss_failures >= MSS_CAPTURE_FAILURE_LIMIT:
                    self._mss_capture_disabled = True
                    logger.error(
                        "Screenshot capture disabled after %d MSS thread errors",
                        self._mss_failures,
                    )
                    log_event(
                        "screenshot_disabled",
                        "screenshot",
                        reason="mss_thread_error",
                        failures=self._mss_failures,
                    )
            elif is_transport_error(e):
                logger.warning("Screenshot upload failed (%s): %s", trigger, e)
            else:
                logger.warning("Screenshot failed (%s): %s", trigger, e)
            log_event("screenshot_error", "screenshot", error=str(e), trigger=trigger)
        finally:
            jpeg_bytes = None
            self._flight_lock.release()

    def _capture_jpeg(self) -> tuple[CaptureMeta, Optional[bytes]]:
        """
        MSS instance is created and closed in this call (same thread as grab).
        """
        if sys.platform != "win32":
            raise RuntimeError("Screenshot capture is only supported on Windows")

        if self._worker_thread_id is not None and threading.get_ident() != self._worker_thread_id:
            raise RuntimeError("mss capture invoked from wrong thread")

        import mss

        _configure_mss_windows()
        sct = mss.mss()
        try:
            capture_start = time.perf_counter()
            monitor = _pick_monitor(sct)
            raw = sct.grab(monitor)
            try:
                source_w, source_h = raw.width, raw.height
                black_ratio = _black_ratio_bgra(raw.raw, source_w, source_h)
                capture_ms = (time.perf_counter() - capture_start) * 1000
                ram_mb = process_ram_mb()

                meta = CaptureMeta(
                    width=0,
                    height=0,
                    source_width=source_w,
                    source_height=source_h,
                    black_ratio=black_ratio,
                    skipped_black=black_ratio >= BLACK_FRAME_RATIO,
                    skipped_reason="",
                    capture_ms=capture_ms,
                    encode_ms=0.0,
                    jpeg_bytes=0,
                    ram_mb=ram_mb,
                )

                if black_ratio >= BLACK_FRAME_RATIO:
                    meta.skipped_reason = "black_frame"
                    return meta, None

                if source_w * source_h > MAX_SOURCE_PIXELS:
                    meta.skipped_reason = "source_too_large"
                    return meta, None

                rgb_bytes = raw.rgb
            finally:
                del raw

            encode_start = time.perf_counter()
            img: Optional[Image.Image] = None
            jpeg_bytes: Optional[bytes] = None
            try:
                img = Image.frombytes("RGB", (source_w, source_h), rgb_bytes)
            finally:
                del rgb_bytes

            try:
                out_w, out_h = source_w, source_h
                if source_w > MAX_CAPTURE_WIDTH:
                    out_h = max(1, round(source_h * MAX_CAPTURE_WIDTH / source_w))
                    resized = img.resize((MAX_CAPTURE_WIDTH, out_h), Image.Resampling.BILINEAR)
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
                meta.ram_mb = process_ram_mb()
                return meta, jpeg_bytes
            finally:
                if img is not None:
                    img.close()
        finally:
            sct.close()


def _pick_monitor(sct) -> dict:
    monitors = sct.monitors
    if len(monitors) > 1:
        return monitors[1]
    return monitors[0]


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
