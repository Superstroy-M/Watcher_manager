"""Tests for verify_build_url.py (config + PyInstaller binary scan)."""

from __future__ import annotations

import subprocess
import sys
import zlib
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
VERIFY = AGENT_DIR / "verify_build_url.py"


def test_verify_config_passes():
    result = subprocess.run(
        [sys.executable, str(VERIFY), "config"],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        env={k: v for k, v in __import__("os").environ.items() if k != "SYNCLAYER_SERVER_URL"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "watcher.tunellink.ru" in result.stdout


def test_verify_agent_exe_on_local_build():
    exe = AGENT_DIR / "dist" / "SyncLayerAgent"
    if sys.platform == "win32":
        exe = AGENT_DIR / "dist" / "SyncLayerAgent.exe"
    if not exe.is_file():
        pytest.skip("SyncLayerAgent binary not built locally")

    result = subprocess.run(
        [sys.executable, str(VERIFY), "agent-exe", "--path", str(exe)],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_binary_scan_fails_on_forbidden_host(tmp_path: Path):
    payload = b"config SERVER_URL http://201.51.8.127:8000"
    compressed = zlib.compress(payload)
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"\x00" * 100 + compressed + b"MEI\x0c\x0b\x0a\x0b\x0e")

    from verify_build_url import _scan_binary

    with pytest.raises(SystemExit, match="201.51.8.127"):
        _scan_binary(fake_exe, "test.exe")


def test_binary_scan_requires_production_host(tmp_path: Path):
    payload = b"unrelated module data without production host"
    compressed = zlib.compress(payload)
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"\x00" * 100 + compressed + b"MEI\x0c\x0b\x0a\x0b\x0e")

    from verify_build_url import _scan_binary

    with pytest.raises(SystemExit, match="watcher.tunellink.ru"):
        _scan_binary(fake_exe, "test.exe")
