from unittest.mock import MagicMock, patch

import memory_guard


def setup_function():
    memory_guard.reset_for_tests()


def test_screenshot_disabled_at_500mb():
    memory_guard.check_memory(force_ram_mb=500.0)
    assert memory_guard.screenshots_allowed() is False


def test_screenshot_stays_disabled_after_recovery():
    memory_guard.check_memory(force_ram_mb=520.0)
    memory_guard.check_memory(force_ram_mb=200.0)
    assert memory_guard.screenshots_allowed() is False


def test_safe_restart_at_750mb(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_guard, "RESTART_STATE_FILE", tmp_path / "restart_guard.json")
    monkeypatch.setattr(memory_guard, "RESTART_COOLDOWN_SEC", 0)
    with patch("memory_guard.subprocess.Popen") as popen_mock, patch(
        "memory_guard.os._exit"
    ) as exit_mock:
        memory_guard.check_memory(force_ram_mb=760.0)

    popen_mock.assert_called_once()
    exit_mock.assert_called_once_with(0)


def test_restart_blocked_in_degraded_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_guard, "RESTART_STATE_FILE", tmp_path / "restart_guard.json")
    monkeypatch.setattr(memory_guard, "MAX_RESTARTS", 1)
    monkeypatch.setattr(memory_guard, "RESTART_COOLDOWN_SEC", 0)
    memory_guard._register_restart()
    memory_guard.reset_for_tests()
    memory_guard._restart_requested = False
    memory_guard._register_restart()

    with patch("memory_guard.subprocess.Popen") as popen_mock, patch(
        "memory_guard.os._exit"
    ):
        memory_guard.check_memory(force_ram_mb=800.0)

    popen_mock.assert_not_called()
    assert memory_guard.is_degraded_mode() is True
    assert memory_guard.screenshots_allowed() is False
