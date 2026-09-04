from datetime import datetime, timedelta

import pytest

from helpers import AUTH
from models import Computer


def _make_computer(db, hostname="pc-1", monitoring_state="active"):
    c = Computer(
        hostname=hostname,
        last_seen=datetime.utcnow(),
        monitoring_state=monitoring_state,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


class TestMonitoringControl:

    def test_heartbeat_returns_monitoring_state(self, client, db_session):
        c = _make_computer(db_session, monitoring_state="paused")
        r = client.post("/api/heartbeat", json={"hostname": c.hostname}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["monitoring_state"] == "paused"

    def test_heartbeat_updates_last_seen_only(self, client, db_session):
        old = datetime.utcnow() - timedelta(hours=2)
        c = Computer(hostname="pc-old", last_seen=old, is_online=False)
        db_session.add(c)
        db_session.commit()

        client.post("/api/heartbeat", json={"hostname": "pc-old"}, headers=AUTH)
        db_session.refresh(c)
        assert (datetime.utcnow() - c.last_seen).total_seconds() < 5

    def test_pause_via_dashboard_api(self, client, db_session):
        c = _make_computer(db_session, monitoring_state="active")
        r = client.post(
            f"/api/computer/{c.id}/monitoring",
            json={"state": "paused"},
        )
        assert r.status_code == 200
        db_session.refresh(c)
        assert c.monitoring_state == "paused"

    def test_resume_via_dashboard_api(self, client, db_session):
        c = _make_computer(db_session, monitoring_state="paused")
        r = client.post(
            f"/api/computer/{c.id}/monitoring",
            json={"state": "active"},
        )
        assert r.status_code == 200
        db_session.refresh(c)
        assert c.monitoring_state == "active"

    def test_events_skipped_when_paused(self, client, db_session):
        c = _make_computer(db_session, monitoring_state="paused")
        now = datetime.utcnow()
        r = client.post("/api/events", json={
            "hostname": c.hostname,
            "events": [{
                "hostname": c.hostname,
                "started_at": (now - timedelta(minutes=1)).isoformat(),
                "ended_at": now.isoformat(),
                "duration_seconds": 60,
                "process_name": "excel.exe",
                "window_title": "",
                "event_type": "focus",
            }],
        }, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["skipped"] == "monitoring_paused"

    def test_api_computers_connection_status_from_last_seen(self, client, db_session):
        c = Computer(
            hostname="stale-pc",
            last_seen=datetime.utcnow() - timedelta(minutes=5),
            monitoring_state="active",
        )
        db_session.add(c)
        db_session.commit()

        r = client.get("/api/computers")
        data = {x["hostname"]: x for x in r.json()}
        assert data["stale-pc"]["connection_status"] == "offline"
        assert data["stale-pc"]["is_online"] is False

    def test_online_recovery_after_stale_last_seen(self, client, db_session):
        c = Computer(
            hostname="recover-pc",
            last_seen=datetime.utcnow() - timedelta(minutes=10),
            monitoring_state="active",
        )
        db_session.add(c)
        db_session.commit()

        r = client.get("/api/computers")
        assert r.json()[0]["connection_status"] == "offline"

        client.post("/api/heartbeat", json={"hostname": "recover-pc"}, headers=AUTH)
        r = client.get("/api/computers")
        assert r.json()[0]["connection_status"] == "online"
