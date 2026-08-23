"""
Тесты SQLAlchemy-моделей (server/models.py).
Проверяют структуру таблиц, ограничения и связи.
"""
import pytest
from datetime import datetime, date
from sqlalchemy.exc import IntegrityError

from models import Computer, Event, DailyStat, ProcessSnapshot, NetworkConnection, PrintJob


# ══════════════════════════════════════════════════════════════════════════════
#  Computer
# ══════════════════════════════════════════════════════════════════════════════

class TestComputerModel:

    def test_create_minimal(self, db_session):
        c = Computer(hostname="workstation-01")
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)
        assert c.id is not None
        assert c.hostname == "workstation-01"
        assert c.is_online is False  # default

    def test_create_full(self, db_session):
        c = Computer(
            hostname="server-01",
            ip_address="192.168.1.100",
            username="admin",
            os_version="Windows Server 2019",
            agent_version="1.0",
            is_online=True,
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)
        assert c.ip_address == "192.168.1.100"
        assert c.username == "admin"
        assert c.is_online is True

    def test_hostname_unique(self, db_session):
        db_session.add(Computer(hostname="dup-pc"))
        db_session.commit()
        db_session.add(Computer(hostname="dup-pc"))
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_hostname_not_null(self, db_session):
        db_session.add(Computer(hostname=None))
        with pytest.raises(IntegrityError):
            db_session.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Event
# ══════════════════════════════════════════════════════════════════════════════

class TestEventModel:

    def test_create_event(self, db_session):
        c = Computer(hostname="pc-01")
        db_session.add(c)
        db_session.flush()

        e = Event(
            computer_id=c.id,
            started_at=datetime(2024, 1, 15, 9, 0, 0),
            ended_at=datetime(2024, 1, 15, 9, 5, 0),
            duration_seconds=300,
            process_name="excel.exe",
            window_title="Book1.xlsx",
            event_type="focus",
        )
        db_session.add(e)
        db_session.commit()
        db_session.refresh(e)
        assert e.id is not None
        assert e.process_name == "excel.exe"
        assert e.duration_seconds == 300

    def test_event_computer_relationship(self, db_session):
        c = Computer(hostname="rel-pc")
        db_session.add(c)
        db_session.flush()
        e = Event(computer_id=c.id, started_at=datetime.utcnow(),
                  duration_seconds=60, process_name="notepad.exe")
        db_session.add(e)
        db_session.commit()
        assert e.computer.hostname == "rel-pc"


# ══════════════════════════════════════════════════════════════════════════════
#  DailyStat
# ══════════════════════════════════════════════════════════════════════════════

class TestDailyStatModel:

    def test_create_daily_stat(self, db_session):
        c = Computer(hostname="stat-pc")
        db_session.add(c)
        db_session.flush()
        s = DailyStat(
            computer_id=c.id,
            date=date(2024, 1, 15),
            process_name="excel.exe",
            total_seconds=3600,
            launches_count=3,
        )
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        assert s.total_seconds == 3600
        assert s.launches_count == 3

    def test_unique_constraint(self, db_session):
        c = Computer(hostname="uc-pc")
        db_session.add(c)
        db_session.flush()
        db_session.add(DailyStat(computer_id=c.id, date=date(2024, 1, 1),
                                  process_name="chrome.exe", total_seconds=100))
        db_session.commit()
        db_session.add(DailyStat(computer_id=c.id, date=date(2024, 1, 1),
                                  process_name="chrome.exe", total_seconds=200))
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_same_process_different_day_allowed(self, db_session):
        c = Computer(hostname="days-pc")
        db_session.add(c)
        db_session.flush()
        db_session.add(DailyStat(computer_id=c.id, date=date(2024, 1, 1),
                                  process_name="chrome.exe", total_seconds=100))
        db_session.add(DailyStat(computer_id=c.id, date=date(2024, 1, 2),
                                  process_name="chrome.exe", total_seconds=200))
        db_session.commit()
        count = db_session.query(DailyStat).filter_by(computer_id=c.id).count()
        assert count == 2


# ══════════════════════════════════════════════════════════════════════════════
#  ProcessSnapshot
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessSnapshotModel:

    def test_create_snapshot_with_json(self, db_session):
        c = Computer(hostname="snap-pc")
        db_session.add(c)
        db_session.flush()
        procs = [{"name": "chrome.exe", "pid": 1234, "cpu_percent": 5.2}]
        s = ProcessSnapshot(computer_id=c.id, captured_at=datetime.utcnow(),
                            processes=procs)
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        assert s.processes[0]["name"] == "chrome.exe"

    def test_empty_processes_list(self, db_session):
        c = Computer(hostname="empty-snap-pc")
        db_session.add(c)
        db_session.flush()
        s = ProcessSnapshot(computer_id=c.id, captured_at=datetime.utcnow(),
                            processes=[])
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        assert s.processes == []


# ══════════════════════════════════════════════════════════════════════════════
#  NetworkConnection
# ══════════════════════════════════════════════════════════════════════════════

class TestNetworkConnectionModel:

    def test_create_connection(self, db_session):
        c = Computer(hostname="net-pc")
        db_session.add(c)
        db_session.flush()
        nc = NetworkConnection(
            computer_id=c.id,
            captured_at=datetime.utcnow(),
            process_name="chrome.exe",
            pid=5000,
            remote_ip="8.8.8.8",
            remote_port=443,
            local_port=55000,
            status="ESTABLISHED",
        )
        db_session.add(nc)
        db_session.commit()
        db_session.refresh(nc)
        assert nc.remote_ip == "8.8.8.8"
        assert nc.status == "ESTABLISHED"


# ══════════════════════════════════════════════════════════════════════════════
#  PrintJob
# ══════════════════════════════════════════════════════════════════════════════

class TestPrintJobModel:

    def test_create_print_job(self, db_session):
        c = Computer(hostname="print-pc")
        db_session.add(c)
        db_session.flush()
        j = PrintJob(
            computer_id=c.id,
            printed_at=datetime.utcnow(),
            document_name="report.pdf",
            printer_name="HP LaserJet",
            pages=10,
            username="user1",
        )
        db_session.add(j)
        db_session.commit()
        db_session.refresh(j)
        assert j.pages == 10
        assert j.document_name == "report.pdf"


# ══════════════════════════════════════════════════════════════════════════════
#  Cascade delete
# ══════════════════════════════════════════════════════════════════════════════

class TestCascadeDelete:

    def test_delete_computer_cascades_events(self, db_session):
        c = Computer(hostname="del-pc")
        db_session.add(c)
        db_session.flush()
        e = Event(computer_id=c.id, started_at=datetime.utcnow(),
                  duration_seconds=60, process_name="test.exe")
        db_session.add(e)
        db_session.commit()

        db_session.delete(c)
        db_session.commit()
        assert db_session.query(Event).filter_by(computer_id=c.id).count() == 0

    def test_delete_computer_cascades_print_jobs(self, db_session):
        c = Computer(hostname="del-print-pc")
        db_session.add(c)
        db_session.flush()
        j = PrintJob(computer_id=c.id, printed_at=datetime.utcnow(),
                     document_name="x.pdf", pages=1, username="u")
        db_session.add(j)
        db_session.commit()

        db_session.delete(c)
        db_session.commit()
        assert db_session.query(PrintJob).filter_by(computer_id=c.id).count() == 0
