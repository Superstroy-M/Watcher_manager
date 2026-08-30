"""
Тестовый запуск агента БЕЗ Windows Service.
Запускать обычным пользователем (не обязательно Администратор).

Остановка: Ctrl+C в этом окне.
"""
import sys
import time

from config import SERVER_URL, API_KEY
from window_tracker import WindowTracker
from sender import EventSender
from screenshot import ScreenshotWorker
from process_monitor import ProcessMonitor
from network_monitor import NetworkMonitor
from print_monitor import PrintMonitor


def main():
    print("=" * 50)
    print(" SyncLayer — тестовый запуск")
    print("=" * 50)
    print(f" Сервер : {SERVER_URL}")
    print(f" API key: {API_KEY[:8]}...")
    print()
    if "YOUR_SERVER_IP" in SERVER_URL:
        print("ОШИБКА: сначала пропишите SERVER_URL в config.py")
        print("Пример: SERVER_URL = \"http://185.233.187.230:8000\"")
        sys.exit(1)

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

    print("Агент работает. Не закрывайте это окно.")
    print("Откройте дашборд в браузере и поработайте 2–3 минуты.")
    print("Остановка: Ctrl+C")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстановка...")
        tracker.stop()
        sender.stop()
        shots.stop()
        processes.stop()
        network.stop()
        printer.stop()
        print("Остановлено.")


if __name__ == "__main__":
    main()
