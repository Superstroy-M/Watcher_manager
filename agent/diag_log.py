"""
Структурированный JSONL-лог для TEST/DEBUG режима агента.

Файл: activity_trace.jsonl (рядом с SyncLayerAgent.exe / agent.log)
Формат: одна JSON-строка = одно событие.

SYNCLAYER_DEBUG=1 — подробная трассировка для тестового ПК.
SYNCLAYER_DEBUG=0 — activity_trace.jsonl не пополняется (минимальный режим).

Не логирует содержимое документов, заголовков окон, нажатий клавиш и паролей.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEBUG_MODE = os.environ.get("SYNCLAYER_DEBUG", "0").strip() == "1"

TRACE_MAX_BYTES = 10 * 1024 * 1024
TRACE_KEEP_ROTATED = 3
MAX_ERROR_LEN = 240

# Поля, которые никогда не пишем в trace (PII / содержимое документов).
_BLOCKED_FIELD_KEYS = frozenset({
    "window_title",
    "title",
    "document",
    "document_name",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "clipboard",
    "form_text",
    "key",
    "keystroke",
    "keyboard",
    "typed_text",
    "input_text",
    "x",
    "y",
    "mouse_x",
    "mouse_y",
    "coordinates",
    "coordinate",
    "click_x",
    "click_y",
})

# В minimal-режиме trace не используется; исключения — только в agent.log.
_MINIMAL_TRACE_EVENTS = frozenset()

_lock = threading.Lock()


def get_agent_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


TRACE_FILE = get_agent_dir() / "activity_trace.jsonl"


def is_debug_mode() -> bool:
    return DEBUG_MODE


def truncate_text(value: str, limit: int = 120) -> str:
    text = (value or "").replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in fields.items():
        lowered = key.lower()
        if lowered in _BLOCKED_FIELD_KEYS:
            continue
        if isinstance(value, str):
            if lowered == "error":
                clean[key] = truncate_text(value, MAX_ERROR_LEN)
            else:
                clean[key] = value
        else:
            clean[key] = value
    return clean


def _should_trace(event_type: str) -> bool:
    if DEBUG_MODE:
        return True
    return event_type in _MINIMAL_TRACE_EVENTS


def process_memory_stats() -> dict[str, float]:
    try:
        import psutil

        mem = psutil.Process(os.getpid()).memory_info()
        rss_mb = round(mem.rss / (1024 * 1024), 1)
        private_bytes = getattr(mem, "private", None)
        if private_bytes is None:
            private_bytes = mem.rss
        private_mb = round(private_bytes / (1024 * 1024), 1)
        return {"ram_mb": rss_mb, "private_mb": private_mb}
    except Exception:
        return {"ram_mb": 0.0, "private_mb": 0.0}


def log_event(event_type: str, component: str, **fields: Any) -> None:
    if not _should_trace(event_type):
        return

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "component": component,
        **_sanitize_fields(fields),
    }

    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock:
        _rotate_trace_if_needed()
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACE_FILE, "a", encoding="utf-8") as handle:
            handle.write(line)

    if DEBUG_MODE:
        payload = json.dumps(_sanitize_fields(fields), ensure_ascii=False)
        logging.getLogger(component).info("trace %s %s", event_type, payload)


def log_exception(component: str, exc: BaseException, *, context: str = "") -> None:
    logger = logging.getLogger(component)
    logger.exception("Uncaught exception%s", f" ({context})" if context else "")

    if not DEBUG_MODE:
        return

    log_event(
        "uncaught_exception",
        component,
        context=context or None,
        error=truncate_text(str(exc), MAX_ERROR_LEN),
        exc_type=type(exc).__name__,
    )


def log_memory_sample(component: str = "app") -> None:
    if not DEBUG_MODE:
        return
    stats = process_memory_stats()
    log_event(
        "memory_sample",
        component,
        pid=os.getpid(),
        ram_mb=stats["ram_mb"],
        private_mb=stats["private_mb"],
    )


def _rotate_trace_if_needed() -> None:
    if not TRACE_FILE.exists():
        return
    if TRACE_FILE.stat().st_size < TRACE_MAX_BYTES:
        return

    for idx in range(TRACE_KEEP_ROTATED - 1, 0, -1):
        src = TRACE_FILE.with_name(f"activity_trace.{idx}.jsonl")
        dst = TRACE_FILE.with_name(f"activity_trace.{idx + 1}.jsonl")
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)

    rotated = TRACE_FILE.with_name("activity_trace.1.jsonl")
    if rotated.exists():
        rotated.unlink()
    TRACE_FILE.rename(rotated)
