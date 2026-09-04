"""
Жёсткий предохранитель по RAM процесса агента.

>500 MB — screenshot subsystem отключается до перезапуска.
>750 MB — безопасный restart процесса (с защитой от restart loop).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from diag_log import log_event

logger = logging.getLogger("memory_guard")

SCREENSHOT_DISABLE_MB = int(os.environ.get("AGENT_SCREENSHOT_DISABLE_MB", "500"))
AGENT_RESTART_MB = int(os.environ.get("AGENT_RESTART_MB", "750"))
MAX_RESTARTS = int(os.environ.get("AGENT_MAX_RESTARTS", "3"))
RESTART_WINDOW_SEC = int(os.environ.get("AGENT_RESTART_WINDOW_SEC", "1800"))
RESTART_COOLDOWN_SEC = int(os.environ.get("AGENT_RESTART_COOLDOWN_SEC", "600"))

_BASE_DIR = Path(__file__).parent
RESTART_STATE_FILE = _BASE_DIR / "restart_guard.json"

_lock = threading.RLock()
_screenshot_disabled = False
_restart_requested = False
_degraded_mode = False
_degraded_announced = False
_last_ram_mb = 0.0


def process_ram_mb() -> float:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return 0.0


def screenshots_allowed() -> bool:
    with _lock:
        return not _screenshot_disabled


def screenshot_disabled_reason() -> Optional[str]:
    with _lock:
        if _degraded_mode:
            return "restart_loop_protection"
        if _screenshot_disabled:
            return f"ram>={SCREENSHOT_DISABLE_MB}mb"
        return None


def is_degraded_mode() -> bool:
    with _lock:
        return _degraded_mode


def last_ram_mb() -> float:
    with _lock:
        return _last_ram_mb


def reset_for_tests() -> None:
    global _screenshot_disabled, _restart_requested, _degraded_mode, _degraded_announced, _last_ram_mb
    with _lock:
        _screenshot_disabled = False
        _restart_requested = False
        _degraded_mode = False
        _degraded_announced = False
        _last_ram_mb = 0.0
    try:
        RESTART_STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _load_restart_timestamps(now: Optional[float] = None) -> list[float]:
    now = now if now is not None else time.time()
    try:
        data = json.loads(RESTART_STATE_FILE.read_text(encoding="utf-8"))
        timestamps = [float(v) for v in data.get("timestamps", [])]
    except Exception:
        timestamps = []
    cutoff = now - RESTART_WINDOW_SEC
    return [ts for ts in timestamps if ts >= cutoff]


def _save_restart_timestamps(timestamps: list[float]) -> None:
    RESTART_STATE_FILE.write_text(
        json.dumps({"timestamps": timestamps}, separators=(",", ":")),
        encoding="utf-8",
    )


def _can_restart(now: Optional[float] = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    timestamps = _load_restart_timestamps(now)
    if len(timestamps) >= MAX_RESTARTS:
        return False, "max_restarts"
    if timestamps and (now - timestamps[-1]) < RESTART_COOLDOWN_SEC:
        return False, "cooldown"
    return True, ""


def _register_restart(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    timestamps = _load_restart_timestamps(now)
    timestamps.append(now)
    _save_restart_timestamps(timestamps)


def _enter_degraded_mode(ram_mb: float) -> None:
    global _degraded_mode, _degraded_announced, _screenshot_disabled
    with _lock:
        _degraded_mode = True
        _screenshot_disabled = True
        if _degraded_announced:
            return
        _degraded_announced = True
    logger.critical(
        "Restart loop protection active: RAM %.1f MB >= %d MB, "
        "screenshots disabled, heartbeat-only mode",
        ram_mb,
        AGENT_RESTART_MB,
    )
    log_event(
        "restart_loop_protection",
        "memory_guard",
        ram_mb=ram_mb,
        threshold_mb=AGENT_RESTART_MB,
        max_restarts=MAX_RESTARTS,
        window_sec=RESTART_WINDOW_SEC,
    )


def check_memory(force_ram_mb: Optional[float] = None) -> None:
    global _screenshot_disabled, _restart_requested, _last_ram_mb
    ram_mb = force_ram_mb if force_ram_mb is not None else process_ram_mb()

    with _lock:
        _last_ram_mb = ram_mb
        if ram_mb >= AGENT_RESTART_MB:
            _screenshot_disabled = True
            if _restart_requested or _degraded_mode:
                return
            allowed, reason = _can_restart()
            if not allowed:
                if reason == "max_restarts":
                    _enter_degraded_mode(ram_mb)
                return

            _restart_requested = True
            logger.critical(
                "Agent RAM %.1f MB >= %d MB — initiating safe restart",
                ram_mb,
                AGENT_RESTART_MB,
            )
            log_event(
                "agent_restart",
                "memory_guard",
                ram_mb=ram_mb,
                threshold_mb=AGENT_RESTART_MB,
            )
            _register_restart()
            threading.Thread(target=_safe_restart, name="AgentRestart", daemon=True).start()
            return

        if ram_mb >= SCREENSHOT_DISABLE_MB and not _screenshot_disabled:
            _screenshot_disabled = True
            logger.error(
                "Screenshot subsystem disabled until restart: RAM %.1f MB >= %d MB",
                ram_mb,
                SCREENSHOT_DISABLE_MB,
            )
            log_event(
                "screenshot_disabled",
                "memory_guard",
                ram_mb=ram_mb,
                threshold_mb=SCREENSHOT_DISABLE_MB,
            )


def _safe_restart() -> None:
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
        subprocess.Popen(cmd, close_fds=True)
    except Exception as e:
        logger.critical("Safe restart failed: %s", e)
        return
    os._exit(0)
