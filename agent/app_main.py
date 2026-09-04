"""
Один процесс агента: трекеры + иконка в трее.
Собирается в SyncLayerAgent.exe — на рабочие ПК Python не нужен.
"""
import os
import sys
from pathlib import Path

# PyInstaller: ресурсы рядом с exe, до single-instance lock.
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from single_instance import acquire_or_exit

acquire_or_exit()


def _bootstrap_log(message: str) -> None:
    """Пишет в agent.log до полной инициализации logging (если exe падает на import)."""
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent
        base.mkdir(parents=True, exist_ok=True)
        with (base / "agent.log").open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


_bootstrap_log("bootstrap: SyncLayerAgent process started")
if getattr(sys, "frozen", False):
    _bootstrap_log(f"bootstrap: cwd={os.getcwd()}")
_bootstrap_log("bootstrap: single-instance lock acquired")

import threading
import time
import logging

try:
    from window_tracker import WindowTracker
    from sender import EventSender
    from screenshot import ScreenshotWorker
    from process_monitor import ProcessMonitor
    from network_monitor import NetworkMonitor
    from print_monitor import PrintMonitor
    from diag_log import get_agent_dir, is_debug_mode, log_event, log_exception, log_memory_sample
    from config import AGENT_VERSION, SERVER_URL
    from input_counter import get_input_counter
    from memory_guard import check_memory
except Exception as exc:
    _bootstrap_log(f"bootstrap: import failed: {exc!r}")
    raise

_bootstrap_log("bootstrap: imports ok")

SHOW_TRAY = os.environ.get("SYNC_SHOW_TRAY", "0").strip() == "1"
LOG_FILE = str(get_agent_dir() / "agent.log")


def setup_logging():
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if is_debug_mode() else logging.INFO)
    if not root.handlers:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(handler)
    logging.getLogger("app").info(
        "SyncLayer agent started v%s (debug=%s)",
        AGENT_VERSION,
        is_debug_mode(),
    )


def _install_exception_hooks():
    def _handle_exception(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log_exception("app", exc, context="sys.excepthook")

    sys.excepthook = _handle_exception

    if hasattr(threading, "excepthook"):
        def _handle_thread_exception(args):
            if args.exc_value is not None:
                log_exception("app", args.exc_value, context=f"thread:{args.thread.name}")

        threading.excepthook = _handle_thread_exception


def main():
    setup_logging()
    _install_exception_hooks()
    log_event(
        "agent_start",
        "app",
        agent_version=AGENT_VERSION,
        pid=os.getpid(),
        server_url=SERVER_URL,
        debug_mode=is_debug_mode(),
    )
    tracker = WindowTracker()
    sender = EventSender(tracker)
    shots = ScreenshotWorker()
    processes = ProcessMonitor()
    network = NetworkMonitor()
    printer = PrintMonitor()

    tracker.start()
    sender.start()
    shots.start()
    processes.start()
    network.start()
    printer.start()
    get_input_counter().sync_monitoring_state()

    if SHOW_TRAY:
        from tray_app import TrayApp
        tray = TrayApp()
        tray.start()
    else:
        while True:
            check_memory()
            get_input_counter().sync_monitoring_state()
            log_memory_sample("app")
            time.sleep(60)


if __name__ == "__main__":
    threading.current_thread().name = "SyncLayer"
    main()
