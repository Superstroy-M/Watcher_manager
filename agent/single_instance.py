"""
Гарантирует один процесс SyncLayerAgent.exe на машине (Windows mutex).
"""
from __future__ import annotations

import logging
import os
import sys
import time

logger = logging.getLogger("single_instance")

_MUTEX_NAME = "Global\\SyncLayerAgent_SingleInstance_v1"
_mutex_handle = None
RESTART_WAIT_SEC = float(os.environ.get("SYNCLAYER_RESTART_WAIT_SEC", "15"))
DUPLICATE_WAIT_SEC = float(os.environ.get("SYNCLAYER_DUPLICATE_WAIT_SEC", "3"))


def _create_mutex(take_ownership: bool):
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, take_ownership, _MUTEX_NAME)
    if not handle:
        raise OSError("CreateMutexW failed")
    return handle, kernel32.GetLastError()


def _close_handle(handle) -> None:
    import ctypes

    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def acquire_or_exit() -> None:
    if sys.platform != "win32":
        return

    global _mutex_handle
    handle, last_error = _create_mutex(take_ownership=True)
    if last_error != 183:  # ERROR_ALREADY_EXISTS
        _mutex_handle = handle
        return

    _close_handle(handle)

    if os.environ.get("SYNCLAYER_RESTART") == "1":
        deadline = time.monotonic() + RESTART_WAIT_SEC
        while time.monotonic() < deadline:
            time.sleep(0.5)
            retry_handle, retry_error = _create_mutex(take_ownership=True)
            if retry_error != 183:
                _mutex_handle = retry_handle
                logger.info("Acquired single-instance mutex after restart wait")
                return
            _close_handle(retry_handle)
        logger.warning("Restart mutex wait timed out after %.0fs", RESTART_WAIT_SEC)

    deadline = time.monotonic() + DUPLICATE_WAIT_SEC
    while time.monotonic() < deadline:
        time.sleep(0.2)
        retry_handle, retry_error = _create_mutex(take_ownership=True)
        if retry_error != 183:
            _mutex_handle = retry_handle
            logger.info("Acquired single-instance mutex after duplicate wait")
            return
        _close_handle(retry_handle)

    logger.warning("Another SyncLayerAgent instance is already running - exiting")
    sys.exit(0)
