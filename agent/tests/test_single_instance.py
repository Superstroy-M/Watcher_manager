import sys
from unittest.mock import MagicMock, patch

import pytest

import single_instance


def test_acquire_or_exit_exits_when_mutex_already_exists(monkeypatch):
    monkeypatch.setattr(single_instance, "_mutex_handle", None)

    kernel32 = MagicMock()
    kernel32.CreateMutexW.return_value = 42
    kernel32.GetLastError.return_value = 183

    with patch.object(sys, "platform", "win32"), patch(
        "single_instance._create_mutex", return_value=(42, 183)
    ), patch.object(sys, "exit") as exit_mock:
        single_instance.acquire_or_exit()

    exit_mock.assert_called_once_with(0)


def test_acquire_or_exit_skips_on_non_windows(monkeypatch):
    monkeypatch.setattr(single_instance, "_mutex_handle", None)
    with patch.object(sys, "platform", "darwin"):
        single_instance.acquire_or_exit()
    assert single_instance._mutex_handle is None
