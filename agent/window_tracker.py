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

        self.hostname = socket.gethostname()
        self.username = get_current_username()
        self.os_version = get_os_version()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        with self._lock:
            self._flush_current()

    def _loop(self):
        while self._running:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    def _tick(self):
        idle_secs = get_idle_seconds()
        now = datetime.utcnow()

        with self._lock:
            if idle_secs >= IDLE_THRESHOLD:
                # Пользователь не активен — закрываем текущее событие, фиксируем idle
                if not self._is_idle:
                    self._flush_current(now=now)
                    self._is_idle = True
                    self._current_process = "idle"
                    self._current_title = ""
                    self._current_started = now
            else:
                info = get_active_window_info()
                new_proc = info["process_name"]
                new_title = info["window_title"]

                if self._is_idle:
                    # Вышли из idle
                    self._flush_current(now=now)
                    self._is_idle = False
                    self._current_process = new_proc
                    self._current_title = new_title
                    self._current_started = now
                elif new_proc != self._current_process or new_title != self._current_title:
                    # Сменилось окно
                    self._flush_current(now=now)
                    self._current_process = new_proc
                    self._current_title = new_title
                    self._current_started = now
                # Иначе — то же окно, продолжаем

    def _flush_current(self, now: Optional[datetime] = None):
        if not self._current_process or not self._current_started:
            return

        if now is None:
            now = datetime.utcnow()
        duration = int((now - self._current_started).total_seconds())
        if duration < 1:
            return

        event = {
            "hostname": self.hostname,
            "started_at": self._current_started.isoformat(),
            "ended_at": now.isoformat(),
            "duration_seconds": duration,
            "process_name": self._current_process,
            "window_title": self._current_title or "",
            "event_type": "idle" if self._is_idle else "focus",
        }

        # _flush_current всегда вызывается под self._lock,
        # поэтому не берем блокировку повторно.
        self._pending_events.append(event)

        self._current_process = None
        self._current_title = None
        self._current_started = None

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

    def pop_events(self) -> list:
        """Забрать накопленные события и очистить буфер."""
        with self._lock:
            events = list(self._pending_events)
            self._pending_events.clear()
        return events
