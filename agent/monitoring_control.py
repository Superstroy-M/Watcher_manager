"""
Remote monitoring state от сервера (ACTIVE / PAUSED).

PAUSED: только heartbeat + получение команд.
ACTIVE: полный сбор и отправка данных.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from diag_log import log_event

logger = logging.getLogger("monitoring")

_lock = threading.RLock()
_state = "active"


def reset_for_tests(state: str = "active") -> None:
    global _state
    with _lock:
        _state = state


def get_state() -> str:
    with _lock:
        return _state


def is_monitoring_active() -> bool:
    with _lock:
        return _state == "active"


def apply_server_state(state: Optional[str]) -> bool:
    global _state
    normalized = (state or "active").strip().lower()
    if normalized not in ("active", "paused"):
        normalized = "active"

    with _lock:
        changed = normalized != _state
        _state = normalized

    if changed:
        logger.warning("Monitoring state changed to %s", normalized.upper())
        log_event("monitoring_state", "control", state=normalized)

    return changed
