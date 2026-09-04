"""
Структурированный JSONL-лог для анализа поведения агента и повторяющихся действий.

Файл: activity_trace.jsonl (рядом с agent.log)
Формат: одна JSON-строка = одно событие. Удобно grep/jq/Excel/Power BI.

Не дублирует полностью данные сервера — фиксирует локально:
- смены окон / idle
- отправки на сервер
- циклы скриншотов и RAM
- ошибки
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIAG_ENABLED = os.environ.get("DIAG_LOG_ENABLED", "1").strip() != "0"
DIAG_MAX_BYTES = int(os.environ.get("DIAG_LOG_MAX_MB", "10")) * 1024 * 1024
DIAG_KEEP_ROTATED = int(os.environ.get("DIAG_LOG_KEEP", "3"))
MAX_TITLE_LEN = int(os.environ.get("DIAG_TITLE_MAX_LEN", "120"))

_BASE_DIR = Path(__file__).parent
TRACE_FILE = _BASE_DIR / "activity_trace.jsonl"
_lock = threading.Lock()


def truncate_text(value: str, limit: int = MAX_TITLE_LEN) -> str:
    text = (value or "").replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def log_event(event_type: str, component: str, **fields: Any) -> None:
    if not DIAG_ENABLED:
        return

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "component": component,
    }
    for key, value in fields.items():
        if isinstance(value, str):
            record[key] = truncate_text(value) if key in {"window_title", "title", "error"} else value
        else:
            record[key] = value

    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock:
        _rotate_if_needed()
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(line)


def _rotate_if_needed() -> None:
    if not TRACE_FILE.exists():
        return
    if TRACE_FILE.stat().st_size < DIAG_MAX_BYTES:
        return

    for idx in range(DIAG_KEEP_ROTATED - 1, 0, -1):
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
