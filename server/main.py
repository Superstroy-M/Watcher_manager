import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Header, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from pydantic import BaseModel

from database import get_db, init_db
from models import Computer, Event, DailyStat, ProcessSnapshot, NetworkConnection, PrintJob
from s3_storage import (
    upload_screenshot, list_screenshots, list_screenshot_days,
    get_screenshot_url, get_s3, SCREENSHOT_STORAGE
)
from activity_log import (
    save_activity, load_activity, get_activity_for_screenshot,
    build_report_html, _s3_get_json
)
from auth import (
    AUTH_USERNAME,
    AUTH_PASSWORD,
    SESSION_SECRET,
    DashboardAuthMiddleware,
)

API_KEY = os.getenv("API_KEY", "change_this_secret_key_123")
SCREENSHOTS_DIR = Path(os.getenv("SCREENSHOTS_DIR", "./screenshots"))
DISPLAY_TZ_OFFSET_HOURS = int(os.getenv("DISPLAY_TZ_OFFSET_HOURS", "3"))
DISPLAY_TZ_OFFSET = timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)

# Категории продуктивности (расширяемые)
PRODUCTIVITY = {
    "productive": [
        "1cv8.exe", "excel.exe", "word.exe", "outlook.exe", "teams.exe",
        "code.exe", "pycharm64.exe", "devenv.exe", "notepad++.exe",
        "acrobat.exe", "acrord32.exe", "winword.exe", "powerpnt.exe",
        "zoom.exe", "mstsc.exe", "putty.exe", "winscp.exe", "filezilla.exe",
    ],
    "distracting": [
        "chrome.exe", "firefox.exe", "msedge.exe", "opera.exe",
        "telegram.exe", "vk.exe", "discord.exe", "slack.exe",
    ],
    # всё остальное — "neutral"
}

DISTRACTING_SITES = [
    "youtube", "vk.com", "ok.ru", "instagram", "tiktok", "twitch",
    "facebook", "twitter", "reddit", "netflix", "pikabu",
]

app = FastAPI(title="SyncLayer", docs_url=None, redoc_url=None)
app.add_middleware(DashboardAuthMiddleware, api_key=API_KEY)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 24 * 7)

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass

templates = Jinja2Templates(directory="templates")


def to_local_dt(dt: Optional[datetime]):
    if dt is None:
        return None
    return dt + DISPLAY_TZ_OFFSET


templates.env.filters["local_dt"] = to_local_dt


def local_day_utc_bounds(day_value: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(day_value, datetime.min.time())
    local_end = local_start + timedelta(days=1)
    return local_start - DISPLAY_TZ_OFFSET, local_end - DISPLAY_TZ_OFFSET


@app.on_event("startup")
def startup():
    init_db()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    _mark_all_offline()


def _mark_all_offline():
    from database import SessionLocal
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=2)
        db.query(Computer).filter(Computer.last_seen < cutoff).update({"is_online": False})
        db.commit()
    finally:
        db.close()


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key


def get_or_create_computer(db: Session, hostname: str) -> Computer:
    computer = db.query(Computer).filter(Computer.hostname == hostname).first()
    if not computer:
        computer = Computer(hostname=hostname)
        db.add(computer)
        db.flush()
    return computer


def productivity_label(process_name: str, window_title: str = "") -> str:
    p = (process_name or "").lower()
    t = (window_title or "").lower()
    if p in PRODUCTIVITY["productive"]:
        return "productive"
    if p in PRODUCTIVITY["distracting"]:
        if any(s in t for s in DISTRACTING_SITES):
            return "distracting"
        return "neutral"
    return "neutral"


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class HeartbeatSchema(BaseModel):
    hostname: str
    ip_address: Optional[str] = None
    username: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: Optional[str] = "1.0"


class EventSchema(BaseModel):
    hostname: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0
    process_name: str
    window_title: Optional[str] = ""
    event_type: str = "focus"


class EventsBatchSchema(BaseModel):
    hostname: str
    events: List[EventSchema]


