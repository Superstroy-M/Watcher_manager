"""Static checks for SyncLayer Windows install layout policy."""

from __future__ import annotations

from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]

INSTALLER_FILES = [
    AGENT_DIR / "install.bat",
    AGENT_DIR / "INSTALL-ONE.bat",
    AGENT_DIR / "INSTALL-EXE.bat",
    AGENT_DIR / "УСТАНОВИТЬ.bat",
    AGENT_DIR / "installer" / "SyncLayerSetup.iss",
    AGENT_DIR / "build_setup.ps1",
    AGENT_DIR / "BUILD-EXE.bat",
    AGENT_DIR / "gpo_deploy.bat",
]

FORBIDDEN_PATTERNS = [
    "SyncLayerService.exe",
    "SyncLayerTray",
    "tracker_service.py install",
    "tracker_service.py start",
    "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    'schtasks /Create /F /TN "SyncLayer"',
    'schtasks /Create /F /TN "SyncLayerTray"',
    "SyncLayer.exe",
]


@pytest.mark.parametrize("path", INSTALLER_FILES, ids=[p.name for p in INSTALLER_FILES])
def test_installer_files_do_not_use_legacy_layout(path: Path):
    text = path.read_text(encoding="utf-8")
    for pattern in FORBIDDEN_PATTERNS:
        assert pattern not in text, f"{path.name} still contains forbidden pattern: {pattern}"


@pytest.mark.parametrize("path", INSTALLER_FILES, ids=[p.name for p in INSTALLER_FILES])
def test_installer_files_reference_sync_layer_agent_task(path: Path):
    text = path.read_text(encoding="utf-8")
    if 'call "%~dp0install.bat"' in text:
        pytest.skip("alias redirects to install.bat")
    assert "SyncLayerAgent" in text, f"{path.name} must reference SyncLayerAgent"


def test_install_common_contains_required_functions():
    text = (AGENT_DIR / "install_common.ps1").read_text(encoding="utf-8")
    for pattern in [
        "function Remove-LegacySyncLayerInstall",
        "function Test-SyncLayerInstall",
        "function Invoke-SyncLayerInstallFinalize",
        "function Get-SyncLayerInteractiveUser",
        "function Invoke-SchtasksCreateSyncLayerTask",
        "function Write-SyncLayerInstallLog",
        "function Assert-SyncLayerScheduledTask",
        "$Script:TaskName = 'SyncLayerAgent'",
    ]:
        assert pattern in text, f"install_common.ps1 missing: {pattern}"


def test_installer_runs_finalize_and_verify():
    text = (AGENT_DIR / "installer" / "SyncLayerSetup.iss").read_text(encoding="utf-8")
    assert "install_finalize.ps1" in text
    assert "install_verify.ps1" in text
    assert "procedure CurStepChanged" in text
    assert "abortiferror" not in text
    assert "runascurrentuser" not in text


def test_install_common_uses_direct_schtasks_tr():
    text = (AGENT_DIR / "install_common.ps1").read_text(encoding="utf-8")
    assert "Invoke-SchtasksCreateSyncLayerTask" in text
    assert "TASK CREATE ARGV:" in text
    assert "/RU" not in text.split("function Invoke-SchtasksCreateSyncLayerTask")[1].split("function Assert")[0]
    assert "cmd.exe /c cd /d" not in text
    assert "Register-SyncLayerScheduledTaskViaApi" not in text


def test_install_finalize_uses_common_helpers():
    text = (AGENT_DIR / "install_finalize.ps1").read_text(encoding="utf-8")
    assert "install_common.ps1" in text
    assert "Invoke-SyncLayerInstallFinalize" in text


def test_install_verify_uses_test_helper():
    text = (AGENT_DIR / "install_verify.ps1").read_text(encoding="utf-8")
    assert "Test-SyncLayerInstall" in text


def test_uninstall_uses_shared_cleanup():
    text = (AGENT_DIR / "uninstall.bat").read_text(encoding="utf-8")
    assert "install_common.ps1" in text
    assert "Remove-LegacySyncLayerInstall" in text
    assert "RequireScheduledTask $false" in text


def test_config_uses_production_server_url():
    import config

    assert config.SERVER_URL == "https://watcher.tunellink.ru"
    assert "201.51.8.127" not in config.SERVER_URL
    assert ":8000" not in config.SERVER_URL


def test_installer_scripts_reference_production_dashboard():
    for name in ("install.bat", "INSTALL-ONE.bat", "INSTALL-EXE.bat"):
        text = (AGENT_DIR / name).read_text(encoding="utf-8")
        assert "https://watcher.tunellink.ru" in text
        assert "201.51.8.127" not in text


def test_install_all_points_to_install_bat():
    text = (AGENT_DIR / "install_all.bat").read_text(encoding="utf-8")
    assert "install.bat" in text
    assert "УСТАНОВИТЬ.bat" not in text


def test_ustanovit_is_alias_to_install_bat():
    text = (AGENT_DIR / "УСТАНОВИТЬ.bat").read_text(encoding="utf-8")
    assert "install.bat" in text
    assert "tracker_service.py" not in text
