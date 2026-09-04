"""
Проверка production SERVER_URL перед/после сборки PyInstaller.

Использование (CI и локально):
  python verify_build_url.py config
  python verify_build_url.py agent-exe --path dist/SyncLayerAgent.exe
  python verify_build_url.py installer --path dist/SyncLayerSetup.exe

findstr/strings по onefile EXE ненадёжны: URL лежит в сжатых zlib-блоках CArchive.
Здесь — проверка config.py + скан zlib-декомпрессии бинарника.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import zlib
from pathlib import Path

PRODUCTION_URL = "https://watcher.tunellink.ru"
REQUIRED_HOST = "watcher.tunellink.ru"
FORBIDDEN_HOSTS = ("201.51.8.127",)
PYINSTALLER_COOKIE = b"MEI\x0c\x0b\x0a\x0b\x0e"


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

    print(f"OK config.py SERVER_URL={url}")


def _iter_zlib_blocks(data: bytes):
    end = len(data)
    idx = 0
    while idx < end - 2:
        if data[idx] == 0x78 and data[idx + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
                for size in (256, 1024, 4096, 65536, 524288, 2097152, 8388608):
                    try:
                        yield zlib.decompress(data[idx : idx + size], wbits)
                        break
                    except zlib.error:
                        continue
        idx += 1


def _scan_binary(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{label} not found: {path}")

    data = path.read_bytes()
    if PYINSTALLER_COOKIE not in data:
        raise SystemExit(f"{label} is not a PyInstaller bundle: {path}")

    required_hits = 0
    forbidden_hits: list[str] = []

    for block in _iter_zlib_blocks(data):
        if REQUIRED_HOST.encode("ascii") in block:
            required_hits += 1
        for forbidden in FORBIDDEN_HOSTS:
            if forbidden.encode("ascii") in block:
                forbidden_hits.append(forbidden)

    if forbidden_hits:
        raise SystemExit(
            f"{label} contains forbidden host(s) in compressed payload: "
            f"{sorted(set(forbidden_hits))}"
        )
    if required_hits < 1:
        raise SystemExit(
            f"{label} does not contain {REQUIRED_HOST!r} in any decompressible block"
        )

    print(
        f"OK {label}: PyInstaller bundle verified "
        f"({required_hits} zlib block(s) with {REQUIRED_HOST!r})"
    )


def verify_agent_exe(path: Path) -> None:
    _scan_binary(path, "SyncLayerAgent.exe")


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

    sub.add_parser("config", help="Verify agent/config.py before PyInstaller")

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
