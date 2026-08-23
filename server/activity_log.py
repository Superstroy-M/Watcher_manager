"""
Генерация и хранение дневных отчётов активности в S3.
Рядом со скриншотами лежат activity.json и report.txt.
"""
import json
import logging
from datetime import datetime, date
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from s3_storage import get_s3, S3_BUCKET

logger = logging.getLogger("activity_log")

PRODUCTIVITY_LABELS = {
    "productive": "Рабочее",
    "neutral": "Нейтральное",
    "distracting": "Отвлечение",
}


def _activity_json_key(hostname: str, day: str) -> str:
    return f"screenshots/{hostname}/{day}/activity.json"


def _report_txt_key(hostname: str, day: str) -> str:
    return f"screenshots/{hostname}/{day}/report.txt"


def load_activity(hostname: str, day: str) -> list:
    """Загружает activity.json из S3. Возвращает [] если не существует."""
    key = _activity_json_key(hostname, day)
    try:
        resp = get_s3().get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return []
        raise


def save_activity(hostname: str, day: str, events: list):
    """
    Сохраняет/обновляет activity.json и report.txt в S3.
    events — список словарей из БД (process_name, window_title, started_at, duration_seconds, event_type, productivity).
    """
    # Загружаем существующие события
    existing = load_activity(hostname, day)
    existing_ids = {e["id"] for e in existing if "id" in e}

    # Добавляем новые
    for ev in events:
        if ev.get("id") not in existing_ids:
            existing.append(ev)

    # Сортируем по времени
    existing.sort(key=lambda e: e.get("started_at", ""))

    # Сохраняем JSON
    json_key = _activity_json_key(hostname, day)
    try:
        get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=json_key,
            Body=json.dumps(existing, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
    except Exception as e:
        logger.error(f"Save activity.json failed: {e}")
        raise

    # Генерируем и сохраняем читаемый отчёт
    _save_report_txt(hostname, day, existing)


def _save_report_txt(hostname: str, day: str, events: list):
    """Генерирует читаемый отчёт за день и сохраняет в S3."""
    lines = []
    lines.append(f"═══════════════════════════════════════════════════════════")
    lines.append(f"  SyncLayer — Отчёт активности")
    lines.append(f"  Компьютер : {hostname}")
    lines.append(f"  Дата      : {day}")
    lines.append(f"  Событий   : {len([e for e in events if e.get('event_type') != 'idle'])}")
    lines.append(f"═══════════════════════════════════════════════════════════")
    lines.append("")

    total_work = sum(
        e.get("duration_seconds", 0)
        for e in events
        if e.get("event_type") not in ("idle",) and e.get("productivity") in ("productive", "neutral")
    )
    total_distract = sum(
        e.get("duration_seconds", 0)
        for e in events
        if e.get("productivity") == "distracting"
    )
    total_idle = sum(
        e.get("duration_seconds", 0)
        for e in events
        if e.get("event_type") == "idle"
    )

    lines.append(f"СВОДКА:")
    lines.append(f"  Рабочее/нейтральное : {_fmt_time(total_work)}")
    lines.append(f"  Отвлечения          : {_fmt_time(total_distract)}")
    lines.append(f"  Простой             : {_fmt_time(total_idle)}")
    lines.append("")
    lines.append("ХРОНОЛОГИЯ:")
    lines.append("")

    for ev in events:
        started = ev.get("started_at", "")[:19].replace("T", " ")
        ended = (ev.get("ended_at") or "")[:19].replace("T", " ")
        dur = _fmt_time(ev.get("duration_seconds", 0))
        proc = ev.get("process_name", "—")
        title = ev.get("window_title", "") or ""
        etype = ev.get("event_type", "focus")
        prod = ev.get("productivity", "neutral")
        prod_label = PRODUCTIVITY_LABELS.get(prod, prod)

        if etype == "idle":
            lines.append(f"  {started}  [ПРОСТОЙ]  {dur}")
        else:
            marker = {"productive": "✓", "distracting": "✗", "neutral": "·"}.get(prod, "·")
            lines.append(f"  {started}  {marker} {proc:<30} {dur:<10} [{prod_label}]")
            if title and title != proc:
                # Обрезаем длинные заголовки
                short_title = title[:80] + ("…" if len(title) > 80 else "")
                lines.append(f"              └─ {short_title}")

    lines.append("")
    lines.append("─" * 63)
    lines.append(f"  Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")

    report = "\n".join(lines)
    txt_key = _report_txt_key(hostname, day)
    try:
        get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=txt_key,
            Body=report.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
    except Exception as e:
        logger.warning(f"Save report.txt failed: {e}")


def get_activity_for_screenshot(activity: list, screenshot_time_str: str) -> Optional[dict]:
    """
    Находит событие активности ближайшее к времени скриншота.
    screenshot_time_str — 'HH:MM:SS'
    """
    if not activity:
        return None

    def time_to_sec(t: str) -> int:
        try:
            parts = t.replace("T", " ").split(" ")[-1][:8].split(":")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            return 0

    shot_sec = time_to_sec(screenshot_time_str)

    best = None
    best_diff = 99999
    for ev in activity:
        if ev.get("event_type") == "idle":
            continue
        ev_sec = time_to_sec(ev.get("started_at", ""))
        diff = abs(shot_sec - ev_sec)
        if diff < best_diff:
            best_diff = diff
            best = ev

    return best if best_diff < 120 else None  # не дальше 2 минут


def _fmt_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м {seconds % 60}с"
    return f"{seconds // 3600}ч {(seconds % 3600) // 60}м"