class ProcessSnapshotSchema(BaseModel):
    hostname: str
    captured_at: datetime
    processes: list


class NetworkSnapshotSchema(BaseModel):
    hostname: str
    captured_at: datetime
    connections: list


class PrintJobSchema(BaseModel):
    hostname: str
    printed_at: datetime
    document_name: Optional[str] = ""
    printer_name: Optional[str] = ""
    pages: int = 0
    username: Optional[str] = ""


# ─── Agent API ───────────────────────────────────────────────────────────────

@app.post("/api/heartbeat")
def heartbeat(data: HeartbeatSchema, db: Session = Depends(get_db), _=Depends(verify_api_key)):
    computer = get_or_create_computer(db, data.hostname)
    computer.ip_address = data.ip_address
    computer.username = data.username
    computer.os_version = data.os_version
    computer.agent_version = data.agent_version
    computer.last_seen = datetime.utcnow()
    computer.is_online = True
    db.commit()
    return {"status": "ok"}


@app.post("/api/events")
def add_events(data: EventsBatchSchema, db: Session = Depends(get_db), _=Depends(verify_api_key)):
    computer = get_or_create_computer(db, data.hostname)

    for ev in data.events:
        event = Event(
            computer_id=computer.id,
            started_at=ev.started_at,
            ended_at=ev.ended_at,
            duration_seconds=ev.duration_seconds,
            process_name=ev.process_name,
            window_title=ev.window_title,
            event_type=ev.event_type,
        )
        db.add(event)

        event_date = ev.started_at.date()
        stat = db.query(DailyStat).filter(
            DailyStat.computer_id == computer.id,
            DailyStat.date == event_date,
            DailyStat.process_name == ev.process_name,
        ).first()
        if not stat:
            stat = DailyStat(
                computer_id=computer.id,
                date=event_date,
                process_name=ev.process_name,
                total_seconds=0,
                launches_count=0,
            )
            db.add(stat)
        stat.total_seconds += ev.duration_seconds
        stat.launches_count += 1

    computer.last_seen = datetime.utcnow()
    computer.is_online = True
    db.commit()

    # Обновляем activity.json и report.txt в S3
    if SCREENSHOT_STORAGE == "s3":
        try:
            # Группируем события по дате
            from collections import defaultdict
            by_day: dict = defaultdict(list)
            for ev in data.events:
                day_str = ev.started_at.strftime("%Y-%m-%d")
                by_day[day_str].append({
                    "id": None,  # id ещё не знаем, используем timestamp как ключ
                    "started_at": ev.started_at.isoformat(),
                    "ended_at": ev.ended_at.isoformat() if ev.ended_at else None,
                    "duration_seconds": ev.duration_seconds,
                    "process_name": ev.process_name,
                    "window_title": ev.window_title or "",
                    "event_type": ev.event_type,
                    "productivity": productivity_label(ev.process_name, ev.window_title),
                })
            for day_str, evs in by_day.items():
                save_activity(computer.hostname, day_str, evs)
        except Exception as e:
            import logging
            logging.getLogger("main").warning(f"Activity log update failed: {e}")

    return {"status": "ok", "saved": len(data.events)}


@app.post("/api/screenshot")
async def receive_screenshot(
    file: UploadFile = File(...),
    hostname: str = Form(...),
    timestamp: str = Form(...),
    _=Depends(verify_api_key),
):
    ts = datetime.fromisoformat(timestamp)
    data = await file.read()

    if SCREENSHOT_STORAGE == "s3":
        key = upload_screenshot(hostname, ts, data)
        return {"status": "ok", "key": key}
    else:
        day_dir = SCREENSHOTS_DIR / hostname / ts.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / (ts.strftime("%H-%M-%S") + ".jpg")).write_bytes(data)
        return {"status": "ok"}


@app.post("/api/processes")
def add_processes(data: ProcessSnapshotSchema, db: Session = Depends(get_db), _=Depends(verify_api_key)):
    computer = get_or_create_computer(db, data.hostname)
    snap = ProcessSnapshot(
        computer_id=computer.id,
        captured_at=data.captured_at,
        processes=data.processes,
    )
    db.add(snap)
    db.commit()
    return {"status": "ok"}


