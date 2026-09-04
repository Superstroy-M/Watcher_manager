"""Tests for verify_build_url.py (config + build marker in exe)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
VERIFY = AGENT_DIR / "verify_build_url.py"
MARKER = b"SYNCLAYER_SERVER_URL=https://watcher.tunellink.ru"


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

    data = exe.read_bytes()
    if MARKER not in data and b"watcher.tunellink.ru" not in data:
        pytest.skip("local build missing production URL embed — CI build only")

    result = subprocess.run(
        [sys.executable, str(VERIFY), "agent-exe", "--path", str(exe)],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_verify_agent_exe_accepts_build_marker(tmp_path: Path):
    exe = tmp_path / "SyncLayerAgent.exe"
    exe.write_bytes(b"\x00" * (5 * 1024 * 1024) + MARKER)

    from verify_build_url import verify_agent_exe

    verify_agent_exe(exe)


def test_verify_agent_exe_rejects_missing_host(tmp_path: Path):
    exe = tmp_path / "SyncLayerAgent.exe"
    exe.write_bytes(b"\x00" * (5 * 1024 * 1024))

    from verify_build_url import verify_agent_exe

    with pytest.raises(SystemExit, match="watcher.tunellink.ru"):
        verify_agent_exe(exe)


def test_verify_agent_exe_rejects_tiny_file(tmp_path: Path):
    exe = tmp_path / "SyncLayerAgent.exe"
    exe.write_bytes(MARKER)

    from verify_build_url import verify_agent_exe

    with pytest.raises(SystemExit, match="too small"):
        verify_agent_exe(exe)
