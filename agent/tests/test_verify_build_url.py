"""Tests for verify_build_url.py (config source checks for CI)."""

from __future__ import annotations

import subprocess
import sys
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


def test_verify_installer_checks_file_exists(tmp_path: Path):
    installer = tmp_path / "SyncLayerSetup.exe"
    installer.write_bytes(b"\x00" * (200 * 1024))

    from verify_build_url import verify_installer

    verify_installer(installer)


def test_verify_installer_rejects_tiny_file(tmp_path: Path):
    installer = tmp_path / "SyncLayerSetup.exe"
    installer.write_bytes(b" tiny")

    from verify_build_url import verify_installer

    with pytest.raises(SystemExit, match="suspiciously small"):
        verify_installer(installer)
