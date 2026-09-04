"""
Генерация и хранение аналитических файлов за день в S3:
  activity.json  — сырые события (с метаданными скриншота)
  timeline.json  — дедуплицированные сессии (09:00–09:18 Chrome × 38 скринов)
  summary.json   — агрегаты за день
  report.html    — HTML-отчёт (генерируется по запросу, не при каждом событии)
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from s3_storage import get_s3, S3_BUCKET

logger = logging.getLogger("activity_log")

# ─── Справочники ─────────────────────────────────────────────────────────────

APP_NAMES: dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "firefox.exe": "Mozilla Firefox",
    "msedge.exe": "Microsoft Edge",
    "opera.exe": "Opera",
    "1cv8.exe": "1С:Предприятие",
    "excel.exe": "Microsoft Excel",
    "word.exe": "Microsoft Word",
    "winword.exe": "Microsoft Word",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Microsoft Outlook",
    "teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "telegram.exe": "Telegram",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "code.exe": "VS Code",
    "pycharm64.exe": "PyCharm",
    "devenv.exe": "Visual Studio",
    "notepad++.exe": "Notepad++",
    "notepad.exe": "Блокнот",
    "mstsc.exe": "Remote Desktop",
    "putty.exe": "PuTTY",
    "winscp.exe": "WinSCP",
    "filezilla.exe": "FileZilla",
    "acrobat.exe": "Adobe Acrobat",
    "acrord32.exe": "Adobe Reader",
    "explorer.exe": "Проводник",
    "idle": "Простой",
}

APP_CATEGORIES: dict[str, str] = {
    "chrome.exe": "browser",
    "firefox.exe": "browser",
    "msedge.exe": "browser",
    "opera.exe": "browser",
    "1cv8.exe": "erp",
    "excel.exe": "office",
    "word.exe": "office",
    "winword.exe": "office",
    "powerpnt.exe": "office",
    "outlook.exe": "email",
    "teams.exe": "communication",
    "zoom.exe": "communication",
    "telegram.exe": "messenger",
    "discord.exe": "messenger",
    "slack.exe": "messenger",
    "code.exe": "development",
    "pycharm64.exe": "development",
    "devenv.exe": "development",
    "mstsc.exe": "remote",
    "idle": "idle",
}

PRODUCTIVITY: dict[str, str] = {
    "1cv8.exe": "productive",
    "excel.exe": "productive",
    "word.exe": "productive",
    "winword.exe": "productive",
    "powerpnt.exe": "productive",
    "outlook.exe": "productive",
    "teams.exe": "productive",
    "zoom.exe": "productive",
    "code.exe": "productive",
    "pycharm64.exe": "productive",
    "devenv.exe": "productive",
    "mstsc.exe": "productive",
    "putty.exe": "productive",
    "winscp.exe": "productive",
    "filezilla.exe": "productive",
    "telegram.exe": "neutral",
    "discord.exe": "distracting",
    "slack.exe": "neutral",
    "chrome.exe": "neutral",
    "firefox.exe": "neutral",
    "msedge.exe": "neutral",
    "idle": "idle",
}

DISTRACTING_SITES = [
    "youtube", "vk.com", "ok.ru", "instagram", "tiktok",
    "twitch", "facebook", "twitter", "reddit", "netflix", "pikabu",
]


def _get_app_name(proc: str) -> str:
    return APP_NAMES.get((proc or "").lower(), proc or "unknown")


def _get_category(proc: str) -> str:
    return APP_CATEGORIES.get((proc or "").lower(), "other")


def _get_productivity(proc: str, title: str = "") -> str:
    p = (proc or "").lower()
    t = (title or "").lower()
    base = PRODUCTIVITY.get(p, "neutral")
    if base == "neutral" and _get_category(p) == "browser":
        if any(s in t for s in DISTRACTING_SITES):
            return "distracting"
    return base


def _session_id(hostname: str, started_at: str, app: str) -> str:
    raw = f"{hostname}:{started_at}:{app}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _fmt(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м {seconds % 60}с"
    return f"{seconds // 3600}ч {(seconds % 3600) // 60}м"


def _ts_to_sec(ts: str) -> int:
    """HH:MM:SS или ISO → секунды от полуночи."""
    try:
        t = ts.replace("T", " ").split(" ")[-1][:8]
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except Exception:
        return 0


# ─── S3 helpers ──────────────────────────────────────────────────────────────

def _s3_key(hostname: str, day: str, filename: str) -> str:
    return f"screenshots/{hostname}/{day}/{filename}"


def _s3_get_json(hostname: str, day: str, filename: str) -> list | dict:
    try:
        resp = get_s3().get_object(
            Bucket=S3_BUCKET,
            Key=_s3_key(hostname, day, filename),
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return [] if filename == "activity.json" else {}


def _s3_put(hostname: str, day: str, filename: str, content: bytes, content_type: str):
    get_s3().put_object(
        Bucket=S3_BUCKET,
        Key=_s3_key(hostname, day, filename),
        Body=content,
        ContentType=content_type,
    )


# ─── Публичные функции ────────────────────────────────────────────────────────

def load_activity(hostname: str, day: str) -> list:
    return _s3_get_json(hostname, day, "activity.json")  # type: ignore


def save_activity(hostname: str, day: str, events: list):
    """
    Добавляет новые события в activity.json.
    Сохраняет activity.json, timeline.json, summary.json.
    report.html — НЕ генерируется здесь (только по запросу).
    """
    existing: list = load_activity(hostname, day)
    existing_keys = {
        (e.get("timestamp", "") or e.get("started_at", ""), e.get("app", ""))
        for e in existing
    }

    for ev in events:
        key = (ev.get("started_at", ""), ev.get("process_name") or ev.get("app", ""))
        if key in existing_keys:
            continue
        proc = ev.get("process_name") or ev.get("app", "")
        title = ev.get("window_title") or ev.get("title", "")
        started = ev.get("started_at", "")
        ended = ev.get("ended_at", "")
        dur = ev.get("duration_seconds", 0)
        etype = ev.get("event_type", "focus")

        # Угадываем ближайший скриншот по времени
        shot_time = started[11:19].replace(":", "-") if len(started) >= 19 else ""
        shot_file = f"{shot_time}.jpg" if shot_time else None

        enriched = {
            "timestamp": started,
            "ended_at": ended,
            "screenshot": shot_file,
            "app": proc,
            "app_name": _get_app_name(proc),
            "window_title": title,
            "category": _get_category(proc),
            "productivity": _get_productivity(proc, title),
            "event_type": etype,
            "duration_seconds": dur,
            "active": etype != "idle",
            "session_id": _session_id(hostname, started, proc),
        }
        existing.append(enriched)
        existing_keys.add(key)

    existing.sort(key=lambda e: e.get("timestamp", ""))

    try:
        _s3_put(hostname, day, "activity.json",
                json.dumps(existing, ensure_ascii=False, indent=2).encode(),
                "application/json; charset=utf-8")
        _save_timeline(hostname, day, existing)
        _save_summary(hostname, day, existing)
    except Exception as e:
        logger.error(f"save_activity failed: {e}")
        raise


def _save_timeline(hostname: str, day: str, events: list):
    """
    Дедуплицирует события в сессии.
    Последовательные события с одним app/title (или пауза < 90с) — одна сессия.
    """
    sessions = []
    current: Optional[dict] = None

    for ev in events:
        if ev.get("event_type") == "idle":
            if current:
                sessions.append(current)
                current = None
            sessions.append({
                "session_id": ev.get("session_id", ""),
                "started_at": ev.get("timestamp", ""),
                "ended_at": ev.get("ended_at", ""),
                "duration_seconds": ev.get("duration_seconds", 0),
                "app": "idle",
                "app_name": "Простой",
                "window_title": "",
                "category": "idle",
                "productivity": "idle",
                "screenshot_count": 0,
                "screenshots": [],
            })
            continue

        same_app = current and current["app"] == ev.get("app", "")
        same_title = current and current["window_title"] == ev.get("window_title", "")
        # Пауза между событиями
        gap = 0
        if current and current.get("ended_at") and ev.get("timestamp"):
            gap = _ts_to_sec(ev["timestamp"]) - _ts_to_sec(current["ended_at"])

        if current and same_app and (same_title or gap < 90):
            # Продолжаем сессию
            current["ended_at"] = ev.get("ended_at") or ev.get("timestamp", "")
            current["duration_seconds"] += ev.get("duration_seconds", 0)
            if ev.get("screenshot"):
                current["screenshots"].append(ev["screenshot"])
                current["screenshot_count"] = len(current["screenshots"])
        else:
            if current:
                sessions.append(current)
            current = {
                "session_id": ev.get("session_id", ""),
                "started_at": ev.get("timestamp", ""),
                "ended_at": ev.get("ended_at") or ev.get("timestamp", ""),
                "duration_seconds": ev.get("duration_seconds", 0),
                "app": ev.get("app", ""),
                "app_name": ev.get("app_name", _get_app_name(ev.get("app", ""))),
                "window_title": ev.get("window_title", ""),
                "category": ev.get("category", "other"),
                "productivity": ev.get("productivity", "neutral"),
                "screenshot_count": 1 if ev.get("screenshot") else 0,
                "screenshots": [ev["screenshot"]] if ev.get("screenshot") else [],
            }

    if current:
        sessions.append(current)

    _s3_put(hostname, day, "timeline.json",
            json.dumps(sessions, ensure_ascii=False, indent=2).encode(),
            "application/json; charset=utf-8")


def _save_summary(hostname: str, day: str, events: list):
    """Агрегированная статистика за день."""
    active_s = idle_s = productive_s = neutral_s = distracting_s = 0
    app_totals: dict[str, int] = defaultdict(int)
    switch_count = 0
    prev_app = None
    first_event = last_event = None

    for ev in events:
        dur = ev.get("duration_seconds", 0)
        app = ev.get("app", "")
        etype = ev.get("event_type", "focus")
        prod = ev.get("productivity", "neutral")

        if etype == "idle":
            idle_s += dur
        else:
            active_s += dur
            app_totals[app] += dur
            if app != prev_app:
                switch_count += 1
                prev_app = app

        if ev.get("timestamp"):
            if not first_event:
                first_event = ev["timestamp"]
            last_event = ev["timestamp"]

        if prod == "productive":
            productive_s += dur
        elif prod == "distracting":
            distracting_s += dur
        elif prod not in ("idle",):
            neutral_s += dur

    total_s = active_s + idle_s
    prod_pct = round(productive_s / active_s * 100) if active_s else 0

    top_apps = sorted(
        [
            {
                "app": app,
                "app_name": _get_app_name(app),
                "category": _get_category(app),
                "productivity": _get_productivity(app),
                "seconds": secs,
                "percent": round(secs / active_s * 100) if active_s else 0,
                "formatted": _fmt(secs),
            }
            for app, secs in app_totals.items()
        ],
        key=lambda x: x["seconds"],
        reverse=True,
    )

    patterns = _build_activity_patterns(events)

    summary = {
        "hostname": hostname,
        "date": day,
        "generated_at": datetime.utcnow().isoformat(),
        "active_seconds": active_s,
        "idle_seconds": idle_s,
        "total_seconds": total_s,
        "active_formatted": _fmt(active_s),
        "idle_formatted": _fmt(idle_s),
        "first_event": first_event,
        "last_event": last_event,
        "productivity": {
            "productive_seconds": productive_s,
            "neutral_seconds": neutral_s,
            "distracting_seconds": distracting_s,
            "productive_percent": prod_pct,
            "productive_formatted": _fmt(productive_s),
            "neutral_formatted": _fmt(neutral_s),
            "distracting_formatted": _fmt(distracting_s),
        },
        "top_apps": top_apps[:15],
        "switch_count": switch_count,
        "event_count": len([e for e in events if e.get("event_type") != "idle"]),
        "patterns": patterns,
    }

    _s3_put(hostname, day, "summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2).encode(),
            "application/json; charset=utf-8")


def _build_activity_patterns(events: list) -> dict:
    """Повторяющиеся действия за день для аналитики."""
    title_stats: dict[str, dict] = {}
    switch_stats: dict[tuple[str, str], int] = defaultdict(int)
    hourly_active: dict[str, int] = defaultdict(int)
    prev_app = None

    for ev in events:
        etype = ev.get("event_type", "focus")
        dur = ev.get("duration_seconds", 0)
        app = ev.get("app", "")
        title = (ev.get("window_title") or "").strip()
        ts = ev.get("timestamp") or ""

        if etype != "idle" and len(ts) >= 13:
            hourly_active[ts[11:13]] += dur

        if etype == "idle":
            prev_app = None
            continue

        if title:
            key = title[:100]
            bucket = title_stats.setdefault(
                key,
                {"title": key, "app": app, "app_name": _get_app_name(app), "count": 0, "seconds": 0},
            )
            bucket["count"] += 1
            bucket["seconds"] += dur
            if not bucket.get("app"):
                bucket["app"] = app
                bucket["app_name"] = _get_app_name(app)

        if prev_app and prev_app != app:
            switch_stats[(prev_app, app)] += 1
        prev_app = app

    repeated_titles = sorted(
        [
            {**data, "formatted": _fmt(data["seconds"])}
            for data in title_stats.values()
            if data["count"] >= 3
        ],
        key=lambda item: item["seconds"],
        reverse=True,
    )[:20]

    frequent_switches = sorted(
        [
            {
                "from_app": src,
                "to_app": dst,
                "from_name": _get_app_name(src),
                "to_name": _get_app_name(dst),
                "count": count,
            }
            for (src, dst), count in switch_stats.items()
            if count >= 5
        ],
        key=lambda item: item["count"],
        reverse=True,
    )[:15]

    return {
        "repeated_window_titles": repeated_titles,
        "frequent_app_switches": frequent_switches,
        "hourly_active_seconds": dict(sorted(hourly_active.items())),
    }


def build_report_html(hostname: str, day: str) -> str:
    """Генерирует HTML-отчёт по данным из S3. Вызывается по запросу."""
    summary = _s3_get_json(hostname, day, "summary.json")
    timeline: list = _s3_get_json(hostname, day, "timeline.json")  # type: ignore

    prod = summary.get("productivity", {}) if summary else {}
    top_apps = summary.get("top_apps", []) if summary else []

    PROD_COLOR = {"productive": "#22c55e", "distracting": "#ef4444",
                  "neutral": "#3b82f6", "idle": "#475569"}
    PROD_RU = {"productive": "Рабочее", "distracting": "Отвлечение",
               "neutral": "Нейтральное", "idle": "Простой"}

    rows = ""
    for sess in timeline:
        if not sess.get("app"):
            continue
        color = PROD_COLOR.get(sess.get("productivity", "neutral"), "#3b82f6")
        prod_ru = PROD_RU.get(sess.get("productivity", "neutral"), "")
        dur = _fmt(sess.get("duration_seconds", 0))
        shots = sess.get("screenshot_count", 0)
        t_start = sess.get("started_at", "")[11:16]
        t_end = sess.get("ended_at", "")[11:16]
        title = sess.get("window_title", "") or ""
        app_name = sess.get("app_name", sess.get("app", ""))

        rows += f"""
        <tr>
          <td class="time">{t_start}–{t_end}</td>
          <td><span class="badge" style="background:{color}22;color:{color};border:1px solid {color}44">{app_name}</span></td>
          <td class="title">{title[:90]}</td>
          <td class="dur">{dur}</td>
          <td class="shots">{shots} скрин{'ов' if shots != 1 else ''}</td>
          <td><span class="prod-label" style="color:{color}">{prod_ru}</span></td>
        </tr>"""

    app_bars = ""
    for a in top_apps[:10]:
        color = PROD_COLOR.get(a.get("productivity", "neutral"), "#3b82f6")
        pct = a.get("percent", 0)
        app_bars += f"""
        <div class="app-row">
          <div class="app-name">{a['app_name']}</div>
          <div class="app-bar-wrap"><div class="app-bar" style="width:{pct}%;background:{color}"></div></div>
          <div class="app-time">{a['formatted']}</div>
        </div>"""

    active_fmt = summary.get("active_formatted", "—") if summary else "—"
    idle_fmt = summary.get("idle_formatted", "—") if summary else "—"
    prod_pct = prod.get("productive_percent", 0)
    prod_fmt = prod.get("productive_formatted", "—")
    dist_fmt = prod.get("distracting_formatted", "—")
    first_ev = (summary.get("first_event", "") or "")[11:16] if summary else "—"
    last_ev = (summary.get("last_event", "") or "")[11:16] if summary else "—"
    switch_count = summary.get("switch_count", 0) if summary else 0

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Отчёт {hostname} — {day}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 32px; }}
  h1 {{ font-size: 24px; font-weight: 700; color: #fff; }}
  h2 {{ font-size: 16px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 12px; }}
  .header {{ margin-bottom: 32px; }}
  .header p {{ color: #64748b; margin-top: 4px; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px 24px; min-width: 160px; }}
  .card .val {{ font-size: 28px; font-weight: 700; }}
  .card .lbl {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
  .section {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
  .app-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
  .app-name {{ width: 160px; font-size: 13px; color: #cbd5e1; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .app-bar-wrap {{ flex: 1; background: #0f172a; border-radius: 4px; height: 8px; }}
  .app-bar {{ height: 8px; border-radius: 4px; transition: width .3s; }}
  .app-time {{ width: 80px; text-align: right; font-size: 12px; color: #64748b; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: #64748b; font-weight: 500; padding: 8px 12px; border-bottom: 1px solid #334155; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; vertical-align: top; }}
  tr:hover td {{ background: #1e293b88; }}
  .time {{ color: #94a3b8; white-space: nowrap; font-family: monospace; }}
  .title {{ color: #94a3b8; max-width: 320px; }}
  .dur {{ white-space: nowrap; color: #cbd5e1; }}
  .shots {{ color: #475569; }}
  .badge {{ padding: 2px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; white-space: nowrap; }}
  .prod-label {{ font-size: 12px; font-weight: 500; }}
  .footer {{ margin-top: 32px; color: #334155; font-size: 12px; }}
</style>
</head>
<body>
<div class="header">
  <h1>SyncLayer — Отчёт за день</h1>
  <p>{hostname} · {day} · сгенерировано {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC</p>
</div>

<div class="cards">
  <div class="card"><div class="val" style="color:#22c55e">{active_fmt}</div><div class="lbl">Активное время</div></div>
  <div class="card"><div class="val" style="color:#475569">{idle_fmt}</div><div class="lbl">Простой</div></div>
  <div class="card"><div class="val" style="color:#22c55e">{prod_pct}%</div><div class="lbl">Продуктивность</div></div>
  <div class="card"><div class="val" style="color:#ef4444">{dist_fmt}</div><div class="lbl">Отвлечения</div></div>
  <div class="card"><div class="val">{first_ev}–{last_ev}</div><div class="lbl">Рабочее время</div></div>
  <div class="card"><div class="val" style="color:#6366f1">{switch_count}</div><div class="lbl">Переключений</div></div>
</div>

<div class="section">
  <h2>Топ приложений</h2>
  {app_bars}
</div>

<div class="section">
  <h2>Хронология (сессии)</h2>
  <table>
    <thead><tr>
      <th>Время</th><th>Приложение</th><th>Заголовок окна</th>
      <th>Длительность</th><th>Скриншоты</th><th>Тип</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>

<div class="footer">Отчёт создан SyncLayer · {hostname} · {day}</div>
</body>
</html>"""

    _s3_put(hostname, day, "report.html",
            html.encode("utf-8"),
            "text/html; charset=utf-8")
    return html


def get_activity_for_screenshot(activity: list, screenshot_time_str: str) -> Optional[dict]:
    """Ближайшее событие к времени скриншота (не дальше 90 сек)."""
    if not activity:
        return None
    shot_sec = _ts_to_sec(screenshot_time_str)
    best, best_diff = None, 9999
    for ev in activity:
        if ev.get("event_type") == "idle":
            continue
        diff = abs(shot_sec - _ts_to_sec(ev.get("timestamp", "")))
        if diff < best_diff:
            best_diff, best = diff, ev
    return best if best_diff < 90 else None
