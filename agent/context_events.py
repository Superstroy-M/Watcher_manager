"""
Уведомления о смене активного окна/приложения (для event-driven screenshots).
"""
from __future__ import annotations

import threading
from typing import Callable

_lock = threading.Lock()
_listeners: list[Callable[[str, str], None]] = []


def register_context_listener(callback: Callable[[str, str], None]) -> None:
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def unregister_context_listener(callback: Callable[[str, str], None]) -> None:
    with _lock:
        if callback in _listeners:
            _listeners.remove(callback)


def notify_context_change(process_name: str, window_title: str) -> None:
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(process_name or "", window_title or "")
        except Exception:
            pass
