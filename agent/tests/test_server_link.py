import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import server_link


@pytest.fixture(autouse=True)
def reset_server_link():
    server_link.reset_state(start_online=False)
    yield


def test_starts_offline_until_probe():
    assert server_link.is_online() is False


def test_mark_offline_purges_buffer_and_screenshots(tmp_path, monkeypatch):
    buffer_file = tmp_path / "offline_buffer.jsonl"
    shots_dir = tmp_path / "screenshots_offline"
    shots_dir.mkdir()
    (shots_dir / "old.jpg").write_bytes(b"jpg")
    buffer_file.write_text(json.dumps({"id": 1}) + "\n", encoding="utf-8")

    monkeypatch.setattr(server_link, "BUFFER_FILE", buffer_file)
    monkeypatch.setattr(server_link, "OFFLINE_SCREENSHOT_DIR", shots_dir)
    server_link.mark_online()

    server_link.mark_offline("timeout")

    assert server_link.is_online() is False
    assert not buffer_file.exists()
    assert not list(shots_dir.glob("*.jpg"))


def test_probe_marks_online_on_success():
    response = MagicMock()
    response.raise_for_status.return_value = None

    with patch("server_link.get", return_value=response):
        assert server_link.try_probe() is True

    assert server_link.is_online() is True


def test_probe_marks_offline_on_failure():
    with patch("server_link.get", side_effect=ConnectionError("down")):
        assert server_link.try_probe() is False

    assert server_link.is_online() is False


def test_try_probe_is_single_flight(monkeypatch):
    calls = {"count": 0}
    started = threading.Event()
    release = threading.Event()

    def slow_get(*args, **kwargs):
        calls["count"] += 1
        started.set()
        release.wait(timeout=2)
        response = MagicMock()
        response.raise_for_status.return_value = None
        return response

    monkeypatch.setattr(server_link, "get", slow_get)
    monkeypatch.setattr(server_link, "OFFLINE_PROBE_INTERVAL", 9999)

    t1 = threading.Thread(target=server_link.try_probe)
    t2 = threading.Thread(target=server_link.try_probe)
    t1.start()
    assert started.wait(timeout=2)
    t2.start()
    t2.join(timeout=2)
    release.set()
    t1.join(timeout=2)

    assert calls["count"] == 1


def test_mark_offline_on_transport_error_ignores_non_network():
    server_link.mark_online()
    assert server_link.is_online() is True

    assert server_link.mark_offline_on_transport_error(AttributeError("'srcdc'")) is False
    assert server_link.is_online() is True

    assert server_link.mark_offline_on_transport_error(ConnectionError("down")) is True
    assert server_link.is_online() is False


def test_sleep_interval_changes_with_state():
    server_link.mark_online()
    assert server_link.sleep_interval() == server_link.SEND_INTERVAL

    server_link.mark_offline("down")
    assert server_link.sleep_interval() == server_link.OFFLINE_PROBE_INTERVAL