@app.post("/api/network")
def add_network(data: NetworkSnapshotSchema, db: Session = Depends(get_db), _=Depends(verify_api_key)):
    computer = get_or_create_computer(db, data.hostname)
    for conn in data.connections:
        nc = NetworkConnection(
            computer_id=computer.id,
            captured_at=data.captured_at,
            process_name=conn.get("process_name"),
            pid=conn.get("pid"),
            remote_ip=conn.get("remote_ip"),
            remote_port=conn.get("remote_port"),
            local_port=conn.get("local_port"),
            status=conn.get("status"),
        )
        db.add(nc)
    db.commit()
    return {"status": "ok", "saved": len(data.connections)}


@app.post("/api/print")
def add_print_job(data: PrintJobSchema, db: Session = Depends(get_db), _=Depends(verify_api_key)):
    computer = get_or_create_computer(db, data.hostname)
    job = PrintJob(
        computer_id=computer.id,
        printed_at=data.printed_at,
        document_name=data.document_name,
        printer_name=data.printer_name,
        pages=data.pages,
        username=data.username,
    )
    db.add(job)
    db.commit()
    return {"status": "ok"}


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if request.session.get("authenticated"):
        target = next if next.startswith("/") else "/"
        return RedirectResponse(target, status_code=303)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "next": next,
        "error": None,
    })


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        request.session["authenticated"] = True
        request.session["username"] = username
        target = next if next.startswith("/") else "/"
        return RedirectResponse(target, status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next,
            "error": "Неверный логин или пароль",
        },
        status_code=401,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard_index(request: Request, db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(minutes=2)
    db.query(Computer).filter(Computer.last_seen < cutoff).update({"is_online": False})
    db.commit()
    computers = db.query(Computer).order_by(desc(Computer.last_seen)).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "computers": computers,
        "online_count": sum(1 for c in computers if c.is_online),
        "total_count": len(computers),
    })


@app.get("/live", response_class=HTMLResponse)
def live_view(request: Request, db: Session = Depends(get_db)):
    """Реальное время — все ПК на одном экране."""
    cutoff = datetime.utcnow() - timedelta(minutes=2)
    db.query(Computer).filter(Computer.last_seen < cutoff).update({"is_online": False})
    db.commit()
    computers = db.query(Computer).order_by(desc(Computer.last_seen)).all()
    return templates.TemplateResponse("live.html", {
        "request": request,
        "computers": computers,
    })


