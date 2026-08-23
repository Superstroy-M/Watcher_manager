"""
Тесты FastAPI-эндпоинтов (server/main.py).
Используют SQLite in-memory через conftest.py.
"""
import io
import json
from datetime import datetime, date, timedelta

import pytest
from sqlalchemy.orm import Session

from helpers import AUTH, API_KEY
from models import Computer, Event, DailyStat, ProcessSnapshot, NetworkConnection, PrintJob


# ══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════════════

def _make_computer(db: Session, hostname: str = "test-pc", online: bool = True) -> Computer:
    c = Computer(hostname=hostname, ip_address="10.0.0.1", username="user1",
                 last_seen=datetime.utcnow(), is_online=online)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_event(db: Session, computer_id: int, proc: str = "chrome.exe",
                title: str = "", etype: str = "focus", dur: int = 60) -> Event:
    e = Event(
        computer_id=computer_id,
        started_at=datetime.utcnow() - timedelta(minutes=5),
        ended_at=datetime.utcnow(),
        duration_seconds=dur,
        process_name=proc,
        window_title=title,
        event_type=etype,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


# ══════════════════════════════════════════════════════════════════════════════
#  productivity_label
# ══════════════════════════════════════════════════════════════════════════════

class TestProductivityLabel:
    """Тесты функции классификации продуктивности."""

    def test_productive_app(self):
        from main import productivity_label
        assert productivity_label("excel.exe") == "productive"

    def test_productive_app_1c(self):
        from main import productivity_label
        assert productivity_label("1cv8.exe") == "productive"

    def test_distracting_app_no_site(self):
        from main import productivity_label
        # chrome без отвлекающего сайта — neutral
        assert productivity_label("chrome.exe", "GitHub") == "neutral"

    def test_distracting_app_with_site(self):
        from main import productivity_label
        assert productivity_label("chrome.exe", "youtube - смотреть видео") == "distracting"

    def test_distracting_app_vk(self):
        from main import productivity_label
        assert productivity_label("firefox.exe", "vk.com — социальная сеть") == "distracting"

    def test_neutral_unknown_app(self):
        from main import productivity_label
        assert productivity_label("unknown_app.exe") == "neutral"

    def test_none_process(self):
        from main import productivity_label
        assert productivity_label(None) == "neutral"

    def test_empty_strings(self):
        from main import productivity_label
        assert productivity_label("", "") == "neutral"

    def test_case_insensitive(self):
        from main import productivity_label
        # Проверяем lowercase
        assert productivity_label("EXCEL.EXE".lower()) == "productive"


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/heartbeat
# ══════════════════════════════════════════════════════════════════════════════

class TestHeartbeat:

    def test_valid_heartbeat_creates_computer(self, client, db_session):
        r = client.post("/api/heartbeat", json={
            "hostname": "pc-001",
            "ip_address": "192.168.1.1",
            "username": "admin",
            "os_version": "Windows 10",
            "agent_version": "1.0",
        }, headers=AUTH)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        c = db_session.query(Computer).filter_by(hostname="pc-001").first()
        assert c is not None
        assert c.ip_address == "192.168.1.1"
        assert c.is_online is True

    def test_heartbeat_minimal_hostname_only(self, client, db_session):
        r = client.post("/api/heartbeat", json={"hostname": "pc-002"}, headers=AUTH)
        assert r.status_code == 200
        c = db_session.query(Computer).filter_by(hostname="pc-002").first()
        assert c is not None

    def test_heartbeat_updates_existing(self, client, db_session):
        client.post("/api/heartbeat", json={"hostname": "pc-001", "ip_address": "10.0.0.1"},
                    headers=AUTH)
        client.post("/api/heartbeat", json={"hostname": "pc-001", "ip_address": "10.0.0.99"},
                    headers=AUTH)
        computers = db_session.query(Computer).filter_by(hostname="pc-001").all()
        assert len(computers) == 1
        db_session.refresh(computers[0])
        assert computers[0].ip_address == "10.0.0.99"

    def test_heartbeat_wrong_api_key(self, client):
        r = client.post("/api/heartbeat", json={"hostname": "pc-001"},
                        headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 403

    def test_heartbeat_missing_api_key(self, client):
        r = client.post("/api/heartbeat", json={"hostname": "pc-001"})
        assert r.status_code == 422

    def test_heartbeat_missing_hostname(self, client):
        r = client.post("/api/heartbeat", json={"ip_address": "1.2.3.4"}, headers=AUTH)
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/events
# ══════════════════════════════════════════════════════════════════════════════

class TestEvents:

    def _event_payload(self, hostname="test-pc", proc="excel.exe", dur=120):
        now = datetime.utcnow()
        return {
            "hostname": hostname,
            "events": [{
                "hostname": hostname,
                "started_at": (now - timedelta(seconds=dur)).isoformat(),
                "ended_at": now.isoformat(),
                "duration_seconds": dur,
                "process_name": proc,
                "window_title": "Book1.xlsx",
                "event_type": "focus",
            }]
        }

    def test_add_single_event(self, client, db_session):
        r = client.post("/api/events", json=self._event_payload(), headers=AUTH)
        assert r.status_code == 200
        assert r.json()["saved"] == 1
        events = db_session.query(Event).all()
        assert len(events) == 1
        assert events[0].process_name == "excel.exe"

    def test_add_multiple_events(self, client, db_session):
        now = datetime.utcnow()
        payload = {
            "hostname": "test-pc",
            "events": [
                {
                    "hostname": "test-pc",
                    "started_at": (now - timedelta(minutes=10)).isoformat(),
                    "ended_at": (now - timedelta(minutes=5)).isoformat(),
                    "duration_seconds": 300,
                    "process_name": "word.exe",
                    "window_title": "doc.docx",
                    "event_type": "focus",
                },
                {
                    "hostname": "test-pc",
                    "started_at": (now - timedelta(minutes=5)).isoformat(),
                    "ended_at": now.isoformat(),
                    "duration_seconds": 300,
                    "process_name": "idle",
                    "window_title": "",
                    "event_type": "idle",
                },
            ]
        }
        r = client.post("/api/events", json=payload, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["saved"] == 2

    def test_events_create_daily_stat(self, client, db_session):
        r = client.post("/api/events", json=self._event_payload(dur=300), headers=AUTH)
        assert r.status_code == 200
        stat = db_session.query(DailyStat).first()
        assert stat is not None
        assert stat.total_seconds == 300
        assert stat.launches_count == 1

    def test_events_aggregate_daily_stat(self, client, db_session):
        client.post("/api/events", json=self._event_payload(dur=200), headers=AUTH)
        client.post("/api/events", json=self._event_payload(dur=100), headers=AUTH)
        stats = db_session.query(DailyStat).filter_by(process_name="excel.exe").all()
        assert len(stats) == 1
        assert stats[0].total_seconds == 300
        assert stats[0].launches_count == 2

    def test_events_empty_list(self, client, db_session):
        r = client.post("/api/events", json={"hostname": "pc", "events": []}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["saved"] == 0

    def test_events_wrong_api_key(self, client):
        r = client.post("/api/events",
                        json=self._event_payload(),
                        headers={"X-API-Key": "bad"})
        assert r.status_code == 403

    def test_events_creates_computer(self, client, db_session):
        r = client.post("/api/events",
                        json=self._event_payload(hostname="new-pc"),
                        headers=AUTH)
        assert r.status_code == 200
        c = db_session.query(Computer).filter_by(hostname="new-pc").first()
        assert c is not None


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/screenshot  +  GET /api/screenshot/view
# ══════════════════════════════════════════════════════════════════════════════

class TestScreenshot:

    def test_upload_screenshot_local(self, client, tmp_path, monkeypatch):
        import main as m
        monkeypatch.setattr(m, "SCREENSHOTS_DIR", tmp_path)
        monkeypatch.setattr(m, "SCREENSHOT_STORAGE", "local")

        ts = datetime.utcnow()
        data = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 100)
        r = client.post(
            "/api/screenshot",
            data={"hostname": "test-pc", "timestamp": ts.isoformat()},
            files={"file": ("shot.jpg", data, "image/jpeg")},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_view_screenshot_not_found(self, client):
        r = client.get("/api/screenshot/view?key=nonexistent/key.jpg",
                       follow_redirects=False)
        assert r.status_code in (302, 307, 404)

    def test_screenshot_file_not_found(self, client):
        r = client.get("/screenshots/img/pc/2024-01-01/10-00-00.jpg")
        assert r.status_code == 404

    def test_screenshots_page_local(self, client, db_session, tmp_path, monkeypatch):
        import main as m
        monkeypatch.setattr(m, "SCREENSHOTS_DIR", tmp_path)
        monkeypatch.setattr(m, "SCREENSHOT_STORAGE", "local")

        c = _make_computer(db_session, "test-pc")
        r = client.get("/screenshots/test-pc/2024-01-01")
        assert r.status_code == 200
        assert "test-pc" in r.text


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/processes  +  GET /api/computer/{id}/processes
# ══════════════════════════════════════════════════════════════════════════════

class TestProcesses:

    def test_add_processes(self, client, db_session):
        procs = [{"name": "chrome.exe", "pid": 1234, "cpu_percent": 5.0,
                  "memory_mb": 200, "username": "user1"}]
        r = client.post("/api/processes", json={
            "hostname": "test-pc",
            "captured_at": datetime.utcnow().isoformat(),
            "processes": procs,
        }, headers=AUTH)
        assert r.status_code == 200
        snap = db_session.query(ProcessSnapshot).first()
        assert snap is not None
        assert snap.processes[0]["name"] == "chrome.exe"

    def test_get_processes_empty(self, client, db_session):
        c = _make_computer(db_session)
        r = client.get(f"/api/computer/{c.id}/processes")
        assert r.status_code == 200
        assert r.json()["processes"] == []

    def test_get_processes_returns_latest(self, client, db_session):
        c = _make_computer(db_session)
        old_ts = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        new_ts = datetime.utcnow().isoformat()
        client.post("/api/processes", json={
            "hostname": c.hostname, "captured_at": old_ts,
            "processes": [{"name": "old.exe"}]
        }, headers=AUTH)
        client.post("/api/processes", json={
            "hostname": c.hostname, "captured_at": new_ts,
            "processes": [{"name": "new.exe"}]
        }, headers=AUTH)
        r = client.get(f"/api/computer/{c.id}/processes")
        assert r.json()["processes"][0]["name"] == "new.exe"


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/network  +  GET /api/computer/{id}/network
# ══════════════════════════════════════════════════════════════════════════════

class TestNetwork:

    def test_add_network_connections(self, client, db_session):
        conns = [{"process_name": "chrome.exe", "pid": 100,
                  "remote_ip": "8.8.8.8", "remote_port": 443,
                  "local_port": 55000, "status": "ESTABLISHED"}]
        r = client.post("/api/network", json={
            "hostname": "test-pc",
            "captured_at": datetime.utcnow().isoformat(),
            "connections": conns,
        }, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["saved"] == 1
        nc = db_session.query(NetworkConnection).first()
        assert nc.remote_ip == "8.8.8.8"

    def test_add_network_empty(self, client):
        r = client.post("/api/network", json={
            "hostname": "test-pc",
            "captured_at": datetime.utcnow().isoformat(),
            "connections": [],
        }, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["saved"] == 0

    def test_get_network_connections(self, client, db_session):
        c = _make_computer(db_session)
        nc = NetworkConnection(
            computer_id=c.id, captured_at=datetime.utcnow(),
            process_name="firefox.exe", remote_ip="1.2.3.4",
            remote_port=80, status="ESTABLISHED"
        )
        db_session.add(nc)
        db_session.commit()
        r = client.get(f"/api/computer/{c.id}/network")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["remote_ip"] == "1.2.3.4"

    def test_get_network_empty(self, client, db_session):
        c = _make_computer(db_session)
        r = client.get(f"/api/computer/{c.id}/network")
        assert r.status_code == 200
        assert r.json() == []


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/print  +  GET /api/computer/{id}/print
# ══════════════════════════════════════════════════════════════════════════════

class TestPrint:

    def test_add_print_job(self, client, db_session):
        r = client.post("/api/print", json={
            "hostname": "test-pc",
            "printed_at": datetime.utcnow().isoformat(),
            "document_name": "report.pdf",
            "printer_name": "HP LaserJet",
            "pages": 5,
            "username": "user1",
        }, headers=AUTH)
        assert r.status_code == 200
        job = db_session.query(PrintJob).first()
        assert job.document_name == "report.pdf"
        assert job.pages == 5

    def test_add_print_job_minimal(self, client, db_session):
        r = client.post("/api/print", json={
            "hostname": "test-pc",
            "printed_at": datetime.utcnow().isoformat(),
        }, headers=AUTH)
        assert r.status_code == 200

    def test_get_print_jobs(self, client, db_session):
        c = _make_computer(db_session)
        db_session.add(PrintJob(
            computer_id=c.id, printed_at=datetime.utcnow(),
            document_name="doc.docx", printer_name="Canon", pages=3, username="u1"
        ))
        db_session.commit()
        r = client.get(f"/api/computer/{c.id}/print")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["document_name"] == "doc.docx"

    def test_get_print_jobs_empty(self, client, db_session):
        c = _make_computer(db_session)
        r = client.get(f"/api/computer/{c.id}/print")
        assert r.json() == []

    def test_print_wrong_key(self, client):
        r = client.post("/api/print", json={
            "hostname": "pc", "printed_at": datetime.utcnow().isoformat()
        }, headers={"X-API-Key": "bad"})
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/computers  +  GET /api/live
# ══════════════════════════════════════════════════════════════════════════════

class TestComputersAPI:

    def test_api_computers_empty(self, client):
        r = client.get("/api/computers")
        assert r.status_code == 200
        assert r.json() == []

    def test_api_computers_returns_list(self, client, db_session):
        _make_computer(db_session, "pc-1")
        _make_computer(db_session, "pc-2")
        r = client.get("/api/computers")
        assert r.status_code == 200
        hostnames = {c["hostname"] for c in r.json()}
        assert hostnames == {"pc-1", "pc-2"}

    def test_api_computers_marks_offline(self, client, db_session):
        old = Computer(hostname="old-pc",
                       last_seen=datetime.utcnow() - timedelta(minutes=10),
                       is_online=True)
        db_session.add(old)
        db_session.commit()
        r = client.get("/api/computers")
        data = {c["hostname"]: c for c in r.json()}
        assert data["old-pc"]["is_online"] is False

    def test_api_live_empty(self, client):
        r = client.get("/api/live")
        assert r.status_code == 200
        assert r.json() == []

    def test_api_live_includes_last_event(self, client, db_session):
        c = _make_computer(db_session)
        _make_event(db_session, c.id, proc="word.exe")
        r = client.get("/api/live")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["current_app"] == "word.exe"

    def test_api_events_for_computer(self, client, db_session):
        c = _make_computer(db_session)
        _make_event(db_session, c.id, proc="code.exe", dur=300)
        r = client.get(f"/api/computer/{c.id}/events")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["process_name"] == "code.exe"
        assert data[0]["productivity"] == "productive"

    def test_api_events_empty_for_computer(self, client, db_session):
        c = _make_computer(db_session)
        r = client.get(f"/api/computer/{c.id}/events")
        assert r.json() == []

    def test_api_screenshot_days_local_empty(self, client, db_session):
        c = _make_computer(db_session)
        r = client.get(f"/api/computer/{c.id}/screenshot-days")
        assert r.status_code == 200
        assert r.json() == []

    def test_api_screenshot_days_not_found(self, client):
        r = client.get("/api/computer/9999/screenshot-days")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Dashboard HTML эндпоинты
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboard:

    def test_index_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_index_shows_computers(self, client, db_session):
        _make_computer(db_session, "workstation-01")
        r = client.get("/")
        assert r.status_code == 200
        assert "workstation-01" in r.text

    def test_live_page(self, client):
        r = client.get("/live")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_gallery_page(self, client):
        r = client.get("/gallery")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_computer_detail_not_found(self, client):
        r = client.get("/computer/9999")
        assert r.status_code == 404

    def test_computer_detail(self, client, db_session):
        c = _make_computer(db_session, "detail-pc")
        r = client.get(f"/computer/{c.id}")
        assert r.status_code == 200
        assert "detail-pc" in r.text

    def test_computer_detail_with_day(self, client, db_session):
        c = _make_computer(db_session, "detail-pc")
        _make_event(db_session, c.id, proc="excel.exe", dur=200)
        r = client.get(f"/computer/{c.id}?day={date.today().isoformat()}")
        assert r.status_code == 200

    def test_computer_detail_productivity_labels(self, client, db_session):
        c = _make_computer(db_session, "prod-pc")
        _make_event(db_session, c.id, proc="1cv8.exe", dur=3600)
        r = client.get(f"/computer/{c.id}?day={date.today().isoformat()}")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
#  GET /report/{hostname}/{day}
# ══════════════════════════════════════════════════════════════════════════════

class TestReport:

    def test_report_html_returns_html(self, client, mocker):
        mocker.patch("activity_log._s3_get_json", return_value={})
        mocker.patch("activity_log._s3_put")
        r = client.get("/report/test-pc/2024-01-15")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "SyncLayer" in r.text

    def test_report_html_with_data(self, client, mocker):
        summary = {
            "hostname": "test-pc",
            "date": "2024-01-15",
            "active_seconds": 7200,
            "idle_seconds": 1800,
            "active_formatted": "2ч 0м",
            "idle_formatted": "30м 0с",
            "first_event": "2024-01-15T09:00:00",
            "last_event": "2024-01-15T18:00:00",
            "switch_count": 42,
            "productivity": {
                "productive_seconds": 5000,
                "productive_percent": 69,
                "productive_formatted": "1ч 23м",
                "neutral_seconds": 2000,
                "neutral_formatted": "33м 20с",
                "distracting_seconds": 200,
                "distracting_formatted": "3м 20с",
            },
            "top_apps": [],
        }
        mocker.patch("activity_log._s3_get_json", side_effect=lambda h, d, f: (
            summary if f == "summary.json" else []
        ))
        mocker.patch("activity_log._s3_put")
        r = client.get("/report/test-pc/2024-01-15")
        assert r.status_code == 200
        assert "test-pc" in r.text


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/activity/...
# ══════════════════════════════════════════════════════════════════════════════

class TestActivityAPI:

    def test_api_activity_empty(self, client, mocker):
        mocker.patch("activity_log._s3_get_json", return_value=[])
        r = client.get("/api/activity/test-pc/2024-01-15")
        assert r.status_code == 200
        assert r.json() == []

    def test_api_timeline_empty(self, client, mocker):
        mocker.patch("activity_log._s3_get_json", return_value={})
        r = client.get("/api/activity/test-pc/2024-01-15/timeline")
        assert r.status_code == 200
        assert r.json() == {}

    def test_api_summary_empty(self, client, mocker):
        mocker.patch("activity_log._s3_get_json", return_value={})
        r = client.get("/api/activity/test-pc/2024-01-15/summary")
        assert r.status_code == 200
        assert r.json() == {}

    def test_api_screenshots_rich_local(self, client, db_session, tmp_path, monkeypatch):
        import main as m
        monkeypatch.setattr(m, "SCREENSHOTS_DIR", tmp_path)
        monkeypatch.setattr(m, "SCREENSHOT_STORAGE", "local")

        r = client.get("/api/screenshots/test-pc/2024-01-15")
        assert r.status_code == 200
        data = r.json()
        assert "screenshots" in data
        assert "summary" in data

    def test_api_screenshots_list_local_empty(self, client, tmp_path, monkeypatch):
        import main as m
        monkeypatch.setattr(m, "SCREENSHOTS_DIR", tmp_path)
        monkeypatch.setattr(m, "SCREENSHOT_STORAGE", "local")

        r = client.get("/screenshots/api/test-pc/2024-01-15")
        assert r.status_code == 200
        assert r.json() == []


# ══════════════════════════════════════════════════════════════════════════════
#  Прочие edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_invalid_day_param(self, client, db_session):
        c = _make_computer(db_session)
        r = client.get(f"/computer/{c.id}?day=not-a-date")
        assert r.status_code == 400

    def test_heartbeat_marks_computer_online(self, client, db_session):
        old = Computer(hostname="offline-pc",
                       last_seen=datetime.utcnow() - timedelta(hours=1),
                       is_online=False)
        db_session.add(old)
        db_session.commit()
        client.post("/api/heartbeat", json={"hostname": "offline-pc"}, headers=AUTH)
        db_session.refresh(old)
        assert old.is_online is True

    def test_network_connection_saves_all_fields(self, client, db_session):
        r = client.post("/api/network", json={
            "hostname": "test-pc",
            "captured_at": datetime.utcnow().isoformat(),
            "connections": [{
                "process_name": "putty.exe",
                "pid": 555,
                "remote_ip": "203.0.113.1",
                "remote_port": 22,
                "local_port": 60000,
                "status": "ESTABLISHED",
            }]
        }, headers=AUTH)
        assert r.status_code == 200
        nc = db_session.query(NetworkConnection).first()
        assert nc.process_name == "putty.exe"
        assert nc.remote_port == 22
        assert nc.local_port == 60000
        assert nc.status == "ESTABLISHED"

    def test_events_with_idle_type_counted(self, client, db_session):
        now = datetime.utcnow()
        payload = {
            "hostname": "test-pc",
            "events": [{
                "hostname": "test-pc",
                "started_at": (now - timedelta(minutes=30)).isoformat(),
                "ended_at": now.isoformat(),
                "duration_seconds": 1800,
                "process_name": "idle",
                "window_title": "",
                "event_type": "idle",
            }]
        }
        r = client.post("/api/events", json=payload, headers=AUTH)
        assert r.status_code == 200
        stat = db_session.query(DailyStat).filter_by(process_name="idle").first()
        assert stat is not None
        assert stat.total_seconds == 1800
