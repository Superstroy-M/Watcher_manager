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

SHOW_TRAY = os.environ.get("SYNC_SHOW_TRAY", "0").strip() == "1"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.log")


def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("app").info("SyncLayer agent started")


def main():
    setup_logging()
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
            time.sleep(60)


if __name__ == "__main__":
    threading.current_thread().name = "SyncLayer"
    main()