@app.get("/computer/{computer_id}", response_class=HTMLResponse)
def computer_detail(
    request: Request,
    computer_id: int,
    day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    computer = db.query(Computer).filter(Computer.id == computer_id).first()
    if not computer:
        raise HTTPException(status_code=404)

    selected_date = date.today()
    if day:
        try:
            selected_date = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    start_utc, end_utc = local_day_utc_bounds(selected_date)
    events = (
        db.query(Event)
        .filter(Event.computer_id == computer_id, Event.started_at >= start_utc, Event.started_at < end_utc)
        .order_by(Event.started_at)
        .all()
    )

    # Строим статистику приложений из отфильтрованных событий (локальный день пользователя).
    stats_map: dict[str, dict] = {}
    for ev in events:
        key = ev.process_name or "unknown"
        if key not in stats_map:
            stats_map[key] = {"process_name": key, "total_seconds": 0, "launches_count": 0}
        stats_map[key]["total_seconds"] += ev.duration_seconds or 0
        stats_map[key]["launches_count"] += 1
    stats = sorted(stats_map.values(), key=lambda x: x["total_seconds"], reverse=True)

    # Доступные дни также считаем по локальной дате.
    day_set = set()
    all_event_times = (
        db.query(Event.started_at)
        .filter(Event.computer_id == computer_id)
        .order_by(desc(Event.started_at))
        .limit(3000)
        .all()
    )
    for row in all_event_times:
        if row.started_at:
            day_set.add((row.started_at + DISPLAY_TZ_OFFSET).date().isoformat())
    available_days = sorted(day_set, reverse=True)[:30]

    # Подсчёт продуктивности
    productive_s = neutral_s = distracting_s = 0
    for e in events:
        label = productivity_label(e.process_name, e.window_title)
        if label == "productive":
            productive_s += e.duration_seconds
        elif label == "distracting":
            distracting_s += e.duration_seconds
        else:
            neutral_s += e.duration_seconds

    # Задания на печать за день
    print_jobs = (
        db.query(PrintJob)
        .filter(PrintJob.computer_id == computer_id, PrintJob.printed_at >= start_utc, PrintJob.printed_at < end_utc)
        .order_by(desc(PrintJob.printed_at))
        .all()
    )

    return templates.TemplateResponse("computer.html", {
        "request": request,
        "computer": computer,
        "events": events,
        "stats": stats,
        "selected_date": selected_date,
        "available_days": available_days,
        "productive_s": productive_s,
        "neutral_s": neutral_s,
        "distracting_s": distracting_s,
        "print_jobs": print_jobs,
    })


# ─── API для live view ────────────────────────────────────────────────────────

@app.get("/api/computers")
def api_computers(db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(minutes=2)
    db.query(Computer).filter(Computer.last_seen < cutoff).update({"is_online": False})
    db.commit()
    computers = db.query(Computer).order_by(desc(Computer.last_seen)).all()
    return [
        {
            "id": c.id,
            "hostname": c.hostname,
            "ip_address": c.ip_address,
            "username": c.username,
            "is_online": c.is_online,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        }
        for c in computers
    ]


@app.get("/api/live")
def api_live(db: Session = Depends(get_db)):
    """Текущее состояние всех ПК для live view."""
    cutoff = datetime.utcnow() - timedelta(minutes=2)
    db.query(Computer).filter(Computer.last_seen < cutoff).update({"is_online": False})
    db.commit()

    computers = db.query(Computer).order_by(desc(Computer.last_seen)).all()
    result = []
    for c in computers:
        last_event = (
            db.query(Event)
            .filter(Event.computer_id == c.id)
            .order_by(desc(Event.started_at))
            .first()
        )
        # Последний скриншот (S3 или local)
        last_screenshot_url = None
        if SCREENSHOT_STORAGE == "s3":
            today = date.today().isoformat()
            shots = list_screenshots(c.hostname, today)
            if shots:
                last_screenshot_url = get_screenshot_url(shots[-1]["key"])
        else:
            today_dir = SCREENSHOTS_DIR / c.hostname / date.today().isoformat()
            if today_dir.exists():
                files = sorted(today_dir.glob("*.jpg"))
                if files:
                    last_screenshot_url = f"/screenshots/img/{c.hostname}/{date.today().isoformat()}/{files[-1].name}"

        result.append({
            "id": c.id,
            "hostname": c.hostname,
            "username": c.username,
            "ip_address": c.ip_address,
            "is_online": c.is_online,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            "current_app": last_event.process_name if last_event else None,
            "current_title": last_event.window_title if last_event else None,
            "current_type": last_event.event_type if last_event else None,
            "last_screenshot": last_screenshot_url,
        })
    return result


@app.get("/api/computer/{computer_id}/events")
def api_events(computer_id: int, day: Optional[str] = None, db: Session = Depends(get_db)):
    selected_date = date.today()
    if day:
        try:
            selected_date = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
    start_utc, end_utc = local_day_utc_bounds(selected_date)
    events = (
        db.query(Event)
        .filter(Event.computer_id == computer_id, Event.started_at >= start_utc, Event.started_at < end_utc)
        .order_by(Event.started_at)
        .all()
    )
    return [
        {
            "id": e.id,
            "started_at": e.started_at.isoformat(),
            "ended_at": e.ended_at.isoformat() if e.ended_at else None,
            "duration_seconds": e.duration_seconds,
            "process_name": e.process_name,
            "window_title": e.window_title,
            "event_type": e.event_type,
            "productivity": productivity_label(e.process_name, e.window_title),
        }
        for e in events
    ]


@app.get("/api/computer/{computer_id}/processes")
def api_processes(computer_id: int, db: Session = Depends(get_db)):
    snap = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.computer_id == computer_id)
        .order_by(desc(ProcessSnapshot.captured_at))
        .first()
    )
    if not snap:
        return {"captured_at": None, "processes": []}
    return {"captured_at": snap.captured_at.isoformat(), "processes": snap.processes}


