"""
Один процесс агента: трекеры + иконка в трее.
Собирается в SyncLayer.exe — на рабочие ПК Python не нужен.
"""
import os
import sys
import threading
import time
import logging

# PyInstaller: ресурсы рядом с exe
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from window_tracker import WindowTracker
from sender import EventSender
from screenshot import ScreenshotWorker
from process_monitor import ProcessMonitor
from network_monitor import NetworkMonitor
from print_monitor import PrintMonitor
from diag_log import log_event
from config import AGENT_VERSION, SERVER_URL
from memory_guard import check_memory

SHOW_TRAY = os.environ.get("SYNC_SHOW_TRAY", "0").strip() == "1"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.log")


def setup_logging():
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(handler)
    logging.getLogger("app").info("SyncLayer agent started v%s", AGENT_VERSION)


def main():
    setup_logging()
    log_event(
        "agent_start",
        "app",
        version=AGENT_VERSION,
        server_url=SERVER_URL,
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

    if SHOW_TRAY:
        from tray_app import TrayApp
        tray = TrayApp()
        tray.start()
    else:
        # Фоновый режим без UI/окна.
        while True:
            check_memory()
            time.sleep(60)


if __name__ == "__main__":
    threading.current_thread().name = "SyncLayer"
    main()
