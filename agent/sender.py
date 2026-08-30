"""
Отправка событий на сервер. Буферизует при недоступности сети.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import requests

from config import SERVER_URL, API_KEY, AGENT_VERSION, IDLE_THRESHOLD
from window_tracker import get_active_window_info, get_idle_seconds

logger = logging.getLogger("sender")

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
BUFFER_FILE = Path(__file__).parent / "offline_buffer.jsonl"
SEND_INTERVAL = 30  # секунд


class EventSender:
    def __init__(self, tracker):
        self.tracker = tracker
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._send_heartbeat()
                self._send_events()
            except Exception as e:
                logger.warning(f"Send error: {e}")
            time.sleep(SEND_INTERVAL)

    def _send_heartbeat(self):
        import socket
        import os
        import platform

        payload = {
            "hostname": socket.gethostname(),
            "ip_address": _get_local_ip(),
            "username": os.environ.get("USERNAME") or os.environ.get("USER"),
            "os_version": platform.platform(),
            "agent_version": AGENT_VERSION,
        }
        resp = requests.post(
            f"{SERVER_URL}/api/heartbeat",
            json=payload,
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()

    def _send_events(self):
        import socket

        # Чтобы в дашборде были данные даже без переключения окон:
        # делаем срез текущей сессии раз в SEND_INTERVAL.
        try:
            self.tracker.force_checkpoint()
        except Exception:
            pass

        # Сначала пробуем отправить то, что лежит в буфере офлайн
        buffered = _load_buffer()

        live_events = self.tracker.pop_events()

        all_events = buffered + live_events
        if not all_events:
            fallback = self._build_fallback_event()
            if fallback:
                all_events = [fallback]
            else:
                return

        # Группируем по hostname (всегда один, но на всякий случай)
        hostname = socket.gethostname()
        payload = {"hostname": hostname, "events": all_events}

        try:
            resp = requests.post(
                f"{SERVER_URL}/api/events",
                json=payload,
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            _clear_buffer()
        except Exception:
            # Сервер недоступен — сохраняем в файл-буфер
            _save_to_buffer(all_events)
            raise

    def _build_fallback_event(self):
        """Резервный срез активности, если основной трекер ничего не дал."""
        try:
            now = datetime.utcnow()
            started = now - timedelta(seconds=SEND_INTERVAL)
            idle_secs = get_idle_seconds()
            if idle_secs >= IDLE_THRESHOLD:
                return {
                    "hostname": "",
                    "started_at": started.isoformat(),
                    "ended_at": now.isoformat(),
                    "duration_seconds": SEND_INTERVAL,
                    "process_name": "idle",
                    "window_title": "",
                    "event_type": "idle",
                }

            info = get_active_window_info()
            return {
                "hostname": "",
                "started_at": started.isoformat(),
                "ended_at": now.isoformat(),
                "duration_seconds": SEND_INTERVAL,
                "process_name": info.get("process_name") or "unknown",
                "window_title": info.get("window_title") or "",
                "event_type": "focus",
            }
        except Exception:
            return None


def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _load_buffer() -> List[dict]:
    if not BUFFER_FILE.exists():
        return []
    events = []
    try:
        with open(BUFFER_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception:
        pass
    return events


def _save_to_buffer(events: List[dict]):
    try:
        with open(BUFFER_FILE, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _clear_buffer():
    try:
        BUFFER_FILE.unlink(missing_ok=True)
    except Exception:
        pass