@app.get("/api/computer/{computer_id}/network")
def api_network(computer_id: int, db: Session = Depends(get_db)):
    conns = (
        db.query(NetworkConnection)
        .filter(NetworkConnection.computer_id == computer_id)
        .order_by(desc(NetworkConnection.captured_at))
        .limit(100)
        .all()
    )
    return [
        {
            "captured_at": c.captured_at.isoformat(),
            "process_name": c.process_name,
            "remote_ip": c.remote_ip,
            "remote_port": c.remote_port,
            "status": c.status,
        }
        for c in conns
    ]


@app.get("/api/computer/{computer_id}/print")
def api_print(computer_id: int, db: Session = Depends(get_db)):
    jobs = (
        db.query(PrintJob)
        .filter(PrintJob.computer_id == computer_id)
        .order_by(desc(PrintJob.printed_at))
        .limit(50)
        .all()
    )
    return [
        {
            "printed_at": j.printed_at.isoformat(),
            "document_name": j.document_name,
            "printer_name": j.printer_name,
            "pages": j.pages,
            "username": j.username,
        }
        for j in jobs
    ]


@app.get("/api/computer/{computer_id}/screenshot-days")
def screenshot_days(computer_id: int, db: Session = Depends(get_db)):
    computer = db.query(Computer).filter(Computer.id == computer_id).first()
    if not computer:
        raise HTTPException(status_code=404)
    if SCREENSHOT_STORAGE == "s3":
        return list_screenshot_days(computer.hostname)
    base = SCREENSHOTS_DIR / computer.hostname
    if not base.exists():
        return []
    return sorted([d.name for d in base.iterdir() if d.is_dir()], reverse=True)


@app.get("/api/screenshot/view")
def view_screenshot(key: str):
    """Редирект на presigned S3 URL для просмотра скриншота."""
    url = get_screenshot_url(key)
    if not url:
        raise HTTPException(status_code=404)
    return RedirectResponse(url)


@app.get("/screenshots/{hostname}/{day}", response_class=HTMLResponse)
def screenshots_page(request: Request, hostname: str, day: str, db: Session = Depends(get_db)):
    if SCREENSHOT_STORAGE == "s3":
        shots = list_screenshots(hostname, day)
    else:
        day_dir = SCREENSHOTS_DIR / hostname / day
        files = sorted(day_dir.glob("*.jpg")) if day_dir.exists() else []
        shots = [
            {"time": f.stem.replace("-", ":"), "url": f"/screenshots/img/{hostname}/{day}/{f.name}"}
            for f in files
        ]
    computer = db.query(Computer).filter(Computer.hostname == hostname).first()
    return templates.TemplateResponse("screenshots.html", {
        "request": request,
        "hostname": hostname,
        "day": day,
        "shots": shots,
        "computer": computer,
    })


@app.get("/screenshots/img/{hostname}/{day}/{filename}")
def screenshot_file(hostname: str, day: str, filename: str):
    from fastapi.responses import FileResponse
    path = SCREENSHOTS_DIR / hostname / day / filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/report/{hostname}/{day}")
