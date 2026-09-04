"""
Лёгкий счётчик активности ввода для Windows.

Собирает только агрегированные счётчики в памяти:
mouse_clicks, key_activity, scroll_events.

Не сохраняет клавиши, текст, координаты или буфер обмена.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Optional

from diag_log import is_debug_mode, log_event
from monitoring_control import is_monitoring_active

logger = logging.getLogger("input_counter")

_instance: Optional["InputCounter"] = None
_instance_lock = threading.Lock()


def get_input_counter() -> "InputCounter":
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = InputCounter()
        return _instance


def reset_input_counter_for_tests() -> None:
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.stop()
        _instance = None


class InputCounter:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mouse_clicks = 0
        self._key_activity = 0
        self._scroll_events = 0
        self._listener_started = False
        self._mouse_listener = None
        self._keyboard_listener = None

    @property
    def listener_started(self) -> bool:
        with self._lock:
            return self._listener_started

    def sync_monitoring_state(self) -> None:
        if is_monitoring_active():
            self.start()

    def start(self) -> None:
        with self._lock:
            if self._listener_started:
                return
            if sys.platform != "win32":
                self._listener_started = True
                if is_debug_mode():
                    log_event("input_counter_started", "input_counter", platform="non-windows")
                return
            try:
                from pynput import keyboard, mouse

                self._mouse_listener = mouse.Listener(
                    on_click=self._on_click,
                    on_scroll=self._on_scroll,
                )
                self._keyboard_listener = keyboard.Listener(
                    on_press=self._on_key_press,
                )
                self._mouse_listener.start()
                self._keyboard_listener.start()
                self._listener_started = True
                if is_debug_mode():
                    log_event("input_counter_started", "input_counter")
            except Exception as exc:
                logger.warning("InputCounter listener start failed: %s", exc)

    def stop(self) -> None:
        with self._lock:
            if not self._listener_started:
                return
            for listener in (self._mouse_listener, self._keyboard_listener):
                if listener is not None:
                    try:
                        listener.stop()
                    except Exception:
                        pass
            self._mouse_listener = None
            self._keyboard_listener = None
            self._listener_started = False
            if is_debug_mode():
                log_event("input_counter_stopped", "input_counter")

    def _collecting(self) -> bool:
        return is_monitoring_active()

    def _on_click(self, _x, _y, _button, pressed) -> None:
        if pressed:
            self.record_click()

    def _on_scroll(self, _x, _y, _dx, _dy) -> None:
        self.record_scroll()

    def _on_key_press(self, _key) -> None:
        self.record_key()

    def record_click(self) -> None:
        if not self._collecting():
            return
        with self._lock:
            self._mouse_clicks += 1

    def record_key(self) -> None:
        if not self._collecting():
            return
        with self._lock:
            self._key_activity += 1

    def record_scroll(self) -> None:
        if not self._collecting():
            return
        with self._lock:
            self._scroll_events += 1

    def peek(self) -> dict[str, int]:
        with self._lock:
            return {
                "mouse_clicks": self._mouse_clicks,
                "key_activity": self._key_activity,
                "scroll_events": self._scroll_events,
            }

    def take_and_reset(self) -> dict[str, int]:
        with self._lock:
            totals = {
                "mouse_clicks": self._mouse_clicks,
                "key_activity": self._key_activity,
                "scroll_events": self._scroll_events,
            }
            self._mouse_clicks = 0
            self._key_activity = 0
            self._scroll_events = 0
            if is_debug_mode() and any(totals.values()):
                log_event(
                    "input_session_flush",
                    "input_counter",
                    mouse_clicks=totals["mouse_clicks"],
                    key_activity=totals["key_activity"],
                    scroll_events=totals["scroll_events"],
                )
            return totals
