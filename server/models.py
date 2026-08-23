from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text,
    DateTime, Boolean, ForeignKey, Date, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship
from database import Base

# BigInteger PK совместимый с SQLite (для тестов), и с PostgreSQL (в продакшне)
_BigPK = BigInteger().with_variant(Integer(), "sqlite")


class Computer(Base):
    __tablename__ = "computers"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(255), unique=True, nullable=False, index=True)
    ip_address = Column(String(50))
    username = Column(String(255))
    os_version = Column(String(255))
    agent_version = Column(String(50))
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_online = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    events = relationship("Event", back_populates="computer", cascade="all, delete-orphan")
    daily_stats = relationship("DailyStat", back_populates="computer", cascade="all, delete-orphan")
    process_snapshots = relationship("ProcessSnapshot", back_populates="computer", cascade="all, delete-orphan")
    network_connections = relationship("NetworkConnection", back_populates="computer", cascade="all, delete-orphan")
    print_jobs = relationship("PrintJob", back_populates="computer", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"

    id = Column(_BigPK, primary_key=True, index=True)
    computer_id = Column(Integer, ForeignKey("computers.id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, index=True)
    ended_at = Column(DateTime)
    duration_seconds = Column(Integer, default=0)
    process_name = Column(String(255), index=True)
    window_title = Column(Text)
    event_type = Column(String(50), default="focus")  # focus | idle | login | logout

    computer = relationship("Computer", back_populates="events")


class DailyStat(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, index=True)
    computer_id = Column(Integer, ForeignKey("computers.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    process_name = Column(String(255), nullable=False)
    total_seconds = Column(Integer, default=0)
    launches_count = Column(Integer, default=0)

    computer = relationship("Computer", back_populates="daily_stats")

    __table_args__ = (
        UniqueConstraint("computer_id", "date", "process_name", name="uq_daily_stat"),
    )


class ProcessSnapshot(Base):
    """Снимок всех запущенных процессов раз в 5 минут."""
    __tablename__ = "process_snapshots"

    id = Column(_BigPK, primary_key=True, index=True)
    computer_id = Column(Integer, ForeignKey("computers.id"), nullable=False, index=True)
    captured_at = Column(DateTime, nullable=False, index=True)
    # JSON список: [{name, pid, cpu_percent, memory_mb, username}]
    processes = Column(JSON, nullable=False)

    computer = relationship("Computer", back_populates="process_snapshots")


class NetworkConnection(Base):
    """Активные сетевые подключения процессов."""
    __tablename__ = "network_connections"

    id = Column(_BigPK, primary_key=True, index=True)
    computer_id = Column(Integer, ForeignKey("computers.id"), nullable=False, index=True)
    captured_at = Column(DateTime, nullable=False, index=True)
    process_name = Column(String(255), index=True)
    pid = Column(Integer)
    remote_ip = Column(String(50))
    remote_port = Column(Integer)
    local_port = Column(Integer)
    status = Column(String(50))  # ESTABLISHED, TIME_WAIT, etc.

    computer = relationship("Computer", back_populates="network_connections")


class PrintJob(Base):
    """Задания на печать."""
    __tablename__ = "print_jobs"

    id = Column(Integer, primary_key=True, index=True)
    computer_id = Column(Integer, ForeignKey("computers.id"), nullable=False, index=True)
    printed_at = Column(DateTime, nullable=False, index=True)
    document_name = Column(Text)
    printer_name = Column(String(255))
    pages = Column(Integer, default=0)
    username = Column(String(255))

    computer = relationship("Computer", back_populates="print_jobs")