def download_report(hostname: str, day: str, fmt: str = "html"):
    """Отчёт за день. Генерируется на лету из S3-данных."""
    from fastapi.responses import StreamingResponse, HTMLResponse as HR
    import io
    if fmt == "html":
        html = build_report_html(hostname, day)
        return HR(html)
    # txt fallback
    try:
        resp = get_s3().get_object(
            Bucket=os.getenv("S3_BUCKET", "watcher"),
            Key=f"screenshots/{hostname}/{day}/report.html"
        )
        return StreamingResponse(
            io.BytesIO(resp["Body"].read()),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=report_{hostname}_{day}.html"}
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Report not found")


@app.get("/api/activity/{hostname}/{day}")
def api_activity(hostname: str, day: str):
    """Сырые события за день (activity.json)."""
    return load_activity(hostname, day)


@app.get("/api/activity/{hostname}/{day}/timeline")
def api_timeline(hostname: str, day: str):
    """Дедуплицированные сессии (timeline.json)."""
    return _s3_get_json(hostname, day, "timeline.json")


@app.get("/api/activity/{hostname}/{day}/summary")
def api_summary(hostname: str, day: str):
    """Агрегаты за день (summary.json)."""
    return _s3_get_json(hostname, day, "summary.json")


@app.get("/api/screenshots/{hostname}/{day}")
def api_screenshots_rich(hostname: str, day: str):
    """Скриншоты + activity в одном ответе."""
    if SCREENSHOT_STORAGE == "s3":
        shots = list_screenshots(hostname, day)
        activity = load_activity(hostname, day)
    else:
        day_dir = SCREENSHOTS_DIR / hostname / day
        files = sorted(day_dir.glob("*.jpg")) if day_dir.exists() else []
        shots = [{"time": f.stem.replace("-", ":"), "url": f"/screenshots/img/{hostname}/{day}/{f.name}"} for f in files]
        activity = []

    for shot in shots:
        ev = get_activity_for_screenshot(activity, shot["time"])
        shot["app"] = ev.get("app", "") if ev else ""
        shot["app_name"] = ev.get("app_name", "") if ev else ""
        shot["window_title"] = ev.get("window_title", "") if ev else ""
        shot["productivity"] = ev.get("productivity", "neutral") if ev else "neutral"
        shot["category"] = ev.get("category", "other") if ev else "other"
        shot["event_type"] = ev.get("event_type", "focus") if ev else "focus"

    summary = _s3_get_json(hostname, day, "summary.json")
    return {
        "hostname": hostname,
        "day": day,
        "summary": {
            "active_seconds": summary.get("active_seconds", 0) if summary else 0,
            "idle_seconds": summary.get("idle_seconds", 0) if summary else 0,
            "active_formatted": summary.get("active_formatted", "") if summary else "",
            "productive_percent": summary.get("productivity", {}).get("productive_percent", 0) if summary else 0,
        },
        "screenshots": shots,
    }


@app.get("/gallery", response_class=HTMLResponse)
def gallery(request: Request, db: Session = Depends(get_db)):
    """Единая галерея — выбрать ПК и дату."""
    return templates.TemplateResponse("gallery.html", {"request": request})


@app.get("/screenshots/api/{hostname}/{day}")
def api_screenshots_list(hostname: str, day: str):
    """JSON список скриншотов с описанием активности для галереи."""
    if SCREENSHOT_STORAGE == "s3":
        shots = list_screenshots(hostname, day)
        # Подгружаем activity.json и добавляем описание к каждому скриншоту
        try:
            activity = load_activity(hostname, day)
        except Exception:
            activity = []

        for shot in shots:
            ev = get_activity_for_screenshot(activity, shot["time"])
            if ev:
                shot["app"] = ev.get("process_name", "")
                shot["title"] = ev.get("window_title", "")
                shot["productivity"] = ev.get("productivity", "neutral")
                shot["event_type"] = ev.get("event_type", "focus")
            else:
                shot["app"] = ""
                shot["title"] = ""
                shot["productivity"] = "neutral"
                shot["event_type"] = "focus"
        return shots
    else:
        day_dir = SCREENSHOTS_DIR / hostname / day
        files = sorted(day_dir.glob("*.jpg")) if day_dir.exists() else []
        return [
            {"time": f.stem.replace("-", ":"), "url": f"/screenshots/img/{hostname}/{day}/{f.name}",
             "app": "", "title": "", "productivity": "neutral"}
            for f in files
        ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
