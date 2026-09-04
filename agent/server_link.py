"""
Thread-safe circuit breaker для доступности сервера.

Стартуем в OFFLINE до первого успешного probe/heartbeat.
Probe — только GET /api/health с коротким timeout.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from config import SERVER_URL, API_KEY
from diag_log import log_event
from http_client import PROBE_TIMEOUT, get

logger = logging.getLogger("server_link")

HEADERS = {"X-API-Key": API_KEY}
SEND_INTERVAL = int(os.environ.get("SEND_INTERVAL", "30"))
OFFLINE_PROBE_INTERVAL = int(os.environ.get("SERVER_PROBE_INTERVAL", "120"))
HEALTH_URL = f"{SERVER_URL}/api/health"

_BASE_DIR = Path(__file__).parent
BUFFER_FILE = _BASE_DIR / "offline_buffer.jsonl"
OFFLINE_SCREENSHOT_DIR = _BASE_DIR / "screenshots_offline"

_lock = threading.RLock()
_online = False
_offline_reason: Optional[str] = None
_offline_announced = False
_next_probe_at = 0.0
_probe_running = False


def reset_state(*, start_online: bool = False) -> None:
    """Только для тестов."""
    global _online, _offline_reason, _offline_announced, _next_probe_at, _probe_running
    with _lock:
        _online = start_online
        _offline_reason = None
        _offline_announced = False
        _next_probe_at = 0.0 if not start_online else time.monotonic()
        _probe_running = False


def is_online() -> bool:
    with _lock:
        return _online


def offline_reason() -> Optional[str]:
    with _lock:
        return _offline_reason


def mark_online() -> None:
    global _online, _offline_reason, _offline_announced, _next_probe_at
    with _lock:
        was_offline = not _online
        if was_offline:
            logger.warning("Server is back online")
            log_event("server_online", "server_link")
        _online = True
        _offline_reason = None
        _offline_announced = False
        _next_probe_at = time.monotonic() + OFFLINE_PROBE_INTERVAL


def mark_offline(reason: str = "") -> None:
    global _online, _offline_reason, _offline_announced, _next_probe_at
    purge = False
    with _lock:
        was_online = _online
        _online = False
        _offline_reason = reason or _offline_reason
        _next_probe_at = time.monotonic() + OFFLINE_PROBE_INTERVAL
        if was_online and not _offline_announced:
            logger.error(
                "Server unreachable — all uploads paused (no buffering): %s",
                _offline_reason or "unknown",
            )
            log_event(
                "server_offline",
                "server_link",
                reason=_offline_reason or "unknown",
            )
            _offline_announced = True
            purge = True
    if purge:
        purge_offline_storage()


def try_probe() -> bool:
    """
    Выполняет probe, если наступило время. Thread-safe: только один поток probe'ит.
    Возвращает True, если после probe сервер online.
    """
    global _probe_running, _next_probe_at
    with _lock:
        if _online:
            return True
        now = time.monotonic()
        if now < _next_probe_at or _probe_running:
            return False
        _probe_running = True

    try:
        return _run_health_probe()
    finally:
        with _lock:
            _probe_running = False
            _next_probe_at = time.monotonic() + OFFLINE_PROBE_INTERVAL


def probe() -> bool:
    """Явный probe (используется sender). Эквивалент try_probe()."""
    return try_probe()


def _run_health_probe() -> bool:
    try:
        resp = get(HEALTH_URL, headers=HEADERS, timeout=PROBE_TIMEOUT)
        resp.raise_for_status()
        mark_online()
        return True
    except Exception as e:
        mark_offline(str(e))
        return False


def sleep_interval() -> int:
    with _lock:
        return SEND_INTERVAL if _online else OFFLINE_PROBE_INTERVAL


def purge_offline_storage() -> None:
    try:
        BUFFER_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    if not OFFLINE_SCREENSHOT_DIR.exists():
        return
    for path in OFFLINE_SCREENSHOT_DIR.glob("*.jpg"):
        try:
            path.unlink()
        except Exception:
            break
