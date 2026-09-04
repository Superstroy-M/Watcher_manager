from datetime import datetime, timedelta

import pytest

from computer_status import connection_status, is_connection_online, serialize_computer
from models import Computer

AUTH = {"X-API-Key": "test-key-123"}


def test_connection_status_online():
    now = datetime.utcnow()
    assert connection_status(now - timedelta(seconds=30), now) == "online"


def test_connection_status_unstable():
    now = datetime.utcnow()
    assert connection_status(now - timedelta(seconds=120), now) == "unstable"


def test_connection_status_offline():
    now = datetime.utcnow()
    assert connection_status(now - timedelta(seconds=300), now) == "offline"


def test_heartbeat_stores_agent_diagnostics(client, db_session):
    r = client.post(
        "/api/heartbeat",
        json={
            "hostname": "pc-diag",
            "agent_version": "1.3",
            "ram_mb": 185.6,
            "screenshots_enabled": False,
            "monitoring_state": "active",
        },
        headers=AUTH,
    )
    assert r.status_code == 200
    db_session.expire_all()
    c = db_session.query(Computer).filter_by(hostname="pc-diag").first()
    assert c.agent_ram_mb == 186
    assert c.screenshots_enabled is False


def test_serialize_computer_includes_agent_diagnostics(db_session):
    c = Computer(
        hostname="pc-2",
        last_seen=datetime.utcnow(),
        monitoring_state="active",
        agent_version="1.3",
        agent_ram_mb=210,
        screenshots_enabled=True,
    )
    db_session.add(c)
    db_session.commit()
    data = serialize_computer(c)
    assert data["agent_ram_mb"] == 210
    assert data["screenshots_enabled"] is True


def test_serialize_computer_includes_monitoring_state(db_session):
    c = Computer(
        hostname="pc-1",
        last_seen=datetime.utcnow(),
        monitoring_state="paused",
        agent_version="1.3",
    )
    db_session.add(c)
    db_session.commit()
    data = serialize_computer(c)
    assert data["monitoring_state"] == "paused"
    assert data["connection_status"] == "online"
    assert data["agent_version"] == "1.3"
