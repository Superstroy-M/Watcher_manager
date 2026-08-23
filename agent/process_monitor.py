"""
Снимок всех запущенных процессов каждые 5 минут.
"""
import time
import socket
import logging
import threading
from datetime import datetime
from typing import Optional

import psutil
import requests

from config import SERVER_URL, API_KEY

logger = logging.getLogger("processes")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
INTERVAL = 300  # 5 минут


class ProcessMonitor:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._snapshot()
            except Exception as e:
                logger.warning(f"Process snapshot error: {e}")
            time.sleep(INTERVAL)

    def _snapshot(self):
        procs = []
        for p in psutil.process_iter(["name", "pid", "cpu_percent", "memory_info", "username"]):
            try:
                info = p.info
                procs.append({
                    "name": info["name"] or "unknown",
                    "pid": info["pid"],
                    "cpu": round(info["cpu_percent"] or 0, 1),
                    "mem_mb": round((info["memory_info"].rss if info["memory_info"] else 0) / 1024 / 1024, 1),
                    "user": info["username"] or "",
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        payload = {
            "hostname": socket.gethostname(),
            "captured_at": datetime.utcnow().isoformat(),
            "processes": procs,
        }
        resp = requests.post(
            f"{SERVER_URL}/api/processes",
            json=payload,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        logger.debug(f"Sent {len(procs)} processes")
