"""
Конфигурация тестового окружения.
Устанавливает env-переменные и патчит БД ДО любых импортов.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

# ── Пути ─────────────────────────────────────────────────────────────────────
SERVER_DIR = Path(__file__).parent.parent
TESTS_DIR = Path(__file__).parent
os.chdir(str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(TESTS_DIR))

# ── Env vars (до импорта database/main) ──────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("API_KEY", "test-key-123")
os.environ.setdefault("AUTH_USERNAME", "administrator")
os.environ.setdefault("AUTH_PASSWORD", "superwatcher")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-pytest-only")
os.environ.setdefault("SCREENSHOT_STORAGE", "local")
os.environ.setdefault("SCREENSHOTS_DIR", str(SERVER_DIR / "test_screenshots_tmp"))
os.environ.setdefault("S3_BUCKET", "watcher-test")

# ── SQLite in-memory engine (до импорта database.py) ─────────────────────────
import sqlalchemy as _sa
from sqlalchemy import create_engine as _real_create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_ENGINE = _real_create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TEST_SESSION = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


# Перехватываем create_engine в database.py — SQLite не поддерживает
# pool_size/max_overflow, поэтому возвращаем наш готовый движок
with patch.object(_sa, "create_engine", return_value=TEST_ENGINE):
    import database

# Принудительно указываем тестовые значения
database.engine = TEST_ENGINE
database.SessionLocal = TEST_SESSION

# ── Импорт приложения ─────────────────────────────────────────────────────────
import pytest
from fastapi.testclient import TestClient

from database import Base, get_db
from main import app


def _override_get_db():
    db = TEST_SESSION()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

# ── Константы ─────────────────────────────────────────────────────────────────
API_KEY = "test-key-123"
AUTH = {"X-API-Key": API_KEY}


# ── Фикстуры ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_db():
    """Создаёт таблицы перед тестом, удаляет после."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def anon_client(reset_db):
    """TestClient без авторизации."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(anon_client):
    """TestClient с активной сессией дашборда."""
    anon_client.post(
        "/login",
        data={"username": "administrator", "password": "superwatcher", "next": "/"},
        follow_redirects=False,
    )
    yield anon_client


@pytest.fixture
def db_session(reset_db):
    """Прямая сессия БД для подготовки данных / проверок."""
    session = TEST_SESSION()
    try:
        yield session
    finally:
        session.close()
