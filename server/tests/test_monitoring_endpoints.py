import io
from datetime import datetime, timedelta

from helpers import AUTH
from models import Computer


class TestPausedEndpoints:

    def _paused_computer(self, db_session, hostname="paused-pc"):
        c = Computer(
            hostname=hostname,
            last_seen=datetime.utcnow(),
            monitoring_state="paused",
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)
        return c

    def test_screenshot_skipped_when_paused(self, client, db_session, tmp_path, monkeypatch):
        import main as m

        monkeypatch.setattr(m, "SCREENSHOTS_DIR", tmp_path)
        monkeypatch.setattr(m, "SCREENSHOT_STORAGE", "local")
        c = self._paused_computer(db_session)

        data = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 50)
        r = client.post(
            "/api/screenshot",
            data={"hostname": c.hostname, "timestamp": datetime.utcnow().isoformat()},
            files={"file": ("shot.jpg", data, "image/jpeg")},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["reason"] == "monitoring_paused"

    def test_processes_skipped_when_paused(self, client, db_session):
        c = self._paused_computer(db_session)
        r = client.post("/api/processes", json={
            "hostname": c.hostname,
            "captured_at": datetime.utcnow().isoformat(),
            "processes": [{"name": "a.exe"}],
        }, headers=AUTH)
        assert r.json()["reason"] == "monitoring_paused"

    def test_network_skipped_when_paused(self, client, db_session):
        c = self._paused_computer(db_session)
        r = client.post("/api/network", json={
            "hostname": c.hostname,
            "captured_at": datetime.utcnow().isoformat(),
            "connections": [{"process_name": "a.exe", "remote_ip": "8.8.8.8"}],
        }, headers=AUTH)
        assert r.json()["reason"] == "monitoring_paused"

    def test_print_skipped_when_paused(self, client, db_session):
        c = self._paused_computer(db_session)
        r = client.post("/api/print", json={
            "hostname": c.hostname,
            "printed_at": datetime.utcnow().isoformat(),
            "document_name": "doc.pdf",
        }, headers=AUTH)
        assert r.json()["reason"] == "monitoring_paused"


class TestConnectionStatusThresholds:

    def test_unstable_status(self, client, db_session):
        c = Computer(
            hostname="unstable-pc",
            last_seen=datetime.utcnow() - timedelta(seconds=120),
            monitoring_state="active",
        )
        db_session.add(c)
        db_session.commit()

        data = client.get("/api/computers").json()[0]
        assert data["connection_status"] == "unstable"
        assert data["is_online"] is False

    def test_online_status_recent_heartbeat(self, client, db_session):
        c = Computer(
            hostname="fresh-pc",
            last_seen=datetime.utcnow() - timedelta(seconds=20),
            monitoring_state="active",
            agent_version="1.3",
        )
        db_session.add(c)
        db_session.commit()

        data = client.get("/api/computers").json()[0]
        assert data["connection_status"] == "online"
        assert data["is_online"] is True
        assert data["agent_version"] == "1.3"
        assert data["last_seen_seconds"] <= 30


class TestMonitoringAPIValidation:

    def test_invalid_monitoring_state_rejected(self, client, db_session):
        c = Computer(hostname="pc", last_seen=datetime.utcnow())
        db_session.add(c)
        db_session.commit()

        r = client.post(f"/api/computer/{c.id}/monitoring", json={"state": "destroy"})
        assert r.status_code == 400

    def test_monitoring_api_requires_auth(self, anon_client, db_session):
        c = Computer(hostname="pc", last_seen=datetime.utcnow())
        db_session.add(c)
        db_session.commit()

        r = anon_client.post(f"/api/computer/{c.id}/monitoring", json={"state": "paused"})
        assert r.status_code == 401

    def test_monitoring_api_not_found(self, client):
        r = client.post("/api/computer/99999/monitoring", json={"state": "paused"})
        assert r.status_code == 404
