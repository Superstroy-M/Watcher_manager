"""
Иконка в системном трее.
Показывает статус агента. Нельзя закрыть через меню — только информация.
Запускается отдельным процессом от сервиса.
"""
import os
import sys
import subprocess
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from config import SERVER_URL, SERVICE_NAME

def _icon_path() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = os.path.join(sys._MEIPASS, "icon.png")
        if os.path.isfile(p):
            return p
        return os.path.join(os.path.dirname(sys.executable), "icon.png")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")


ICON_PATH = _icon_path()


def _create_icon_image(online: bool = True) -> Image.Image:
    """Загружаем иконку SyncLayer, добавляем индикатор статуса."""
    try:
        base = Image.open(ICON_PATH).convert("RGBA").resize((32, 32), Image.LANCZOS)
    except Exception:
        base = Image.new("RGBA", (32, 32), (30, 30, 50, 255))

    # Маленький индикатор онлайн/офлайн в правом нижнем углу
    draw = ImageDraw.Draw(base)
    color = (80, 220, 80) if online else (120, 120, 120)
    draw.ellipse([23, 23, 31, 31], fill=color, outline=(0, 0, 0), width=1)
    return base


class TrayApp:
    def __init__(self):
        self._online = False
        self._icon = None
        self._running = True

    def start(self):
        self._icon = pystray.Icon(
            name=SERVICE_NAME,
            icon=_create_icon_image(False),
            title="Учёт рабочего времени",
            menu=pystray.Menu(
                pystray.MenuItem("Учёт рабочего времени активен", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda _: f"Статус: {'Подключено' if self._online else 'Нет связи с сервером'}",
                    lambda: None,
                    enabled=False,
                ),
                pystray.MenuItem(
                    lambda _: f"Сервер: {SERVER_URL}",
                    lambda: None,
                    enabled=False,
                ),
            ),
        )

        # Фоновый поток для обновления статуса
        t = threading.Thread(target=self._status_updater, daemon=True)
        t.start()

        self._icon.run()

    def _status_updater(self):
        import requests
        while self._running:
            try:
                r = requests.get(f"{SERVER_URL}/api/health", timeout=5)
                online = r.status_code == 200
            except Exception:
                online = False

            if online != self._online:
                self._online = online
                if self._icon:
                    self._icon.icon = _create_icon_image(online)
                    self._icon.title = (
                        "Учёт рабочего времени — подключено"
                        if online
                        else "Учёт рабочего времени — нет связи"
                    )

            time.sleep(60)


def main():
    app = TrayApp()
    app.start()


if __name__ == "__main__":
    main()
