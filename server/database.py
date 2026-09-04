import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://watcher:watcher_pass@localhost:5432/watcher_db"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import (  # noqa: F401
        Computer, Event, DailyStat, ProcessSnapshot, NetworkConnection, PrintJob
    )
    Base.metadata.create_all(bind=engine)
    _ensure_computer_columns()
    _ensure_event_columns()


def _telemetry_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ensure_event_columns():
    """Добавляет telemetry-поля в events на существующих БД без Alembic."""
    from sqlalchemy import inspect, text

    columns = {
        "mouse_clicks": "INTEGER DEFAULT 0",
        "key_activity": "INTEGER DEFAULT 0",
        "scroll_events": "INTEGER DEFAULT 0",
        "idle_seconds": "INTEGER DEFAULT 0",
    }
    try:
        insp = inspect(engine)
        if "events" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("events")}
        for name, ddl in columns.items():
            if name not in existing:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE events ADD COLUMN {name} {ddl}"))
    except Exception:
        pass


def _ensure_computer_columns():
    """Добавляет новые колонки на существующих БД без Alembic."""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        if "computers" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("computers")}
        if "monitoring_state" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE computers ADD COLUMN monitoring_state "
                        "VARCHAR(20) DEFAULT 'active'"
                    )
                )
        if "agent_ram_mb" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE computers ADD COLUMN agent_ram_mb INTEGER"))
        if "screenshots_enabled" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE computers ADD COLUMN screenshots_enabled "
                        "BOOLEAN DEFAULT TRUE"
                    )
                )
    except Exception:
        pass
