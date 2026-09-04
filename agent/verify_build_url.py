"""
Проверка production SERVER_URL перед/после сборки PyInstaller.

  python verify_build_url.py config
  python verify_build_url.py agent-exe --path dist/SyncLayerAgent.exe
  python verify_build_url.py installer --path dist/SyncLayerSetup.exe

CI не полагается на findstr/strings: в onefile EXE зашивается build_server_url.txt
с маркером SYNCLAYER_SERVER_URL=...
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

PRODUCTION_URL = "https://watcher.tunellink.ru"
REQUIRED_HOST = "watcher.tunellink.ru"
BUILD_MARKER = f"SYNCLAYER_SERVER_URL={PRODUCTION_URL}".encode("ascii")
FORBIDDEN_HOSTS = ("201.51.8.127",)
MIN_AGENT_EXE_BYTES = 5 * 1024 * 1024


def _agent_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_config_module():
    agent_dir = _agent_dir()
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    os.environ.pop("SYNCLAYER_SERVER_URL", None)
    os.environ.pop("SYNCLAYER_API_KEY", None)

    spec = importlib.util.spec_from_file_location("config", agent_dir / "config.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_config() -> None:
    config = _load_config_module()
    url = getattr(config, "SERVER_URL", "")
    if url != PRODUCTION_URL:
        raise SystemExit(f"config SERVER_URL must be {PRODUCTION_URL!r}, got {url!r}")

    source = (_agent_dir() / "config.py").read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_HOSTS:
        if forbidden in source:
            raise SystemExit(f"config.py must not contain forbidden host {forbidden!r}")

    marker_file = _agent_dir() / "build_server_url.txt"
    if not marker_file.is_file():
        raise SystemExit("build_server_url.txt missing — run build_setup.ps1 first")
    marker = marker_file.read_text(encoding="utf-8").strip()
    if marker != BUILD_MARKER.decode("ascii"):
        raise SystemExit(f"build_server_url.txt mismatch: {marker!r}")

    print(f"OK config.py SERVER_URL={url}")


def verify_agent_exe(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"SyncLayerAgent.exe not found: {path}")

    size = path.stat().st_size
    if size < MIN_AGENT_EXE_BYTES:
        raise SystemExit(
            f"SyncLayerAgent.exe too small ({size} bytes, need >= {MIN_AGENT_EXE_BYTES})"
        )

    data = path.read_bytes()
    if BUILD_MARKER in data:
        print(f"OK SyncLayerAgent.exe: build marker found ({size // (1024 * 1024)} MB)")
        return

    if REQUIRED_HOST.encode("ascii") in data:
        print(f"OK SyncLayerAgent.exe: {REQUIRED_HOST!r} found in payload ({size // (1024 * 1024)} MB)")
        return

    host_utf16 = REQUIRED_HOST.encode("utf-16le")
    if host_utf16 in data:
        print(f"OK SyncLayerAgent.exe: {REQUIRED_HOST!r} found as UTF-16 ({size // (1024 * 1024)} MB)")
        return

    raise SystemExit(
        f"SyncLayerAgent.exe missing production URL marker and {REQUIRED_HOST!r} "
        f"(size={size} bytes)"
    )


def verify_installer(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"installer not found: {path}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb < 0.1:
        raise SystemExit(f"installer suspiciously small: {size_mb:.2f} MB")
    print(f"OK SyncLayerSetup.exe present ({size_mb:.1f} MB)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify SyncLayer production SERVER_URL")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Verify config.py and build marker before PyInstaller")

    agent_p = sub.add_parser("agent-exe", help="Verify built SyncLayerAgent.exe")
    agent_p.add_argument("--path", type=Path, default=Path("dist/SyncLayerAgent.exe"))

    inst_p = sub.add_parser("installer", help="Verify final SyncLayerSetup.exe exists")
    inst_p.add_argument("--path", type=Path, default=Path("dist/SyncLayerSetup.exe"))

    args = parser.parse_args(argv)

    if args.command == "config":
        verify_config()
    elif args.command == "agent-exe":
        verify_agent_exe(args.path)
    else:
        verify_installer(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
