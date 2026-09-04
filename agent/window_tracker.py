"""
Отслеживание активного окна через Windows API (pywin32).
Собирает события и возвращает их батчами для отправки на сервер.
"""
import time
import os
import socket
import threading
from datetime import datetime
from typing import Optional

import win32gui
import win32process
import win32api
import win32con
import psutil
import ctypes

from config import POLL_INTERVAL, IDLE_THRESHOLD
from context_events import notify_context_change
from diag_log import log_event
from input_counter import get_input_counter
from monitoring_control import is_monitoring_active

MAX_PENDING_EVENTS = int(os.environ.get("TRACKER_MAX_PENDING_EVENTS", "1000"))


def get_idle_seconds() -> float:
    """Время в секундах с последнего действия пользователя (мышь/клавиатура)."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    millis = win32api.GetTickCount() - info.dwTime
    return millis / 1000.0


def get_active_window_info() -> dict:
    """Возвращает информацию об активном окне."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return {"process_name": "unknown", "window_title": "", "pid": 0}

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        process_name = proc.name()
    except Exception:
        process_name = "unknown"
        pid = 0

    try:
        window_title = win32gui.GetWindowText(hwnd)
    except Exception:
        window_title = ""

    return {
        "process_name": process_name,
        "window_title": window_title,
        "pid": pid,
    }


def get_current_username() -> str:
    try:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    except Exception:
        return "unknown"


def get_os_version() -> str:
    try:
        import platform
        return platform.platform()
    except Exception:
        return "Windows"


class WindowTracker:
    """
    Главный трекер. Запускается в потоке, копит события,
    каждые N секунд отдаёт батч для отправки.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._pending_events: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._current_process: Optional[str] = None
        self._current_title: Optional[str] = None
        self._current_started: Optional[datetime] = None
        self._is_idle = False
        self._session_idle_seconds = 0
        self._last_poll_monotonic = time.monotonic()

        self.hostname = socket.gethostname()
        self.username = get_current_username()
        self.os_version = get_os_version()
        self._input_counter = get_input_counter()

    def start(self):
        self._input_counter.sync_monitoring_state()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        with self._lock:
            self._flush_current()
        self._input_counter.stop()

    def _loop(self):
        while self._running:
            try:
                self._input_counter.sync_monitoring_state()
                self._tick()
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    def _accumulate_session_idle(self, idle_secs: float) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_poll_monotonic)
        self._last_poll_monotonic = now
        if idle_secs >= IDLE_THRESHOLD:
            return
        if idle_secs >= min(POLL_INTERVAL, IDLE_THRESHOLD / 2):
            self._session_idle_seconds += int(min(elapsed, idle_secs))

    def _tick(self):
        if not is_monitoring_active():
            return

        idle_secs = get_idle_seconds()
        now = datetime.utcnow()

        with self._lock:
            self._accumulate_session_idle(idle_secs)

            if idle_secs >= IDLE_THRESHOLD:
                if not self._is_idle:
                    self._flush_current(now=now)
                    self._is_idle = True
                    self._current_process = "idle"
                    self._current_title = ""
                    self._current_started = now
                    self._session_idle_seconds = 0
            else:
                info = get_active_window_info()
                new_proc = info["process_name"]
                new_title = info["window_title"]

                if self._is_idle:
                    self._flush_current(now=now)
                    self._is_idle = False
                    self._current_process = new_proc
                    self._current_title = new_title
                    self._current_started = now
                    self._session_idle_seconds = 0
                    notify_context_change(new_proc, new_title)
                elif new_proc != self._current_process or new_title != self._current_title:
                    self._flush_current(now=now)
                    self._current_process = new_proc
                    self._current_title = new_title
                    self._current_started = now
                    self._session_idle_seconds = 0
                    notify_context_change(new_proc, new_title)

    def _flush_current(self, now: Optional[datetime] = None):
        if not self._current_process or not self._current_started:
            return

        if now is None:
            now = datetime.utcnow()
        duration = int((now - self._current_started).total_seconds())
        if duration < 1:
            return

        counters = self._input_counter.take_and_reset()
        is_idle_event = self._is_idle or self._current_process == "idle"
        idle_seconds = duration if is_idle_event else min(self._session_idle_seconds, duration)

        event = {
            "hostname": self.hostname,
            "started_at": self._current_started.isoformat(),
            "ended_at": now.isoformat(),
            "duration_seconds": duration,
            "process_name": self._current_process,
            "window_title": self._current_title or "",
            "event_type": "idle" if is_idle_event else "focus",
            "mouse_clicks": counters["mouse_clicks"],
            "key_activity": counters["key_activity"],
            "scroll_events": counters["scroll_events"],
            "idle_seconds": idle_seconds,
        }

        self._pending_events.append(event)
        if len(self._pending_events) > MAX_PENDING_EVENTS:
            overflow = len(self._pending_events) - MAX_PENDING_EVENTS
            del self._pending_events[:overflow]

        log_event(
            "activity_segment",
            "tracker",
            process_name=self._current_process or event["process_name"],
            duration_seconds=duration,
            segment_type=event["event_type"],
            mouse_clicks=event["mouse_clicks"],
            key_activity=event["key_activity"],
            scroll_events=event["scroll_events"],
            idle_seconds=idle_seconds,
        )

        self._current_process = None
        self._current_title = None
        self._current_started = None
        self._session_idle_seconds = 0

    def force_checkpoint(self):
        """
        Принудительно закрывает текущий интервал и сразу открывает новый
        с тем же приложением. Нужен, чтобы события появлялись регулярно,
        даже если пользователь долго в одном окне.
        """
        now = datetime.utcnow()
        with self._lock:
            if not self._current_process or not self._current_started:
                return
            process_name = self._current_process
            window_title = self._current_title
            is_idle = self._is_idle
            self._flush_current(now=now)
            self._current_process = process_name
            self._current_title = window_title
            self._is_idle = is_idle
            self._current_started = now
            self._session_idle_seconds = 0

    def pop_events(self) -> list:
        """Забрать накопленные события и очистить буфер."""
        with self._lock:
            events = list(self._pending_events)
            self._pending_events.clear()
        return events
